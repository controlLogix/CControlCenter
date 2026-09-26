"""Armed unless recently and deliberately disarmed. Walking away re-arms it.

WHY THIS IS NOT "A FILE THAT EXISTS AT INSTALL". That design has one failure
mode and it is the fatal one: somebody removes the file to place a trade, and
then it is gone. The switch protects the first order and nothing after it. The
operator who disarmed it three weeks ago is not at the desk now, and neither is
the reason they did.

So the DEFAULT IS ARMED, and staying disarmed requires something recent. A
disarm carries an expiry, the pid that made it, and a digest of the guardrails
it was made under. Anything that invalidates one of those re-arms the switch by
construction, with no cleanup step that could be skipped:

  the expiry passes (60 minutes)      you walked away
  the process restarts                pid no longer matches
  the guardrails change               they are not the rules you agreed to
  a selector drifts                   the page is not the one we know
  a read-back does not match          we do not know what we just did
  an outcome is unknown               same, and worse

THE BROKER IS AUTHORITATIVE AND TRUSTS NOTHING IT IS TOLD. Every check re-reads
from disk, and `allowed()` takes no "the API said it was fine" argument, because
there is no argument it could be given that should override what is on disk. The
API runs in WSL and the broker on Windows; a value that crossed that boundary is
a claim about the past, and the click happens now.

NEVER CACHED. state() reads the files on every call, and submit paths call it
IMMEDIATELY BEFORE the click rather than at the top of the function. The gap
between "we checked" and "we clicked" is the only place this can be wrong, so
the design is to make that gap as close to zero as the language allows.

FAIL-ARMED, ALWAYS. Every error path - unreadable file, malformed JSON, a clock
that went backwards, a home that does not exist - reports ARMED. A kill switch
that fails open is not a kill switch. There is no code path here that returns
"disarmed" without having positively read a valid, current, matching disarm
record.
"""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

# The installer's sentinel. Its PRESENCE disables submission, permanently, until
# somebody removes it on purpose. Separate from the disarm record so that an
# operator can hard-disable the whole thing without racing the expiry logic.
SENTINEL_NAME = "SUBMIT_DISABLED"
DISARM_NAME = "disarm.json"

# Sixty minutes. Long enough to research, decide and place an order; short
# enough that a forgotten disarm does not outlive the attention that justified
# it. Walking away from the desk re-arms it.
DEFAULT_TTL_S = 3600.0
MAX_TTL_S = 3600.0

# What has to be typed to disarm. Not "yes" and not a click: the phrase is the
# pause, and it is the same reasoning as the typed phrase on an equipment write.
DISARM_PHRASE = "DISARM TRADING"

# Re-arm reasons that are not time-based. Recorded so the operator learns WHY it
# came back on, which is the difference between a safety feature and an
# annoyance they route around.
REARM_REASONS = (
    "selector_drift",
    "verification_mismatch",
    "unknown_outcome",
    "guardrails_changed",
    "manual",
)


class Armed(Exception):
    """Submission is blocked. The message says which of the reasons applies."""


def broker_root(root=None):
    """Where the switch state lives: OUTSIDE the repo, on purpose.

    %LOCALAPPDATA%\\agentmux\\broker on Windows, $AGENTMUX_HOME/broker otherwise.
    See docs/investing-boundary.md - this repo is public, and switch state sits
    beside order records.
    """
    if root is not None:
        return Path(root)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "agentmux" / "broker"
    home = os.environ.get("AGENTMUX_HOME")
    return (Path(home) if home else Path.home() / ".agentmux") / "broker"


def _read_json(path):
    """None on ANY problem. A record we cannot read is a record we do not have,
    and not having one means armed."""
    try:
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def guardrails_digest(config):
    """A stable digest of the rules a disarm was granted under.

    Sorted keys, so re-ordering a config file does not re-arm the switch for no
    reason - but any change to a LIMIT does. Loosening max_notional while
    disarmed would otherwise let an order through under rules the operator never
    saw.
    """
    try:
        blob = json.dumps(config or {}, sort_keys=True, separators=(",", ":"),
                          default=str)
    except (TypeError, ValueError):
        # Unserialisable config is not a reason to fail open.
        blob = repr(config)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def state(root=None, *, config=None, now=None):
    """Whether submission is allowed, and why not. Reads disk every time.

    Never raises, and never returns disarmed without positively reading a valid,
    current, matching record.
    """
    now = time.time() if now is None else now
    base = broker_root(root)
    armed = {"armed": True, "expires_in": None, "disarmed_by": None}

    if (base / SENTINEL_NAME).exists():
        return dict(armed, reason=f"{SENTINEL_NAME} is present; submission is disabled")

    record = _read_json(base / DISARM_NAME)
    if record is None:
        return dict(armed, reason="no disarm on file; the switch is armed by default")

    expires_at = record.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        return dict(armed, reason="the disarm record has no usable expiry")
    if now >= expires_at:
        return dict(armed, reason="the disarm expired; disarm again if you are still here")
    # A clock that went backwards must not extend a disarm indefinitely.
    granted_at = record.get("granted_at")
    if isinstance(granted_at, (int, float)) and expires_at - granted_at > MAX_TTL_S + 1:
        return dict(armed, reason="the disarm claims a longer life than is allowed")

    if record.get("pid") != os.getpid():
        # A disarm belongs to the process that made it. A restart is a new
        # process with no memory of why, so it starts armed.
        return dict(armed, reason="the disarm belongs to a process that has exited")

    if config is not None:
        want = guardrails_digest(config)
        if not hmac.compare_digest(str(record.get("guardrails") or ""), want):
            return dict(armed, reason="the guardrails changed since the disarm was granted")

    return {
        "armed": False,
        "reason": "disarmed",
        "expires_in": max(0.0, expires_at - now),
        "disarmed_by": record.get("actor"),
    }


def allowed(root=None, *, config=None, now=None):
    """True only when submission is permitted. Takes NO override argument.

    There is deliberately no `api_says_ok` parameter. The API runs in WSL and
    this runs on Windows; anything it told us is a claim about the past, and the
    click happens now. The only authority is the disk under this process.
    """
    return state(root, config=config, now=now)["armed"] is False


def require_disarmed(root=None, *, config=None, now=None):
    """Raise Armed unless submission is permitted. Call IMMEDIATELY before the click.

    Not at the top of the submit function - immediately before. The gap between
    the check and the click is the only window in which this can be wrong.
    """
    current = state(root, config=config, now=now)
    if current["armed"]:
        raise Armed(current["reason"])
    return current


def disarm(phrase, *, actor, config=None, root=None, ttl=DEFAULT_TTL_S, now=None):
    """Permit submission for a bounded time. Requires the exact typed phrase.

    The phrase is compared in constant time - not because an attacker is
    guessing it, but because there is no reason to write the version that is
    not.
    """
    now = time.time() if now is None else now
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("disarming requires a named actor")
    if not isinstance(phrase, str) or not hmac.compare_digest(phrase, DISARM_PHRASE):
        raise Armed(f"the disarm phrase must be typed exactly: {DISARM_PHRASE!r}")
    if not isinstance(ttl, (int, float)) or not 0 < ttl <= MAX_TTL_S:
        raise ValueError(f"ttl must be between 0 and {MAX_TTL_S} seconds")

    base = broker_root(root)
    if (base / SENTINEL_NAME).exists():
        # The sentinel outranks a disarm. Removing it is a deliberate, separate
        # act, and a disarm must not quietly do it for you.
        raise Armed(f"{SENTINEL_NAME} is present; remove it deliberately first")

    record = {
        "version": 1,
        "actor": actor,
        "granted_at": now,
        "expires_at": now + ttl,
        # The two things that make this disarm specific rather than a switch
        # somebody flipped once: whose process, and under which rules.
        "pid": os.getpid(),
        "guardrails": guardrails_digest(config) if config is not None else "",
    }
    base.mkdir(parents=True, exist_ok=True)
    path = base / DISARM_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return record


def arm(reason, *, root=None):
    """Re-arm now. Returns what was recorded.

    The reason is kept so the operator learns WHY it came back on. A switch that
    re-arms silently is one they start working around.
    """
    if reason not in REARM_REASONS:
        raise ValueError(f"reason must be one of {REARM_REASONS}")
    base = broker_root(root)
    base.mkdir(parents=True, exist_ok=True)
    try:
        (base / DISARM_NAME).unlink()
    except OSError:
        pass
    record = {"armed_at": time.time(), "reason": reason}
    (base / "last-rearm.json").write_text(json.dumps(record, indent=2) + "\n",
                                          encoding="utf-8")
    return record
