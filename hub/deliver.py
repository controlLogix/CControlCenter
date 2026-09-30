"""Put a line in front of an agent and prove it was submitted. See docs/TRANSPORT.md 5.

The rule this module exists to enforce: a keystroke is sent only after the screen has
been read and understood. Every failure class the Phase A analysis found - Enter into
a modal (C2), Enter before a paste assembled (C1), text into a booting TUI (C5), keys
into copy-mode (C7) - is a keystroke sent without looking first, or a success reported
without looking after.

deliver_line() returns a Receipt whose stages are each 'ok', 'unverified' or a failure
reason. Nothing here decides retry policy; the hub does that from the Receipt.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import profiles as P
from .transport import Transport

STAGES = ("resolved", "mode", "modal", "ready", "typed", "submitted")


@dataclass
class Receipt:
    outcome: str = "pending"      # submitted | deferred | blocked | dead | failed
    reason: str = ""
    stages: dict = field(default_factory=dict)
    modal_answers: list = field(default_factory=list)
    enters: int = 0
    elapsed_ms: int = 0

    def as_dict(self):
        return {"outcome": self.outcome, "reason": self.reason, "stages": self.stages,
                "modal_answers": self.modal_answers, "enters": self.enters, "elapsed_ms": self.elapsed_ms}


def _norm(s):
    return " ".join(s.split())


def settle(t: Transport, handle: str, quiet_s=0.6, max_s=4.0, poll=0.15):
    """Capture until the screen stops changing (a TUI mid-redraw lies)."""
    last, still, t0 = None, 0.0, time.time()
    while time.time() - t0 < max_s:
        cur = t.capture(handle)
        if cur == last:
            still += poll
            if still >= quiet_s:
                return cur
        else:
            still, last = 0.0, cur
        time.sleep(poll)
    return last or t.capture(handle)


SELECTED = re.compile(r"^\s*[│|]?\s*[❯›▶>]\s*(?:\d+\.\s*)?(\S.*?)\s*$")


def selected_label(screen: str):
    """The text of the highlighted option in a menu, or None."""
    for line in reversed([l for l in screen.splitlines() if l.strip()][-14:]):
        m = SELECTED.match(line)
        if m:
            return m.group(1)
    return None


def select_option(t: Transport, handle: str, screen: str, want: str, max_moves=6):
    """Answer a menu BY LABEL: move the highlight until it reads `want`, confirm on
    screen, then Enter. Positional answers break the day a CLI reorders its options -
    and the preselected option has been the destructive one (No, exit / Update now)."""
    rx = re.compile(want, re.I)
    keys = []
    for direction in ("Down", "Up"):
        for _ in range(max_moves + 1):
            lab = selected_label(screen)
            if lab and rx.search(lab):
                t.send_key(handle, "Enter")
                return keys + ["Enter"]
            t.send_key(handle, direction)
            keys.append(direction)
            time.sleep(0.3)
            screen = t.capture(handle)
    return None


def clear_modals(t: Transport, prof: P.Profile, handle: str, auto: bool, rc: Receipt, passes=4):
    """Answer only modals this profile positively identifies, with their SAFE answer.
    Returns the blocking Modal if one needs a person, else None."""
    for _ in range(passes):
        screen = settle(t, handle)
        m = prof.modal(screen)
        if not m:
            return None
        if m.answer is None or not auto:
            return m
        if isinstance(m.answer, dict):
            keys = select_option(t, handle, screen, m.answer["select"])
            if keys is None:
                return m          # the safe option never became the highlighted one: a person decides
        else:
            keys = list(m.answer)
            for k in keys:
                t.send_key(handle, k)
                time.sleep(0.35)
        rc.modal_answers.append({"kind": m.kind, "keys": keys})
        time.sleep(0.8)
    m = prof.modal(settle(t, handle))
    return m


def deliver_line(t: Transport, prof: P.Profile, session: str, handle: str, text: str, *,
                 strategy: str = "type", auto_modals: bool = True, started_at: float | None = None,
                 allow_busy: bool = False, submit_timeout_s: float = 6.0) -> Receipt:
    """Type ONE line into the agent's input and submit it, verifying every stage.

    strategy: 'type'   send-keys -l  (short text; the doorbell and pointer lines)
              'buffer' load-buffer + paste-buffer -p (long text; eval S2)
    """
    rc = Receipt()
    t0 = time.time()

    def done(outcome, reason=""):
        rc.outcome, rc.reason = outcome, reason
        rc.elapsed_ms = int((time.time() - t0) * 1000)
        return rc

    # 1. resolved: the registered handle is this session's pane, and it is alive.
    h = t.handle(session)
    if not h:
        rc.stages["resolved"] = "dead"
        return done("dead", "no such terminal")
    if h[0] != handle:
        rc.stages["resolved"] = f"handle mismatch {h[0]} != {handle}"
        return done("failed", "identity: pane handle changed (R-ID-2)")
    rc.stages["resolved"] = "ok"

    # 2. mode: copy-mode silently eats keys (D02). Leave it, then re-check.
    md = t.mode(handle)
    if md == "copy":
        t.leave_mode(handle)
        time.sleep(0.2)
        md = t.mode(handle)
    if md != "normal":
        rc.stages["mode"] = md
        return done("dead" if md == "dead" else "deferred", f"pane mode {md}")
    rc.stages["mode"] = "ok"

    # 3. booting: a fresh TUI reports "ready" before it accepts input (C5).
    if started_at and time.time() - started_at < prof.boot_s:
        rc.stages["ready"] = "booting"
        return done("deferred", "booting")

    # 4. modal: answer the known-safe ones, never type into any other (C2).
    m = clear_modals(t, prof, handle, auto_modals, rc)
    if m:
        rc.stages["modal"] = m.kind
        return done("blocked", f"modal {m.kind}: {m.note}")
    rc.stages["modal"] = "ok"

    # 5. ready: prompt visible, not busy, composer empty (or holding only OUR stale line).
    screen = settle(t, handle)
    if prof.is_busy(screen) and not allow_busy:
        rc.stages["ready"] = "busy"
        return done("deferred", "busy")
    if not prof.is_ready(screen):
        rc.stages["ready"] = "no prompt"
        return done("deferred", "no input prompt visible")
    pending = prof.composer_text(screen)
    if prof.has_placeholder(screen) or (pending and _norm(pending) in _norm(text)):
        # A previous line of ours is sitting unsubmitted (C1). Submit it; do not retype.
        t.send_key(handle, "Enter")
        rc.enters += 1
        rc.stages["typed"] = "ok (already present)"
    else:
        # Something else is in the input line. With ANSI stripped, a TUI's grey hint
        # ("Ask Codex to do anything", 'Try "..."') is indistinguishable from real
        # text, so clear the line: harmless on a hint, and on real stale text it
        # prevents our line being glued onto it. Recorded, never silent.
        rc.stages["ready"] = f"ok (cleared composer: {pending[:40]!r})" if pending else "ok"
        if pending:
            t.send_key(handle, "C-u")
            time.sleep(0.2)
        # 6. typed
        if strategy == "buffer":
            t.send_buffer(handle, text)
        else:
            t.send_text(handle, text)
        time.sleep(max(prof.pre_enter_s, 0.25 if len(text) < 200 else 0.6))
        after = settle(t, handle, quiet_s=0.4, max_s=3.0)
        if _norm(text)[:30] in _norm(after) or prof.has_placeholder(after):
            rc.stages["typed"] = "ok"
        else:
            rc.stages["typed"] = "unverified"
        # a modal can appear between look and type; never Enter into it
        m = prof.modal(after)
        if m:
            t.send_key(handle, "C-u")
            rc.stages["modal"] = f"appeared: {m.kind}"
            return done("blocked", f"modal {m.kind} appeared while typing")
        t.send_key(handle, "Enter")
        rc.enters += 1

    # 7. submitted: our text left the composer, and no placeholder remains.
    timeout = max(submit_timeout_s, prof.submit_timeout_s)
    deadline = time.time() + timeout
    last_enter = time.time()
    probe = _norm(text)[:30]
    while time.time() < deadline:
        time.sleep(0.4)
        scr = t.capture(handle)
        comp = prof.composer_text(scr)
        still_there = prof.has_placeholder(scr) or (probe and probe in _norm(comp))
        if not still_there:
            rc.stages["submitted"] = "ok"
            return done("submitted")
        if rc.enters < 3 and time.time() - last_enter >= prof.enter_retry_s:
            # The C1 case: Enter arrived while the input was still being assembled
            # (a paste, or grok's typing burst). Retries are SPACED - an earlier draft
            # fired them on consecutive polls, which is no retry at all.
            t.send_key(handle, "Enter")
            rc.enters += 1
            last_enter = time.time()
    rc.stages["submitted"] = "still in composer"
    return done("failed", "text still in the input box after submit")
