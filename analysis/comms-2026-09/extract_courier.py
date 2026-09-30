#!/usr/bin/env python3
"""Courier-side extractor for the 2026-09 communication-failure analysis.

Read-only. Stdlib only. Deterministic: no "now" in any record, output sorted.
Run inside WSL with the analysis folder as the working directory:

    python C:\\Users\\Nick\\.claude\\skills\\wsl-cli\\scripts\\wsl.py py ^
        C:\\Dev\\agentmux\\analysis\\comms-2026-09\\extract_courier.py ^
        --cwd C:\\Dev\\agentmux\\analysis\\comms-2026-09 --timeout 1800

Writes out/courier.jsonl (the record stream, schema in README.md) and
out/courier.summary.json (the counts the extractor report quotes).

SOURCES AND THEIR CLOCKS (established from taskmgmt/courier.py, coordination.py,
run.py, agentmux.sh and the data itself - see TZ_NOTES below):
  queue/*.jsonl 'at'         explicit offset; -0500 (CDT) for all but 10 early lines,
                             which carry +00:00 (codexdev, grokrev, orchestrator,
                             written 2026-09-19 by an older seeding tool)
  courier/courier.log        time.strftime('%Y-%m-%dT%H:%M:%S%z') -> local, -0500
  courier/dead-letter.jsonl  courier.now() -> local, -0500
  journal.jsonl (fallback)   coordination.now() -> local, -0500
  claims/*.json 'at'         coordination.now() -> local, -0500
  runs/*/events.jsonl        -0500
  dispatch/pool.log          -0500
  db/cc.db journal, board_history, board_comments   UTC, +00:00, microseconds
  run/.idle.log              NO TIMESTAMP AT ALL (printf in agentmux.sh cmd_idle)
  run/*.started              -05:00
  claims/.steal.*            empty tombstones; file mtime only
  dispatch/*.md, jobs/*.md   file mtime only
The machine is America/Chicago; every date in scope is CDT, UTC-5.

LINKING courier.log TO QUEUE LINES. The courier never logs a body or an id - only
"sent S -> R (kind[, retry N])", "defer S -> R: reason", "gave up S -> R: reason".
Each courier event is linked to a queue line by replaying the courier's own
algorithm per (sender, recipient): the courier reads each outbox in file order, so
the first "sent"/"defer" for (S, R, kind) is the earliest not-yet-linked queue line
from S to R with that kind whose 'at' is not after the event. A "defer" makes the
line pending; a "sent ... retry N" or "gave up" consumes the earliest pending line
(or, failing that, a line that was held "queued behind an earlier message" and so
never logged a defer). A "gave up" is additionally matched exactly against
dead-letter.jsonl, which keeps the whole message, whenever that row exists.
"""
import collections
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

SNAP = Path("/home/nick/agentmux-comms-snapshot/20260929-215601")
REPO = Path("/mnt/c/Dev/agentmux")
HIST_JOURNALS = sorted(glob.glob(str(REPO / "audit_2026-09-17" / "*journal*.jsonl"))) + [
    str(REPO / "wsl-agent-teams" / "hardening-journal.jsonl")]

UTC = dt.timezone.utc
CDT = dt.timezone(dt.timedelta(hours=-5))

OUT_DIR = Path.cwd() / "out"
OUT = OUT_DIR / "courier.jsonl"
SUMMARY = OUT_DIR / "courier.summary.json"

# Names that are real addresses without a pane, or that are not agents at all.
VIRTUAL = {"orchestrator"}
NON_AGENT_ACTORS = {"orchestrator", "dashboard", "migration", "operator (dashboard)",
                    "courier", "run", "pool"}
MESSAGE_KINDS = {"plan", "request", "reply", "status", "finding", "error", "claim",
                 "release"}
NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
MAX_ATTEMPTS = 12

TZ_NOTES = {
    "queue": "queue 'at' carries an explicit offset; -0500 = CDT except 10 lines "
             "with +00:00 (2026-09-19 seed in codexdev/grokrev/orchestrator outboxes)",
    "courier.log": "courier.log(): time.strftime('%Y-%m-%dT%H:%M:%S%z'), local CDT, "
                   "explicit -0500 on every one of its lines",
    "cc.db": "cc.db journal/board_history/board_comments 'at' is UTC (+00:00, "
             "microseconds) - 5 h ahead of every file-based source",
    "idle.log": ".idle.log lines have no timestamp (agentmux.sh cmd_idle printf); "
                "time is bounded from other evidence, never read from the line",
}

# ───────────────────────────────────────────────────────────── helpers ──

ISO_RX = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d)(\.\d+)?)?"
                    r"\s*(Z|[+-]\d\d:?\d\d)?$")


def parse_ts(text, default_tz=None):
    """ISO-ish text -> aware datetime, or None. No tz and no default -> None."""
    if not isinstance(text, str):
        return None
    m = ISO_RX.match(text.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, tz = m.groups()
    micro = int((frac or ".0")[1:].ljust(6, "0")[:6])
    if tz is None:
        if default_tz is None:
            return None
        tzinfo = default_tz
    elif tz == "Z":
        tzinfo = UTC
    else:
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        tzinfo = dt.timezone(sign * dt.timedelta(hours=int(digits[:2]),
                                                 minutes=int(digits[2:])))
    return dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), micro,
                       tzinfo=tzinfo)


def iso_z(when):
    if when is None:
        return None
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def basis_of(when, text=None):
    """t_basis for a parsed timestamp: which clock the SOURCE wrote."""
    if when is None:
        return "unknown"
    off = when.utcoffset()
    if off == dt.timedelta(0):
        return "utc"
    if off == dt.timedelta(hours=-5):
        return "local-cdt"
    return "unknown"


def mtime_of(path):
    return dt.datetime.fromtimestamp(os.stat(path).st_mtime, tz=UTC)


def epoch(when):
    return when.timestamp() if when is not None else None


ANSI_RX = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|"
                     r"\x1b[@-Z\\-_]")
PASTE_RX = re.compile(r"\x1b?\[20[01]~")
ENVELOPE_RX = re.compile(r"^\s*\[agentmux\] from ([A-Za-z0-9_.-]+) \(([a-z]+)\)"
                         r"(?: ref (\S+))?: ")
WS_RX = re.compile(r"\s+")


def normalize(body):
    """README normalization. Returns (normalized_text, envelope_dict_or_None)."""
    if body is None:
        return None, None
    text = ANSI_RX.sub("", body)
    text = PASTE_RX.sub("", text)
    env = None
    m = ENVELOPE_RX.match(text)
    if m:
        env = {"from": m.group(1), "kind": m.group(2), "ref": m.group(3)}
        text = text[m.end():]
    text = WS_RX.sub(" ", text).strip()
    return text, env


def body_fields(body):
    norm, env = normalize(body)
    if norm is None:
        return None, None, None, None
    return (norm[:80], hashlib.sha1(norm.encode("utf-8")).hexdigest(), len(norm), env)


def sp(path):
    return str(path)


def rel_ref(path, line=None, offset=None):
    if line is not None:
        return f"{path}:{line}"
    if offset is not None:
        return f"{path}@{offset}"
    return str(path)


RECORDS = []


def emit(type_, t, t_basis, agent, sender, path, body=None, detail=None, ref=None,
         prefix=None, body_sha=None, body_len=None):
    if body is not None:
        prefix, body_sha, body_len, env = body_fields(body)
        if env:
            detail = dict(detail or {})
            detail["envelope"] = env
    RECORDS.append({
        "src": "courier", "type": type_, "t": t, "t_basis": t_basis,
        "agent": agent, "sender": sender, "path": path, "prefix": prefix,
        "body_sha": body_sha, "body_len": body_len, "detail": detail or {},
        "ref": ref,
    })
    return RECORDS[-1]


def read_lines(path):
    """[(1-based line number, byte offset, raw bytes)] for every non-blank line."""
    with open(path, "rb") as fh:
        data = fh.read()
    out, offset = [], 0
    for i, raw in enumerate(data.split(b"\n")):
        if raw.strip():
            out.append((i + 1, offset, raw))
        offset += len(raw) + 1
    return out


def ro_db(path):
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


# ─────────────────────────────────────────────── liveness evidence store ──

ALIVE = collections.defaultdict(list)   # name -> [(epoch, what, ref)]
DEAD = collections.defaultdict(list)    # name -> [(epoch, what, ref)]


def alive(name, when, what, ref):
    if name and when is not None:
        ALIVE[name].append((epoch(when), what, ref))


def dead(name, when, what, ref):
    if name and when is not None:
        DEAD[name].append((epoch(when), what, ref))


# ───────────────────────────────────────────────────────────── queue ──

QUEUE = []           # dicts, one per queue line
ADOPTED = {}         # outbox -> offset adopted at EOF by the courier's first pass


def load_queue():
    for f in sorted(glob.glob(sp(SNAP / "queue" / "*.jsonl"))):
        outbox = Path(f).stem
        for line, offset, raw in read_lines(f):
            try:
                rec = json.loads(raw)
            except ValueError:
                QUEUE.append({"outbox": outbox, "line": line, "offset": offset,
                              "end": offset + len(raw) + 1, "bad": True, "file": f})
                continue
            when = parse_ts(rec.get("at"))
            q = {"outbox": outbox, "file": f, "line": line, "offset": offset,
                 "end": offset + len(raw) + 1, "bad": False, "rec": rec,
                 "at": when, "ep": epoch(when), "sender": rec.get("sender"),
                 "recipient": rec.get("recipient"), "kind": rec.get("kind"),
                 "body": rec.get("body"), "ref_field": rec.get("ref"),
                 "events": [], "state": "fresh"}
            QUEUE.append(q)


def valid_for_courier(q):
    """Mirror of courier.parse_record: would the courier even consider this line?"""
    if q["bad"]:
        return False, "unparseable JSON"
    r = q["rec"]
    if r.get("kind") not in MESSAGE_KINDS:
        return False, f"unknown kind {r.get('kind')!r}"
    rc = r.get("recipient")
    if not isinstance(rc, str) or not NAME_PATTERN.fullmatch(rc):
        return False, "no recipient (null) - a broadcast/log line, never delivered by design"
    s = r.get("sender")
    if not isinstance(s, str) or not NAME_PATTERN.fullmatch(s):
        return False, "invalid sender"
    b = r.get("body")
    if not isinstance(b, str) or not b.strip():
        return False, "empty body"
    if q["outbox"] == "courier":
        return False, "courier's own outbox is never redelivered"
    return True, None


# ───────────────────────────────────────────────────────────── courier.log ──

LOG_RX = re.compile(r"^(\S+)  (.*)$")
SENT_RX = re.compile(r"^sent    ([A-Za-z0-9_.-]+) -> ([A-Za-z0-9_.-]+) \(([a-z]+)"
                     r"(?:, retry (\d+))?\)$")
DEFER_RX = re.compile(r"^defer   ([A-Za-z0-9_.-]+) -> ([A-Za-z0-9_.-]+): (.*)$")
GAVE_RX = re.compile(r"^gave up ([A-Za-z0-9_.-]+) -> ([A-Za-z0-9_.-]+): (.*)$")
CURSOR_RX = re.compile(r"^cursor  ([A-Za-z0-9_.-]+) (.*)$")
WATCH_RX = re.compile(r"^courier watching (\S+) every ([\d.]+)s \(pid (\d+)\)$")
NOTRUN_RX = re.compile(r"'([A-Za-z0-9_.-]+)' is not running")


def load_courier_log():
    path = SNAP / "courier" / "courier.log"
    events, lifecycle = [], []
    for line, _off, raw in read_lines(path):
        text = raw.decode("utf-8", "replace")
        m = LOG_RX.match(text)
        if not m:
            continue
        when = parse_ts(m.group(1))
        msg = m.group(2)
        ev = {"t": when, "ep": epoch(when), "line": line, "raw": msg,
              "ref": rel_ref(path, line)}
        if (s := SENT_RX.match(msg)):
            ev.update(kind="sent", s=s.group(1), r=s.group(2), k=s.group(3),
                      retry=int(s.group(4)) if s.group(4) else None)
        elif (s := DEFER_RX.match(msg)):
            ev.update(kind="defer", s=s.group(1), r=s.group(2), reason=s.group(3), k=None)
        elif (s := GAVE_RX.match(msg)):
            ev.update(kind="gave_up", s=s.group(1), r=s.group(2), reason=s.group(3), k=None)
        elif (s := CURSOR_RX.match(msg)):
            ev.update(kind="cursor", outbox=s.group(1), note=s.group(2))
            m2 = re.search(r"adopting at EOF \(offset (\d+)\)", s.group(2))
            if m2:
                ADOPTED[s.group(1)] = int(m2.group(1))
        elif (s := WATCH_RX.match(msg)):
            ev.update(kind="watching", pid=int(s.group(3)), interval=float(s.group(2)))
        elif msg == "courier stopped" or "nothing left to deliver" in msg:
            # NOT "another courier ... refusing to start": that is a second process
            # declining while the first keeps running.
            ev.update(kind="stopped")
        else:
            ev.update(kind="other")
        if ev["kind"] in ("watching", "stopped"):
            lifecycle.append(ev)
        else:
            events.append(ev)
    return events, lifecycle


def courier_intervals(lifecycle, all_eps):
    """[(start_ep, end_ep_or_None, pid, how)].

    A watcher that vanished without logging 'stopped' (crash, reboot, WSL shutdown)
    is taken to have been up until the LAST line the courier logged before the next
    watcher started - it demonstrably ran until then - and unknown after that."""
    out, cur = [], None
    for ev in lifecycle:
        if ev["kind"] == "watching":
            if cur is not None:
                seen = [e for e in all_eps if cur["ep"] <= e < ev["ep"]]
                out.append((cur["ep"], max(seen) if seen else cur["ep"], cur["pid"],
                            "no stop logged; end = its last logged line"))
            cur = ev
        elif ev["kind"] == "stopped" and cur is not None:
            out.append((cur["ep"], ev["ep"], cur["pid"], "stopped"))
            cur = None
    if cur is not None:
        out.append((cur["ep"], None, cur["pid"], "running at snapshot"))
    return out


def courier_up(intervals, ep, last_log_ep):
    """(True|False|None, pid). None = a watcher started and later vanished without
    logging 'stopped' (crash or reboot), so whether it was still up is unknown."""
    cur = None
    for iv in intervals:
        if iv[0] <= ep:
            cur = iv
    if cur is None:
        return False, None
    start, end, pid, why = cur
    if end is None:
        return True, pid
    if ep <= end:
        return True, pid
    # After a silently-ended watcher's last line: it may or may not still have run.
    return (None if why.startswith("no stop") else False), None


# ──────────────────────────────────────────────────────────────── link ──

def link_courier(events):
    by_pair = collections.defaultdict(list)
    for q in QUEUE:
        if q["bad"]:
            continue
        ok, _why = valid_for_courier(q)
        q["valid"] = ok
        q["history"] = False
        adopted = ADOPTED.get(q["outbox"])
        if adopted is not None and q["end"] <= adopted:
            q["history"] = True
        if ok and not q["history"]:
            by_pair[(q["sender"], q["recipient"])].append(q)

    dl_rows = []
    dl_path = SNAP / "courier" / "dead-letter.jsonl"
    for line, _off, raw in read_lines(dl_path):
        row = json.loads(raw)
        row["_line"] = line
        row["_t"] = parse_ts(row.get("at"))
        row["_used"] = False
        dl_rows.append(row)

    def first(pair, states, kind=None, before=None):
        for q in by_pair.get(pair, []):
            if q["state"] not in states:
                continue
            if kind is not None and q["kind"] != kind:
                continue
            if before is not None and q["ep"] is not None and q["ep"] > before + 2:
                continue
            return q
        return None

    sent_seen = collections.defaultdict(list)
    for ev in events:
        if ev["kind"] not in ("sent", "defer", "gave_up"):
            continue
        pair = (ev["s"], ev["r"])
        q, how = None, None
        if ev["kind"] == "sent" and ev["retry"] is None:
            q = first(pair, ("fresh",), ev["k"], ev["ep"])
            how = "fifo-first-attempt"
            if q is None:
                # A second "sent" for a line already sent seconds ago: a duplicate
                # delivery (two tick() callers racing on one cursor - the courier is
                # at-least-once by design, see the ORDER IS LOAD-BEARING comment).
                prev = next((p for p in reversed(sent_seen.get((pair, ev["k"]), []))
                             if ev["ep"] - p["ep"] <= 5 and p.get("q") is not None), None)
                if prev is not None:
                    q, how = prev["q"], "duplicate-of-previous-send"
                    ev["duplicate_of"] = prev["ref"]
                    q["duplicates"] = q.get("duplicates", 0) + 1
                    ev["q"], ev["how"] = q, how
                    q["events"].append(ev)
                    sent_seen[(pair, ev["k"])].append(ev)
                    continue
        elif ev["kind"] == "defer":
            q = first(pair, ("fresh",), None, ev["ep"])
            how = "fifo-first-attempt"
        elif ev["kind"] == "sent":
            q = first(pair, ("pending",), ev["k"], ev["ep"])
            how = "fifo-pending"
            if q is None:
                q = first(pair, ("fresh",), ev["k"], ev["ep"])
                how = "fifo-queued-behind"
        else:  # gave_up
            row = next((r for r in dl_rows if not r["_used"]
                        and r["message"].get("sender") == ev["s"]
                        and r["message"].get("recipient") == ev["r"]
                        and r["_t"] is not None
                        and abs(epoch(r["_t"]) - ev["ep"]) <= 2), None)
            if row is not None:
                row["_used"] = True
                ev["dead_letter_row"] = row
                msg = row["message"]
                for cand in by_pair.get(pair, []):
                    if cand["state"] in ("fresh", "pending") and cand["body"] == msg.get("body") \
                            and cand["rec"].get("at") == msg.get("at"):
                        q, how = cand, "dead-letter-exact"
                        break
            if q is None:
                q = first(pair, ("pending",), None, ev["ep"])
                how = "fifo-pending"
                if q is None:
                    q = first(pair, ("fresh",), None, ev["ep"])
                    how = "fifo-queued-behind"
        ev["q"], ev["how"] = q, how
        if ev["kind"] == "sent":
            sent_seen[(pair, ev["k"])].append(ev)
        if q is None:
            continue
        q["events"].append(ev)
        if ev["kind"] == "sent":
            q["state"] = "sent"
        elif ev["kind"] == "defer":
            q["state"] = "pending"
        else:
            q["state"] = "dead"
    return dl_rows


# ─────────────────────────────────────────────────────── other loaders ──

def load_db_rows():
    """cc.db (current) journal, board_history, board_comments, roster."""
    con = ro_db(SNAP / "db" / "cc.db")
    journal = con.execute("select id, at, kind, agent, subject, body from journal "
                          "order by id").fetchall()
    history = con.execute("select id, at, entity_key, event, actor, session, detail "
                          "from board_history order by id").fetchall()
    comments = con.execute("select id, entity_key, author, at, text from board_comments "
                           "order by id").fetchall()
    roster = con.execute("select entity_key, agent_name, role, status, member_name, at "
                         "from board_roster order by id").fetchall()
    con.close()
    return journal, history, comments, roster


def load_runs():
    rows = []
    for f in sorted(glob.glob(sp(SNAP / "runs" / "*" / "events.jsonl"))):
        for line, _off, raw in read_lines(f):
            try:
                rows.append((f, line, json.loads(raw)))
            except ValueError:
                continue
    return rows


def pane_names():
    """Every name that demonstrably had a pane: pane log files, run sidecars,
    idle-watchdog targets, courier outboxes, dispatch panes."""
    names = set()
    for line in (SNAP / "logs.index.tsv").read_text(encoding="utf-8").splitlines():
        p = line.split("\t")[0]
        if p.endswith(".log"):
            names.add(Path(p).stem)
    for f in glob.glob(sp(SNAP / "run" / "*.cli")):
        names.add(Path(f).stem)
    for f in glob.glob(sp(SNAP / "queue" / "*.jsonl")):
        names.add(Path(f).stem)
    for line in (SNAP / "run" / ".idle.log").read_text(encoding="utf-8").splitlines():
        m = re.match(r"closing (\S+) after", line)
        if m:
            names.add(m.group(1))
    names.discard("courier")
    return names


# ────────────────────────────────────────────────────────────── main ──

def main():
    if Path.cwd().name != "comms-2026-09":
        sys.exit("run with --cwd set to the analysis folder (comms-2026-09)")
    OUT_DIR.mkdir(exist_ok=True)

    load_queue()
    events, lifecycle = load_courier_log()
    all_eps = sorted(e["ep"] for e in events + lifecycle if e["ep"] is not None)
    intervals = courier_intervals(lifecycle, all_eps)
    last_log_ep = max(e["ep"] for e in events + lifecycle if e["ep"] is not None)
    dl_rows = link_courier(events)
    journal, history, comments, roster = load_db_rows()
    runs = load_runs()
    panes = pane_names()

    # Snapshot's local-fallback journal file (coordination.JOURNAL_FALLBACK).
    fallback_journal = []
    fj = SNAP / "journal.jsonl"
    for line, _off, raw in read_lines(fj):
        try:
            fallback_journal.append((line, json.loads(raw)))
        except ValueError:
            pass

    claims = []
    for f in sorted(glob.glob(sp(SNAP / "claims" / "*.json"))):
        try:
            claims.append((f, json.loads(Path(f).read_text(encoding="utf-8"))))
        except (ValueError, OSError):
            pass
    steals = sorted(glob.glob(sp(SNAP / "claims" / ".steal.*")))

    # ── liveness evidence ─────────────────────────────────────────────
    for q in QUEUE:
        if q["bad"] or q["sender"] in VIRTUAL or q["sender"] == "courier":
            continue
        alive(q["sender"], q["at"], "posted", rel_ref(q["file"], q["line"]))
    for ev in events:
        if ev["kind"] == "sent" and ev["r"] not in VIRTUAL:
            alive(ev["r"], ev["t"], "courier-sent-to", ev["ref"])
        if ev["kind"] in ("defer", "gave_up"):
            m = NOTRUN_RX.search(ev["reason"])
            if m:
                dead(m.group(1), ev["t"], "courier-not-running", ev["ref"])
            elif "showing a prompt" in ev["reason"]:
                alive(ev["r"], ev["t"], "courier-saw-prompt", ev["ref"])
    dbp = sp(SNAP / "db" / "cc.db")
    for (i, at, kind, agent, subj, body) in journal:
        if agent and agent not in NON_AGENT_ACTORS:
            alive(agent, parse_ts(at), "journal", f"{dbp}#journal:{i}")
    for (i, at, ek, ev_, actor, sess, det) in history:
        if actor and actor not in NON_AGENT_ACTORS:
            alive(actor, parse_ts(at), "board_history", f"{dbp}#board_history:{i}")
    for (i, ek, author, at, text) in comments:
        if author and author not in NON_AGENT_ACTORS:
            alive(author, parse_ts(at), "board_comment", f"{dbp}#board_comments:{i}")
    for (f, line, ev) in runs:
        if ev.get("event") in ("submit", "verdict") and ev.get("by"):
            alive(ev["by"], parse_ts(ev.get("at")), f"run-{ev['event']}", rel_ref(f, line))
    for name in ALIVE:
        ALIVE[name].sort()
    for name in DEAD:
        DEAD[name].sort()

    def near(lst, ep, window):
        return [x for x in lst if abs(x[0] - ep) <= window]

    def liveness(q):
        r = q["recipient"]
        if r in VIRTUAL:
            return "virtual-inbox", None
        firsts = [e for e in q["events"] if e["kind"] in ("sent", "defer")]
        if firsts:
            e = firsts[0]
            if e["kind"] == "defer" and NOTRUN_RX.search(e["reason"]):
                return "not-live:courier-said-not-running", e["ref"]
            if e["ep"] - q["ep"] <= 120:
                return "live:courier-reached-pane", e["ref"]
        if q["ep"] is None:
            return "unknown", None
        a = near(ALIVE.get(r, []), q["ep"], 600)
        d = near(DEAD.get(r, []), q["ep"], 600)
        if a and not d:
            return "live:evidence-within-10m", a[0][2]
        if d and not a:
            return "not-live:evidence-within-10m", d[0][2]
        if a and d:
            return "ambiguous:alive-and-dead-evidence-within-10m", d[0][2]
        if r not in ALIVE and r not in panes:
            return "not-live:never-seen-anywhere", None
        return "unknown:no-evidence-within-10m", None

    # ── queued ─────────────────────────────────────────────────────────
    per_recipient = collections.defaultdict(collections.Counter)
    never_attempted, not_live = [], []
    for q in QUEUE:
        ref = rel_ref(q["file"], q["line"])
        if q["bad"]:
            emit("queued", None, "unknown", None, None, "post",
                 detail={"error": "unparseable JSON line", "outbox": q["outbox"]}, ref=ref)
            continue
        ok, why = valid_for_courier(q)
        detail = {"kind": q["kind"], "ref_field": q["ref_field"], "outbox": q["outbox"],
                  "at_raw": q["rec"].get("at"), "byte_offset": q["offset"]}
        if q["at"] is not None and q["at"].utcoffset() == dt.timedelta(0):
            detail["tz_note"] = TZ_NOTES["queue"]
        if not ok:
            outcome = "not-deliverable"
            detail["not_deliverable"] = why
        elif q["history"]:
            outcome = "history-adopted-at-eof"
            detail["not_deliverable"] = (f"line ends at byte {q['end']} <= offset "
                                         f"{ADOPTED[q['outbox']]} adopted at EOF by the "
                                         f"courier's first pass - predates the courier")
        else:
            kinds = [e["kind"] for e in q["events"] if not e.get("duplicate_of")]
            if q.get("duplicates"):
                detail["duplicate_deliveries"] = q["duplicates"]
            if not kinds:
                outcome = "never-attempted"
            elif kinds[-1] == "sent":
                outcome = "sent" if kinds == ["sent"] else "deferred-then-sent"
            elif kinds[-1] == "gave_up":
                outcome = "dead-lettered"
            else:
                outcome = "deferred-no-final-outcome"
            live, live_ref = liveness(q)
            detail["recipient_liveness"] = live
            if live_ref:
                detail["recipient_liveness_ref"] = live_ref
            up, pid = courier_up(intervals, q["ep"], last_log_ep) if q["ep"] else (None, None)
            detail["courier_running_at_queue"] = up
            detail["courier_events"] = [e["ref"] for e in q["events"]]
            if outcome == "never-attempted":
                never_attempted.append(q)
            if live.startswith("not-live"):
                not_live.append((q, live))
        detail["courier_outcome"] = outcome
        q["outcome"] = outcome
        emit("queued", iso_z(q["at"]), basis_of(q["at"]), q["recipient"], q["sender"],
             "post", body=q["body"] if isinstance(q["body"], str) else None,
             detail=detail, ref=ref)

    # ── sent / defer / gave_up ─────────────────────────────────────────
    unmatched = collections.Counter()
    for ev in events:
        if ev["kind"] not in ("sent", "defer", "gave_up"):
            continue
        q = ev.get("q")
        detail = {"log_line": ev["raw"], "link": ev.get("how") if q else None,
                  "queued_ref": rel_ref(q["file"], q["line"]) if q else None}
        if q is None:
            unmatched[ev["kind"]] += 1
            detail["unlinked_reason"] = (
                "no queue line from this sender to this recipient in the snapshot "
                "(test outbox removed, or a duplicate delivery)")
        else:
            detail["queued_at"] = iso_z(q["at"])
            detail["lag_s"] = round(ev["ep"] - q["ep"], 3) if q["ep"] else None
        if ev["kind"] == "sent":
            type_ = "sent"
            detail["kind"] = ev["k"]
            detail["attempts"] = ev["retry"] or 1
            if ev["retry"]:
                detail["retry"] = ev["retry"]
            detail["delivered_to"] = "inbox" if ev["r"] in VIRTUAL else "pane"
            if ev.get("duplicate_of"):
                detail["duplicate_of"] = ev["duplicate_of"]
                detail["duplicate_note"] = (
                    "second 'sent' for the same queue line within 5 s; the pair is not "
                    "separated by the watcher's 'tick' line, so a second tick() caller "
                    "(courier --once, or another watcher) raced this one on the cursor")
        elif ev["kind"] == "defer":
            type_ = "defer"
            detail["reason"] = ev["reason"]
            detail["attempts"] = 1
            detail["kind"] = q["kind"] if q else None
        else:
            type_ = "gave_up"
            detail["reason"] = ev["reason"]
            row = ev.get("dead_letter_row")
            detail["attempts"] = row.get("attempts") if row else None
            if row:
                detail["dead_letter_ref"] = rel_ref(SNAP / "courier" / "dead-letter.jsonl",
                                                    row["_line"])
            detail["kind"] = q["kind"] if q else None
        if q is not None:
            prefix, sha, blen, _env = body_fields(q["body"])
        else:
            prefix = sha = blen = None
        emit(type_, iso_z(ev["t"]), basis_of(ev["t"]), ev["r"], ev["s"], "courier",
             detail=detail, ref=ev["ref"], prefix=prefix, body_sha=sha, body_len=blen)
        per_recipient[ev["r"]][type_] += 1

    # ── dead_letter (dead-letter.jsonl + queue/courier.jsonl notes) ────
    for row in dl_rows:
        msg = row.get("message") or {}
        cand = next((q for q in QUEUE if not q["bad"] and q["sender"] == msg.get("sender")
                     and q["recipient"] == msg.get("recipient")
                     and q["rec"].get("at") == msg.get("at") and q["body"] == msg.get("body")),
                    None)
        emit("dead_letter", iso_z(row["_t"]), basis_of(row["_t"]), msg.get("recipient"),
             msg.get("sender"), "courier", body=msg.get("body"),
             detail={"source": "dead-letter.jsonl", "reason": row.get("reason"),
                     "attempts": row.get("attempts"), "kind": msg.get("kind"),
                     "message_at": msg.get("at"),
                     "queued_ref": rel_ref(cand["file"], cand["line"]) if cand else None,
                     "matched_gave_up_log": row["_used"]},
             ref=rel_ref(SNAP / "courier" / "dead-letter.jsonl", row["_line"]))
        per_recipient[msg.get("recipient")]["dead_letter"] += 1
    note_rx = re.compile(r"^undelivered after (\d+) attempts(, kept in dead-letter)?: "
                         r"([A-Za-z0-9_.-]+) -> ([A-Za-z0-9_.-]+) \(([a-z]+)\) - (.*)$")
    for q in QUEUE:
        if q["bad"] or q["outbox"] != "courier":
            continue
        m = note_rx.match(q["body"] or "")
        if not m:
            continue
        att, kept, s, r, k, reason = m.groups()
        dl = next((row for row in dl_rows if row.get("at") == q["rec"].get("at")
                   and (row.get("message") or {}).get("sender") == s
                   and (row.get("message") or {}).get("recipient") == r), None)
        gave = next((e for e in events if e["kind"] == "gave_up" and e["s"] == s
                     and e["r"] == r and q["ep"] is not None and abs(e["ep"] - q["ep"]) <= 2),
                    None)
        gq = gave.get("q") if gave else None
        emit("dead_letter", iso_z(q["at"]), basis_of(q["at"]), r, s, "courier",
             detail={"source": "queue/courier.jsonl give-up note", "reason": reason,
                     "attempts": int(att), "kind": k,
                     "body_kept": bool(kept),
                     "body_discarded_note": None if kept else
                     "pre-2026-09-22 courier: body thrown away on give-up (courier.py "
                     "dead_letter docstring); only this note survives",
                     "dead_letter_ref": rel_ref(SNAP / "courier" / "dead-letter.jsonl",
                                                dl["_line"]) if dl else None,
                     "queued_ref": rel_ref(gq["file"], gq["line"]) if gq else None},
             ref=rel_ref(q["file"], q["line"]),
             prefix=body_fields(gq["body"])[0] if gq else None,
             body_sha=body_fields(gq["body"])[1] if gq else None,
             body_len=body_fields(gq["body"])[2] if gq else None)
        if not kept:
            per_recipient[r]["dead_letter"] += 1

    # ── kill ───────────────────────────────────────────────────────────
    idle_path = SNAP / "run" / ".idle.log"
    idle_lines = (idle_path.read_text(encoding="utf-8").splitlines())
    idle_mtime = mtime_of(idle_path)
    sweep, kills = 0, []
    for n, text in enumerate(idle_lines, 1):
        m = re.match(r"closing (\S+) after (\d+)m idle \(limit (\d+)m\)", text)
        if not m:
            if text.startswith("closed"):
                sweep += 1
            continue
        name, idle_m, limit_m = m.group(1), int(m.group(2)), int(m.group(3))
        kills.append((n, name, idle_m, limit_m, sweep))
    last_sweep = max((k[4] for k in kills), default=None)
    sweep_members = collections.defaultdict(list)
    for k in kills:
        sweep_members[k[4]].append(k[1])
    # LIFETIMES. A name can be closed more than once (ccc-orchestrator three times).
    # Each name's alive-evidence is split into bursts at every silence longer than the
    # idle limit; the k-th closing of a name is mapped to the k-th burst when the counts
    # agree, else to the most recent bursts (the watchdog only exists late in the
    # period), and the method is recorded. A closing's LOWER bound is its burst's last
    # evidence; its UPPER bound is the first courier "'name' is not running" after that,
    # or the file mtime for the last sweep written.
    occ = collections.defaultdict(list)
    for idx, k in enumerate(kills):
        occ[k[1]].append(idx)
    burst_of = {}
    for name, idxs in occ.items():
        limit_s = kills[idxs[0]][3] * 60
        ev_ = ALIVE.get(name, [])
        bursts = []
        for a in ev_:
            if bursts and a[0] - bursts[-1][-1][0] <= limit_s:
                bursts[-1].append(a)
            else:
                bursts.append([a])
        if len(bursts) == len(idxs):
            method, chosen = "one-to-one", bursts
        elif len(bursts) > len(idxs):
            method, chosen = "most-recent-bursts", bursts[-len(idxs):]
        else:
            method = "fewer-bursts-than-closings"
            chosen = [None] * (len(idxs) - len(bursts)) + bursts
        for idx, b in zip(idxs, chosen):
            burst_of[idx] = (b, method, len(bursts), len(idxs))
    for idx, (n, name, idle_m, limit_m, sw) in enumerate(kills):
        b, method, nb, no = burst_of[idx]
        lower = b[-1] if b else None
        upper = None
        if lower is not None:
            ups = [d for d in DEAD.get(name, []) if 0 <= d[0] - lower[0] <= 86400]
            upper = ups[0] if ups else None
        if sw == last_sweep:
            upper = (epoch(idle_mtime), "idle.log mtime (last sweep written)",
                     sp(idle_path))
        if upper is not None:
            t = dt.datetime.fromtimestamp(upper[0], tz=UTC)
            basis = "file-mtime" if sw == last_sweep else "unknown"
        elif lower is not None:
            t = dt.datetime.fromtimestamp(lower[0], tz=UTC)
            basis = "unknown"
        else:
            t, basis = None, "unknown"
        det = {"source": "run/.idle.log", "cause": "idle-watchdog",
               "idle_minutes": idle_m, "limit_minutes": limit_m, "sweep_index": sw,
               "sweep_members": sweep_members[sw],
               "lifetime_mapping": method, "bursts_for_name": nb, "closings_for_name": no,
               "tz_note": TZ_NOTES["idle.log"] + (
                   "; t is the upper bound" if upper else
                   "; t is the lower bound (last evidence alive)" if lower else ""),
               "t_upper": iso_z(dt.datetime.fromtimestamp(upper[0], tz=UTC)) if upper else None,
               "t_upper_evidence": upper[2] if upper else None,
               "t_lower": iso_z(dt.datetime.fromtimestamp(lower[0], tz=UTC)) if lower else None,
               "t_lower_evidence": lower[2] if lower else None}
        members = sweep_members[sw]
        if len(members) == 6 and all(x.startswith("tm-209-worker") for x in members):
            det["note"] = ("agentmux.sh cmd_idle comment: this six-agent sweep was logged "
                           "by an orphan watchdog of the deleted test home "
                           "/tmp/tmp.ozE3zbYxIr and decapitated the live TM-209 team "
                           "(commit e6b329c)")
        emit("kill", iso_z(t), basis, name, "idle-watchdog", None, detail=det,
             ref=rel_ref(idle_path, n))

    # pool.log (dispatch pool): collect lines reap panes; also dispatch records.
    pool_path = SNAP / "dispatch" / "pool.log"
    pool_kills = []
    pool_lines = []
    for line, _off, raw in read_lines(pool_path):
        text = raw.decode("utf-8", "replace")
        m = re.match(r"^(\S+)  (\w+): (.*)$", text)
        if m:
            pool_lines.append([line, parse_ts(m.group(1)), m.group(2), m.group(3)])
        elif pool_lines:
            pool_lines[-1][3] += " " + text.strip()
    for line, when, verb, rest in pool_lines:
        ref = rel_ref(pool_path, line)
        if verb == "collect":
            m = re.match(r"^(TM-\d+) (.*)$", rest)
            task, what = (m.group(1), m.group(2)) if m else (None, rest)
            who = None
            mm = re.search(r"submitted by (\S+?);", what) or \
                re.search(r"dispatched (?:worker|lead) (\S+) exited", what)
            if mm:
                who = mm.group(1)
            elif task:
                who = task.lower()
            cause = ("reaped-after-submit" if "submitted" in what else
                     "exited-without-completing" if "exited without" in what else
                     "reaped-blocked" if "blocked" in what else "collect")
            pool_kills.append((epoch(when), who))
            emit("kill", iso_z(when), basis_of(when), who, "dispatch-pool", None,
                 detail={"source": "dispatch/pool.log", "cause": cause, "task": task,
                         "line": rest}, ref=ref)
            continue
        det = {"source": "dispatch/pool.log", "event": verb, "line": rest}
        agent = None
        m = re.match(r"^(TM-\d+) -> (\S+) \[(\w+)\](?: \(([^)]*)\))?\s+(.*)$", rest)
        if m:
            det.update(event="dispatch", task=m.group(1), cli=m.group(3),
                       title=m.group(5), note=m.group(4))
            det["pane_busy_brief_queued"] = bool(m.group(4) and "pane busy" in m.group(4))
            agent = m.group(2)
        elif (m := re.match(r"^(TM-\d+) not claimable \((.*)\)$", rest)):
            det.update(event="dispatch-refused", task=m.group(1), reason=m.group(2))
            agent = m.group(1).lower()
        elif (m := re.match(r"^(TM-\d+) already has a worker \((\S+)\)$", rest)):
            det.update(event="dispatch-duplicate", task=m.group(1))
            agent = m.group(2)
        elif rest.startswith("lead lead"):
            det.update(event="lead-definition-fallback")
        elif verb == "pool":
            det.update(event="pool-lifecycle")
        emit("dispatch", iso_z(when), basis_of(when), agent, "dispatch-pool", "dispatch",
             detail=det, ref=ref)

    # cc.db: run teardowns, FORCED completions, watchdog note, parked/reaped comments,
    # roster retire (kill) and hire (dispatch).
    roster_member = {}
    for (ek, name, role, status, member, at) in roster:
        if member:
            roster_member[(ek, name)] = member
    for (i, at, kind, agent, subj, body) in journal:
        when = parse_ts(at)
        ref = f"{dbp}#journal:{i}"
        s = subj or ""
        m = re.match(r"^run (\w+) torn down$", s)
        if m:
            mm = re.search(r"(\d+) agent\(s\) closed", body or "")
            emit("kill", iso_z(when), "utc", None, agent, None,
                 detail={"source": "cc.db journal", "cause": "run-teardown",
                         "run": m.group(1), "agents_closed": int(mm.group(1)) if mm else None,
                         "body": body, "tz_note": TZ_NOTES["cc.db"]}, ref=ref)
            continue
        m = re.match(r"^run (\w+) FORCED: (.*)$", s)
        if m:
            home = re.search(r"see (\S+)/runs/", s)
            emit("kill", iso_z(when), "utc", None, agent, None,
                 detail={"source": "cc.db journal", "cause": "run-forced-completion",
                         "run": m.group(1), "subject": s,
                         "home": home.group(1) if home else None,
                         "test_home": bool(home and home.group(1).startswith("/tmp")),
                         "forced_md_in_snapshot": (SNAP / "runs" / m.group(1) /
                                                   "FORCED.md").exists(),
                         "tz_note": TZ_NOTES["cc.db"]}, ref=ref)
            continue
        if re.search(r"\bwatchdog killed\b", s + " " + (body or "")):
            emit("kill", iso_z(when), "utc", None, agent, None,
                 detail={"source": "cc.db journal", "cause": "watchdog (agent's own report)",
                         "subject": s, "victims_hint": ["ccc-frontend-dev",
                                                        "ccc-frontend-reviewer"]
                         if "8bd2ab" in s else None,
                         "tz_note": TZ_NOTES["cc.db"]}, ref=ref)
    for f in sorted(glob.glob(sp(SNAP / "runs" / "*" / "FORCED.md"))):
        emit("kill", iso_z(mtime_of(f)), "file-mtime", None, None, None,
             detail={"source": "runs/FORCED.md", "cause": "run-forced-completion"},
             ref=f)
    for (i, ek, author, at, text) in comments:
        when = parse_ts(at)
        m = re.search(r"(?:dispatched )?(?:worker|lead) (\S+) (exited without completing|"
                      r"finished and was reaped)", text or "")
        if not m:
            continue
        who, what = m.group(1), m.group(2)
        corroborated = any(abs(pk[0] - epoch(when)) <= 5 and pk[1] == who
                           for pk in pool_kills)
        if corroborated:
            continue   # same event as a dispatch/pool.log collect line (UTC vs CDT)
        emit("kill", iso_z(when), "utc", who, author, None,
             detail={"source": "cc.db board_comments",
                     "cause": "reaped-after-submit" if "reaped" in what
                     else "exited-without-completing", "task": ek, "text": text,
                     "tz_note": TZ_NOTES["cc.db"]},
             ref=f"{dbp}#board_comments:{i}")
    for (i, at, ek, ev_, actor, sess, det) in history:
        when = parse_ts(at)
        try:
            d = json.loads(det) if det else {}
        except ValueError:
            d = {}
        if ev_ == "retire":
            for member_role in d.get("members") or []:
                member = roster_member.get((ek, member_role))
                emit("kill", iso_z(when), "utc", member or member_role, actor, None,
                     detail={"source": "cc.db board_history", "cause": "roster-retire",
                             "task": ek, "role_name": member_role, "member_name": member,
                             "tz_note": TZ_NOTES["cc.db"]},
                     ref=f"{dbp}#board_history:{i}")
        elif ev_ == "hire":
            emit("dispatch", iso_z(when), "utc", d.get("member") or d.get("name"), actor,
                 "dispatch", detail={"source": "cc.db board_history", "event": "hire",
                                     "task": ek, "role_name": d.get("name"),
                                     "member_name": d.get("member"),
                                     "tz_note": TZ_NOTES["cc.db"]},
                 ref=f"{dbp}#board_history:{i}")

    # ── dispatch: runs events, briefs ──────────────────────────────────
    for (f, line, ev) in runs:
        when = parse_ts(ev.get("at"))
        e = ev.get("event")
        agent = ev.get("worker") if e == "assign" else ev.get("by")
        det = {"source": "runs/events.jsonl", "event": e, "run": ev.get("run"),
               "job": ev.get("job"), "by": ev.get("by"), "via": ev.get("via"),
               "pane": ev.get("pane"), "origin": ev.get("origin"),
               "worker": ev.get("worker"), "reviewer": ev.get("reviewer"),
               "task": ev.get("task"), "result": ev.get("result"),
               "attempt": ev.get("attempt")}
        det = {k: v for k, v in det.items() if v is not None}
        if e == "assign" and ev.get("job"):
            jobdir = Path(f).parent / "jobs" / ev["job"].split("/")[-1]
            brief = jobdir / "brief.md"
            if brief.exists():
                data = brief.read_text(encoding="utf-8", errors="replace")
                det["brief_file"] = sp(brief)
                det["brief_sha"] = body_fields(data)[1]
                det["brief_prefix"] = body_fields(data)[0]
            if ev.get("by") and ev.get("by") != "orchestrator":
                det["anomaly"] = ("assign recorded with by != orchestrator (legacy run.py "
                                  "folded worker into 'by')")
        emit("dispatch", iso_z(when), basis_of(when), agent, ev.get("by"), "dispatch",
             body=ev.get("detail") if isinstance(ev.get("detail"), str) and ev.get("detail")
             else None, detail=det, ref=rel_ref(f, line))
    brief_by_path = {}
    for f in sorted(glob.glob(sp(SNAP / "dispatch" / "TM-*.md"))):
        data = Path(f).read_text(encoding="utf-8", errors="replace")
        task = Path(f).stem
        live_path = f"/home/nick/.agentmux/dispatch/{Path(f).name}"
        pointer = [q for q in QUEUE if not q["bad"] and isinstance(q["body"], str)
                   and live_path in q["body"]]
        emit("dispatch", iso_z(mtime_of(f)), "file-mtime", task.lower(), "dispatch-pool",
             "dispatch", body=data,
             detail={"source": "dispatch/*.md", "event": "brief-written", "task": task,
                     "queued_pointer_refs": [rel_ref(q["file"], q["line"]) for q in pointer],
                     "tz_note": "file mtime of the snapshot copy (cp -p assumed); "
                                "brief content, not the text typed into the pane"},
             ref=f)

    # ── identity ───────────────────────────────────────────────────────
    identity_records = []

    def ident(t, basis, agent, detail, ref, body=None):
        identity_records.append(emit("identity", t, basis, agent, None, None, body=body,
                                     detail=detail, ref=ref))

    queue_by_sender_sec = collections.defaultdict(list)
    for q in QUEUE:
        if not q["bad"] and q["ep"] is not None:
            queue_by_sender_sec[q["sender"]].append(q)
    hyphen_panes = {n for n in panes if "-" in n}
    roster_alias = {}
    for (ek, name, role, status, member, at) in roster:
        if member and member != name:
            roster_alias[name] = member
    # roster names ever hired (board_history), with their members
    for (i, at, ek, ev_, actor, sess, det) in history:
        if ev_ == "hire":
            try:
                d = json.loads(det)
            except ValueError:
                continue
            if d.get("name") and d.get("member") and d["name"] != d["member"]:
                roster_alias.setdefault(d["name"], d["member"])

    def alive_near(name, ep, window=1800):
        return bool(near(ALIVE.get(name, []), ep, window))

    SELF_PAT = r"(?:^|\bworker |\bfor )({name})\b(?: orientation| review protocol| stand-down|" \
               r" received| acknowledges| records| sequencing| distinct| coordination)?"

    def cross_pane(actor, when, subj, body, ref, table):
        """H1: row filed under `actor` but written by (self-identifying as) another
        live pane."""
        if actor is None or when is None or actor in NON_AGENT_ACTORS:
            # 'orchestrator' describes workers by name all the time ("worker tm-038
            # finished and was reaped"); H1 is about one PANE's rows landing under
            # another pane's name, which needs a pane on the recorded side.
            return
        ep = epoch(when)
        texts = [("subject", subj or ""), ("body", body or "")]
        hits = []
        for field, text in texts:
            tok = re.match(r"\s*([A-Za-z0-9_.-]+)", text)
            first = tok.group(1) if tok else None
            for b in sorted(hyphen_panes):
                if b == actor or b in roster_alias and not alive_near(b, ep, 600):
                    continue
                pat = None
                if field == "subject" and text.strip() == b:
                    pat = "subject is exactly the other pane's name"
                elif first == b:
                    after = text[tok.end():tok.end() + 24].strip().split(" ")[0] if tok else ""
                    pat = f"first token of {field}" + (f" (then '{after}')" if after else "")
                elif re.search(rf"\b{re.escape(b)} (?:orientation|distinct record|review "
                               rf"protocol|stand-down)\b", text):
                    pat = f"'<name> orientation/distinct record/...' in {field}"
                elif re.search(rf"\bworker {re.escape(b)}\b", text):
                    pat = f"'worker <name>' in {field}"
                if pat:
                    hits.append((b, pat, field))
        if not hits:
            return
        rank = lambda h: (0 if h[1].startswith("subject is exactly") else
                          1 if h[1].startswith("'<name>") else
                          2 if h[1].startswith("first token of subject") else
                          3 if h[1].startswith("first token") else 4, h[0])
        for b, pat, field in sorted(hits, key=rank)[:1]:
            twins = [q for q in queue_by_sender_sec.get(b, [])
                     if abs(q["ep"] - ep) <= 3]
            b_live = alive_near(b, ep, 1800)
            if not (twins or b_live):
                continue
            third_party = bool(re.match(rf"\s*{re.escape(b)} (dispatched|directs|says|reports|"
                                        rf"confirms|corrected|retracts|changed|reiterated|"
                                        rf"claimed|released|blocked)",
                                        (subj if field == "subject" else body) or ""))
            # strong: a queue line from the other pane in the same 3 s, or the subject
            #         is exactly its name (each pane used its own name as subject)
            # medium: '<name> orientation' style self-description, or the other name
            #         opens the subject/body in the first person
            # weak:   'worker <name>' or third-party phrasing ("<name> dispatched ...")
            self_word = re.search(r"\(then '(orientation|received|acknowledges|records|"
                                  r"distinct|sequencing|review|stand-down|coordination)",
                                  pat)
            if twins or pat.startswith("subject is exactly"):
                conf = "strong"
            elif third_party or pat.startswith("'worker"):
                conf = "weak"
            elif pat.startswith("first token of body") and not self_word:
                conf = "weak"      # "<name> reconfirmed ..." reads as a report about B
            else:
                conf = "medium"
            ident(iso_z(when), basis_of(when), actor,
                  {"heuristic": "H1 cross-pane attribution: filed under one live pane, "
                                "text self-identifies as another live pane",
                   "table": table, "recorded_actor": actor, "suspected_actual": b,
                   "evidence": pat, "third_party_phrasing": third_party,
                   "queue_twin_refs": [rel_ref(q["file"], q["line"]) for q in twins],
                   "suspected_actual_alive_within_30m": b_live,
                   "confidence": conf, "subject": (subj or "")[:160]},
                  ref, body=(subj or "") + " " + (body or ""))

    phantom = collections.defaultdict(list)

    def phantom_check(actor, when, ref, table):
        """H2: an actor that never had a pane on this box, filed in the live ledger."""
        if actor is None:
            phantom[("<null>", table, when.astimezone(UTC).date().isoformat()
                     if when else None)].append((when, ref))
            return
        if actor in NON_AGENT_ACTORS or actor in panes:
            return
        phantom[(actor, table, when.astimezone(UTC).date().isoformat()
                 if when else None)].append((when, ref))

    def alias_selfid(actor, when, subj, body, ref, table):
        """H3b: a tm-209 member describing itself by its roster role name."""
        if not actor or when is None:
            return
        text = (subj or "") + " " + (body or "")
        for alias, member in sorted(roster_alias.items()):
            if member != actor:
                continue
            if re.search(rf"(?:^|\W){re.escape(alias)}(?:\W|$)", text) and \
                    not alive_near(alias, epoch(when), 600):
                ident(iso_z(when), basis_of(when), actor,
                      {"heuristic": "H3b pane briefed/self-identifying under its roster "
                                    "role name, which is not a pane",
                       "table": table, "recorded_actor": actor, "role_alias": alias,
                       "alias_is_live_pane_at_time": False, "confidence": "info",
                       "subject": (subj or "")[:160]},
                      ref, body=text)
                return

    # A whole resource name of the form __x__ (a probe), not a path like foo/__init__.py.
    diag_rx = re.compile(r"(?<![/\w.])__[A-Za-z0-9_.-]+__(?![\w./])")

    for (i, at, kind, agent, subj, body) in journal:
        when = parse_ts(at)
        ref = f"{dbp}#journal:{i}"
        cross_pane(agent, when, subj, body, ref, "cc.db journal")
        phantom_check(agent, when, ref, "cc.db journal")
        alias_selfid(agent, when, subj, body, ref, "cc.db journal")
        if diag_rx.search(subj or ""):
            res = diag_rx.search(subj).group(0)
            tomb = [s for s in steals if f".steal.{res}.json." in s]
            conc = [r for r in journal if r[0] != i and diag_rx.search(r[4] or "")
                    and abs(epoch(parse_ts(r[1])) - epoch(when)) <= 5]
            ident(iso_z(when), "utc", agent,
                  {"heuristic": "H4 diagnostic probe written into the live ledger",
                   "table": "cc.db journal", "resource": res, "kind": kind,
                   "recorded_actor": agent,
                   "orchestrator_identity_note": (
                       "'orchestrator' is granted by the ABSENCE of $AGENTMUX_AGENT "
                       "(coordination.orchestrator_identity) - any process outside a pane, "
                       "including a diagnostic script, files as orchestrator")
                   if agent == "orchestrator" else None,
                   "concurrent_probe_rows": [f"{dbp}#journal:{r[0]} {r[3]} {r[4]}"
                                             for r in conc],
                   "steal_tombstones": [{"file": s, "mtime": iso_z(mtime_of(s))}
                                        for s in tomb],
                   "confidence": "info", "tz_note": TZ_NOTES["cc.db"]},
                  ref, body=subj)
    for (i, at, ek, ev_, actor, sess, det) in history:
        phantom_check(actor, parse_ts(at), f"{dbp}#board_history:{i}", "cc.db board_history")
    for (i, ek, author, at, text) in comments:
        when = parse_ts(at)
        ref = f"{dbp}#board_comments:{i}"
        phantom_check(author, when, ref, "cc.db board_comments")
        cross_pane(author, when, None, text, ref, "cc.db board_comments")
    for (line, row) in fallback_journal:
        when = parse_ts(row.get("at"))
        ref = rel_ref(fj, line)
        cross_pane(row.get("agent"), when, row.get("subject"), row.get("body"), ref,
                   "journal.jsonl (fallback)")
        phantom_check(row.get("agent"), when, ref, "journal.jsonl (fallback)")
        alias_selfid(row.get("agent"), when, row.get("subject"), row.get("body"), ref,
                     "journal.jsonl (fallback)")
    for (f, c) in claims:
        when = parse_ts(c.get("at"))
        phantom_check(c.get("holder"), when, f, "claims/*.json")
    for s in steals:
        m = re.search(r"\.steal\.(.+)\.json\.(\d+)$", Path(s).name)
        if m and diag_rx.fullmatch(m.group(1)):
            pass   # reported with the H4 journal row that shares the resource name

    for (actor, table, day), rows in sorted(phantom.items(), key=lambda kv: (
            kv[0][0], kv[0][1], kv[0][2] or "")):
        rows.sort(key=lambda x: (x[0] or dt.datetime.min.replace(tzinfo=UTC), x[1]))
        first_t = rows[0][0]
        ident(iso_z(first_t), basis_of(first_t), None if actor == "<null>" else actor,
              {"heuristic": "H2 actor never had a pane on this box (not in pane logs, "
                            "run sidecars, outboxes or idle targets) - test or "
                            "argument-parsing residue in the live ledger"
                            if actor != "<null>" else
                            "H2 row filed with no actor at all",
               "table": table, "utc_date": day, "rows": len(rows),
               "first": iso_z(rows[0][0]), "last": iso_z(rows[-1][0]),
               "sample_refs": [r[1] for r in rows[:5]], "confidence": "info"},
              rows[0][1])

    # H3a: queued messages addressed to a roster role alias that was not a pane.
    for q in QUEUE:
        if q["bad"] or not isinstance(q["recipient"], str):
            continue
        r = q["recipient"]
        if r in roster_alias and q["ep"] is not None and not alive_near(r, q["ep"], 600):
            ident(iso_z(q["at"]), basis_of(q["at"]), r,
                  {"heuristic": "H3a message addressed to a roster role name while the "
                                "role's pane was named differently",
                   "role_alias": r, "member_pane": roster_alias[r], "sender": q["sender"],
                   "courier_outcome": q.get("outcome"),
                   "queued_ref": rel_ref(q["file"], q["line"]), "confidence": "strong"},
                  rel_ref(q["file"], q["line"]), body=q["body"])

    # ── historical journals: workflow-agent audit runs, no pane traffic ──
    hist = []
    for f in HIST_JOURNALS:
        if not os.path.exists(f):
            continue
        types = collections.Counter()
        for line, _off, raw in read_lines(f):
            try:
                types[json.loads(raw).get("type")] += 1
            except ValueError:
                types["unparseable"] += 1
        hist.append({"file": f, "types": dict(sorted(types.items(), key=str)),
                     "records_emitted": 0,
                     "why": "Claude Code workflow journals (launched/started/result/failed "
                            "of audit subagents): no timestamps, no agentmux queue, courier "
                            "or pane-delivery events - nothing maps to a courier record type"})

    # ── write ──────────────────────────────────────────────────────────
    type_order = {k: i for i, k in enumerate(["queued", "sent", "defer", "gave_up",
                                              "dead_letter", "kill", "identity",
                                              "dispatch"])}
    RECORDS.sort(key=lambda r: (r["t"] or "9999", type_order[r["type"]], r["ref"] or "",
                                json.dumps(r, sort_keys=True)))
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        for r in RECORDS:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")

    # ── summary ────────────────────────────────────────────────────────
    types = collections.Counter(r["type"] for r in RECORDS)
    outcomes = collections.Counter(q.get("outcome") for q in QUEUE if not q["bad"])
    defer_reasons = collections.Counter(
        re.sub(r"'[^']+'", "'X'", e["reason"]) for e in events if e["kind"] == "defer")
    summary = {
        "records": dict(sorted(types.items())),
        "queue_lines": len(QUEUE),
        "queued_outcomes": dict(sorted(outcomes.items(), key=str)),
        "courier_log_events": dict(sorted(collections.Counter(
            e["kind"] for e in events).items())),
        "courier_events_unlinked": dict(sorted(unmatched.items())),
        "defer_reasons": dict(sorted(defer_reasons.items())),
        "per_recipient": {r: dict(sorted(c.items())) for r, c in
                          sorted(per_recipient.items(), key=lambda kv: str(kv[0]))},
        "never_attempted": [{"ref": rel_ref(q["file"], q["line"]), "at": iso_z(q["at"]),
                             "sender": q["sender"], "recipient": q["recipient"],
                             "kind": q["kind"],
                             "prefix": body_fields(q["body"])[0],
                             "courier_running_at_queue": courier_up(intervals, q["ep"],
                                                                    last_log_ep)[0]
                             if q["ep"] else None}
                            for q in never_attempted],
        "recipient_not_live_at_queue": [{"ref": rel_ref(q["file"], q["line"]),
                                         "at": iso_z(q["at"]), "sender": q["sender"],
                                         "recipient": q["recipient"], "why": why,
                                         "outcome": q.get("outcome")}
                                        for q, why in not_live],
        "identity": collections.Counter(r["detail"]["heuristic"].split(" ")[0] + " " +
                                        r["detail"].get("confidence", "")
                                        for r in identity_records),
        "identity_h1_pairs": collections.Counter(
            f"{r['detail']['recorded_actor']} <- {r['detail']['suspected_actual']} "
            f"({r['detail']['confidence']})"
            for r in identity_records if r["detail"]["heuristic"].startswith("H1")),
        "identity_h2_actors": collections.Counter(
            (r["agent"] or "<null>") for r in identity_records
            if r["detail"]["heuristic"].startswith("H2")),
        "courier_intervals": [{"start": iso_z(dt.datetime.fromtimestamp(s, tz=UTC)),
                               "end": iso_z(dt.datetime.fromtimestamp(e, tz=UTC)) if e else None,
                               "pid": p, "how": w} for s, e, p, w in intervals],
        "adopted_at_eof": ADOPTED,
        "tz_notes": TZ_NOTES,
        "historical_journals": hist,
        "courier_out_vs_log": "courier.out is the watcher's stdout; every line in it is "
                              "also in courier.log (0 extra lines), so only courier.log "
                              "is parsed",
    }
    summary["identity"] = dict(sorted(summary["identity"].items()))
    summary["identity_h1_pairs"] = dict(sorted(summary["identity_h1_pairs"].items()))
    summary["identity_h2_actors"] = dict(sorted(summary["identity_h2_actors"].items()))
    with open(SUMMARY, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps({"records": summary["records"], "outcomes": summary["queued_outcomes"],
                      "unlinked": summary["courier_events_unlinked"]}, sort_keys=True))


if __name__ == "__main__":
    main()
