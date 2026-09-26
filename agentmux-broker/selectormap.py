"""A locator is the one we verified, or it is nothing. There is no second guess.

WHY THIS MODULE HAS NO FALLBACK PATH, which is the entire design. On an order
form, guessing which button is Place Order is how you submit something nobody
authorised. Every resilience instinct that is correct elsewhere - try the next
selector, match on the visible text, click the button that looks right - is a
bug here, and it is the kind of bug that succeeds. A retry against a login form
locks an account; a retry against an order form fills one.

So the failure mode is deliberately the loud one. A locator that no longer
identifies the thing it names is `SelectorDrift`, and drift is not an error to
recover from. It is a statement that THE PAGE IS NOT THE ONE WE KNOW, and
everything downstream of that sentence is untrustworthy, including any
cleverness this module could apply to work around it.

HOW "NEVER A FALLBACK" IS ENFORCED RATHER THAN DOCUMENTED. A comment saying
"do not add a fallback" survives exactly as long as the first author. Three
mechanical guards outlive them:

  * `resolve()` is the ONLY function in this module that returns a locator, and
    it is named in LOCATOR_RETURNING. `entry()` hands back metadata with the
    locator removed. test_selectors enumerates the public surface and fails on
    any new callable that is not classified - the same shape as the Rockwell
    write-capability whitelist.
  * `resolve()`'s signature is asserted EXACTLY. No `default=`, no `fallback=`,
    no `or_else=`. A parameter is how a fallback gets added without anyone
    calling it one.
  * The LOADER refuses the data shape. A locator that is a LIST is a fallback
    chain in disguise and is rejected; an entry carrying a key from GUESSING
    (`fallback`, `candidates`, `alternates`, ...) is rejected BY NAME rather
    than quietly ignored, because an operator who wrote one needs to be told it
    will never be used.

WHERE THE MAP LIVES, AND WHY NOT HERE. This repository is PUBLIC. Real locators
for a brokerage's order form are operational detail about a live account's
automation, and screenshots and DOM snapshots taken on drift are worse - they
carry whatever was on screen, which on that page is positions and balances. So:

  the operator's map      %LOCALAPPDATA%\\agentmux\\broker\\selectors.json
  drift evidence          %LOCALAPPDATA%\\agentmux\\broker\\captures\\
  the drift journal       %LOCALAPPDATA%\\agentmux\\broker\\broker-journal.jsonl

all outside the tree, beside the kill switch state. See docs/investing-boundary.md.
What SHIPS here is a schema and a map of logical names whose locators are
placeholders - and a placeholder does not resolve. A checkout of this repo
cannot click anything, by construction rather than by omission.

THE ORDER OF THE DRIFT RESPONSE, AND THE ONE STEP THAT CANNOT BE SKIPPED.
`on_drift()` runs the plan's sequence - evidence, journal, DEGRADED, arm the
kill switch, alert - and ARMS THE SWITCH EVEN WHEN EVERY EARLIER STEP FAILS. A
screenshot that could not be written is not a reason to leave trading enabled.
Each earlier step therefore records its own failure instead of propagating it,
and the arm sits in a `finally` so that even a BaseException on the way through
leaves the switch armed on its way out.

It NEVER RETURNS NORMALLY. A handler that can return is a handler somebody
wraps in a try/except and continues past.

NO PLAYWRIGHT, NO BROWSER, NO NETWORK. The evidence capture is an injected
callable. This module imports and is fully testable with no browser present,
which is also what stops it growing a "just check the page quickly" shortcut.

WHY THIS IS NOT CALLED selectors.py, which is what the plan's prose implies.
`selectors` IS A STANDARD-LIBRARY MODULE, and `subprocess` imports it at module
scope. Every suite in this directory is run as `python3 agentmux-broker/test_x.py`,
which puts agentmux-broker at `sys.path[0]` - so a file called selectors.py here
shadows the stdlib for the whole process. Measured, not theorised: with that name
in place, `test_killswitch.py` fails with `module 'selectors' has no attribute
'SelectSelector'` the moment it reaches `from unittest.mock import patch`, and
the broker's own Playwright event loop would die the same way, with a traceback
pointing nowhere near the cause. The map file on disk is still `selectors.json`;
only the Python module is renamed. For the same reason this module NEVER puts
its own directory on `sys.path` - it loads its siblings by path.
"""

import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The repo. Nothing this module writes may land inside it - see the boundary doc.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _sibling(name, path):
    """Import a module by path, WITHOUT touching sys.path. See the filename note.

    Reuses whatever is already loaded under that name from that same file, so
    the broker and its tests hold ONE killswitch module object rather than two
    with separate state.
    """
    existing = sys.modules.get(name)
    if existing is not None and \
            Path(getattr(existing, "__file__", "") or "").resolve() == path.resolve():
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules.setdefault(name, module)
    return module


killswitch = _sibling("killswitch", Path(__file__).resolve().parent / "killswitch.py")

SCHEMA_VERSION = 1
REGISTRY_NAME = "selectors.json"
CAPTURE_DIR_NAME = "captures"
JOURNAL_NAME = "broker-journal.jsonl"
SESSION_STATE_NAME = "session-state.json"

# The re-arm reason this module raises. Asserted against killswitch.REARM_REASONS
# in the tests, because a reason that module does not accept would raise
# ValueError at the exact moment the switch most needs arming.
DRIFT_REASON = "selector_drift"

# Session states. DEGRADED is the one this module sets. There is deliberately no
# function here that clears it: a session that un-degrades itself is the same
# lie as a locator that re-verifies itself.
STATES = ("OK", "DEGRADED", "LOCKED")

# An entry is these keys and no others. A key nobody classified is a key whose
# meaning the next reader will invent.
ENTRY_KEYS = ("locator", "probe", "last_verified", "note")
REQUIRED_ENTRY_KEYS = ("locator", "probe", "last_verified")
TOP_LEVEL_KEYS = ("version", "venue", "entries", "note")

# How a probe says "this locator still identifies the right thing". Small and
# closed: an open vocabulary becomes "eval this expression" within a year.
PROBE_KINDS = ("text_equals", "text_contains", "attribute_equals",
               "role_and_name", "unique_match", "manual")

# The shipped locators. A locator beginning with this NEVER resolves, so a fresh
# checkout - or an operator map that is half filled in - refuses rather than
# clicks.
PLACEHOLDER_PREFIX = "REPLACE-ME"

# Older than this and the entry is reported stale. Reported: `resolve()` does
# NOT refuse on age. A locator that still matches is not drift, and a hard date
# that blocks trading is a window somebody widens until it means nothing.
STALE_AFTER_DAYS = 30.0

# The ONLY name that hands back a locator. The surface test holds this line: a
# new public callable that could return one fails until somebody classifies it.
LOCATOR_RETURNING = ("resolve",)

# The vocabulary of guessing. Used twice on purpose - the loader REFUSES an
# entry carrying one of these as a key, and the test scans the public surface
# for one of these in a name. One constant, two enforcement points, so they
# cannot drift apart.
GUESSING = (
    "fallback", "fallbacks", "alternate", "alternates", "alternative",
    "alternatives", "candidate", "candidates", "guess", "likely", "nearest",
    "similar", "fuzzy", "approx", "heuristic", "next_best", "backup",
    "or_else", "default_locator", "retry", "try_also", "any_of",
)


class SelectorDrift(Exception):
    """The page is not the one we know. Never recovered from, only reported.

    Carries the logical name and the detail. It deliberately carries NO
    suggested alternative: there is nothing this exception could offer that a
    caller should act on other than stopping.

    `record` is None for a drift raised by `resolve()` - detected but not yet
    responded to - and is the step-by-step record once `on_drift()` has run. A
    drift that reaches an operator with `record is None` was caught by somebody
    who did not respond to it.
    """

    def __init__(self, message, *, name=None, detail=None, record=None):
        super().__init__(message)
        self.name = name
        self.detail = detail
        self.record = record


class RegistryError(Exception):
    """The map itself is wrong. Raised at load, never converted into a default.

    A half-read map is worse than no map: it resolves some names and silently
    loses others, and the ones it loses are whichever the author got wrong.
    """


# -- where things live --------------------------------------------------------

def registry_path(root=None):
    """The operator's map. OUTSIDE the repo, beside the kill switch state."""
    return killswitch.broker_root(root) / REGISTRY_NAME


def capture_dir(root=None):
    """Where drift evidence goes. Refuses to name a path inside this repo.

    This repo is PUBLIC and a DOM snapshot of a brokerage page carries positions
    and balances. The .gitignore pins agentmux-broker/captures/ so a stray write
    lands ignored; this refuses to make the write in the first place.
    """
    path = killswitch.broker_root(root) / CAPTURE_DIR_NAME
    try:
        path.resolve().relative_to(_REPO_ROOT)
    except ValueError:
        return path
    raise RegistryError(
        f"{path} is inside the repository, which is public; drift evidence "
        f"belongs in %LOCALAPPDATA%\\agentmux\\broker\\{CAPTURE_DIR_NAME} - see "
        f"docs/investing-boundary.md")


def journal_path(root=None):
    """The broker's own journal. Separate from the field-write journal: a
    selector drift is not a write to equipment, and one file answering two
    questions answers neither when it is read in a hurry."""
    return killswitch.broker_root(root) / JOURNAL_NAME


def session_state_path(root=None):
    return killswitch.broker_root(root) / SESSION_STATE_NAME


# -- the shipped map ----------------------------------------------------------

def default_registry():
    """The logical names, with PLACEHOLDER locators. Never resolves.

    THE REAL MAP IS OPERATOR-SUPPLIED AND LIVES OUTSIDE THIS REPO, at
    %LOCALAPPDATA%\\agentmux\\broker\\selectors.json. Nothing in this file is a
    real locator for any venue: this repo is public, and a working locator for a
    live brokerage's order form is operational detail about somebody's account.

    The names are the contract - the browser layer asks for `order.placeButton`
    and the map says what that is today. Copy this out, fill in the locators
    against the real page, probe each one, and record when you did.
    """
    def entry(kind, expect, note):
        return {
            "locator": f"{PLACEHOLDER_PREFIX}: no locator is shipped for this name",
            "probe": {"kind": kind, "expect": expect},
            "last_verified": None,
            "note": note,
        }

    return {
        "version": SCHEMA_VERSION,
        "venue": "placeholder",
        "note": "placeholders only; the real map is operator-supplied and lives "
                "outside this public repository",
        "entries": {
            "login.username": entry(
                "unique_match", None, "exactly one field, or the page changed"),
            "login.password": entry(
                "unique_match", None, "exactly one field, or the page changed"),
            "login.submit": entry(
                "role_and_name", None, "the submit control on the login form"),
            "login.twoFactorPrompt": entry(
                "text_contains", None,
                "presence means a human is needed; the broker never re-auths"),
            "session.signedInMarker": entry(
                "unique_match", None,
                "the cheapest proof the persistent profile is still logged in"),
            "order.symbol": entry("unique_match", None, "symbol input"),
            "order.quantity": entry("unique_match", None, "share quantity input"),
            "order.sideBuy": entry("role_and_name", None, "buy control"),
            "order.sideSell": entry("role_and_name", None, "sell control"),
            "order.orderType": entry("unique_match", None, "market/limit control"),
            "order.limitPrice": entry("unique_match", None, "limit price input"),
            "order.previewButton": entry(
                "role_and_name", None,
                "Preview only. Never mapped to the same node as placeButton"),
            "order.placeButton": entry(
                "role_and_name", None,
                "THE one that spends money; probe it hardest"),
            "order.confirmationNumber": entry(
                "unique_match", None, "read back after submission"),
            "orders.statusTable": entry("unique_match", None, "open orders"),
            "positions.table": entry("unique_match", None, "positions"),
            "balances.total": entry("unique_match", None, "account value"),
        },
    }


# -- validation ---------------------------------------------------------------

def _is_placeholder(locator):
    return isinstance(locator, str) and locator.startswith(PLACEHOLDER_PREFIX)


def _parse_iso(value):
    """Epoch seconds, or None when the value is absent or unreadable.

    None means NEVER VERIFIED, and verify_all reports that as stale. A date we
    cannot read must not read as a recent one - same discipline as an unpriced
    order not reading as a small one.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def _validate(data):
    """Return (version, venue, entries) or raise RegistryError. Never repairs."""
    if not isinstance(data, dict):
        raise RegistryError("the selector map is not an object")

    unknown = [k for k in data if k not in TOP_LEVEL_KEYS]
    if unknown:
        raise RegistryError(f"the selector map has unknown top-level keys: {unknown}")

    version = data.get("version")
    if version != SCHEMA_VERSION:
        # Not "best effort". A map written against a schema this code does not
        # know is a map whose meaning this code is guessing at.
        raise RegistryError(
            f"the selector map declares version {version!r}; this broker reads "
            f"version {SCHEMA_VERSION}")

    entries = data.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise RegistryError("the selector map has no entries")

    seen = {}
    clean = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not name.strip():
            raise RegistryError(f"{name!r} is not a usable logical name")
        if not isinstance(entry, dict):
            raise RegistryError(f"{name}: the entry is not an object")

        offending = [k for k in entry if str(k).lower() in GUESSING]
        if offending:
            # Refused BY NAME rather than ignored. An operator who wrote a
            # fallback needs to be told it will never be used, not left
            # believing there is a safety net under the Place Order button.
            raise RegistryError(
                f"{name}: {offending} is a fallback locator, and there is no "
                f"fallback path; on an order form, clicking the next likely "
                f"button is how you submit something nobody authorised")

        extra = [k for k in entry if k not in ENTRY_KEYS]
        if extra:
            raise RegistryError(f"{name}: unknown entry keys {extra}")
        missing = [k for k in REQUIRED_ENTRY_KEYS if k not in entry]
        if missing:
            raise RegistryError(f"{name}: the entry is missing {missing}")

        locator = entry["locator"]
        if isinstance(locator, (list, tuple, set)):
            raise RegistryError(
                f"{name}: a list of locators is a fallback chain; one logical "
                f"name identifies one thing, or it identifies nothing")
        if not isinstance(locator, str) or not locator.strip():
            raise RegistryError(f"{name}: the locator is not a non-empty string")

        probe = entry["probe"]
        if not isinstance(probe, dict):
            raise RegistryError(f"{name}: the probe is not an object")
        kind = probe.get("kind")
        if kind not in PROBE_KINDS:
            raise RegistryError(
                f"{name}: probe kind {kind!r} is not one of {list(PROBE_KINDS)}")

        last = entry["last_verified"]
        if last is not None and _parse_iso(last) is None:
            raise RegistryError(
                f"{name}: last_verified {last!r} is not an ISO-8601 date; use "
                f"null for never rather than a date nobody can read")

        if not _is_placeholder(locator):
            key = locator.strip()
            if key in seen:
                # Two names on one node is the failure this module exists to
                # prevent, wearing a different hat: map Preview and Place to the
                # same button and the dry run places the order.
                raise RegistryError(
                    f"{name} and {seen[key]} share the locator {locator!r}; two "
                    f"logical names on one node means one of them clicks the "
                    f"wrong thing")
            seen[key] = name

        clean[name] = {
            "locator": locator,
            "probe": dict(probe),
            "last_verified": last,
            "note": entry.get("note", ""),
        }

    return version, data.get("venue", ""), clean


class Registry:
    """A loaded selector map. Hands out a locator only through resolve()."""

    __slots__ = ("version", "venue", "path", "source", "installed", "_entries")

    def __init__(self, data, *, path=None, source="shipped-default", installed=False):
        self.version, self.venue, self._entries = _validate(data)
        self.path = Path(path) if path is not None else None
        self.source = source
        self.installed = bool(installed)

    def names(self):
        """Every logical name, sorted. Names are not locators."""
        return tuple(sorted(self._entries))

    def entry(self, name):
        """Metadata for one name, WITHOUT the locator.

        The locator is deliberately absent. Reporting, staleness and the blade
        all want to talk about an entry without being handed the thing that
        clicks - and a second accessor that returned one would be a second path
        to a locator that nobody classified.
        """
        record = self._entries[name]
        return {
            "name": name,
            "probe": dict(record["probe"]),
            "last_verified": record["last_verified"],
            "note": record["note"],
            "placeholder": _is_placeholder(record["locator"]),
        }

    def resolve(self, name):
        """The locator, or SelectorDrift. No second candidate, ever.

        The three refusals, and none of them has a recovery:
          the name is not in the map       we were asked for something we never verified
          the locator is a placeholder     no operator map is installed
          the map was never installed      same, stated where it is noticed
        """
        record = self._entries.get(name)
        if record is None:
            raise SelectorDrift(
                f"no selector is mapped to {name!r}; the registry knows "
                f"{len(self._entries)} name(s) and this is not one of them",
                name=name, detail="unmapped logical name")
        locator = record["locator"]
        if _is_placeholder(locator):
            raise SelectorDrift(
                f"{name} is a shipped placeholder, not a locator; the real map "
                f"is operator-supplied and lives at {registry_path()}",
                name=name, detail="placeholder locator")
        return locator


def load(path=None, *, root=None):
    """Read the operator's map. Never cached, never repaired.

    A MISSING file returns the shipped placeholder registry, which refuses every
    resolve with a message saying so. That is a known state - not installed yet -
    and the useful answer is a clear refusal at the point of use.

    A file that EXISTS and is wrong raises RegistryError. Malformed is an unknown
    state, and converting an unknown state into a working object is how half a
    map gets used on an order form.

    Not cached at module level on purpose: a cached map means an operator's fix
    does not take effect until a restart, and a stale map is the precise failure
    this module exists to catch.
    """
    target = Path(path) if path is not None else registry_path(root)
    if not target.is_file():
        return Registry(default_registry(), path=target, source="shipped-default",
                        installed=False)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"{target} could not be read: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RegistryError(
            f"{target} is not valid JSON: {exc}; a half-read map resolves some "
            f"names and loses the rest") from exc
    return Registry(data, path=target, source=str(target), installed=True)


def resolve(name, *, registry=None, root=None):
    """The locator for `name`, or SelectorDrift. The only way to get one.

    Wire the refusal to the full response at the call site - `on_drift` never
    returns, so there is no path past it:

        try:
            locator = selectors.resolve("order.placeButton")
        except selectors.SelectorDrift as drift:
            selectors.on_drift(drift.name, str(drift), capture=capture)
    """
    return (registry if registry is not None else load(root=root)).resolve(name)


# -- session state ------------------------------------------------------------

def degrade(reason, *, name=None, root=None, now=None):
    """Mark the session DEGRADED. There is no function here that clears it.

    Clearing is a deliberate operator act - delete the file - for the same
    reason the installer sentinel is removed by hand. A session that recovers
    itself recovers on the strength of no new information.
    """
    at = time.time() if now is None else now
    base = killswitch.broker_root(root)
    base.mkdir(parents=True, exist_ok=True)
    record = {"state": "DEGRADED", "since": at, "reason": str(reason),
              "selector": name}
    path = session_state_path(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return record


def session_state(root=None):
    """The current state. Unreadable reads DEGRADED, absent reads OK.

    Those are different answers to different questions. Nothing on disk means
    nothing has gone wrong yet, which is a fresh install. Something on disk that
    cannot be read means something WAS recorded and we cannot tell what, and the
    safe reading of that is not OK.
    """
    path = session_state_path(root)
    if not path.exists():
        return {"state": "OK", "since": None, "reason": "nothing has been recorded",
                "selector": None}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("state") not in STATES:
        return {"state": "DEGRADED", "since": None,
                "reason": f"{path} is unreadable, so the session state is unknown",
                "selector": None}
    return {"state": record["state"], "since": record.get("since"),
            "reason": record.get("reason", ""), "selector": record.get("selector")}


# -- the drift response -------------------------------------------------------

_JOURNAL_MODULE = None


def _journal_module():
    """dashboard/writejournal.py, imported on demand and BY PATH.

    Lazily, so that importing this module does not reach across the tree, and so
    that a broker running without the dashboard beside it fails the JOURNAL step
    - recorded, visible - rather than failing to import at all and taking the
    kill switch arming down with it.
    """
    global _JOURNAL_MODULE
    if _JOURNAL_MODULE is None:
        _JOURNAL_MODULE = _sibling("writejournal",
                                   _REPO_ROOT / "dashboard" / "writejournal.py")
    return _JOURNAL_MODULE


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-") or "unnamed"


def _capture_files(written, dest):
    """Filenames only. The journal records WHAT was captured and where, never
    the contents: a DOM snapshot of a brokerage page is the thing we are being
    careful with, and copying it into a second file helps nobody."""
    if isinstance(written, (str, os.PathLike)):
        written = [written]
    if isinstance(written, dict):
        written = list(written.values())
    if written:
        return sorted(Path(p).name for p in written)
    try:
        return sorted(p.name for p in dest.iterdir())
    except OSError:
        return []


def on_drift(name, detail, *, capture=None, root=None, journal=None, now=None):
    """The whole response to drift. Runs the plan's order. NEVER RETURNS.

        evidence -> journal -> session DEGRADED -> kill switch ARMED -> alert

    THE ARM HAPPENS EVEN IF EVERY EARLIER STEP FAILS. A screenshot that could
    not be written is not a reason to leave trading enabled, so each earlier
    step catches its own failure and records it as a second problem rather than
    propagating it - and the arm sits in a `finally`, so even a BaseException
    passing through leaves the switch armed on its way out.

    AND THE ARM IS VERIFIED, not assumed. killswitch.arm() swallows an OSError
    while removing the disarm record, so a returning arm() is not proof the
    switch is armed. This re-reads `allowed()` afterwards and, if submission is
    somehow still permitted, writes the installer sentinel - the documented hard
    stop, cleared only by hand. A switch that would not arm while the page is
    unknown is the one case that warrants it.

    `capture` is injected: `capture(dest_dir, context) -> paths or None`. No
    Playwright here, and no browser needed to test any of this.
    """
    at = time.time() if now is None else now
    base = killswitch.broker_root(root)
    record = {
        "event": "selector_drift",
        "selector": name,
        "detail": str(detail),
        "at": at,
        "steps": [],
        "evidence": None,
        "journalled": False,
        "state": None,
        "armed": False,
        "sentinel": False,
    }

    def step(kind, ok, note, **extra):
        record["steps"].append(dict({"step": kind, "ok": ok, "note": note}, **extra))

    try:
        # 1. evidence, outside the repo.
        dest = None
        try:
            if capture is None:
                raise RuntimeError("no capture function was supplied")
            dest = capture_dir(root) / f"{_slug(name)}-{int(at)}"
            dest.mkdir(parents=True, exist_ok=True)
            written = capture(dest, {"selector": name, "detail": str(detail),
                                     "at": at})
            record["evidence"] = str(dest)
            step("capture", True, f"evidence written to {dest}",
                 files=_capture_files(written, dest))
        except Exception as exc:                            # noqa: BLE001
            if dest is not None:
                try:
                    dest.rmdir()                            # only if still empty
                except OSError:
                    pass
            step("capture", False,
                 f"evidence capture failed and the response continued: {exc!r}")

        # 2. the journal record.
        try:
            sink = journal
            if sink is None:
                sink = _journal_module().WriteJournal(journal_path(root),
                                                      transport="broker")
            sink.append({
                "event": "selector_drift",
                "transport": getattr(sink, "transport", "broker"),
                "selector": name,
                "detail": str(detail),
                "evidence": record["evidence"],
                "outcome": "unknown",
                "reason": "the page is not the one we know; nothing about the "
                          "session's state can be assumed",
            })
            record["journalled"] = True
            step("journal", True, "drift recorded in the broker journal")
        except Exception as exc:                            # noqa: BLE001
            step("journal", False,
                 f"the journal record failed and the response continued: {exc!r}")

        # 3. the session is DEGRADED.
        try:
            degrade(f"selector drift on {name}", name=name, root=root, now=at)
            record["state"] = "DEGRADED"
            step("degrade", True, "session state set to DEGRADED")
        except Exception as exc:                            # noqa: BLE001
            step("degrade", False,
                 f"the session state could not be written and the response "
                 f"continued: {exc!r}")
    finally:
        # 4. THE STEP THAT CANNOT BE SKIPPED.
        try:
            killswitch.arm(DRIFT_REASON, root=base)
            step("arm", True, f"kill switch armed: {DRIFT_REASON}")
        except Exception as exc:                            # noqa: BLE001
            step("arm", False, f"killswitch.arm raised: {exc!r}")
        # Verified, not assumed.
        try:
            record["armed"] = not killswitch.allowed(base)
        except Exception:                                   # noqa: BLE001
            record["armed"] = False
        if not record["armed"]:
            try:
                base.mkdir(parents=True, exist_ok=True)
                (base / killswitch.SENTINEL_NAME).write_text(
                    f"written by selectors.on_drift at {at}: the kill switch "
                    f"would not arm after drift on {name}\n", encoding="utf-8")
                record["sentinel"] = True
                record["armed"] = not killswitch.allowed(base)
                step("escalate", True,
                     f"{killswitch.SENTINEL_NAME} written; submission is disabled "
                     f"until an operator removes it by hand")
            except Exception as exc:                        # noqa: BLE001
                step("escalate", False,
                     f"the switch would not arm and the sentinel could not be "
                     f"written: {exc!r}")

    raise SelectorDrift(
        f"selector drift on {name}: {detail}. Trading is "
        f"{'disabled' if record['armed'] else 'NOT CONFIRMED DISABLED - STOP'}; "
        f"the session is DEGRADED and this is never retried. Evidence: "
        f"{record['evidence'] or 'NOT CAPTURED'}",
        name=name, detail=str(detail), record=record)


# -- the staleness sweep ------------------------------------------------------

def verify_all(registry=None, *, root=None, probe=None, now=None,
               stale_after_days=STALE_AFTER_DAYS):
    """Report which entries are stale. Reports. Never updates anything.

    THERE IS NO WRITE IN THIS FUNCTION, and that is the point. An entry that
    silently re-verifies itself is the same lie as a fallback locator: both
    replace "somebody checked" with "the software decided it was fine". So a
    PASSING probe does not touch `last_verified` and does not clear `stale` -
    re-verification is a person looking at the page and editing the map.

    Age is measured from `last_verified`. Absent or unreadable is NEVER
    VERIFIED, which reports stale - a date we cannot read must not read as a
    recent one.

    A FAILING probe is reported as `drifted`. This function does not arm the
    switch: it is a sweep somebody runs, and a sweep that also took action is
    one they stop running. Acting on a drifted entry is `on_drift()`, and the
    caller makes that call where it is visible.
    """
    reg = registry if registry is not None else load(root=root)
    at = time.time() if now is None else now
    cutoff = float(stale_after_days) * 86400.0

    entries, stale, drifted = [], [], []
    for name in reg.names():
        meta = reg.entry(name)
        when = _parse_iso(meta["last_verified"])
        age_days = None if when is None else max(0.0, (at - when) / 86400.0)

        if meta["placeholder"]:
            is_stale, why = True, ("a shipped placeholder; no operator locator is "
                                   "installed for this name")
        elif when is None:
            is_stale, why = True, "never verified"
        elif age_days > stale_after_days:
            is_stale, why = True, f"last verified {age_days:.1f} days ago"
        else:
            is_stale, why = False, f"verified {age_days:.1f} days ago"

        report = {
            "name": name,
            "last_verified": meta["last_verified"],
            "age_days": age_days,
            "stale": is_stale,
            "placeholder": meta["placeholder"],
            "probe": meta["probe"],
            "probe_result": None,
            "drifted": False,
            "reason": why,
        }

        if probe is not None:
            try:
                outcome = probe(name, meta["probe"])
            except Exception as exc:                        # noqa: BLE001
                report["probe_result"] = "error"
                report["drifted"] = True
                report["reason"] = f"{why}; the probe raised {exc!r}"
            else:
                if outcome:
                    # Deliberately NOT clearing `stale`, and deliberately not
                    # writing last_verified. See the docstring.
                    report["probe_result"] = "ok"
                    report["reason"] = (f"{why}; the probe passed, which is not "
                                        f"a re-verification")
                else:
                    report["probe_result"] = "failed"
                    report["drifted"] = True
                    report["reason"] = f"{why}; the probe did not match"

        entries.append(report)
        if is_stale:
            stale.append(name)
        if report["drifted"]:
            drifted.append(name)

    return {
        "checked": len(entries),
        "installed": reg.installed,
        "source": reg.source,
        "stale_after_days": float(stale_after_days),
        "entries": entries,
        "stale": stale,
        "drifted": drifted,
    }
