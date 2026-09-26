"""The sentinel suite: store a known value, then try every way out of the module.

THE TEST THAT MATTERS is SentinelTests. It puts one distinctive, obviously
synthetic value into a store and then drives every public route the module has -
repr, str, format, %-interpolation, pprint, json.dumps of describe(), json.dumps
of snapshot(), dataclasses.asdict, the CLI's own stdout, every log record the
module emits, and every exception it raises on the way - and asserts the value
appears in exactly one place: the return of `get(...).reveal()`. Anywhere else
is a failure.

It is written as a sweep rather than as twenty assertions because the failure
mode is a route nobody thought of. A list of forbidden spellings checked against
a list of produced strings grows by one line when a route is added; twenty
hand-written assertions grow by an argument about whether the new one matters.

THE SECOND TEST THAT MATTERS is ExceptionTests. A credential in a traceback is
how it reaches a log file, and a log file is the one place nobody greps. Both
spellings are checked - the plaintext AND the UTF-16-LE byte repr - because the
blob crossing the ctypes boundary is UTF-16, and a grep for the plaintext would
sail straight past `S\\x00E\\x00N\\x00...` in a UnicodeDecodeError's repr.

THE THIRD is EnvFileTests, asserted BY PATH. `~/.agentmux/env` is sourced into
every agent pane, so a credential written there is handed to every codex and
claude worker on the machine. The test spies on every file-opening call the
module can reach and compares real paths, because "we do not write there" is an
intention and a path comparison is a fact.

SKIPS NAME THEIR REASON. The Windows backends cannot run under WSL, where this
suite runs. A skip that says which backend and why is information; a test that
quietly passes on Linux is decoration - the same standard dashboard/ninep.py
applies to a filesystem that will not answer.
"""

import builtins
import contextlib
import dataclasses
import io
import json
import logging
import os
import pickle
import pprint
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import creds
except ImportError as exc:
    creds = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


# Obviously synthetic, and it says so in the value itself. THIS REPO IS PUBLIC:
# a plausible-looking fixture is a fixture somebody will one day mistake for a
# real one, and a real one cannot be taken back out of a public history.
SENTINEL = "SENTINEL-DO-NOT-USE-synthetic-fixture-7f3a-b19c-4e2d"

# The same value as it appears inside a bytes repr after the UTF-16-LE encode
# the ctypes boundary requires. Without this spelling, a grep for the plaintext
# misses the exact leak the decode path can produce.
SENTINEL_AS_UTF16_REPR = repr(SENTINEL.encode("utf-16-le"))[2:-1]

FORBIDDEN_SPELLINGS = (SENTINEL, SENTINEL_AS_UTF16_REPR)

# Carries the pid so two runs on the same machine cannot collide in the real
# Credential Manager, which is machine-wide state rather than a temp directory.
NAME = f"sentinel-selftest-{os.getpid()}"
ABSENT_NAME = f"sentinel-absent-{os.getpid()}"


class _Recorder(logging.Handler):
    """Every record the module logs, formatted the way a real handler would.

    Both the rendered message and the raw args: an argument that is a Credential
    renders through __str__ (redacted), but a handler that repr()s its args
    would not, so both are collected and both are grepped.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    def emit(self, record):
        self.lines.append(self.format(record))
        self.lines.append(repr(record.args))
        self.lines.append(repr(record.msg))


class _NeedsCreds(unittest.TestCase):
    def setUp(self):
        if creds is None:
            self.fail(f"agentmux-broker/creds.py is missing: {IMPORT_ERROR}")

    def assertNoSentinel(self, produced, where):
        for index, text in enumerate(produced):
            for spelling in FORBIDDEN_SPELLINGS:
                if spelling in text:
                    self.fail(f"the sentinel escaped through {where} (string #{index})")


# ---------------------------------------------------------------------------
# The redaction contract, route by route
# ---------------------------------------------------------------------------

class RedactionTests(_NeedsCreds):
    def credential(self):
        return creds.Credential(NAME, SENTINEL, source="memory")

    def test_reveal_is_the_only_route_to_the_value(self):
        credential = self.credential()
        self.assertEqual(credential.reveal(), SENTINEL)

    def test_every_stringification_redacts(self):
        credential = self.credential()
        produced = [
            repr(credential), str(credential), f"{credential}", f"{credential:>80}",
            "%s" % (credential,), "%r" % (credential,), "{}".format(credential),
            format(credential, ""), format(credential, "^20"),
            str([credential]), repr({NAME: credential}), repr((credential,)),
            pprint.pformat(credential), pprint.pformat({NAME: [credential]}),
            json.dumps({"c": credential}, default=str),
        ]
        self.assertNoSentinel(produced, "a stringification route")
        self.assertIn(creds.REDACTED, repr(credential))
        # The NAME is still there: a redaction that hides which credential it is
        # makes a log line useless, and a name is not a value.
        self.assertIn(NAME, repr(credential))

    def test_there_is_no_instance_dict_to_walk(self):
        # __slots__, so a generic object-to-dict helper finds nothing. This is
        # the difference between "the repr is careful" and "there is nothing
        # for a careless caller to iterate".
        credential = self.credential()
        self.assertFalse(hasattr(credential, "__dict__"))
        with self.assertRaises(TypeError):
            vars(credential)

    def test_pickling_and_copying_are_refused_rather_than_redacted(self):
        # THE one that a repr cannot cover. pickle reads __slots__ through the
        # reduce protocol and would write the value out verbatim.
        import copy
        credential = self.credential()
        produced = []
        for attempt in (lambda: pickle.dumps(credential),
                        lambda: copy.copy(credential),
                        lambda: copy.deepcopy(credential),
                        lambda: credential.__getstate__(),
                        lambda: bytes(credential),
                        lambda: len(credential)):
            with self.assertRaises(creds.CredentialError) as ctx:
                attempt()
            produced.append(str(ctx.exception))
            produced.append(repr(ctx.exception))
        self.assertNoSentinel(produced, "a serialisation refusal")

    def test_truthiness_works_so_a_guard_clause_does_not_raise(self):
        # len() refuses, and without __bool__ truthiness falls through to it -
        # which would make `if store.get(name):` raise. A guard that breaks the
        # caller is a guard that gets deleted.
        self.assertTrue(bool(self.credential()))

    def test_a_non_string_value_is_refused(self):
        for bad in (b"bytes", 12345, None, ["list"]):
            with self.subTest(value=bad):
                with self.assertRaises(creds.CredentialError):
                    creds.Credential(NAME, bad)

    def test_the_fingerprint_is_stable_domain_separated_and_one_way(self):
        first = creds.fingerprint(NAME, SENTINEL)
        self.assertEqual(first, creds.fingerprint(NAME, SENTINEL))
        self.assertRegex(first, r"\A[0-9a-f]{16}\Z")
        # The same value under a different name is a different fingerprint, so a
        # digest cannot be used to prove two unrelated entries match.
        self.assertNotEqual(first, creds.fingerprint("other-name", SENTINEL))
        self.assertNotEqual(first, creds.fingerprint(NAME, SENTINEL + "x"))
        self.assertNoSentinel([first], "the fingerprint itself")

    def test_comparison_does_not_leak_through_an_error_message(self):
        left, right = self.credential(), self.credential()
        self.assertEqual(left, right)
        self.assertNotEqual(left, creds.Credential(NAME, "different-synthetic"))
        self.assertNotEqual(left, SENTINEL)     # NotImplemented, not a match


# ---------------------------------------------------------------------------
# Presence-not-value, made structural
# ---------------------------------------------------------------------------

class DescriptionTests(_NeedsCreds):
    def test_the_schema_has_no_field_a_value_could_go_in(self):
        # THE structural assertion. Adding somewhere to put a value fails here,
        # rather than requiring a reviewer to notice it.
        names = tuple(f.name for f in dataclasses.fields(creds.Description))
        self.assertEqual(names, creds.DESCRIPTION_FIELDS)
        for forbidden in ("value", "secret", "token", "blob", "plaintext", "key"):
            self.assertNotIn(forbidden, names)

    def test_a_value_cannot_be_smuggled_through_the_fingerprint_field(self):
        # The one field derived from the value is validated to a fixed shape.
        # No credential can satisfy 16 lowercase hex characters by accident.
        with self.assertRaises(creds.CredentialError):
            creds.Description(name=NAME, present=True, known=True, source="memory",
                              fingerprint=SENTINEL, reason="")
        with self.assertRaises(creds.CredentialError):
            creds.Description(name=NAME, present=True, known=True, source="memory",
                              fingerprint="NOTAHEXDIGEST00", reason="")

    def test_presence_without_a_fingerprint_is_refused(self):
        with self.assertRaises(creds.CredentialError):
            creds.Description(name=NAME, present=True, known=True, source="memory",
                              fingerprint="", reason="")

    def test_a_description_is_frozen(self):
        described = creds.absent(NAME, "memory")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            described.name = "changed"

    def test_absent_and_unknown_are_different_answers(self):
        # dashboard/ninep.py's distinction. "there is no such credential" and
        # "the backend could not answer" must not render the same, or a store
        # that is down looks exactly like one that is empty - and the operator
        # types the credential in again somewhere worse.
        gone = creds.absent(NAME, "memory")
        self.assertFalse(gone.present)
        self.assertTrue(gone.known)
        cannot_say = creds.unknown(NAME, "memory", "the backend raised OSError")
        self.assertFalse(cannot_say.present)
        self.assertFalse(cannot_say.known)
        self.assertTrue(cannot_say.reason)

    def test_describe_reports_a_failure_as_unknown_rather_than_raising(self):
        # A status surface that throws tells the operator nothing at all.
        class Broken(creds.MemoryBackend):
            def get(self, name):
                raise OSError(5, "Input/output error")

        store = creds.CredentialStore(Broken())
        described = store.describe(NAME)
        self.assertFalse(described.known)
        self.assertIn("OSError", described.reason)

    def test_describe_rejects_an_unusable_name_without_raising(self):
        store = creds.CredentialStore(creds.MemoryBackend())
        described = store.describe("has a space and a \n newline")
        self.assertFalse(described.known)


# ---------------------------------------------------------------------------
# THE sentinel sweep
# ---------------------------------------------------------------------------

class SentinelTests(_NeedsCreds):
    """One sweep, run against each backend that can actually run here."""

    def sweep(self, store):
        """Drive every public route and return every string the module produced.

        The return is (produced, revealed). `revealed` is the single legitimate
        escape - the value handed back by reveal() - and it is asserted
        separately, because a sweep that found the sentinel nowhere at all would
        also pass if the store simply did not work.
        """
        produced = []
        recorder = _Recorder()
        creds.LOG.addHandler(recorder)
        previous_level = creds.LOG.level
        creds.LOG.setLevel(logging.DEBUG)
        try:
            store.put(NAME, SENTINEL)
            self.addCleanup(self._forget, store, NAME)

            credential = store.get(NAME)
            self.assertIsNotNone(credential, "the store did not return what it stored")
            revealed = credential.reveal()

            described = store.describe(NAME)
            missing = store.describe(ABSENT_NAME)
            snapshot = store.snapshot([NAME, ABSENT_NAME])

            produced += [
                repr(store), str(store), repr(store.backend), str(store.backend),
                repr(credential), str(credential), f"{credential}", f"{credential:>80}",
                "%s" % (credential,), "%r" % (credential,), "{}".format(credential),
                str([credential]), repr({NAME: credential}),
                pprint.pformat(credential), pprint.pformat({NAME: credential}),
                repr(described), str(described), repr(missing),
                json.dumps(described.as_dict(), sort_keys=True),
                json.dumps(missing.as_dict(), sort_keys=True),
                json.dumps(snapshot, sort_keys=True),
                json.dumps(dataclasses.asdict(described), sort_keys=True),
                repr(dataclasses.astuple(described)),
                pprint.pformat(snapshot),
                json.dumps({"credential": credential}, default=str),
                credential.fingerprint(), described.fingerprint,
                json.dumps(creds.backend_availability(), sort_keys=True),
                repr(creds.forbidden_targets()),
            ]

            # The describe path must agree with the value it will not print.
            self.assertTrue(described.present)
            self.assertTrue(described.known)
            self.assertEqual(described.fingerprint, creds.fingerprint(NAME, SENTINEL))
            self.assertEqual(described.source, store.source)
            self.assertFalse(missing.present)
            self.assertTrue(missing.known)

            # The CLI surface: the closest thing this module has to a response
            # body, so it is captured and grepped like one.
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                creds.main([NAME, ABSENT_NAME])
            produced.append(buffer.getvalue())

            # Overwrite, re-read, delete, and read back after the delete. Every
            # one of these is a route, and the last two are where a backend that
            # caches would hand back the old value.
            store.put(NAME, SENTINEL)
            produced.append(repr(store.describe(NAME)))
            self.assertTrue(store.delete(NAME))
            self.assertFalse(store.delete(NAME))
            self.assertIsNone(store.get(NAME))
            after = store.describe(NAME)
            self.assertFalse(after.present)
            self.assertTrue(after.known, after.reason)
            produced += [repr(after), json.dumps(after.as_dict(), sort_keys=True)]

            # Errors raised along the way, with their full traceback text.
            produced += self._refusals(store)

            produced += recorder.lines
        finally:
            creds.LOG.removeHandler(recorder)
            creds.LOG.setLevel(previous_level)
        return produced, revealed

    def _refusals(self, store):
        """Every failure route, as the message AND the rendered traceback."""
        texts = []
        attempts = [
            lambda: store.put(NAME, SENTINEL * 200),      # over the blob limit
            lambda: store.put("not a valid name", SENTINEL),
            lambda: store.put(NAME, SENTINEL.encode()),   # bytes, not str
            lambda: store.put(NAME, ""),
            lambda: store.get("not a valid name"),
            lambda: creds._decode_blob(NAME, SENTINEL.encode("utf-16-le") + b"\x00"),
            lambda: pickle.dumps(creds.Credential(NAME, SENTINEL)),
        ]
        for attempt in attempts:
            try:
                attempt()
            except Exception as exc:
                texts += [str(exc), repr(exc), traceback.format_exc(),
                          repr(getattr(exc, "__context__", None)),
                          repr(getattr(exc, "__cause__", None))]
            else:
                self.fail("a refusal route did not refuse")
        return texts

    @staticmethod
    def _forget(store, name):
        try:
            store.delete(name)
        except creds.CredentialError:
            pass

    def _run_against(self, store):
        produced, revealed = self.sweep(store)
        self.assertEqual(revealed, SENTINEL,
                         "reveal() must return the value that was stored")
        self.assertNoSentinel(produced, f"the {store.source} backend")

    def test_the_sentinel_never_escapes_the_memory_backend(self):
        self._run_against(creds.CredentialStore(creds.MemoryBackend()))

    def test_the_sentinel_never_escapes_the_windows_credential_manager(self):
        reason = creds.WindowsCredentialManagerBackend.unavailable_reason()
        if reason:
            self.skipTest(f"windows-credential-manager: {reason}")
        self._run_against(
            creds.CredentialStore(creds.WindowsCredentialManagerBackend()))

    def test_the_sentinel_never_escapes_dpapi(self):
        reason = creds.DpapiBackend.unavailable_reason()
        if reason:
            self.skipTest(f"dpapi: {reason}")
        with tempfile.TemporaryDirectory() as temp:
            self._run_against(creds.CredentialStore(creds.DpapiBackend(root=temp)))

    def test_the_sweep_would_notice_a_leak(self):
        # A sweep that could not fail is decoration. This feeds the sweep's own
        # assertion a string that DOES contain the sentinel, in each spelling,
        # and requires it to fail - so the suite above is a test rather than a
        # ceremony.
        for spelling in FORBIDDEN_SPELLINGS:
            with self.subTest(spelling=spelling[:20]):
                with self.assertRaises(AssertionError):
                    self.assertNoSentinel(["harmless", f"leaked: {spelling}"], "a fixture")


# ---------------------------------------------------------------------------
# Failure messages and tracebacks
# ---------------------------------------------------------------------------

class ExceptionTests(_NeedsCreds):
    def test_a_decode_failure_carries_neither_the_bytes_nor_a_chained_cause(self):
        # THE traceback case. An odd-length UTF-16 blob raises
        # UnicodeDecodeError, whose repr() contains the ENTIRE undecoded object.
        # `raise ... from None` alone would not be enough: it sets
        # __suppress_context__ but leaves __context__ pointing at the exception
        # that holds the bytes, and any tool that walks the chain prints them.
        raw = SENTINEL.encode("utf-16-le") + b"\x00"
        with self.assertRaises(creds.CredentialError) as ctx:
            creds._decode_blob(NAME, raw)
        error = ctx.exception
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__,
                          "the chained exception still holds the undecoded blob")
        produced = [str(error), repr(error), repr(error.args),
                    "".join(traceback.format_exception(type(error), error,
                                                       error.__traceback__))]
        self.assertNoSentinel(produced, "a decode failure")
        self.assertIn(NAME, str(error))     # it still says WHICH credential

    def test_a_chained_unicode_error_would_have_leaked(self):
        # The differential. Without the discipline above, this is what the
        # message looks like - so the assertion in the test before it is proved
        # to be catching something real rather than passing by luck.
        leaked = ""
        try:
            (SENTINEL.encode("utf-16-le") + b"\x00").decode("utf-16-le")
        except UnicodeDecodeError as exc:
            leaked = repr(exc)
        self.assertIn(SENTINEL_AS_UTF16_REPR, leaked)

    def test_an_oversized_value_is_refused_without_reporting_its_length(self):
        # A byte count is a partial disclosure of a value the caller already
        # holds, and the house rule from dashboard/server.py is that a presence
        # report never carries a length. The limit is named; the actual size is
        # not.
        store = creds.CredentialStore(creds.MemoryBackend())
        oversized = SENTINEL * 200
        with self.assertRaises(creds.CredentialError) as ctx:
            store.put(NAME, oversized)
        message = str(ctx.exception)
        self.assertNoSentinel([message, repr(ctx.exception)], "the size refusal")
        self.assertIn(str(creds.MAX_BLOB_BYTES), message)
        self.assertNotIn(str(len(oversized.encode("utf-16-le"))), message)

    def test_a_wrong_type_is_named_by_type_not_by_value(self):
        store = creds.CredentialStore(creds.MemoryBackend())
        with self.assertRaises(creds.CredentialError) as ctx:
            store.put(NAME, SENTINEL.encode("utf-8"))
        self.assertNoSentinel([str(ctx.exception), repr(ctx.exception)], "a type refusal")
        self.assertIn("bytes", str(ctx.exception))

    def test_every_available_backend_fails_without_the_value(self):
        # Each backend, driven into a real failure on its own code path, not
        # just through the shared validator.
        cases = [("memory", lambda: creds.MemoryBackend())]
        for cls in creds.BACKENDS:
            reason = cls.unavailable_reason()
            if reason:
                continue
            if cls is creds.DpapiBackend:
                temp = tempfile.mkdtemp()
                self.addCleanup(_rmtree, temp)
                # A FILE where the credentials directory must be, so mkdir and
                # the write both fail for a real OS reason.
                blocker = Path(temp) / "broker" / "credentials"
                blocker.parent.mkdir(parents=True, exist_ok=True)
                blocker.write_bytes(b"not a directory")
                cases.append(("dpapi", lambda t=temp: creds.DpapiBackend(root=Path(t) / "broker")))
            else:
                cases.append((cls.name, cls))
        self.assertGreaterEqual(len(cases), 1)
        for label, factory in cases:
            with self.subTest(backend=label):
                backend = factory()
                produced = []
                for attempt in (lambda: backend.put(NAME, SENTINEL * 200),
                                lambda: backend.put("bad name", SENTINEL),
                                lambda: backend.put(NAME, SENTINEL)):
                    try:
                        attempt()
                    except creds.CredentialError as exc:
                        produced += [str(exc), repr(exc), traceback.format_exc()]
                    except Exception as exc:          # noqa: BLE001 - reported below
                        self.fail(f"{label} raised {type(exc).__name__} rather than "
                                  f"a CredentialError: the message is not controlled")
                    else:
                        if attempt is not None:
                            self.addCleanup(_forget_backend, backend, NAME)
                self.assertNoSentinel(produced, f"{label} failure messages")

    def test_a_backend_that_is_unavailable_says_why(self):
        # "not here" with a stated cause, so a skip is information. A bare False
        # would leave the caller to invent a reason.
        for name, reason in creds.backend_availability().items():
            with self.subTest(backend=name):
                self.assertTrue(reason is None or (isinstance(reason, str) and reason.strip()),
                                f"{name} is unavailable and will not say why")
                if reason and sys.platform != "win32":
                    self.assertIn(sys.platform, reason)


# ---------------------------------------------------------------------------
# The file this module must never touch
# ---------------------------------------------------------------------------

class EnvFileTests(_NeedsCreds):
    """Asserted by PATH. `~/.agentmux/env` is SOURCED into every agent pane."""

    def test_forbidden_targets_names_the_agent_env_file(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("AGENTMUX_HOME")
            os.environ["AGENTMUX_HOME"] = temp
            try:
                targets = creds.forbidden_targets()
            finally:
                if previous is None:
                    os.environ.pop("AGENTMUX_HOME", None)
                else:
                    os.environ["AGENTMUX_HOME"] = previous
        self.assertIn(creds._normalise(Path(temp) / "env"), targets)

    def test_the_operator_home_env_file_is_named_even_with_no_agentmux_home(self):
        previous = os.environ.pop("AGENTMUX_HOME", None)
        try:
            targets = creds.forbidden_targets()
        finally:
            if previous is not None:
                os.environ["AGENTMUX_HOME"] = previous
        self.assertIn(creds._normalise(Path.home() / ".agentmux" / "env"), targets)

    def test_the_guard_refuses_that_path(self):
        with self.assertRaises(creds.CredentialError) as ctx:
            creds.check_not_forbidden(Path.home() / ".agentmux" / "env")
        self.assertIn("agent pane", str(ctx.exception))

    def test_the_guard_permits_a_path_under_the_broker_root(self):
        with tempfile.TemporaryDirectory() as temp:
            allowed = Path(temp) / "credentials" / "anything.dpapi"
            self.assertEqual(creds.check_not_forbidden(allowed), allowed)

    def test_no_route_in_this_module_opens_the_env_file(self):
        """Every file-opening call the module can reach, compared by real path."""
        for label, factory, needs_files in self._stores():
            with self.subTest(backend=label):
                touched = []
                with _watch_file_calls(touched):
                    store = factory()
                    store.put(NAME, SENTINEL)
                    store.get(NAME)
                    store.describe(NAME)
                    store.snapshot([NAME, ABSENT_NAME])
                    store.delete(NAME)
                    store.get(NAME)
                forbidden = set(creds.forbidden_targets())
                for path in touched:
                    self.assertNotIn(creds._normalise(path), forbidden,
                                     f"the {label} backend opened {path}")
                # The spy has to be able to SEE something, or this proves
                # nothing. A file-backed store must have opened at least one
                # file; the memory store must have opened none.
                if needs_files:
                    self.assertTrue(touched, "the file-call spy saw nothing at all")
                else:
                    self.assertEqual(touched, [],
                                     "the in-memory backend touched the filesystem")

    def test_the_spy_would_notice_the_env_file_being_opened(self):
        # The failability check for the test above: if the spy cannot see a
        # write to that exact path, every assertion in it is decoration.
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("AGENTMUX_HOME")
            os.environ["AGENTMUX_HOME"] = temp
            try:
                target = Path(temp) / "env"
                touched = []
                with _watch_file_calls(touched):
                    with open(target, "w", encoding="utf-8") as handle:
                        handle.write("SYNTHETIC=1\n")
                forbidden = set(creds.forbidden_targets())
                self.assertIn(creds._normalise(target),
                              {creds._normalise(p) for p in touched})
                self.assertIn(creds._normalise(target), forbidden)
            finally:
                if previous is None:
                    os.environ.pop("AGENTMUX_HOME", None)
                else:
                    os.environ["AGENTMUX_HOME"] = previous

    def test_the_file_backend_checks_the_guard_on_every_path_it_opens(self):
        reason = creds.DpapiBackend.unavailable_reason()
        if reason:
            self.skipTest(f"dpapi: {reason}")
        checked = []
        real_guard = creds.check_not_forbidden

        def spy(path):
            checked.append(creds._normalise(path))
            return real_guard(path)

        with tempfile.TemporaryDirectory() as temp:
            creds.check_not_forbidden = spy
            try:
                backend = creds.DpapiBackend(root=temp)
                backend.put(NAME, SENTINEL)
                backend.get(NAME)
                backend.delete(NAME)
            finally:
                creds.check_not_forbidden = real_guard
        self.assertTrue(checked)
        self.assertIn(creds._normalise(Path(temp) / "credentials" / f"{NAME}.dpapi"),
                      checked)

    def _stores(self):
        yield ("memory", lambda: creds.CredentialStore(creds.MemoryBackend()), False)
        reason = creds.DpapiBackend.unavailable_reason()
        if not reason:
            temp = tempfile.mkdtemp()
            self.addCleanup(_rmtree, temp)
            yield ("dpapi",
                   lambda: creds.CredentialStore(creds.DpapiBackend(root=temp)), True)


# ---------------------------------------------------------------------------
# Choosing a backend
# ---------------------------------------------------------------------------

class SelectionTests(_NeedsCreds):
    def test_memory_is_never_chosen_without_an_explicit_opt_in(self):
        # A store that forgets everything at exit looks exactly like a working
        # one until the credential is needed again - and then the operator
        # re-enters it, which is the thing this module exists to prevent.
        if any(reason is None for reason in creds.backend_availability().values()):
            self.skipTest("an OS credential store is available here, so there is "
                          "nothing to fall back from")
        with self.assertRaises(creds.NoBackend) as ctx:
            creds.open_store()
        message = str(ctx.exception)
        for name in creds.backend_availability():
            self.assertIn(name, message, "the refusal must list what it tried")

    def test_memory_is_returned_when_it_is_asked_for(self):
        store = creds.open_store(prefer="memory", allow_memory=True)
        self.assertIsInstance(store.backend, creds.MemoryBackend)
        self.assertEqual(store.source, "memory")

    def test_the_credential_manager_is_preferred_over_dpapi(self):
        # The recorded decision: revocability over blob simplicity. An OS UI
        # that lists and revokes beats a file nobody remembers exists.
        self.assertEqual(creds.BACKENDS[0], creds.WindowsCredentialManagerBackend)
        self.assertEqual(creds.BACKENDS[1], creds.DpapiBackend)
        self.assertNotIn(creds.MemoryBackend, creds.BACKENDS)

    def test_an_unknown_backend_name_is_refused(self):
        with self.assertRaises(creds.CredentialError):
            creds.open_store(prefer="keychain")

    def test_a_store_needs_a_real_backend(self):
        with self.assertRaises(creds.CredentialError):
            creds.CredentialStore({"put": None})

    def test_names_are_bounded_and_pattern_checked(self):
        store = creds.CredentialStore(creds.MemoryBackend())
        for bad in ("", "a" * 80, "../escape", "with space", "with\nnewline",
                    ".leading-dot", "slash/inside", None, 7):
            with self.subTest(name=bad):
                with self.assertRaises(creds.CredentialError):
                    store.put(bad, SENTINEL)
        for good in ("alpaca_api_key", "broker.session-token", "A1"):
            with self.subTest(name=good):
                store.put(good, SENTINEL)
                self.assertEqual(store.get(good).reveal(), SENTINEL)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _forget_backend(backend, name):
    try:
        backend.delete(name)
    except creds.CredentialError:
        pass


@contextlib.contextmanager
def _watch_file_calls(touched):
    """Record the path of every file-opening call, then restore everything.

    builtins.open and io.open are patched separately because they are looked up
    on their own modules: pathlib calls io.open, and patching only the builtin
    would let every Path.read_bytes through unseen.
    """
    originals = {}
    targets = [(builtins, "open"), (io, "open"), (os, "open"),
               (os, "replace"), (os, "rename"), (os, "unlink"), (os, "remove")]

    def wrap(module, attribute):
        real = getattr(module, attribute)

        def spy(first, *args, **kwargs):
            try:
                touched.append(os.fspath(first))
            except TypeError:
                pass                    # a file descriptor, not a path
            return real(first, *args, **kwargs)

        originals[(module, attribute)] = real
        setattr(module, attribute, spy)

    for module, attribute in targets:
        wrap(module, attribute)
    try:
        yield
    finally:
        for (module, attribute), real in originals.items():
            setattr(module, attribute, real)


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    # A skip that names the backend AND the reason. run_tests.sh greps for this
    # shape, so an unavailable backend is visible in the gate rather than being
    # quietly counted as coverage that does not exist.
    for case, reason in result.skipped:
        print(f"SKIP {case.id().rsplit('.', 1)[-1]}: {reason}")
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
