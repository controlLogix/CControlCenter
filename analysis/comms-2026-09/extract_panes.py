#!/usr/bin/env python3
"""extract_panes.py - mine raw tmux pipe-pane logs for delivery evidence.

Phase A extractor (see README.md in this folder). Stdlib only, deterministic,
read-only against the logs. Writes out/panes.jsonl and nothing else.

INPUT
  logs.index.tsv from the snapshot lists every pane log with its size and mtime AT
  SNAPSHOT TIME. Each log is read in place, in chunks, and never past the indexed
  size - the nfl-* panes are live and still growing, and reading to the current EOF
  would make two runs disagree.

RENDERING
  The logs are raw terminal byte streams. Every escape sequence is removed by one
  tokenizer, which also keeps a map from rendered position back to raw byte offset:
    CSI cursor positioning / vertical moves (H f A B E F d)  -> "\n"
    CSI cursor forward / column absolute (C G)               -> " "
    any other CSI, OSC, DCS, charset, lone ESC, C0 controls  -> removed
    a CR run (optionally ending in LF)                       -> "\n"
  Carriage-return redraws therefore show up as repeated lines rather than being
  overwritten; the per-event dedupe below absorbs the repetition. Matching is done
  on bytes with whitespace-tolerant patterns, because codex paints words with cursor
  moves and a word gap may be a newline, a space or nothing.

EVENTS (types per README)
  arrived        "[agentmux] from X (kind) [ref R]:" envelopes, and bare dispatch
                 pointers "Read <path>.md and do the work". A pointer inside an
                 envelope body is folded into that envelope (detail.dispatch_brief).
  pending_input  (a) a paste placeholder "[Pasted Content N chars]",
                 "[Pasted text #n +N lines]" or "[N lines pasted]", or
                 (b) an arrived message,
                 with NO busy marker in the next PENDING_WINDOW bytes of stream after
                 its first sighting. PENDING_WINDOW = 64 KiB (documented choice: a
                 busy CLI repaints its "esc to interrupt" status many times per
                 second, a few hundred bytes each, so a submitted prompt shows a
                 marker within a few KiB; an idle pane writes almost nothing, so
                 64 KiB of stream with no marker means a long quiet interval or
                 other activity that is not the agent working).
  modal          update / trust / bypass / login / effort / yn / other.
  death          "Please restart", update-install output after an update modal,
                 a shell prompt returning after a CLI banner, CLI exit/resume text,
                 or the log ending on a consent/trust modal whose selection is
                 "No, exit".
  busy           start of a busy episode: a busy marker with no marker in the
                 previous BUSY_GAP bytes. Markers are agentmux.sh busy_marker plus
                 claude 2.1.28x spinner shapes (see BUSY) - without those every claude
                 message read as pending.

  Envelope sender and kind are snapped to the known agent names and the courier's
  MESSAGE_KINDS (garbled repaints drop letters: "eply", "statu"); the raw values stay
  in detail. A modal is dropped (and counted) when the pane's CLI could not have drawn
  it - e.g. claude's "Not logged in" quoted inside a codex agent's report.

DEDUPE
  A pane redraws the same text many times. An event is one DISTINCT occurrence:
  a sighting that matches (fuzzily, for garbled partial repaints) an event of the
  same type seen within REDRAW_WINDOW bytes of that event's LAST sighting extends it
  (detail.sightings, detail.last_offset) instead of emitting a new record. A match
  outside the window is emitted again, flagged detail.redraw_suspect=true.

TIME
  The logs have no timestamps. Anchors, in stream order:
    started  run/<name>.started sidecar, at offset 0 (nfl-* only)
    clock    CLI status text: codex "Worked for Ns • HH:MM" (24h local),
             "done H:MM AM|PM" (claude, older codex), and in grok panes the bare
             "H:MM AM|PM" transcript stamps; time of day only, dated by walking
             forward (evening -> early morning is a midnight rollover; any other drop
             is a scrollback repaint and is ignored) and then aligning the last clock
             to the indexed file mtime.
    mtime    the indexed mtime (minute precision, local), at the indexed size.
  Each event's time is linearly interpolated by byte offset between the bracketing
  anchors; before the first anchor it takes the first anchor's time as an upper
  bound. The machine is US Central, CDT = UTC-5 for this whole period.
"""

import bisect
import difflib
import hashlib
import json
import os
import re
import sys
from array import array
from datetime import datetime, timedelta, timezone

SNAP = "/home/nick/agentmux-comms-snapshot/20260929-215601"
INDEX = SNAP + "/logs.index.tsv"
RUNDIR = SNAP + "/run"
# fixed, so the script can never write anywhere but this analysis folder
OUTDIR = "/mnt/c/Dev/agentmux/analysis/comms-2026-09/out"
OUT = os.path.join(OUTDIR, "panes.jsonl")

CHUNK = 8 << 20
KEEP = 64 << 10            # lookahead kept at the end of every chunk
PENDING_WINDOW = 64 << 10  # N for pending_input
BUSY_GAP = 64 << 10
REDRAW_WINDOW = 1 << 20
MODAL_WINDOW = 256 << 10
CDT = timezone(timedelta(hours=-5))

# ── tokenizer ────────────────────────────────────────────────────────────────
TOK = re.compile(
    rb"\x1b\[[0-?]*[ -/]*[@-~]"
    rb"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"
    rb"|\x1bP[^\x1b]*(?:\x1b\\)?"
    rb"|\x1b[()*+][ -~]?"
    rb"|\x1b[ -/]*[0-~]?"
    rb"|\r+\n?"
    rb"|[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]+"
)
NL_FINALS = frozenset(b"HfABEFd")
SP_FINALS = frozenset(b"CG")


def render(raw, base):
    """Return (rendered bytes, cpos array, rpos array)."""
    out = []
    cps = array("q")
    rps = array("q")
    cpos = 0
    last = 0
    ap = out.append
    for m in TOK.finditer(raw):
        s, e = m.span()
        if s > last:
            ap(raw[last:s]); cps.append(cpos); rps.append(base + last); cpos += s - last
        c0 = raw[s]
        rep = b""
        if c0 == 0x1b:
            if e - s >= 3 and raw[s + 1] == 0x5b:
                f = raw[e - 1]
                if f in NL_FINALS:
                    rep = b"\n"
                elif f in SP_FINALS:
                    rep = b" "
        elif c0 == 0x0d:
            rep = b"\n"
        if rep:
            ap(rep); cps.append(cpos); rps.append(base + s); cpos += 1
        last = e
    if last < len(raw):
        ap(raw[last:]); cps.append(cpos); rps.append(base + last)
    return b"".join(out), cps, rps


def raw_of(cps, rps, c):
    i = bisect.bisect_right(cps, c) - 1
    if i < 0:
        return rps[0] if rps else 0
    return rps[i] + (c - cps[i])


# ── patterns (bytes, rendered text) ──────────────────────────────────────────
def U(s):
    return s.encode("utf-8")

W = rb"\s*"
ENVELOPE = re.compile(
    rb"\[agentmux\]" + W + rb"from" + W + rb"([A-Za-z0-9_.\-]+?)" + W +
    rb"\(" + W + rb"([A-Za-z_\-]+)" + W + rb"\)" + W +
    rb"(?:ref" + W + rb"([^\s:]+)" + W + rb")?:")
DISPATCH = re.compile(
    rb"Read" + W + rb"((?:/|~/)[^\s]+?\.md)" + W + rb"and" + W + rb"do" + W + rb"the" + W + rb"work")
PLACEHOLDER = re.compile(
    rb"(?i)\[pasted" + W + rb"(?:content|text)[^\]\n]{0,40}\]|\[[0-9]+" + W + rb"lines" + W + rb"pasted\]")
# agentmux.sh busy_marker, plus one extension: claude 2.1.28x no longer prints
# "esc to interrupt" in its spinner, only "Scurrying… (1m 19s)" /
# "Tomfoolering… (25s · ↓ 1.4k tokens)" or a bare "✻ Sublimating…" spinner line, and
# "Press up to edit queued messages" when a prompt arrives while it is working.
# Without these alternatives every claude pane would look permanently idle and every
# message to it would read as pending.
BUSY = re.compile(rb"(?i:esc" + W + rb"to" + W + rb"interrupt|ctrl\+c:cancel|ctrl-c" + W + rb"to" + W +
                  rb"stop|to" + W + rb"interrupt)"
                  rb"|[A-Z][a-z]+ing(?:\xe2\x80\xa6|\.\.\.)" + W + rb"\(" + W + rb"[0-9]+[smh]"
                  rb"|(?:\xe2\x9c[\xbb\xb6\xbd\xa2]|\xc2\xb7|\*)[ \t]*[A-Z][a-z]+ing\xe2\x80\xa6"
                  rb"|Press" + W + rb"up" + W + rb"to" + W + rb"edit" + W + rb"queued")
CLOCK24 = re.compile(rb"Worked" + W + rb"for" + W + rb"[0-9hms ]{1,20}?" + W + U("(?:•|·)") + W +
                     rb"([0-9]{1,2}):([0-9]{2})(?![0-9])(?!\s*[AaPp][Mm])")
CLOCK12 = re.compile(rb"done" + W + rb"([0-9]{1,2}):([0-9]{2})" + W + rb"([AP]M)")
# grok stamps each transcript entry with a bare "5:28 PM"; only used in grok panes
CLOCK12G = re.compile(rb"(?<![0-9:])([0-9]{1,2}):([0-9]{2})[ \t]*([AP]M)(?![A-Za-z])")
BANNER = re.compile(rb"OpenAI Codex|Claude Code|Grok Build")
SHELL = re.compile(rb"nick@[A-Za-z0-9_.\-]+:[^\n$]{0,200}\$(?: |\n|$)")

# modal triggers: (kind, subkind, trigger regex, [regexes that must also appear
# within +-window bytes of the trigger], window)
MODALS = [
    ("update", "codex-update-prompt", rb"(?i)update" + W + rb"now" + W + rb"\(runs",
     [rb"(?i)press" + W + rb"enter" + W + rb"to" + W + rb"continue", rb"(?i)skip"], 700),
    ("bypass", "claude-bypass-consent", rb"(?i)bypass" + W + rb"permissions" + W + rb"mode",
     [rb"(?i)yes,?" + W + rb"i" + W + rb"accept", rb"(?i)no,?" + W + rb"exit",
      rb"(?i)enter" + W + rb"to" + W + rb"confirm"], 900),
    ("trust", "codex-grok-directory-trust",
     rb"(?i)do" + W + rb"you" + W + rb"trust" + W + rb"the" + W + rb"contents",
     [rb"(?i)yes,?" + W + rb"(?:continue|proceed)|no,?" + W + rb"quit"], 1200),
    ("trust", "claude-folder-trust", rb"(?i)yes,?" + W + rb"i" + W + rb"trust" + W + rb"this" + W + rb"folder",
     [rb"(?i)enter" + W + rb"to" + W + rb"confirm|no,?" + W + rb"exit"], 900),
    ("login", "claude-login-method", rb"(?i)select" + W + rb"login" + W + rb"method", [], 0),
    ("login", "codex-sign-in", rb"(?i)sign" + W + rb"in" + W + rb"with" + W + rb"chatgpt", [], 0),
    ("login", "not-logged-in", rb"(?i)not" + W + rb"logged" + W + rb"in" + W + rb"(?:\xc2\xb7)?" + W +
     rb"(?:please" + W + rb")?run" + W + rb"/login", [], 0),
    ("effort", "effort-choice", rb"(?i)(?:recommended|recommend)[^\n]{0,60}effort|effort" + W + rb"level",
     [rb"(?i)enter" + W + rb"to" + W + rb"confirm"], 700),
    ("other", "codex-model-switch", rb"(?i)keep" + W + rb"current" + W + rb"model",
     [rb"(?i)press" + W + rb"enter" + W + rb"to" + W + rb"confirm"], 900),
    ("yn", "yes-no", rb"(?:\[[yY]/[nN]\]|\([yY]/[nN]\))[ \t]*(?:\n|$)", [], 0),
    ("other", "press-any-key", rb"(?i)press" + W + rb"any" + W + rb"key|select" + W + rb"an" + W + rb"option", [], 0),
]
MODALS = [(k, sk, re.compile(t), [re.compile(x) for x in req], win) for k, sk, t, req, win in MODALS]
MODAL_ANY = re.compile(b"|".join(b"(?:" + m[2].pattern.replace(b"(?i)", b"") + b")" for m in MODALS), re.I)

SELECTION = re.compile(
    U("(?:❯|›|▶|>)") + W + rb"(?:([0-9])\." + W + rb")?"
    rb"(No,?" + W + rb"exit|Yes,?" + W + rb"I" + W + rb"accept|Yes,?" + W + rb"I" + W + rb"trust" + W +
    rb"this" + W + rb"folder|Yes,?" + W + rb"continue|No,?" + W + rb"quit|Update" + W + rb"now|Skip" + W +
    rb"until" + W + rb"next" + W + rb"version|Skip)")

MESSAGE_KINDS = ["claim", "error", "finding", "plan", "release", "reply", "request", "status"]

SEL_OK = {
    "update": re.compile(rb"(?i)update|skip"),
    "bypass": re.compile(rb"(?i)exit|accept"),
    "trust": re.compile(rb"(?i)trust|continue|quit|exit"),
}
# which CLI can draw each modal; a match in another CLI's pane is quoted content
MODAL_FAMILY = {
    "codex-update-prompt": ("codex",), "claude-bypass-consent": ("claude",),
    "codex-grok-directory-trust": ("codex", "grok"), "claude-folder-trust": ("claude",),
    "claude-login-method": ("claude",), "codex-sign-in": ("codex",), "not-logged-in": ("claude",),
    "effort-choice": ("claude",), "codex-model-switch": ("codex",),
}

DEATHS = [
    ("please-restart", re.compile(rb"(?i)please" + W + rb"restart")),
    ("cli-exit", re.compile(rb"(?i)to" + W + rb"continue" + W + rb"this" + W + rb"session,?" + W + rb"run" + W +
                            rb"codex" + W + rb"resume|resume" + W + rb"this" + W + rb"session" + W + rb"with|"
                            rb"Token usage:" + W + rb"total=")),
]
INSTALL = re.compile(rb"(?i)updating" + W + rb"codex|npm" + W + rb"(?:ERR!|warn)|(?:added|changed)" + W +
                     rb"[0-9]+" + W + rb"packages?")

BOUND = re.compile(
    rb"\n[ \t]*(?:" + b"|".join(re.escape(U(g)) for g in
                               ["›", "❯", "•", "◦", "⏺", "●", "✻", "✶", "✽", "✢", "⎿", "╭", "╰", "│", "┃", "───"]) +
    rb"|Ask Codex|\[Pasted|\[agentmux\]|bash:|nick@)|\[agentmux\]|" + re.escape(U("⏵⏵")) +
    # a truncated render ends in an ellipsis; the rest is status-bar noise
    rb"|" + re.escape(U("…")))

WS = re.compile(r"\s+")
BOXCH = re.compile(r"[│┃]")  # grok draws its composer and transcript inside borders
GROKTIME = re.compile(r"(?<![0-9:])[0-9]{1,2}:[0-9]{2}\s*[AP]M(?![A-Za-z])")
NONALNUM = re.compile(r"[^a-z0-9]")


def norm_text(b):
    s = b.decode("utf-8", "replace")
    s = s.replace("\x1b[200~", "").replace("\x1b[201~", "")
    s = BOXCH.sub(" ", s)
    return WS.sub(" ", s).strip()


def pkey(s, n=48):
    return NONALNUM.sub("", s.lower())[:n]


# ── time anchors ─────────────────────────────────────────────────────────────
def parse_local_minute(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=CDT)


def build_anchors(clocks, size, mtime_local, started):
    """clocks: list of (offset, minutes_of_day). Returns sorted [(off, dt, kind)]."""
    accepted = []
    day = 0
    last = None
    for off, tod in clocks:
        if last is None:
            accepted.append((off, day, tod)); last = tod; continue
        d = tod - last
        if d >= 0:
            accepted.append((off, day, tod)); last = tod
        elif last >= 18 * 60 and tod <= 6 * 60:
            day += 1
            accepted.append((off, day, tod)); last = tod
        # any other drop: a repaint of an older status line (claude re-renders its
        # whole transcript, old "done" times included); ignore
    anchors = []
    if started is not None:
        anchors.append((0, started, "started"))
    if accepted:
        l_off, l_day, l_tod = accepted[-1]
        mt_tod = mtime_local.hour * 60 + mtime_local.minute
        base_date = mtime_local.date()
        if l_tod > mt_tod + 1:
            base_date = base_date - timedelta(days=1)
        for off, dd, tod in accepted:
            dt = datetime(base_date.year, base_date.month, base_date.day, tzinfo=CDT) + \
                timedelta(days=dd - l_day, minutes=tod)
            anchors.append((off, dt, "clock"))
    anchors.append((size, mtime_local + timedelta(seconds=59), "mtime"))
    # enforce monotone time, earliest-kind wins on ties; drop violators deterministically
    anchors.sort(key=lambda a: (a[0], a[1]))
    out = []
    for a in anchors:
        if started is not None and a[1] < started:
            continue
        if out and a[1] < out[-1][1]:
            continue
        out.append(a)
    return out


def utc_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def time_for(anchors, offs, off, size):
    i = bisect.bisect_right(offs, off) - 1
    lo = anchors[i] if i >= 0 else None
    j = bisect.bisect_left(offs, off)
    hi = anchors[j] if j < len(anchors) else None
    det = {"offset": off, "size": size, "offset_frac": round(off / size, 6) if size else None}
    if lo and hi:
        if hi[0] == lo[0]:
            t = lo[1]; method = "exact"
        else:
            frac = (off - lo[0]) / (hi[0] - lo[0])
            t = lo[1] + (hi[1] - lo[1]) * frac
            method = "interp"
        near = lo if (off - lo[0]) <= (hi[0] - off) else hi
    elif hi:
        t = hi[1]; method = "upper-bound"; near = hi
    elif lo:
        t = lo[1]; method = "lower-bound"; near = lo
    else:
        return None, "unknown", det
    det.update({
        "t_method": method,
        "t_lo": utc_iso(lo[1]) if lo else None, "off_lo": lo[0] if lo else None, "lo_kind": lo[2] if lo else None,
        "t_hi": utc_iso(hi[1]) if hi else None, "off_hi": hi[0] if hi else None, "hi_kind": hi[2] if hi else None,
        "tz_note": "anchors are local CDT (UTC-5): CLI clock text, run/<name>.started, indexed mtime",
    })
    basis = "file-mtime" if near[2] == "mtime" else "local-cdt"
    return utc_iso(t), basis, det


# ── per-file scan ────────────────────────────────────────────────────────────
class Deduper:
    """Fuzzy sliding-window dedupe keyed by an exact tuple plus a fuzzy string."""

    def __init__(self, window, ratio=0.85):
        self.window = window
        self.ratio = ratio
        self.live = {}      # tup -> list of [fuzzy, last_off, event]
        self.archive = {}   # tup -> list of fuzzy

    def see(self, tup, fuzzy, off):
        lst = self.live.get(tup)
        if lst:
            keep = []
            for ent in lst:
                if off - ent[1] > self.window:
                    self.archive.setdefault(tup, []).append(ent[0])
                else:
                    keep.append(ent)
            lst[:] = keep
            for ent in lst:
                if self.same(ent[0], fuzzy):
                    ent[1] = off
                    ev = ent[2]
                    ev["detail"]["sightings"] += 1
                    ev["detail"]["last_offset"] = off
                    return None, False
        suspect = False
        for old in self.archive.get(tup, ()):
            if self.same(old, fuzzy):
                suspect = True
                break
        return (lambda ev: self.live.setdefault(tup, []).append([fuzzy, off, ev])), suspect

    def same(self, a, b):
        if a == b:
            return True
        if not a or not b or self.ratio >= 1.0:
            return False
        # a truncated repaint ("CLAIM penguin/review-doc…") is a prefix of the full one
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) >= 12 and long_.startswith(short):
            return True
        return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= self.ratio


def detect_cli(name, first_bytes_banner):
    try:
        with open(os.path.join(RUNDIR, name + ".cli")) as fh:
            c = fh.read().strip()
            if c:
                return c, "sidecar"
    except OSError:
        pass
    return first_bytes_banner, "banner"


def scan_file(path, size, mtime_s, known_names):
    name = os.path.basename(path)[:-4]
    events = []
    busy_offs = array("q")
    clocks = []
    install_offs = []
    shell_hits = []
    first_banner = None
    first_banner_off = None
    env_spans = []         # (raw_start, raw_end) of envelope bodies, for dispatch folding
    dd_arr = Deduper(REDRAW_WINDOW)
    dd_ph = Deduper(REDRAW_WINDOW, ratio=1.0)
    dd_modal = Deduper(MODAL_WINDOW, ratio=1.0)
    dd_death = Deduper(REDRAW_WINDOW, ratio=1.0)
    busy_state = {"last": None, "ev": None}
    dropped = {}
    side_cli, _ = detect_cli(name, None)
    cli_hint = [side_cli]

    def new_event(typ, off, sender, path_kind, prefix, detail):
        ev = {"type": typ, "_off": off, "sender": sender, "path": path_kind, "prefix": prefix,
              "detail": dict(detail, sightings=1, last_offset=off)}
        events.append(ev)
        return ev

    fsize = os.path.getsize(path)
    limit = min(size, fsize)
    proc_from = 0
    buf_start = 0
    with open(path, "rb") as fh:
        while buf_start < limit:
            fh.seek(buf_start)
            raw = fh.read(min(CHUNK, limit - buf_start))
            if not raw:
                break
            buf_end = buf_start + len(raw)
            is_last = buf_end >= limit
            proc_to = buf_end if is_last else buf_end - KEEP
            text, cps, rps = render(raw, buf_start)
            ro = lambda c: raw_of(cps, rps, c)

            def ok(c):
                r = ro(c)
                return (proc_from <= r < proc_to), r

            # busy markers
            for m in BUSY.finditer(text):
                good, r = ok(m.start())
                if not good:
                    continue
                busy_offs.append(r)
                last = busy_state["last"]
                if last is None or r - last > BUSY_GAP:
                    ev = new_event("busy", r, None, None, norm_text(m.group(0))[:80], {"marker": norm_text(m.group(0))})
                    busy_state["ev"] = ev
                else:
                    ev = busy_state["ev"]
                    ev["detail"]["sightings"] += 1
                    ev["detail"]["last_offset"] = r
                busy_state["last"] = r

            # clocks
            for m in CLOCK24.finditer(text):
                good, r = ok(m.start())
                if good:
                    h, mi = int(m.group(1)), int(m.group(2))
                    if h < 24 and mi < 60:
                        clocks.append((r, h * 60 + mi))
            for m in (CLOCK12G if cli_hint[0] == "grok" else CLOCK12).finditer(text):
                good, r = ok(m.start())
                if good:
                    h, mi = int(m.group(1)), int(m.group(2))
                    if 1 <= h <= 12 and mi < 60:
                        h = (h % 12) + (12 if m.group(3) == b"PM" else 0)
                        clocks.append((r, h * 60 + mi))

            # banner
            if first_banner is None:
                m = BANNER.search(text)
                if m:
                    good, r = ok(m.start())
                    if good:
                        first_banner = {b"OpenAI Codex": "codex", b"Claude Code": "claude",
                                        b"Grok Build": "grok"}[m.group(0)]
                        first_banner_off = r
                        if cli_hint[0] is None:
                            cli_hint[0] = first_banner

            # envelopes
            for m in ENVELOPE.finditer(text):
                good, r = ok(m.start())
                if not good:
                    continue
                seg = text[m.end():m.end() + 1500]
                b = BOUND.search(seg, 1)
                body_b = seg[:b.start()] if b else seg
                body = norm_text(body_b)
                if cli_hint[0] == "grok":
                    # grok interleaves its transcript time stamps into wrapped text
                    body = WS.sub(" ", GROKTIME.sub(" ", body)).strip()
                sender_raw = m.group(1).decode("utf-8", "replace")
                kind = m.group(2).decode("utf-8", "replace").lower()
                mref = m.group(3).decode("utf-8", "replace") if m.group(3) else None
                close = difflib.get_close_matches(sender_raw, known_names, n=1, cutoff=0.75)
                sender = close[0] if close else sender_raw
                # partial repaints drop letters ("eply", "statu"); snap to the courier's
                # vocabulary (taskmgmt/courier.py MESSAGE_KINDS)
                kind_raw = kind
                ck = difflib.get_close_matches(kind, MESSAGE_KINDS, n=1, cutoff=0.6)
                kind = ck[0] if ck else kind
                dm = DISPATCH.search(body_b)
                brief = dm.group(1).decode("utf-8", "replace") if dm else None
                env_spans.append((r, ro(m.end() + len(body_b))))
                fz = pkey(body)
                # the ref is garbled by repaints as often as the body, so it joins the
                # fuzzy key rather than the exact one
                reg, suspect = dd_arr.see((sender, kind), pkey(mref or "", 16) + "|" + fz, r)
                if reg is None:
                    continue
                ev = new_event("arrived", r, sender, "courier", body[:80], {
                    "form": "envelope", "sender_raw": sender_raw, "kind": kind, "kind_raw": kind_raw,
                    "msg_ref": mref,
                    "dispatch_brief": brief, "prefix_key": fz[:40],
                    "captured_len": len(body), "captured_sha": hashlib.sha1(body.encode()).hexdigest(),
                    "redraw_suspect": suspect})
                reg(ev)

            # bare dispatch pointers
            for m in DISPATCH.finditer(text):
                good, r = ok(m.start())
                if not good:
                    continue
                inside = False
                for s0, e0 in reversed(env_spans[-50:]):
                    if s0 <= r <= e0:
                        inside = True
                        break
                if inside:
                    continue
                brief = m.group(1).decode("utf-8", "replace")
                if brief.startswith("~/"):
                    brief = "/home/nick/" + brief[2:]
                seg = text[m.start():m.start() + 400]
                bnd = BOUND.search(seg, 1)
                body = norm_text(seg[:bnd.start()] if bnd else seg)
                reg, suspect = dd_arr.see(("<dispatch>", "", brief), pkey(brief), r)
                if reg is None:
                    continue
                ev = new_event("arrived", r, None, "dispatch", body[:80], {
                    "form": "dispatch-pointer", "dispatch_brief": brief, "prefix_key": pkey(body)[:40],
                    "captured_len": len(body), "captured_sha": hashlib.sha1(body.encode()).hexdigest(),
                    "redraw_suspect": suspect})
                reg(ev)

            # placeholders
            for m in PLACEHOLDER.finditer(text):
                good, r = ok(m.start())
                if not good:
                    continue
                ph = norm_text(m.group(0))
                reg, suspect = dd_ph.see(("ph",), pkey(ph), r)
                if reg is None:
                    continue
                mc = re.search(r"(\d+)\s*chars", ph)
                ml = re.search(r"\+?(\d+)\s*lines", ph)
                ev = new_event("pending_input", r, None, None, ph[:80], {
                    "reason": "placeholder", "placeholder": ph,
                    "placeholder_chars": int(mc.group(1)) if mc else None,
                    "placeholder_lines": int(ml.group(1)) if ml else None,
                    "redraw_suspect": suspect})
                ev["_candidate"] = True
                reg(ev)

            # modals
            for m in MODAL_ANY.finditer(text):
                good, r = ok(m.start())
                if not good:
                    continue
                c = m.start()
                for kind, sub, trig, req, win in MODALS:
                    tm = trig.match(text, c)
                    if not tm:
                        continue
                    if req:
                        lo_c, hi_c = max(0, c - win), min(len(text), c + win)
                        if not all(x.search(text, lo_c, hi_c) for x in req):
                            continue
                    snippet = norm_text(text[max(0, c - 60):c + 160])
                    reg, suspect = dd_modal.see((kind, sub), "", r)
                    fam = MODAL_FAMILY.get(sub)
                    if fam and cli_hint[0] in ("codex", "claude", "grok") and cli_hint[0] not in fam:
                        dropped["modal-cli-mismatch"] = dropped.get("modal-cli-mismatch", 0) + 1
                        break
                    sel_seg = text[max(0, c - 200):min(len(text), c + 1500)] \
                        if kind in ("update", "bypass", "trust") else b""
                    sels = [norm_text(s.group(0)) for s in SELECTION.finditer(sel_seg)
                            if SEL_OK[kind].search(s.group(0))]
                    if reg is None:
                        # extend the live one
                        for ent in dd_modal.live.get((kind, sub), []):
                            if sels:
                                ent[2]["detail"]["last_selection"] = sels[-1]
                        break
                    ev = new_event("modal", r, None, None, snippet[:80], {
                        "modal": kind, "subkind": sub, "snippet": snippet[:300],
                        "first_selection": sels[0] if sels else None,
                        "last_selection": sels[-1] if sels else None,
                        "redraw_suspect": suspect})
                    reg(ev)
                    break

            # deaths (direct)
            for dk, rx in DEATHS:
                for m in rx.finditer(text):
                    good, r = ok(m.start())
                    if not good:
                        continue
                    reg, suspect = dd_death.see((dk,), "", r)
                    if reg is None:
                        continue
                    snippet = norm_text(text[max(0, m.start() - 120):m.end() + 160])
                    ev = new_event("death", r, None, None, snippet[:80], {
                        "death": dk, "snippet": snippet[:300], "redraw_suspect": suspect})
                    reg(ev)
            for m in INSTALL.finditer(text):
                good, r = ok(m.start())
                if good:
                    install_offs.append((r, norm_text(text[max(0, m.start() - 120):m.end() + 160])[:300]))
            for m in SHELL.finditer(text):
                good, r = ok(m.start())
                if good:
                    shell_hits.append((r, norm_text(text[max(0, m.start() - 160):m.end() + 80])[:300]))

            proc_from = proc_to
            if is_last:
                break
            # next buffer starts a little before proc_to, at a line break, so the
            # renderer never starts inside an escape sequence we care about
            # the next buffer starts ~4 KiB before proc_to, exactly on an ESC byte
            # (a token boundary), so the renderer never starts mid-sequence
            want = len(raw) - KEEP - 4096
            back = raw.rfind(b"\x1b", max(0, want - 65536), max(1, want))
            if back < 0:
                back = max(0, want)
            buf_start = min(max(buf_start + 1, buf_start + back), proc_to)

    cli, cli_src = detect_cli(name, first_banner or ("shell" if shell_hits and first_banner is None else "unknown"))

    # post: install-output deaths after an update modal
    upd = [e for e in events if e["type"] == "modal" and e["detail"]["modal"] == "update"]
    for u in upd:
        if "skip" in (u["detail"].get("last_selection") or "").lower():
            continue
        lo_o, hi_o = u["_off"], u["detail"]["last_offset"] + MODAL_WINDOW
        for r, snip in install_offs:
            if lo_o <= r <= hi_o:
                new_event("death", r, None, None, snip[:80], {
                    "death": "update-install-output", "snippet": snip, "after_modal_ref": "%s@%d" % (path, u["_off"]),
                    "modal_last_selection": u["detail"].get("last_selection"), "redraw_suspect": False})
                break
    # post: shell prompt returning after a CLI banner
    if first_banner is not None and cli in ("codex", "claude", "grok"):
        last_emit = None
        for r, snip in shell_hits:
            if r <= first_banner_off:
                continue
            if last_emit is not None and r - last_emit <= REDRAW_WINDOW:
                last_emit = r
                continue
            new_event("death", r, None, None, snip[:80], {"death": "shell-prompt-returned", "snippet": snip,
                                                          "redraw_suspect": False})
            last_emit = r
    # post: log ends on a consent/trust modal still at "No, exit"
    tail_modals = [e for e in events if e["type"] == "modal" and e["detail"]["modal"] in ("bypass", "trust")]
    if tail_modals:
        lm = max(tail_modals, key=lambda e: e["detail"]["last_offset"])
        later_work = [e for e in events if e["type"] in ("busy", "arrived") and e["_off"] > lm["detail"]["last_offset"]]
        sel = (lm["detail"].get("last_selection") or "").lower().replace(" ", "")
        if limit - lm["detail"]["last_offset"] <= (16 << 10) and not later_work and ("noexit" in sel.replace(",", "") or
                                                                                     "noquit" in sel.replace(",", "")):
            new_event("death", lm["detail"]["last_offset"], None, None, "log ends on modal with 'No, exit' selected", {
                "death": "ended-on-no-exit-default", "modal_ref": "%s@%d" % (path, lm["_off"]),
                "last_selection": lm["detail"].get("last_selection"), "confidence": "low", "redraw_suspect": False})

    # pending decisions
    busy_sorted = busy_offs  # appended in stream order -> already sorted

    def next_busy(after):
        i = bisect.bisect_right(busy_sorted, after)
        return busy_sorted[i] - after if i < len(busy_sorted) else None

    def busy_before(at, span):
        i = bisect.bisect_left(busy_sorted, at) - 1
        return i >= 0 and at - busy_sorted[i] <= span

    pend = []
    for ev in events:
        if ev["type"] == "arrived":
            nb = next_busy(ev["_off"])
            ev["detail"]["next_busy_bytes"] = nb
            ev["detail"]["busy_in_progress"] = busy_before(ev["_off"], 8 << 10)
            if (nb is None or nb > PENDING_WINDOW) and not ev["detail"]["busy_in_progress"]:
                nbl = next_busy(ev["detail"]["last_offset"])
                pend.append({"type": "pending_input", "_off": ev["_off"], "sender": ev["sender"], "path": ev["path"],
                             "prefix": ev["prefix"], "detail": {
                                 "reason": "arrived-no-busy", "arrived_ref": "%s@%d" % (path, ev["_off"]),
                                 "msg_ref": ev["detail"].get("msg_ref"), "kind": ev["detail"].get("kind"),
                                 "prefix_key": ev["detail"].get("prefix_key"),
                                 "sightings": ev["detail"]["sightings"], "last_offset": ev["detail"]["last_offset"],
                                 "next_busy_bytes_from_first": nb, "next_busy_bytes_from_last": nbl,
                                 "eventually_busy": nb is not None, "window_bytes": PENDING_WINDOW}})
        elif ev.get("_candidate"):
            nb = next_busy(ev["_off"])
            nbl = next_busy(ev["detail"]["last_offset"])
            ev["detail"].update({"next_busy_bytes_from_first": nb, "next_busy_bytes_from_last": nbl,
                                 "eventually_busy": nb is not None, "window_bytes": PENDING_WINDOW,
                                 "busy_in_progress": busy_before(ev["_off"], 8 << 10)})
            ev["_drop"] = not (nb is None or nb > PENDING_WINDOW) or ev["detail"]["busy_in_progress"]
    events = [e for e in events if not e.get("_drop")] + pend

    # times
    started = None
    try:
        with open(os.path.join(RUNDIR, name + ".started")) as fh:
            started = datetime.fromisoformat(fh.read().strip())
    except (OSError, ValueError):
        pass
    mtime_local = parse_local_minute(mtime_s)
    clocks.sort()
    anchors = build_anchors(clocks, limit, mtime_local, started)
    offs = [a[0] for a in anchors]
    recs = []
    for ev in events:
        t, basis, tdet = time_for(anchors, offs, ev["_off"], limit)
        det = dict(ev["detail"])
        det.update(tdet)
        det["cli"] = cli
        det["cli_source"] = cli_src
        det["clock_anchors"] = sum(1 for a in anchors if a[2] == "clock")
        if ev["type"] == "arrived" and ev["path"] == "courier":
            pass
        recs.append({
            "src": "panes", "type": ev["type"], "t": t, "t_basis": basis, "agent": name,
            "sender": ev["sender"], "path": ev["path"], "prefix": ev["prefix"],
            "body_sha": None, "body_len": None, "detail": det,
            "ref": "%s@%d" % (path, ev["_off"]),
        })
    stats = {"file": path, "indexed_size": size, "read": limit, "truncated_since_index": fsize < size,
             "busy_markers": len(busy_offs), "clocks_raw": len(clocks),
             "clock_anchors": sum(1 for a in anchors if a[2] == "clock"), "cli": cli, "dropped": dropped}
    return recs, stats


def main():
    rows = []
    with open(INDEX) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0].endswith(".log"):
                rows.append((parts[0], int(parts[1]), parts[2]))
    rows.sort()
    known = sorted({os.path.basename(p)[:-4] for p, _, _ in rows} | {"orchestrator", "operator"})
    allrecs = []
    allstats = []
    for p, size, mt in rows:
        if not os.path.exists(p):
            allstats.append({"file": p, "missing": True})
            continue
        recs, st = scan_file(p, size, mt, known)
        allrecs.extend(recs)
        allstats.append(st)
        print("%-60s %10d  events=%d" % (p, size, len(recs)), file=sys.stderr, flush=True)
    allrecs.sort(key=lambda r: (r["agent"], int(r["ref"].rsplit("@", 1)[1]), r["type"], r["prefix"] or ""))
    os.makedirs(OUTDIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in allrecs:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT)
    # summary to stdout
    from collections import Counter
    ct = Counter(r["type"] for r in allrecs)
    print("TOTAL", len(allrecs), dict(sorted(ct.items())))
    agg = Counter()
    for s in allstats:
        agg.update(s.get("dropped", {}))
        if s.get("truncated_since_index") or s.get("missing"):
            print("WARN", s)
    print("DROPPED", dict(sorted(agg.items())))
    print("FILES", len(allstats), "no-clock-anchor files",
          sum(1 for s in allstats if not s.get("missing") and s.get("clock_anchors", 0) == 0))


if __name__ == "__main__":
    main()
