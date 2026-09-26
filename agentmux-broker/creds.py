"""Credential storage for the broker: the OS holds the value, this module never shows it.

WHY THE CREDENTIAL MANAGER RATHER THAN A DPAPI BLOB. Both are `ctypes` against a
system DLL and neither adds a dependency, so the choice is not about cost. It is
about what happens a year from now, when nobody remembers what was stored. The
Windows Credential Manager has a UI: `control /name Microsoft.CredentialManager`
lists every entry, says when it was written, and revokes one with a click. A
DPAPI blob is a file whose existence is knowledge somebody has to still have. So
Credential Manager is primary and DPAPI is the documented fallback for a machine
where it cannot be reached - REVOCABILITY MATTERS MORE THAN BLOB SIMPLICITY.

WHY NOT ~/.agentmux/env, WHICH IS ALREADY 0600. Because agentmux.sh SOURCES that
file into every agent pane it starts (agentmux.sh:669, and deliberately so - it
is how a provider key reaches a codex worker without appearing in `ps`). A
brokerage credential put there is handed to every claude and codex worker on the
machine. That is the failure dashboard/check_key_exposure.sh was written after:
one value copied into three files, each 0600, each perfectly correct, and the
blast radius the union of all three. `forbidden_targets()` names that path and
every write here is checked against it BY PATH.

THE PRESENCE-NOT-VALUE CONTRACT, MADE STRUCTURAL. dashboard/server.py's
auth_snapshot() reports whether a credential is set and never what it is, and
that is the right shape - but there it is a convention a reviewer has to keep
enforcing. Here it is built into the types:

  * `get()` returns a `Credential`, never a `str`. The plaintext leaves this
    module only through an explicit `.reveal()`, so every other route out - an
    f-string, a log line, `json.dumps`, `pickle`, a traceback - is redacted
    rather than merely unlikely.
  * `Credential` redacts in `__repr__`, `__str__` and `__format__`, has no
    `__dict__` to walk, and REFUSES to pickle or copy, because `pickle.dumps`
    would otherwise serialise the value out of a slot the repr never touches.
  * `Description` - what `describe()` returns - is a frozen record of four
    declared non-value fields. It has no field a value could be put in, and its
    `__post_init__` rejects a fingerprint that is not exactly 16 lowercase hex
    characters. Returning the value is a schema change, not an oversight.

A FINGERPRINT IS NOT AN ENCRYPTION, and this is stated rather than implied. It
answers "is this the same value I had yesterday" and "do these two machines hold
the same one". It does NOT protect a low-entropy value: sixteen hex characters
of a domain-separated SHA-256 can be confirmed by anyone who can guess the input
and knows the name. Fingerprint high-entropy credential material, and do not
treat the digest of a short passphrase as private.

"NOT HERE" AND "COULD NOT FIND OUT" ARE DIFFERENT ANSWERS, the distinction
dashboard/ninep.py keeps for the 9p mount. A backend that is absent because this
is Linux, and a backend that raised on a call, must not both read as "no
credential". `Description.known` carries it: `present=False, known=False` means
the question was not answered, and `reason` says why. A suite that cannot reach
a backend SKIPS with the reason named; it does not pass quietly.
"""

import ctypes
import hashlib
import hmac
import logging
import os
import re
import sys
from dataclasses import dataclass, fields
from pathlib import Path

LOG = logging.getLogger("agentmux.broker.creds")

# Names are identifiers, not values: they appear in log lines, in describe()
# output and in the Credential Manager UI. Bounded and pattern-checked so a
# caller cannot smuggle a newline into a log line or a path separator into a
# filename.
NAME_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

# One namespace in the Credential Manager, so every entry this project writes is
# findable and revocable together. A person looking at that list should be able
# to tell in one glance which rows are ours.
TARGET_PREFIX = "agentmux-broker:"

# Shown in the Credential Manager's "user name" column. Not a value, not an
# account identifier - a label, so a row is attributable to this project.
TARGET_USER = "agentmux-broker"

# Domain separation, so a fingerprint here cannot be compared against a digest
# computed somewhere else for some other purpose, and so the same value under
# two names does not produce the same digest.
FINGERPRINT_DOMAIN = b"agentmux-broker.creds.v1"
FINGERPRINT_CHARS = 16
FINGERPRINT_PATTERN = re.compile(r"\A[0-9a-f]{16}\Z")

# CRED_MAX_CREDENTIAL_BLOB_SIZE. Enforced for every backend, not just the one it
# belongs to, so a value that fits under DPAPI today does not fail to migrate to
# the Credential Manager tomorrow.
MAX_BLOB_BYTES = 5 * 512

REDACTED = "<redacted>"


class CredentialError(Exception):
    """Something failed. The message names the operation and the NAME, never the
    value - see `_fail` for why the chained context is cut as well."""


class BackendUnavailable(CredentialError):
    """This backend cannot run here, and the message says why.

    A distinct type because "no Credential Manager on this box" is a SKIP with a
    stated cause, and "CredWriteW returned 1168" is a failure. Collapsing them
    gives you a suite that silently tests nothing on Linux.
    """


def _fail(message):
    """Raise a CredentialError carrying no chained exception at all.

    MUST BE CALLED OUTSIDE the `except` block that decided to fail. Two separate
    leaks are being closed here:

      `raise ... from None` only sets `__suppress_context__`. `__context__`
      still HOLDS the original exception, and `repr(UnicodeDecodeError(...))`
      contains the entire undecoded object. Any logger that formats with repr,
      or any tool that walks `__context__`, prints the blob.

      Python re-attaches `__context__` at raise time if an exception is being
      handled, so clearing the attribute before raising inside the handler does
      nothing. Leaving the handler first is the only thing that works.

    A credential in a traceback is how it reaches a log file, and a log file is
    the one place nobody thinks to grep.
    """
    error = CredentialError(message)
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    raise error


def fingerprint(name, value):
    """A stable 16-hex-character digest of (name, value). One-way, by construction.

    Not private for a guessable input - see the module docstring. It is here so
    two machines can agree they hold the same credential material without either
    of them saying what it is.
    """
    digest = hashlib.sha256()
    digest.update(FINGERPRINT_DOMAIN)
    digest.update(b"\x00")
    digest.update(name.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(value.encode("utf-8"))
    return digest.hexdigest()[:FINGERPRINT_CHARS]


class Credential:
    """An opaque holder. The value comes out of `reveal()` and nowhere else.

    `__slots__` rather than a dict: there is nothing for `vars()` to walk, and
    nothing a generic object-to-dict helper can pick up by accident. The point
    is not that the value is unreachable - `_value` is right there for anyone
    who means it - but that reaching it is a DELIBERATE act that shows up in a
    diff, rather than the default behaviour of an f-string.
    """

    __slots__ = ("name", "source", "_value")

    def __init__(self, name, value, source="unknown"):
        if not isinstance(value, str):
            _fail(f"a credential value must be str, got {type(value).__name__}")
        self.name = str(name)
        self.source = str(source)
        self._value = value

    def reveal(self):
        """The plaintext. The ONLY route out, and it is named so it greps."""
        return self._value

    def fingerprint(self):
        return fingerprint(self.name, self._value)

    def describe(self, present=True, known=True, reason=""):
        return Description(name=self.name, present=bool(present), known=bool(known),
                           source=self.source, fingerprint=self.fingerprint(),
                           reason=str(reason))

    # ---- every route to a string is redacted -------------------------------
    def __repr__(self):
        return f"Credential(name={self.name!r}, source={self.source!r}, value={REDACTED})"

    __str__ = __repr__

    def __format__(self, spec):
        # Deliberately ignores the format spec. `f"{cred:>40}"` would otherwise
        # fall through to object.__format__, which raises for a non-empty spec -
        # and an exception here is a worse outcome than a redacted string in a
        # message somebody is already writing.
        return self.__repr__()

    def __bytes__(self):
        _fail(f"{self.name!r} cannot be converted to bytes; call reveal() if you mean it")

    def __bool__(self):
        # Defined so that `if store.get(name):` works. Without it, truthiness
        # falls through to __len__, which refuses - and a guard clause that
        # raises is a worse failure than the one it was written to prevent.
        return True

    def __len__(self):
        # A length is a partial disclosure. dashboard/server.py already refuses
        # to report one beside a presence flag - "never a value, never a length,
        # never a prefix, because a prefix is still a leak" - and the same
        # reasoning applies to len().
        _fail(f"the length of {self.name!r} is not reported")

    # ---- serialisation is refused, not redacted ----------------------------
    #
    # pickle reads __slots__ through __reduce_ex__ and would write _value out
    # verbatim, past every redaction above. copy.copy and copy.deepcopy go
    # through the same protocol. Each is refused with its own signature, because
    # a TypeError about argument counts is a refusal nobody can act on.
    def __reduce__(self):
        _fail(f"{self.name!r} is not serialisable; a pickled credential is a credential in a file")

    def __reduce_ex__(self, protocol=None):
        _fail(f"{self.name!r} is not serialisable; a pickled credential is a credential in a file")

    def __getstate__(self):
        _fail(f"{self.name!r} has no serialisable state")

    def __copy__(self):
        _fail(f"{self.name!r} is not copyable; one holder is easier to reason about than two")

    def __deepcopy__(self, memo):
        _fail(f"{self.name!r} is not copyable; one holder is easier to reason about than two")

    # ---- comparison without a timing side-channel --------------------------
    def __eq__(self, other):
        if not isinstance(other, Credential):
            return NotImplemented
        return hmac.compare_digest(self._value, other._value)

    def __hash__(self):
        return hash(("agentmux.credential", self.fingerprint()))


@dataclass(frozen=True)
class Description:
    """Presence, provenance and a digest. There is no field for the value.

    Frozen and slotted, and `DESCRIPTION_FIELDS` below is asserted by the suite,
    so adding somewhere to put a value is a visible schema change that fails a
    test rather than a line a reviewer has to notice.

    `present` and `known` are separate on purpose. `present=False, known=True`
    is "there is no such credential". `present=False, known=False` is "the
    backend could not answer", and `reason` says why. Collapsing them is the
    same bug dashboard/ninep.py exists to prevent.
    """

    __slots__ = ("name", "present", "known", "source", "fingerprint", "reason")

    # No defaults, because a dataclass field with a default and a manual
    # __slots__ is a ValueError at class creation. `absent()`, `unknown()` and
    # `Credential.describe()` below are the intended constructors and they carry
    # the defaults instead.
    name: str
    present: bool
    known: bool
    source: str
    fingerprint: str
    reason: str

    def __post_init__(self):
        for field in ("name", "source", "fingerprint", "reason"):
            if not isinstance(getattr(self, field), str):
                _fail(f"Description.{field} must be str")
        for field in ("present", "known"):
            if not isinstance(getattr(self, field), bool):
                _fail(f"Description.{field} must be bool")
        # THE STRUCTURAL GUARD. A fingerprint is 16 lowercase hex characters or
        # the empty string. No credential value can satisfy that by accident,
        # and a caller who tried to pass one through this field gets a raise
        # rather than a response body.
        if self.fingerprint and not FINGERPRINT_PATTERN.match(self.fingerprint):
            _fail(f"Description.fingerprint for {self.name!r} is not a {FINGERPRINT_CHARS}-character digest")
        if self.present and not self.fingerprint:
            _fail(f"Description for {self.name!r} claims presence with no fingerprint")
        if self.present and not self.known:
            _fail(f"Description for {self.name!r} claims presence without knowing")

    def as_dict(self):
        """The payload shape. Exactly the declared fields, nothing derived."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


DESCRIPTION_FIELDS = ("name", "present", "known", "source", "fingerprint", "reason")


def absent(name, source, reason=""):
    return Description(name=str(name), present=False, known=True, source=str(source),
                       fingerprint="", reason=str(reason))


def unknown(name, source, reason):
    """The backend could not answer. NOT the same as absent."""
    return Description(name=str(name), present=False, known=False, source=str(source),
                       fingerprint="", reason=str(reason))


# ---------------------------------------------------------------------------
# Paths this module must never touch
# ---------------------------------------------------------------------------

def broker_root(root=None):
    """Where a file-backed credential lives: OUTSIDE the repo, on purpose.

    Same resolution as killswitch.broker_root - %LOCALAPPDATA%\\agentmux\\broker
    on Windows, $AGENTMUX_HOME/broker otherwise. docs/investing-boundary.md
    records why: this repo is public, and a push cannot be taken back.
    """
    if root is not None:
        return Path(root)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "agentmux" / "broker"
    home = os.environ.get("AGENTMUX_HOME")
    return (Path(home) if home else Path.home() / ".agentmux") / "broker"


def forbidden_targets():
    """Files this module must never open, by PATH rather than by intention.

    `~/.agentmux/env` (and `$AGENTMUX_HOME/env`) is SOURCED into every agent
    pane agentmux.sh starts. A credential written there is handed to every
    codex and claude worker on the machine, which is the exact shape of the
    exposure check_key_exposure.sh was written to find.

    Returned as normalised strings: comparing Path objects across a drvfs mount
    and a symlinked home does not do what it looks like it does.
    """
    roots = []
    home = os.environ.get("AGENTMUX_HOME")
    if home:
        roots.append(Path(home))
    try:
        # Both, when AGENTMUX_HOME is set: the operator's real home is still a
        # place agentmux.sh sources from in another shell.
        roots.append(Path.home() / ".agentmux")
    except RuntimeError:
        pass                    # no resolvable home; the AGENTMUX_HOME entry stands
    targets = []
    for root in roots:
        for leaf in ("env", "auth.json"):
            targets.append(_normalise(root / leaf))
    return tuple(sorted(set(targets)))


def _normalise(path):
    """A comparable spelling of a path. Never raises, never touches the disk.

    os.path.realpath would be better and is not usable: it stats, and a stat on
    the 9p mount raises EIO under load (dashboard/ninep.py). A guard that can
    fail transiently is a guard that gets removed.
    """
    try:
        text = os.path.abspath(os.fspath(path))
    except (OSError, TypeError, ValueError):
        text = str(path)
    return os.path.normcase(text.replace("\\", os.sep))


def check_not_forbidden(path):
    """Refuse a path this module must not write. Called before every open."""
    if _normalise(path) in forbidden_targets():
        _fail(f"refusing to touch {path}: that file is sourced into every agent pane")
    return Path(path)


def _check_name(name):
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        _fail(f"{name!r} is not a usable credential name "
              f"(letters, digits, dot, dash, underscore; 1-64 characters)")
    return name


def _check_value(name, value):
    """Validate without ever putting the value in a message.

    The size limit is reported WITHOUT the actual size. A byte count is a
    partial disclosure of a value the caller already holds, and the house rule
    from dashboard/server.py is that a presence report never carries a length.
    The caller can measure their own string.
    """
    if not isinstance(value, str):
        _fail(f"the value for {name!r} must be str, got {type(value).__name__}")
    if not value:
        _fail(f"the value for {name!r} is empty; delete() is how you remove one")
    try:
        encoded = value.encode("utf-16-le")
    except (UnicodeEncodeError, ValueError):
        encoded = None
    if encoded is None:
        _fail(f"the value for {name!r} is not encodable as UTF-16")
    if len(encoded) > MAX_BLOB_BYTES:
        _fail(f"the value for {name!r} exceeds the {MAX_BLOB_BYTES}-byte blob limit")
    return encoded


def _decode_blob(name, raw):
    """UTF-16-LE bytes back to text, without the bytes reaching the message.

    UnicodeDecodeError carries the whole offending object in its repr. `_fail`
    is called after the handler exits precisely so that object cannot ride out
    on `__context__`.
    """
    problem = None
    try:
        return bytes(raw).decode("utf-16-le")
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        problem = type(exc).__name__
    _fail(f"the stored blob for {name!r} is not UTF-16 text ({problem})")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class Backend:
    """get/put/delete against one store. Availability is answered, not assumed."""

    name = "backend"
    writes_files = False

    @classmethod
    def unavailable_reason(cls):
        """None when this backend can run here, else a sentence saying why not.

        The ninep.py shape: a caller that cannot use a backend gets a stated
        cause it can put in a SKIP message, not an exception it has to catch and
        summarise itself.
        """
        return None

    @classmethod
    def available(cls):
        return cls.unavailable_reason() is None

    def get(self, name):
        raise NotImplementedError

    def put(self, name, value):
        raise NotImplementedError

    def delete(self, name):
        raise NotImplementedError

    def __repr__(self):
        return f"{type(self).__name__}(name={self.name!r})"

    __str__ = __repr__


class MemoryBackend(Backend):
    """For tests, and for nothing else.

    It exists so the module imports and is fully exercisable on Linux, where the
    suite runs. It is never selected automatically - `open_store()` refuses
    rather than silently handing back a store that forgets everything at exit.
    A credential store that quietly loses the credential is worse than one that
    says it is not there.
    """

    name = "memory"

    def __init__(self):
        self._values = {}

    def get(self, name):
        _check_name(name)
        value = self._values.get(name)
        if value is None:
            return None
        return Credential(name, value, source=self.name)

    def put(self, name, value):
        _check_name(name)
        _check_value(name, value)
        self._values[name] = value

    def delete(self, name):
        _check_name(name)
        return self._values.pop(name, None) is not None

    def __repr__(self):
        # Count, never names and never values. A name is not a value, but a list
        # of them in a repr is a shape somebody will paste into a ticket.
        return f"MemoryBackend(entries={len(self._values)})"

    __str__ = __repr__


_WINDOWS = None


def _windows_bindings():
    """ctypes bindings for advapi32 and crypt32, built once.

    Deferred rather than done at import, because `ctypes.wintypes` itself raises
    on Linux (VARIANT_BOOL has no non-Windows equivalent) and this module must
    import cleanly where the suite runs.
    """
    global _WINDOWS
    if _WINDOWS is not None:
        if isinstance(_WINDOWS, str):
            raise BackendUnavailable(_WINDOWS)
        return _WINDOWS
    reason = _build_windows_bindings()
    if isinstance(reason, str):
        _WINDOWS = reason
        raise BackendUnavailable(reason)
    _WINDOWS = reason
    return _WINDOWS


def _build_windows_bindings():
    if sys.platform != "win32":
        return (f"the Windows Credential Manager and DPAPI are Windows-only; "
                f"this is sys.platform={sys.platform!r}")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        return "ctypes has no WinDLL on this interpreter"
    try:
        from ctypes import wintypes
    except (ImportError, ValueError) as exc:
        return f"ctypes.wintypes is unusable here ({type(exc).__name__})"
    try:
        advapi32 = loader("advapi32", use_last_error=True)
        crypt32 = loader("crypt32", use_last_error=True)
        kernel32 = loader("kernel32", use_last_error=True)
    except OSError as exc:
        return f"a system DLL could not be loaded ({type(exc).__name__})"

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
        _fields_ = [("Keyword", wintypes.LPWSTR),
                    ("Flags", wintypes.DWORD),
                    ("ValueSize", wintypes.DWORD),
                    ("Value", ctypes.POINTER(ctypes.c_byte))]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR),
                    ("LastWritten", FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
                    ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    try:
        advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi32.CredDeleteW.restype = wintypes.BOOL
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        advapi32.CredFree.restype = None
        crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR,
                                             ctypes.POINTER(DATA_BLOB), ctypes.c_void_p,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p,
                                               ctypes.POINTER(DATA_BLOB), ctypes.c_void_p,
                                               ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
    except AttributeError as exc:
        return f"a required system entry point is missing ({exc.args[0] if exc.args else 'unknown'})"

    return {"advapi32": advapi32, "crypt32": crypt32, "kernel32": kernel32,
            "CREDENTIALW": CREDENTIALW, "DATA_BLOB": DATA_BLOB, "wintypes": wintypes}


# Windows constants, named rather than inlined so a failure message can say
# which one it means.
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
CRYPTPROTECT_UI_FORBIDDEN = 0x1

_WIN_ERRORS = {
    1168: "ERROR_NOT_FOUND",
    5: "ERROR_ACCESS_DENIED",
    87: "ERROR_INVALID_PARAMETER",
    1004: "ERROR_INVALID_FLAGS",
    13: "ERROR_INVALID_DATA",
    1312: "ERROR_NO_SUCH_LOGON_SESSION",
}


def _win_error(code):
    """A code AND its symbolic name. `CredWriteW failed (87)` sends the reader to
    a search engine; `ERROR_INVALID_PARAMETER` tells them what to look at."""
    return f"{_WIN_ERRORS.get(code, 'error')} ({code})"


class WindowsCredentialManagerBackend(Backend):
    """advapi32 CredReadW / CredWriteW / CredDeleteW. The preferred backend.

    Entries are generic credentials under a shared target prefix, persisted
    local-machine. The blob is UTF-16-LE so the Credential Manager UI renders it
    as text rather than as a hex dump - which is the whole argument for choosing
    this over a DPAPI blob. An operator who wants to know what is stored, or to
    revoke it, should not need this module to do either.
    """

    name = "windows-credential-manager"

    @classmethod
    def unavailable_reason(cls):
        try:
            _windows_bindings()
        except BackendUnavailable as exc:
            return str(exc)
        return None

    def _target(self, name):
        return TARGET_PREFIX + name

    def get(self, name):
        _check_name(name)
        win = _windows_bindings()
        pointer = ctypes.POINTER(win["CREDENTIALW"])()
        ctypes.set_last_error(0)
        ok = win["advapi32"].CredReadW(self._target(name), CRED_TYPE_GENERIC, 0,
                                       ctypes.byref(pointer))
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                LOG.debug("creds: %s not found in %s", name, self.name)
                return None
            _fail(f"reading {name!r} from the Windows Credential Manager failed: {_win_error(code)}")
        try:
            record = pointer.contents
            size = int(record.CredentialBlobSize)
            if size <= 0:
                return None
            raw = ctypes.string_at(record.CredentialBlob, size)
            value = _decode_blob(name, raw)
        finally:
            win["advapi32"].CredFree(ctypes.cast(pointer, ctypes.c_void_p))
        LOG.debug("creds: read %s from %s", name, self.name)
        return Credential(name, value, source=self.name)

    def put(self, name, value):
        _check_name(name)
        encoded = _check_value(name, value)
        win = _windows_bindings()
        # A buffer this process owns, so it can be zeroed after the call.
        # CPython cannot zero the str - it is immutable and may be interned -
        # but it can refuse to leave a second copy lying in the heap.
        buffer = ctypes.create_string_buffer(encoded, len(encoded))
        record = win["CREDENTIALW"]()
        record.Type = CRED_TYPE_GENERIC
        record.TargetName = self._target(name)
        record.Comment = "agentmux broker credential"
        record.CredentialBlobSize = len(encoded)
        record.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        record.Persist = CRED_PERSIST_LOCAL_MACHINE
        record.UserName = TARGET_USER
        ctypes.set_last_error(0)
        ok = win["advapi32"].CredWriteW(ctypes.byref(record), 0)
        code = ctypes.get_last_error()
        ctypes.memset(buffer, 0, len(encoded))
        del encoded
        if not ok:
            _fail(f"writing {name!r} to the Windows Credential Manager failed: {_win_error(code)}")
        LOG.info("creds: stored %s in %s", name, self.name)

    def delete(self, name):
        _check_name(name)
        win = _windows_bindings()
        ctypes.set_last_error(0)
        ok = win["advapi32"].CredDeleteW(self._target(name), CRED_TYPE_GENERIC, 0)
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                return False
            _fail(f"deleting {name!r} from the Windows Credential Manager failed: {_win_error(code)}")
        LOG.info("creds: deleted %s from %s", name, self.name)
        return True


class DpapiBackend(Backend):
    """crypt32 CryptProtectData / CryptUnprotectData over a file. THE FALLBACK.

    WHY IT IS THE FALLBACK AND NOT THE PRIMARY. The cryptography is the same
    machinery the Credential Manager uses underneath, and the protection is
    equivalent: the blob is bound to the user account and is unreadable by
    another. What is missing is everything AROUND it.

      There is no OS UI. `control /name Microsoft.CredentialManager` lists every
      Credential Manager entry with its last-written date and revokes one with a
      click. A DPAPI blob is a file at a path, and an operator can only inspect
      or revoke it if they still know the file exists. Eighteen months later,
      they do not.

      Revocation becomes a delete of a file nobody has a reason to look for, and
      an audit becomes a directory listing somebody has to be told about.

    So this is here for a machine where advapi32 cannot be reached, and it says
    so. The blob lands under broker_root() - outside the repo, per
    docs/investing-boundary.md - at mode 0600, written through a temp file so it
    is never briefly readable by anyone else.

    The optional entropy is derived from the name, so a blob moved to another
    name does not decrypt: a file rename should not silently repoint a
    credential.
    """

    name = "dpapi"
    writes_files = True

    def __init__(self, root=None):
        self.root = Path(broker_root(root)) / "credentials"

    @classmethod
    def unavailable_reason(cls):
        try:
            _windows_bindings()
        except BackendUnavailable as exc:
            return str(exc)
        return None

    def path_for(self, name):
        _check_name(name)
        # NAME_PATTERN already excludes a separator and a leading dot, so this
        # cannot escape the directory; check_not_forbidden is belt and braces
        # against a future loosening of the pattern.
        return check_not_forbidden(self.root / f"{name}.dpapi")

    def _blobs(self, win, data, entropy):
        DATA_BLOB = win["DATA_BLOB"]
        source = DATA_BLOB()
        source.cbData = len(data)
        source_buffer = ctypes.create_string_buffer(data, len(data))
        source.pbData = ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
        extra = DATA_BLOB()
        extra.cbData = len(entropy)
        extra_buffer = ctypes.create_string_buffer(entropy, len(entropy))
        extra.pbData = ctypes.cast(extra_buffer, ctypes.POINTER(ctypes.c_byte))
        return source, source_buffer, extra, extra_buffer

    def _entropy(self, name):
        return hashlib.sha256(FINGERPRINT_DOMAIN + b"|entropy|"
                              + name.encode("utf-8")).digest()

    def get(self, name):
        path = self.path_for(name)
        stored, detail = None, None
        try:
            if not path.is_file():
                return None
            stored = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            # "could not find out" is not "not there" - dashboard/ninep.py.
            detail = exc.strerror or type(exc).__name__
        if detail is not None:
            _fail(f"the DPAPI blob for {name!r} could not be read: {detail}")
        win = _windows_bindings()
        DATA_BLOB = win["DATA_BLOB"]
        source, _sbuf, extra, _ebuf = self._blobs(win, stored, self._entropy(name))
        out = DATA_BLOB()
        ctypes.set_last_error(0)
        ok = win["crypt32"].CryptUnprotectData(ctypes.byref(source), None,
                                               ctypes.byref(extra), None, None,
                                               CRYPTPROTECT_UI_FORBIDDEN,
                                               ctypes.byref(out))
        if not ok:
            code = ctypes.get_last_error()
            _fail(f"unprotecting the DPAPI blob for {name!r} failed: {_win_error(code)}")
        try:
            raw = ctypes.string_at(out.pbData, int(out.cbData))
            value = _decode_blob(name, raw)
        finally:
            ctypes.memset(out.pbData, 0, int(out.cbData))
            win["kernel32"].LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
        LOG.debug("creds: read %s from %s", name, self.name)
        return Credential(name, value, source=self.name)

    def put(self, name, value):
        path = self.path_for(name)
        encoded = _check_value(name, value)
        win = _windows_bindings()
        DATA_BLOB = win["DATA_BLOB"]
        source, source_buffer, extra, _ebuf = self._blobs(win, encoded, self._entropy(name))
        out = DATA_BLOB()
        ctypes.set_last_error(0)
        ok = win["crypt32"].CryptProtectData(ctypes.byref(source), f"agentmux:{name}",
                                             ctypes.byref(extra), None, None,
                                             CRYPTPROTECT_UI_FORBIDDEN,
                                             ctypes.byref(out))
        code = ctypes.get_last_error()
        ctypes.memset(source_buffer, 0, len(encoded))
        del encoded
        if not ok:
            _fail(f"protecting {name!r} with DPAPI failed: {_win_error(code)}")
        try:
            protected = ctypes.string_at(out.pbData, int(out.cbData))
        finally:
            win["kernel32"].LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
        self._write_private(path, protected, name)
        LOG.info("creds: stored %s in %s", name, self.name)

    def _write_private(self, path, blob, name):
        """0600 from creation, via a temp file in the same directory.

        The same shape dashboard/server.py uses for the auth settings: a file
        written and then chmod'd is briefly world-readable, and briefly is
        enough.
        """
        check_not_forbidden(path)
        temporary = path.with_suffix(".tmp")
        check_not_forbidden(temporary)
        previous_umask, detail = None, None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "umask"):
                previous_umask = os.umask(0o077)
            with open(temporary, "wb") as handle:
                handle.write(blob)
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass            # NTFS ACLs govern here; the mode is decoration
            os.replace(temporary, path)
        except OSError as exc:
            detail = exc.strerror or type(exc).__name__
        finally:
            if previous_umask is not None:
                os.umask(previous_umask)
        if detail is not None:
            _fail(f"the DPAPI blob for {name!r} could not be written: {detail}")

    def delete(self, name):
        path = self.path_for(name)
        detail = None
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            detail = exc.strerror or type(exc).__name__
        if detail is not None:
            _fail(f"the DPAPI blob for {name!r} could not be deleted: {detail}")
        LOG.info("creds: deleted %s from %s", name, self.name)
        return True

    def __repr__(self):
        return f"DpapiBackend(root={str(self.root)!r})"

    __str__ = __repr__


# Preference order. The Credential Manager first, DPAPI as the stated fallback,
# and memory NOT in this list - it is opt-in only, see open_store().
BACKENDS = (WindowsCredentialManagerBackend, DpapiBackend)


def backend_availability():
    """{backend name: None or the reason it cannot run here}.

    What a suite reads to SKIP with a stated cause. A skip that says "windows
    credential manager: the Windows Credential Manager and DPAPI are Windows-
    only; this is sys.platform='linux'" is information. A silent pass is not.
    """
    return {cls.name: cls.unavailable_reason() for cls in BACKENDS}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class CredentialStore:
    """get / put / delete / describe over one backend.

    `describe()` is the only surface meant for a response body, and it cannot
    carry a value - see Description. `get()` is the only surface that can, and
    what it hands back is a Credential rather than a str.
    """

    def __init__(self, backend):
        if not isinstance(backend, Backend):
            _fail(f"a CredentialStore needs a Backend, got {type(backend).__name__}")
        self.backend = backend

    @property
    def source(self):
        return self.backend.name

    def get(self, name):
        """The Credential, or None when there is no such entry.

        Raises rather than returning None when the backend could not answer:
        a caller that treats "unreadable" as "unset" prompts for a credential
        that is already there, and the operator types it again somewhere worse.
        """
        _check_name(name)
        return self.backend.get(name)

    def put(self, name, value):
        _check_name(name)
        self.backend.put(name, value)

    def delete(self, name):
        """True when something was removed, False when there was nothing to remove."""
        _check_name(name)
        return self.backend.delete(name)

    def describe(self, name):
        """Presence, provenance and a fingerprint. Never the value.

        Never raises: a description is what a status surface renders, and a
        status surface that throws tells the operator nothing at all. A backend
        failure becomes `known=False` with the reason attached, which is the
        distinction ninep.py keeps and the one a UI has to render differently.
        """
        try:
            _check_name(name)
        except CredentialError as exc:
            return unknown(str(name)[:64], self.source, str(exc))
        try:
            credential = self.backend.get(name)
        except CredentialError as exc:
            return unknown(name, self.source, str(exc))
        except OSError as exc:
            return unknown(name, self.source,
                           f"the backend raised {type(exc).__name__}")
        if credential is None:
            return absent(name, self.source)
        return credential.describe()

    def snapshot(self, names):
        """The payload shape for a status route: a list of describe() dicts.

        Here rather than in a handler so there is exactly one place that builds
        it, and so the sentinel suite has one thing to grep rather than one per
        future endpoint.
        """
        return [self.describe(name).as_dict() for name in names]

    def __repr__(self):
        return f"CredentialStore(backend={self.backend!r})"

    __str__ = __repr__


class NoBackend(CredentialError):
    """No OS credential store here, and the message lists what was tried.

    A distinct type so a caller can offer the operator the fallback, rather than
    catching every CredentialError and guessing which one this was.
    """


def open_store(prefer=None, *, root=None, allow_memory=False):
    """The first usable backend, in preference order.

    MEMORY IS NEVER CHOSEN AUTOMATICALLY. `allow_memory=True` is an explicit
    opt-in for a test, because falling back to a store that forgets everything
    at process exit would look exactly like working, right up until the moment
    the credential was needed again - and the operator would re-enter it, which
    is the thing this module exists to make unnecessary.
    """
    reasons = []
    order = BACKENDS
    if prefer:
        order = tuple(cls for cls in BACKENDS if cls.name == prefer) + \
                tuple(cls for cls in BACKENDS if cls.name != prefer)
        if not any(cls.name == prefer for cls in BACKENDS) and not (
                allow_memory and prefer == MemoryBackend.name):
            _fail(f"{prefer!r} is not a known backend")
    if prefer == MemoryBackend.name and allow_memory:
        return CredentialStore(MemoryBackend())
    for cls in order:
        reason = cls.unavailable_reason()
        if reason is None:
            backend = cls(root=root) if cls is DpapiBackend else cls()
            LOG.info("creds: using the %s backend", backend.name)
            return CredentialStore(backend)
        reasons.append(f"{cls.name}: {reason}")
    if allow_memory:
        LOG.warning("creds: falling back to the in-memory backend; nothing is persisted")
        return CredentialStore(MemoryBackend())
    raise NoBackend("no OS credential store is usable here - "
                    + "; ".join(reasons)
                    + ". Pass allow_memory=True only in a test.")


def main(argv=None):
    """Report what is available here. Presence only, and nothing is written."""
    argv = list(sys.argv[1:] if argv is None else argv)
    print("backends:")
    for name, reason in backend_availability().items():
        print(f"  {name:32} {'available' if reason is None else 'unavailable: ' + reason}")
    if argv:
        try:
            store = open_store()
        except NoBackend as exc:
            print(f"  {exc}")
            return 1
        for name in argv:
            print("  " + repr(store.describe(name).as_dict()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
