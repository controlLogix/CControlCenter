"""The selector registry: one locator or none, and drift arms the switch.

THREE PROPERTIES CARRY THIS FILE, and only one of them is about today's code.

  NEVER A FALLBACK, ENFORCED. SurfaceTests is written for whoever adds the next
  method rather than for the current one: a new public callable that could hand
  back a guessed locator fails until somebody classifies it, exactly as the
  Rockwell write-capability whitelist does. A comment asking for the same thing
  survives one author. The loader half is the other side of it - a map that
  carries a `fallback` key is REFUSED BY NAME, not ignored, because an operator
  who wrote one believes there is a safety net under the Place Order button.

  THE SWITCH IS ARMED EVEN WHEN THE EVIDENCE FAILS. OrderingTests makes the
  capture raise, the journal raise, and the session-state write raise, one at a
  time and all at once, and asserts `killswitch.allowed()` is False afterwards
  every time. A screenshot that could not be written is not a reason to leave
  trading enabled, and that is the whole ordering argument in one assertion.

  NOTHING RE-VERIFIES ITSELF. A probe that passes does not touch
  `last_verified` and does not clear `stale`; the sweep is proved to write no
  bytes at all. An entry that re-verifies itself replaces "somebody checked"
  with "the software decided it was fine", which is the fallback locator again
  in a different costume.

No browser, no network, no clock dependence beyond an injected `now`. The
capture function is a fake that writes two files into a temporary directory.
"""

import ast
import inspect
import json
import os
import sys
import tempfile
import textwrap
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
try:
    import killswitch
    import selectormap
except ImportError as exc:      # a tree without the module - see _NeedsSelectors
    killswitch = selectormap = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


# A Friday. Fixed, so "stale" is a fact about the data and not about the day the
# suite happens to run.
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).timestamp()

# A map shaped like an operator's, with locators that are obviously not real.
GOOD = {
    "version": 1,
    "venue": "example-venue",
    "entries": {
        "order.placeButton": {
            "locator": "css=#example-place-order",
            "probe": {"kind": "role_and_name", "expect": "Place Order"},
            "last_verified": "2026-09-20",
        },
        "order.previewButton": {
            "locator": "css=#example-preview-order",
            "probe": {"kind": "role_and_name", "expect": "Preview Order"},
            "last_verified": "2026-01-01",
        },
        "order.quantity": {
            "locator": "css=#example-quantity",
            "probe": {"kind": "unique_match", "expect": None},
            "last_verified": None,
            "note": "never verified on this machine",
        },
    },
}

GUARDRAILS = {"max_notional": 25000}


def _module_publics():
    """Public names DEFINED here - not the imports that happen to be visible."""
    found = {}
    for name in dir(selectormap):
        if name.startswith("_"):
            continue
        value = getattr(selectormap, name)
        if isinstance(value, types.ModuleType):
            continue
        if callable(value) and \
                getattr(value, "__module__", None) != selectormap.__name__:
            continue
        found[name] = value
    return found


class _NeedsSelectors(unittest.TestCase):
    def setUp(self):
        if selectormap is None:
            self.fail(f"agentmux-broker/selectormap.py is missing: {IMPORT_ERROR}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "broker"
        self.root.mkdir(parents=True)

    def write_map(self, data=None):
        path = selectormap.registry_path(self.root)
        path.write_text(json.dumps(data if data is not None else GOOD),
                        encoding="utf-8")
        return path

    def registry(self, data=None):
        self.write_map(data)
        return selectormap.load(root=self.root)

    def disarm(self):
        killswitch.disarm(killswitch.DISARM_PHRASE, actor="operator",
                          config=GUARDRAILS, root=self.root, ttl=600)
        assert killswitch.allowed(self.root, config=GUARDRAILS)

    def capture(self, dest, context):
        (dest / "screenshot.png").write_bytes(b"\x89PNG-not-really")
        (dest / "dom.html").write_text("<html>page</html>", encoding="utf-8")
        return None

    def drift(self, **kw):
        kw.setdefault("capture", self.capture)
        kw.setdefault("root", self.root)
        kw.setdefault("now", NOW)
        with self.assertRaises(selectormap.SelectorDrift) as caught:
            selectormap.on_drift("order.placeButton",
                                      "the locator matched nothing", **kw)
        return caught.exception

    def tree(self):
        """Every file under the broker root, by path and bytes."""
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in sorted(self.root.rglob("*")) if p.is_file()}


# -- never a fallback, enforced ----------------------------------------------

class SurfaceTests(_NeedsSelectors):
    def test_resolve_is_the_only_thing_that_hands_back_a_locator(self):
        # Written for whoever adds the next method. A second way to get a
        # locator is where a fallback lands, and it will not be called one.
        self.assertEqual(selectormap.LOCATOR_RETURNING, ("resolve",))
        public = {name for name in dir(selectormap.Registry)
                  if not name.startswith("_")}
        callables = {name for name in public
                     if callable(getattr(selectormap.Registry, name, None))}
        self.assertEqual(callables, {"names", "entry", "resolve"},
                         "a new public method on Registry is unclassified; decide "
                         "whether it returns a locator, do not widen this set to "
                         "make the test pass")

    def test_the_module_surface_is_exactly_what_is_declared(self):
        declared = {
            "SelectorDrift", "RegistryError", "Registry",
            "registry_path", "capture_dir", "journal_path", "session_state_path",
            "default_registry", "load", "resolve", "degrade", "session_state",
            "on_drift", "verify_all",
        }
        found = {name for name, value in _module_publics().items()
                 if callable(value)}
        self.assertEqual(found, declared,
                         "a new public callable is unclassified; a function that "
                         "could return a guessed locator must fail this test until "
                         "somebody says what it does")

    def test_no_public_name_uses_the_vocabulary_of_guessing(self):
        # GUESSING is exempt: it is the declaration of the banned words, and the
        # loader refuses map keys with the same constant.
        for name in _module_publics():
            if name == "GUESSING":
                continue
            for word in selectormap.GUESSING:
                self.assertNotIn(word, name.lower(),
                                 f"{name} reads as a fallback path")

    def test_resolve_takes_no_default_or_fallback_argument(self):
        # A parameter is how a fallback gets added without anyone calling it
        # one, so the signature is asserted EXACTLY rather than scanned.
        self.assertEqual(
            set(inspect.signature(selectormap.Registry.resolve).parameters),
            {"self", "name"})
        self.assertEqual(
            set(inspect.signature(selectormap.resolve).parameters),
            {"name", "registry", "root"})

    def test_on_drift_cannot_be_asked_not_to_arm(self):
        params = set(inspect.signature(selectormap.on_drift).parameters)
        self.assertEqual(params, {"name", "detail", "capture", "root", "journal",
                                  "now"})
        for opt_out in ("arm", "no_arm", "skip_arm", "dry_run", "quiet", "soft"):
            self.assertNotIn(opt_out, params)

    def test_on_drift_has_no_return_statement_at_all(self):
        # It must not return normally as if nothing happened. Structural, not a
        # promise: a handler that can return is one somebody wraps and continues
        # past.
        source = textwrap.dedent(inspect.getsource(selectormap.on_drift))
        tree = ast.parse(source)
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Return)],
                         [])
        body = tree.body[0].body
        self.assertIsInstance(body[-1], ast.Raise)

    def test_entry_metadata_never_carries_the_locator(self):
        registry = self.registry()
        for name in registry.names():
            meta = registry.entry(name)
            self.assertNotIn("locator", meta)
            locator = GOOD["entries"][name]["locator"]
            self.assertNotIn(locator, repr(meta),
                             "entry() leaked a locator; resolve() is the only "
                             "way to get one")

    def test_the_drift_reason_is_one_the_kill_switch_accepts(self):
        # A reason killswitch.arm() rejects would raise ValueError at the exact
        # moment the switch most needs arming.
        self.assertIn(selectormap.DRIFT_REASON, killswitch.REARM_REASONS)


# -- the loader ---------------------------------------------------------------

class LoaderTests(_NeedsSelectors):
    def test_a_missing_map_loads_placeholders_that_resolve_nothing(self):
        registry = selectormap.load(root=self.root)
        self.assertFalse(registry.installed)
        self.assertTrue(registry.names())
        for name in registry.names():
            with self.subTest(name=name), \
                 self.assertRaises(selectormap.SelectorDrift):
                registry.resolve(name)

    def test_the_shipped_map_contains_no_real_locator(self):
        # THIS REPO IS PUBLIC. A checkout must not be able to click anything.
        shipped = selectormap.default_registry()
        for name, entry in shipped["entries"].items():
            with self.subTest(name=name):
                self.assertTrue(
                    entry["locator"].startswith(selectormap.PLACEHOLDER_PREFIX))
                self.assertIsNone(entry["last_verified"])
        self.assertNotIn("fidelity", json.dumps(shipped).lower(),
                         "the shipped map names a venue; the real map is "
                         "operator-supplied and lives outside this repo")

    def test_an_unknown_schema_version_is_refused_not_guessed_at(self):
        for version in (2, 0, None, "1"):
            with self.subTest(version=version), \
                 self.assertRaises(selectormap.RegistryError):
                self.registry(dict(GOOD, version=version))

    def test_malformed_json_is_refused_rather_than_half_read(self):
        path = selectormap.registry_path(self.root)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(selectormap.RegistryError):
            selectormap.load(root=self.root)

    def test_an_entry_missing_its_probe_or_date_is_refused(self):
        for dropped in ("locator", "probe", "last_verified"):
            entries = json.loads(json.dumps(GOOD["entries"]))
            del entries["order.placeButton"][dropped]
            with self.subTest(dropped=dropped), \
                 self.assertRaises(selectormap.RegistryError):
                self.registry(dict(GOOD, entries=entries))

    def test_a_list_of_locators_is_refused_as_a_fallback_chain(self):
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.placeButton"]["locator"] = ["css=#a", "css=#b"]
        with self.assertRaises(selectormap.RegistryError) as caught:
            self.registry(dict(GOOD, entries=entries))
        self.assertIn("fallback chain", str(caught.exception))

    def test_a_fallback_key_is_refused_by_name_not_ignored(self):
        # Ignoring it would leave the operator believing there is a safety net
        # under the Place Order button.
        for key in ("fallback", "candidates", "alternates", "retry", "any_of"):
            entries = json.loads(json.dumps(GOOD["entries"]))
            entries["order.placeButton"][key] = "css=#something-else"
            with self.subTest(key=key), \
                 self.assertRaises(selectormap.RegistryError) as caught:
                self.registry(dict(GOOD, entries=entries))
            self.assertIn(key, str(caught.exception))

    def test_two_names_sharing_one_locator_are_refused(self):
        # Map Preview and Place to the same node and the dry run places the
        # order. Same failure as guessing, wearing a different hat.
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.previewButton"]["locator"] = \
            entries["order.placeButton"]["locator"]
        with self.assertRaises(selectormap.RegistryError) as caught:
            self.registry(dict(GOOD, entries=entries))
        self.assertIn("order.previewButton", str(caught.exception))

    def test_an_unknown_probe_kind_is_refused(self):
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.placeButton"]["probe"] = {"kind": "looks_about_right"}
        with self.assertRaises(selectormap.RegistryError):
            self.registry(dict(GOOD, entries=entries))

    def test_an_unreadable_date_is_refused_rather_than_treated_as_never(self):
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.placeButton"]["last_verified"] = "last Tuesday"
        with self.assertRaises(selectormap.RegistryError):
            self.registry(dict(GOOD, entries=entries))

    def test_an_unknown_entry_key_is_refused(self):
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.placeButton"]["timeout_ms"] = 5000
        with self.assertRaises(selectormap.RegistryError):
            self.registry(dict(GOOD, entries=entries))

    def test_the_map_is_re_read_and_never_cached(self):
        # A cached map means an operator's fix does not take effect until a
        # restart, and a stale map is the failure this module exists to catch.
        self.write_map()
        self.assertEqual(
            selectormap.resolve("order.placeButton", root=self.root),
            "css=#example-place-order")
        moved = json.loads(json.dumps(GOOD))
        moved["entries"]["order.placeButton"]["locator"] = "css=#moved"
        self.write_map(moved)
        self.assertEqual(
            selectormap.resolve("order.placeButton", root=self.root),
            "css=#moved")

    def test_every_path_this_module_writes_to_is_outside_the_repo(self):
        repo = Path(selectormap.__file__).resolve().parents[1]
        # ABSOLUTE for whichever platform is running, because capture_dir()
        # validates the path rather than just joining it. A Windows LOCALAPPDATA
        # string is not an absolute path on POSIX, so resolve() would anchor it
        # on the cwd - which under the gate IS the repo, and the guard would
        # then fire on the test rather than on a real misconfiguration.
        local = (r"C:\Users\x\AppData\Local" if os.name == "nt"
                 else "/home/x/.local/share")
        with patch.dict(os.environ, {"LOCALAPPDATA": local}):
            for path in (selectormap.registry_path(),
                         selectormap.capture_dir(),
                         selectormap.journal_path(),
                         selectormap.session_state_path()):
                with self.subTest(path=str(path)):
                    self.assertIn("agentmux", str(path))
                    self.assertNotIn(str(repo).lower(), str(path).lower())

    def test_a_capture_path_inside_the_repo_is_refused(self):
        # The .gitignore pin makes a stray write land ignored. This refuses to
        # make the write at all.
        repo = Path(selectormap.__file__).resolve().parents[1]
        with self.assertRaises(selectormap.RegistryError):
            selectormap.capture_dir(repo / "agentmux-broker")


# -- resolve ------------------------------------------------------------------

class ResolveTests(_NeedsSelectors):
    def test_a_known_entry_returns_exactly_the_configured_locator(self):
        registry = self.registry()
        self.assertEqual(registry.resolve("order.placeButton"),
                         "css=#example-place-order")

    def test_an_unknown_name_drifts_rather_than_guessing(self):
        registry = self.registry()
        with self.assertRaises(selectormap.SelectorDrift) as caught:
            registry.resolve("order.placeButtonV2")
        self.assertEqual(caught.exception.name, "order.placeButtonV2")

    def test_a_placeholder_never_resolves_even_when_the_name_is_known(self):
        entries = json.loads(json.dumps(GOOD["entries"]))
        entries["order.placeButton"]["locator"] = \
            selectormap.PLACEHOLDER_PREFIX + ": fill this in"
        registry = self.registry(dict(GOOD, entries=entries))
        with self.assertRaises(selectormap.SelectorDrift) as caught:
            registry.resolve("order.placeButton")
        self.assertIn("placeholder", str(caught.exception).lower())

    def test_the_drift_carries_no_suggestion_of_what_to_click_instead(self):
        registry = self.registry()
        with self.assertRaises(selectormap.SelectorDrift) as caught:
            registry.resolve("order.notAThing")
        drift = caught.exception
        for other in ("css=#example-place-order", "css=#example-preview-order",
                      "css=#example-quantity"):
            self.assertNotIn(other, str(drift))
        for word in selectormap.GUESSING:
            self.assertFalse(hasattr(drift, word), f"the drift offers {word}")

    def test_a_drift_from_resolve_has_not_yet_been_responded_to(self):
        # `record is None` is how an operator tells a drift somebody caught and
        # ignored from one that was handled.
        registry = self.registry()
        with self.assertRaises(selectormap.SelectorDrift) as caught:
            registry.resolve("order.nope")
        self.assertIsNone(caught.exception.record)


# -- the drift response -------------------------------------------------------

class DriftResponseTests(_NeedsSelectors):
    def test_on_drift_never_returns_normally(self):
        self.disarm()
        drift = self.drift()
        self.assertEqual(drift.name, "order.placeButton")
        self.assertIn("order.placeButton", str(drift))

    def test_the_steps_run_in_the_plan_s_order(self):
        self.disarm()
        drift = self.drift()
        self.assertEqual([s["step"] for s in drift.record["steps"]],
                         ["capture", "journal", "degrade", "arm"])
        self.assertTrue(all(s["ok"] for s in drift.record["steps"]))

    def test_the_evidence_lands_outside_the_repo(self):
        self.disarm()
        drift = self.drift()
        dest = Path(drift.record["evidence"])
        self.assertTrue(dest.is_dir())
        self.assertEqual(sorted(p.name for p in dest.iterdir()),
                         ["dom.html", "screenshot.png"])
        repo = Path(selectormap.__file__).resolve().parents[1]
        self.assertNotIn(str(repo).lower(), str(dest).lower())

    def test_a_journal_record_is_written_with_no_page_content_in_it(self):
        self.disarm()
        self.drift()
        rows = [json.loads(line) for line in
                selectormap.journal_path(self.root)
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "selector_drift")
        self.assertEqual(rows[0]["selector"], "order.placeButton")
        self.assertEqual(rows[0]["outcome"], "unknown")
        # The evidence is referenced by path. Copying a DOM snapshot of a
        # brokerage page into a second file helps nobody.
        self.assertNotIn("<html>", json.dumps(rows[0]))

    def test_the_session_goes_degraded(self):
        self.assertEqual(selectormap.session_state(self.root)["state"], "OK")
        self.disarm()
        self.drift()
        state = selectormap.session_state(self.root)
        self.assertEqual(state["state"], "DEGRADED")
        self.assertIn("order.placeButton", state["reason"])

    def test_the_kill_switch_is_armed(self):
        self.disarm()
        drift = self.drift()
        self.assertTrue(drift.record["armed"])
        self.assertFalse(killswitch.allowed(self.root, config=GUARDRAILS))
        last = json.loads((self.root / "last-rearm.json").read_text())
        self.assertEqual(last["reason"], "selector_drift")

    def test_the_sentinel_is_not_written_on_the_ordinary_path(self):
        # It is the last resort, not the routine response: clearing it is a
        # manual act and a routine one would be automated away.
        self.disarm()
        self.drift()
        self.assertFalse((self.root / killswitch.SENTINEL_NAME).exists())

    def test_a_degraded_session_does_not_clear_itself(self):
        self.disarm()
        self.drift()
        for _ in range(3):
            self.assertEqual(selectormap.session_state(self.root)["state"],
                             "DEGRADED")

    def test_an_unreadable_session_state_reads_degraded_not_ok(self):
        selectormap.session_state_path(self.root).write_text(
            "not json", encoding="utf-8")
        self.assertEqual(selectormap.session_state(self.root)["state"],
                         "DEGRADED")


# -- the ordering proof -------------------------------------------------------

class OrderingTests(_NeedsSelectors):
    """The switch is armed even when everything before it fails."""

    def assert_disabled(self, drift):
        self.assertTrue(drift.record["armed"])
        self.assertFalse(killswitch.allowed(self.root, config=GUARDRAILS))

    def test_the_switch_is_armed_even_when_the_capture_raises(self):
        # THE test named in the brief. A screenshot failing is not a reason to
        # leave trading enabled.
        def boom(dest, context):
            raise OSError("the screenshot could not be written")

        self.disarm()
        drift = self.drift(capture=boom)
        self.assert_disabled(drift)
        capture_step = drift.record["steps"][0]
        self.assertEqual(capture_step["step"], "capture")
        self.assertFalse(capture_step["ok"])
        self.assertIsNone(drift.record["evidence"])

    def test_a_failed_capture_is_recorded_not_swallowed(self):
        def boom(dest, context):
            raise RuntimeError("chromium is gone")

        self.disarm()
        drift = self.drift(capture=boom)
        self.assertIn("chromium is gone", drift.record["steps"][0]["note"])
        self.assertIn("NOT CAPTURED", str(drift))

    def test_the_switch_is_armed_when_no_capture_function_is_supplied(self):
        self.disarm()
        drift = self.drift(capture=None)
        self.assert_disabled(drift)
        self.assertFalse(drift.record["steps"][0]["ok"])

    def test_the_switch_is_armed_even_when_the_journal_write_fails(self):
        class BrokenJournal:
            transport = "broker"

            def append(self, record):
                raise OSError("no space left on device")

        self.disarm()
        drift = self.drift(journal=BrokenJournal())
        self.assert_disabled(drift)
        self.assertFalse(drift.record["journalled"])

    def test_the_switch_is_armed_even_when_the_session_state_cannot_be_written(self):
        def boom(*args, **kwargs):
            raise OSError("read-only filesystem")

        self.disarm()
        with patch.object(selectormap, "degrade", boom):
            drift = self.drift()
        self.assert_disabled(drift)
        self.assertIsNone(drift.record["state"])

    def test_the_switch_is_armed_when_every_earlier_step_fails_at_once(self):
        class BrokenJournal:
            transport = "broker"

            def append(self, record):
                raise OSError("no space left on device")

        def boom(dest, context):
            raise OSError("no screenshot")

        def no_state(*args, **kwargs):
            raise OSError("read-only filesystem")

        self.disarm()
        with patch.object(selectormap, "degrade", no_state):
            drift = self.drift(capture=boom, journal=BrokenJournal())
        self.assert_disabled(drift)
        self.assertEqual([s["ok"] for s in drift.record["steps"]],
                         [False, False, False, True])

    def test_a_switch_that_will_not_arm_escalates_to_the_sentinel(self):
        # killswitch.arm() swallows an OSError while removing the disarm record,
        # so a returning arm() is not proof. The arm is VERIFIED, and a switch
        # that is still permitting after it gets the installer sentinel - the
        # documented hard stop, cleared only by hand.
        self.disarm()
        with patch.object(selectormap.killswitch, "arm",
                          lambda reason, root=None: {"armed_at": 0}):
            drift = self.drift()
        self.assertTrue(drift.record["sentinel"])
        self.assert_disabled(drift)
        self.assertTrue((self.root / killswitch.SENTINEL_NAME).exists())

    def test_the_alert_says_plainly_whether_trading_is_disabled(self):
        self.disarm()
        self.assertIn("disabled", str(self.drift()))


# -- the staleness sweep ------------------------------------------------------

class VerifyAllTests(_NeedsSelectors):
    def report(self, **kw):
        kw.setdefault("root", self.root)
        kw.setdefault("now", NOW)
        return selectormap.verify_all(self.registry(), **kw)

    def named(self, report, name):
        return next(e for e in report["entries"] if e["name"] == name)

    def test_a_stale_entry_is_reported(self):
        report = self.report()
        self.assertIn("order.previewButton", report["stale"])
        entry = self.named(report, "order.previewButton")
        self.assertTrue(entry["stale"])
        self.assertGreater(entry["age_days"], 200)

    def test_a_recently_verified_entry_is_not_reported_stale(self):
        entry = self.named(self.report(), "order.placeButton")
        self.assertFalse(entry["stale"])
        self.assertLess(entry["age_days"], 10)

    def test_an_entry_never_verified_is_stale_not_fresh(self):
        # A missing date must never read as a recent one - the same discipline
        # as an unpriced order never reading as a small one.
        entry = self.named(self.report(), "order.quantity")
        self.assertTrue(entry["stale"])
        self.assertIsNone(entry["age_days"])
        self.assertIn("never verified", entry["reason"])

    def test_shipped_placeholders_are_reported_as_never_installed(self):
        report = selectormap.verify_all(root=self.root, now=NOW)
        self.assertFalse(report["installed"])
        self.assertEqual(len(report["stale"]), report["checked"])
        self.assertTrue(all(e["placeholder"] for e in report["entries"]))

    def test_the_sweep_writes_nothing_at_all(self):
        self.write_map()
        before = self.tree()
        selectormap.verify_all(root=self.root, now=NOW,
                                    probe=lambda name, probe: True)
        self.assertEqual(self.tree(), before)

    def test_a_passing_probe_does_not_re_verify_the_entry(self):
        # An entry that silently re-verifies itself is the same lie as a
        # fallback locator: "somebody checked" replaced by "the software decided
        # it was fine".
        report = self.report(probe=lambda name, probe: True)
        entry = self.named(report, "order.previewButton")
        self.assertEqual(entry["probe_result"], "ok")
        self.assertTrue(entry["stale"], "a passing probe cleared staleness")
        self.assertEqual(entry["last_verified"], "2026-01-01")
        self.assertIn("order.previewButton", report["stale"])

    def test_a_failing_probe_is_reported_as_drifted_not_repaired(self):
        report = self.report(probe=lambda name, probe: False)
        self.assertEqual(sorted(report["drifted"]), sorted(GOOD["entries"]))
        entry = self.named(report, "order.placeButton")
        self.assertEqual(entry["probe_result"], "failed")
        self.assertTrue(entry["drifted"])

    def test_a_probe_that_raises_is_drift_rather_than_a_pass(self):
        def boom(name, probe):
            raise RuntimeError("the page never loaded")

        entry = self.named(self.report(probe=boom), "order.placeButton")
        self.assertEqual(entry["probe_result"], "error")
        self.assertTrue(entry["drifted"])

    def test_the_sweep_reports_the_probe_so_a_person_can_run_it(self):
        entry = self.named(self.report(), "order.placeButton")
        self.assertEqual(entry["probe"]["kind"], "role_and_name")
        self.assertEqual(entry["probe"]["expect"], "Place Order")

    def test_no_public_function_can_mark_an_entry_verified(self):
        # Re-verification is a person looking at the page and editing the map.
        for name, value in _module_publics().items():
            if not callable(value):
                continue
            for word in ("touch", "bump", "refresh", "renew", "reverify",
                         "mark_verified", "set_verified", "save", "write_map"):
                self.assertNotIn(word, name.lower(),
                                 f"{name} could re-verify an entry in software")


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
