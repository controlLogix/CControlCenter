#!/usr/bin/env python3
"""correlate.py - join the four extractor outputs into one delivery ledger and label
every intended delivery with exactly one outcome (README "Merge").

Read-only. Inputs: out/{courier,panes,receipts,receipts.rescued-claude-config,
transcripts}.jsonl and, if present, spotcheck.judgments.json and
spotcheck.pass1.judgments.json (verdicts from spotcheck.py). For rows with no receipt
match, contained_receipt() also opens the raw queue line and the raw receipt lines in a
bounded time window, to find a message contained in a larger user turn.
Outputs: out/outcomes.jsonl, out/summary.md. Deterministic: every collection is sorted,
no clock is read, and the spot-check sample uses a fixed seed.

Ledger = courier `queued` lines that name a recipient
       + operator `send|ask|unblock` intents from the orchestrator transcripts that are
         not test-home runs, name a recipient seen in some other source, and are
         deduplicated by (tool_use_id, invocation_index) - a resumed Claude Code
         session copies earlier tool calls into a second transcript file.
`post` intents are not added: every real post is already a queue line, and the
transcript `post` hits are mostly instructions quoted inside briefs.
`key` intents are keystrokes, not messages; they are counted, not labeled.
"""
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

OUTCOMES = ["received", "typed-not-submitted", "into-modal", "deferred-then-received",
            "dead-lettered", "lost-silent", "wrong-recipient", "truncated", "duplicated",
            "unknown"]

RECEIPT_BEFORE = timedelta(seconds=120)   # clock skew between sources
RECEIPT_AFTER = timedelta(hours=4)        # courier downtime (43 min) + grok pager (25 min)
PANE_SLACK = timedelta(minutes=15)        # pane times are minute-granular windows
MODAL_SLACK = timedelta(minutes=5)
CODEX_GAP = ("2026-09-28T01:44:00Z", "2026-09-29T19:22:00Z")  # no codex rollouts at all
NONALNUM = re.compile(r"[^a-z0-9]")
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
VAR = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(.*?\)")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ts(s):
    if not s:
        return None
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def pkey(s, n=40):
    return NONALNUM.sub("", (s or "").lower())[:n]


def keys_match(a, b, minlen=12):
    if not a or not b:
        return False
    n = min(len(a), len(b))
    return n >= minlen and a[:n] == b[:n]


# ─────────────────────────────────────────────────────────────── load everything
courier = load("courier.jsonl")
panes = load("panes.jsonl")
# The rescued-claude-config file repeats 78 records already in receipts.jsonl (the
# nfl-lead / nfl-rev sessions). Drop exact repeats, or a single user turn counts twice
# and a duplicated delivery looks like two turns. The key is the whole record, NOT the
# ref alone: grok folds several queued messages into ONE user turn, and the extractor
# emits one receipt per contained message under the same ref.
_rc_seen = set()
receipts = []
for _r in load("receipts.jsonl") + load("receipts.rescued-claude-config.jsonl"):
    _k = json.dumps(_r, sort_keys=True)
    if _k in _rc_seen:
        continue
    _rc_seen.add(_k)
    receipts.append(_r)
transcripts = load("transcripts.jsonl")

known_agents = set()
for r in courier + panes + receipts:
    if r.get("agent"):
        known_agents.add(r["agent"])
    if r.get("sender"):
        known_agents.add(r["sender"])

# CLI per agent: pane banner first, then receipts, then courier dispatch detail
cli_votes = defaultdict(Counter)
for r in panes:
    if r.get("agent") and r["detail"].get("cli"):
        cli_votes[r["agent"]][r["detail"]["cli"]] += 3
for r in receipts:
    if r.get("agent"):
        cli_votes[r["agent"]][r["detail"]["cli"]] += 1
for r in courier:
    if r["type"] == "dispatch" and r.get("agent") and r["detail"].get("cli"):
        cli_votes[r["agent"]][r["detail"]["cli"]] += 1


def cli_of(agent):
    v = cli_votes.get(agent)
    if not v:
        return "unknown"
    return sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


# courier events keyed by the queue line they belong to
events_by_q = defaultdict(list)
for r in courier:
    if r["type"] in ("sent", "defer", "gave_up", "dead_letter"):
        q = r["detail"].get("queued_ref")
        if q:
            events_by_q[q].append(r)
kills_by_agent = defaultdict(list)
for r in courier:
    if r["type"] == "kill" and r.get("agent"):
        kills_by_agent[r["agent"]].append(r)

# receipts indexed by agent
rc_by_agent = defaultdict(list)
for i, r in enumerate(receipts):
    if not r.get("agent"):
        continue
    t = ts(r["t"])
    rc_by_agent[r["agent"]].append({
        "i": i, "t": t, "sha": r.get("body_sha"), "key": pkey(r.get("prefix")),
        "len": r.get("body_len"), "env": r["detail"].get("envelope"),
        "sender": r.get("sender") or r["detail"].get("env_sender"),
        "sess": r["detail"].get("session_id"), "conf": r["detail"].get("map_conf"),
        "ref": r["ref"], "prefix": r.get("prefix"), "used": 0})
for a in rc_by_agent:
    rc_by_agent[a].sort(key=lambda x: (x["t"], x["ref"]))

# session spans per agent, for "was the receipt store watching at time t"
spans = defaultdict(list)
for a, lst in rc_by_agent.items():
    by_sess = defaultdict(list)
    for x in lst:
        by_sess[x["sess"]].append(x["t"])
    for s, tl in sorted(by_sess.items(), key=lambda kv: (min(kv[1]), str(kv[0]))):
        spans[a].append((min(tl), max(tl), s))


def covered(agent, t):
    for lo, hi, s in spans.get(agent, []):
        if lo <= t <= hi:
            return s
    return None


# pane evidence indexed by agent
pane_by_agent = defaultdict(lambda: defaultdict(list))
for i, r in enumerate(panes):
    if not r.get("agent"):
        continue
    d = r["detail"]
    hi = ts(d.get("t_hi")) or ts(r["t"])
    lo = ts(d.get("t_lo"))
    pane_by_agent[r["agent"]][r["type"]].append({
        "i": i, "lo": lo, "hi": hi, "key": d.get("prefix_key"), "ref": r["ref"],
        "sender": r.get("sender"), "modal": d.get("subkind") or d.get("modal"),
        "busy_after": d.get("next_busy_bytes") is not None and not d.get("busy_in_progress"),
        "busy_in_progress": d.get("busy_in_progress"), "reason": d.get("reason"),
        "used": 0})


def pane_window_hit(p, t, slack):
    lo = p["lo"] or (p["hi"] - timedelta(hours=6))
    return lo - slack <= t <= p["hi"] + slack


def find_pane(agent, typ, key, t, sender=None):
    best = None
    for p in pane_by_agent.get(agent, {}).get(typ, []):
        if not keys_match(key, p["key"]):
            continue
        if not pane_window_hit(p, t, PANE_SLACK):
            continue
        if sender and p["sender"] and p["sender"] != sender:
            continue
        mid = p["lo"] + (p["hi"] - p["lo"]) / 2 if p["lo"] else p["hi"]
        score = (p["used"], abs((mid - t).total_seconds()), p["i"])
        if best is None or score < best[0]:
            best = (score, p)
    return best[1] if best else None


def find_modal(agent, t):
    """First modal whose window covers t; `kinds` lists every modal covering t."""
    hit = None
    kinds = []
    for p in pane_by_agent.get(agent, {}).get("modal", []):
        lo = p["lo"] or (p["hi"] - timedelta(minutes=30))
        if lo - MODAL_SLACK <= t <= p["hi"] + MODAL_SLACK:
            hit = hit or p
            if p["modal"] not in kinds:
                kinds.append(p["modal"])
    if hit:
        hit = dict(hit, kinds="+".join(str(k) for k in kinds), windowed=hit["lo"] is None)
    return hit


# ─────────────────────────────────────────────────────────────── build the ledger
ledger = []
skipped = Counter()

for r in courier:
    if r["type"] != "queued":
        continue
    d = r["detail"]
    co = d.get("courier_outcome")
    if not r.get("agent") or co == "not-deliverable":
        skipped["queue line with no recipient (broadcast/log, not-deliverable)"] += 1
        continue
    ledger.append({
        "id": "q:" + r["ref"].split("/")[-1], "origin": "courier", "path": "courier",
        "t": ts(r["t"]), "agent": r["agent"], "sender": r.get("sender"),
        "kind": d.get("kind"), "sha": r.get("body_sha"), "prefix": r.get("prefix"),
        "key": pkey(r.get("prefix")), "len": r.get("body_len"), "courier": co,
        "liveness": d.get("recipient_liveness"), "ref": r["ref"],
        "events": sorted(events_by_q.get(r["ref"], []), key=lambda e: (e["t"], e["ref"])),
        "expansion": False, "rejected": False})

seen_calls = set()
for r in transcripts:
    if r["type"] != "intent":
        continue
    d = r["detail"]
    if d.get("test_home"):
        skipped["intent in a test AGENTMUX_HOME"] += 1
        continue
    if r["path"] == "key":
        skipped["key intent (keystrokes, not a message)"] += 1
        continue
    if r["path"] == "post":
        skipped["post intent (the queue line is the ledger row)"] += 1
        continue
    if r["path"] not in ("send", "ask", "unblock"):
        skipped["other intent verb (dispatch, inbox, ...)"] += 1
        continue
    a = r.get("agent")
    if not a or d.get("recipient_unexpanded") or not NAME_OK.match(a) or a not in known_agents:
        skipped["intent recipient unresolvable (shell variable, prose, or never seen)"] += 1
        continue
    if not r.get("prefix"):
        skipped["intent with empty body"] += 1
        continue
    call = (d.get("tool_use_id"), d.get("invocation_index"))
    if call in seen_calls:
        skipped["intent duplicated across resumed transcripts"] += 1
        continue
    seen_calls.add(call)
    res = d.get("result") or {}
    out = (res.get("output_head") or "") + "\n" + (res.get("stderr_head") or "")
    rejected = (f"'{a}' is showing a prompt" in out or f"'{a}' is not running" in out
                or (res.get("exit_code") not in (0, None)))
    ledger.append({
        "id": "i:" + r["ref"].split("/")[-1] + "#" + a, "origin": "operator", "path": r["path"],
        "t": ts(r["t"]), "agent": a, "sender": "operator", "kind": r["path"],
        "sha": r.get("body_sha"), "prefix": r.get("prefix"),
        "key": pkey(VAR.split(r.get("prefix") or "")[0]) if d.get("body_has_expansion") else pkey(r.get("prefix")),
        "len": r.get("body_len"), "courier": None, "liveness": None, "ref": r["ref"],
        "events": [], "expansion": bool(d.get("body_has_expansion")), "rejected": rejected,
        "argv_body": (d.get("positional") or [None])[-1],
        "literal": max(VAR.split(r.get("prefix") or ""), key=len).strip() if d.get("body_has_expansion") else None})

ledger.sort(key=lambda x: (x["t"], x["id"]))


# ─────────────────────────────────────────────────────────────── receipt matching
def match_receipts(item, want=1):
    """Return up to `want` unused receipts at the intended agent."""
    got = []
    lo, hi = item["t"] - RECEIPT_BEFORE, item["t"] + RECEIPT_AFTER
    for x in rc_by_agent.get(item["agent"], []):
        if x["used"] or not (lo <= x["t"] <= hi):
            continue
        how = None
        if item["sha"] and x["sha"] == item["sha"] and not item["expansion"]:
            how = "sha"
        elif not item["expansion"] and keys_match(item["key"], x["key"], 16):
            how = "prefix"
        elif item["expansion"] and not x["env"] and x["t"] <= item["t"] + timedelta(minutes=15):
            lit = pkey(item.get("literal") or "", 400)
            if (len(lit) >= 12 and lit[:60] in pkey(x["prefix"] or "", 400)) or \
               (item["key"] and keys_match(item["key"], x["key"], 12)):
                how = "literal"
            elif not lit or len(lit) < 12:
                how = "time-only"
        if how:
            got.append((x, how))
            if len(got) >= want:
                break
    return got


# ── second-chance match: the message is CONTAINED in a larger user turn.
# Two real causes, both found by the raw spot check:
#   - the body began with a shell variable, so its literal lies past the 80-char prefix
#   - earlier unsubmitted composer text was submitted together with this message
# Only receipt lines in [t-2m, t+CONTAIN_AFTER] whose body is at least as long as the
# needle's source are opened, each file is read once, and matching is on lowercase
# alphanumerics of every string in the decoded JSON line.
CONTAIN_AFTER = timedelta(minutes=30)
AN = re.compile(r"[^a-z0-9]")
_file_cache = {}
_queue_cache = {}


def _an(s):
    return AN.sub("", (s or "").lower())


def _strings(o, acc):
    if isinstance(o, str):
        acc.append(o)
    elif isinstance(o, dict):
        for k in sorted(o):
            _strings(o[k], acc)
    elif isinstance(o, list):
        for v in o:
            _strings(v, acc)


def _raw_line(path, lineno, cache):
    if path not in cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                cache[path] = f.read().split("\n")
        except OSError:
            cache[path] = None
    lines = cache[path]
    if lines is None or lineno < 1 or lineno > len(lines):
        return None
    return lines[lineno - 1]


def full_body(item):
    """The whole body from the raw source: queue line, or the argv literal."""
    if item["origin"] == "operator":
        return item.get("argv_body") or item["prefix"] or ""
    m = re.match(r"^(.*):(\d+)$", item["ref"])
    raw = _raw_line(m.group(1), int(m.group(2)), _queue_cache) if m else None
    try:
        return json.loads(raw).get("body") or ""
    except Exception:
        return ""


def contained_receipt(item):
    body = full_body(item)
    if item["expansion"]:
        segs = sorted(VAR.split(body), key=lambda s: (-len(_an(s)), s))
        body = segs[0] if segs else ""
    k = _an(body)
    if len(k) < 24:
        return None
    mid = len(k) // 2
    nds = [k[:40], k[mid:mid + 40]]
    lo, hi = item["t"] - RECEIPT_BEFORE, item["t"] + CONTAIN_AFTER
    for x in rc_by_agent.get(item["agent"], []):
        # a merged turn may serve several DIFFERENT messages, never the same body twice
        if item["sha"] in x.get("shas", ()) or not (lo <= x["t"] <= hi):
            continue
        if x["len"] is not None and x["len"] < 0.9 * len(body.strip()):
            continue
        m = re.match(r"^(.*):(\d+)$", x["ref"])
        if not m:
            continue
        raw = _raw_line(m.group(1), int(m.group(2)), _file_cache)
        if raw is None:
            continue
        try:
            acc = []
            _strings(json.loads(raw), acc)
        except Exception:
            continue
        text = _an(" ".join(acc))
        if all(n in text for n in nds):
            # merged: the receipt's own first words are not this message's first words
            merged = not item["expansion"] and not _an(x["prefix"] or "").startswith(k[:20])
            return x, ("contained-merged" if merged else "contained")
    return None


def wrong_recipient(item):
    if not item["sha"] or item["expansion"]:
        return None
    lo, hi = item["t"] - RECEIPT_BEFORE, item["t"] + RECEIPT_AFTER
    for a in sorted(rc_by_agent):
        if a == item["agent"]:
            continue
        # the other agent was itself an intended recipient of this body -> not wrong
        if (a, item["sha"]) in intended_pairs:
            continue
        for x in rc_by_agent[a]:
            if x["used"] or x["conf"] not in ("high", "med"):
                continue
            if lo <= x["t"] <= hi and x["sha"] == item["sha"]:
                return x
    return None


intended_pairs = {(it["agent"], it["sha"]) for it in ledger if it["sha"]}

rows = []
pane_matched = set()
for it in ledger:
    ev = it["events"]
    sends = [e for e in ev if e["type"] == "sent"]
    dup_sends = [e for e in sends if e["detail"].get("link") == "duplicate-of-previous-send"]
    defers = [e for e in ev if e["type"] == "defer"]
    dls = [e for e in ev if e["type"] in ("dead_letter", "gave_up")]
    cli = cli_of(it["agent"])
    evidence = []
    reason = None
    outcome = None

    want = 2 if dup_sends else 1
    rm = match_receipts(it, want)
    if not rm and it["courier"] not in ("dead-lettered", "never-attempted", "history-adopted-at-eof",
                                          "deferred-no-final-outcome") and not dls:
        c = contained_receipt(it)
        if c:
            rm = [c]
    for x, how in rm:
        x["used"] += 1
        x.setdefault("shas", set()).add(it["sha"])
    rrefs = [x["ref"] for x, _ in rm]
    parr = find_pane(it["agent"], "arrived", it["key"], it["t"], it["sender"] if it["origin"] == "courier" else None)
    ppend = find_pane(it["agent"], "pending_input", it["key"], it["t"])
    pmodal = find_modal(it["agent"], it["t"])
    if parr:
        parr["used"] += 1

    co = it["courier"]
    if co == "dead-lettered" or (dls and not rm):
        outcome, reason = "dead-lettered", "courier gave up: " + (
            (dls[0]["detail"].get("reason") if dls else None) or "recipient not running")
        evidence += [e["ref"] for e in dls]
    elif it["rejected"] and not rm:
        outcome, reason = "dead-lettered", "agentmux send refused (prompt showing / not running); sender saw the refusal"
    elif co in ("never-attempted", "history-adopted-at-eof", "deferred-no-final-outcome") and not rm:
        outcome = "lost-silent"
        reason = {"never-attempted": "courier never attempted it (stale courier skipped claim/release kinds)",
                  "history-adopted-at-eof": "courier adopted the outbox at EOF on first start; line skipped",
                  "deferred-no-final-outcome": "deferred forever to a recipient that never existed; no notice"}[co]
    elif dup_sends:
        outcome = "duplicated"
        reason = f"courier sent it {len(sends)} times; {len(rm)} distinct user turn(s) matched"
        evidence += [e["ref"] for e in sends]
    elif rm:
        x, how = rm[0]
        if how == "prefix" and it["len"] and x["len"] and x["len"] < 0.9 * it["len"]:
            outcome, reason = "truncated", f"receipt body {x['len']} < queued body {it['len']}"
        elif defers:
            outcome, reason = "deferred-then-received", f"{len(defers)} defer(s) then delivered"
        else:
            outcome, reason = "received", f"receipt matched by {how}"
        if how == "contained-merged":
            reason += " (earlier unsubmitted composer text was submitted in the same turn)"
        if how == "time-only":
            reason += " (body had an unexpanded shell variable; weakest match)"
    elif ppend and cli != "shell":
        # a shell has no busy marker and executes on Enter, so "arrived, no busy" means
        # nothing there; those rows fall through to the shell blind spot below
        outcome, reason = "typed-not-submitted", "text/placeholder left in the input box: " + str(ppend["reason"])
        evidence.append(ppend["ref"])
    elif pmodal and not (parr and parr["busy_after"]):
        outcome = "into-modal"
        reason = f"pane showed {pmodal['kinds']} at delivery time" + (
            " (modal time is an upper bound; window = 30 min before it)" if pmodal["windowed"] else "")
        evidence.append(pmodal["ref"])
    elif parr and parr["busy_after"] and not covered(it["agent"], it["t"]):
        outcome, reason = "received", "pane: text arrived and a busy marker followed (no receipt store)"
    else:
        wr = wrong_recipient(it)
        sess = covered(it["agent"], it["t"])
        if wr:
            wr["used"] += 1
            outcome = "wrong-recipient"
            reason = f"same body received by {wr['ref'].split('/')[-3] if False else 'another agent'} at map_conf={wr['conf']}"
            evidence.append(wr["ref"])
        elif sess:
            outcome = "lost-silent"
            reason = ("receipt store was recording this agent (session %s) but has no turn for it" % sess)
            if parr:
                reason += "; text did appear in the pane"
        else:
            outcome = "unknown"
            if it["liveness"] == "virtual-inbox":
                reason = "blind: virtual inbox (no pane; read is not logged)"
            elif not rc_by_agent.get(it["agent"]):
                if cli == "claude":
                    reason = "blind: no claude receipts for this agent (claude-config deleted at teardown)"
                elif cli == "shell":
                    reason = "blind: shell pane (no CLI receipt store)"
                else:
                    reason = "blind: no receipt store mapped to this agent"
            elif cli == "codex" and CODEX_GAP[0] <= iso(it["t"]) <= CODEX_GAP[1]:
                reason = "blind: codex receipt gap 09-28 01:44Z..09-29 19:22Z"
            else:
                reason = "blind: outside any mapped receipt session for this agent"
            if parr:
                reason += "; pane shows arrival" + (" + busy" if parr["busy_after"] else " (no busy marker)")
    if parr:
        evidence.append(parr["ref"])
    for p in (parr, ppend, pmodal):
        if p:
            pane_matched.add(p["i"])
    rows.append({
        "id": it["id"], "t": iso(it["t"]), "day": iso(it["t"])[:10], "origin": it["origin"],
        "path": it["path"], "agent": it["agent"], "sender": it["sender"], "cli": cli,
        "kind": it["kind"], "prefix": it["prefix"], "body_sha": it["sha"], "body_len": it["len"],
        "courier_outcome": co, "liveness": it["liveness"], "outcome": outcome,
        "reason": reason, "receipt_refs": rrefs,
        "receipt_match": [how for _, how in rm], "evidence_refs": sorted(set(evidence)),
        "ref": it["ref"]})

rows.sort(key=lambda r: (r["t"], r["id"]))
with open(os.path.join(OUT, "outcomes.jsonl"), "w", encoding="utf-8", newline="\n") as f:
    for r in rows:
        f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")

# ─────────────────────────────────────────────────────────────── spot-check sample
rng = random.Random(20260930)
received = [r for r in rows if r["outcome"] == "received"]
sample = sorted(rng.sample(received, min(20, len(received))), key=lambda r: r["id"])
lost = [r for r in rows if r["outcome"] == "lost-silent"]
with open(os.path.join(OUT, "spotcheck.sample.jsonl"), "w", encoding="utf-8", newline="\n") as f:
    for r in sample + lost:
        f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
jpath = os.path.join(HERE, "spotcheck.judgments.json")
judg = {}
if os.path.exists(jpath):
    with open(jpath, encoding="utf-8") as f:
        judg = json.load(f)


# ─────────────────────────────────────────────────────────────── summary.md
def table(counter, rowkeys, colkeys, title_r, title_c=None):
    out = ["| " + title_r + " | " + " | ".join(colkeys) + " | total |",
           "|---" * (len(colkeys) + 2) + "|"]
    for rk in rowkeys:
        vals = [counter.get((rk, c), 0) for c in colkeys]
        out.append("| " + str(rk) + " | " + " | ".join(str(v) if v else "." for v in vals)
                   + " | " + str(sum(vals)) + " |")
    tot = [sum(counter.get((rk, c), 0) for rk in rowkeys) for c in colkeys]
    out.append("| **total** | " + " | ".join(str(v) for v in tot) + " | " + str(sum(tot)) + " |")
    return out


oc = Counter(r["outcome"] for r in rows)
L = ["# Delivery outcomes (correlate.py)", "",
     "Generated from `out/*.jsonl` only. Deterministic; no clock read.", "",
     f"Ledger rows: **{len(rows)}** "
     f"({sum(1 for r in rows if r['origin']=='courier')} courier queue lines, "
     f"{sum(1 for r in rows if r['origin']=='operator')} operator send/ask intents). "
     f"Date range {rows[0]['t']} .. {rows[-1]['t']} (UTC).", "",
     "## Outcome totals", "", "| outcome | count | share |", "|---|---|---|"]
for o in OUTCOMES:
    L.append(f"| {o} | {oc.get(o,0)} | {100.0*oc.get(o,0)/len(rows):.1f}% |")
L += ["", "## Outcome x CLI", ""]
clis = sorted({r["cli"] for r in rows})
L += table(Counter((r["outcome"], r["cli"]) for r in rows), OUTCOMES, clis, "outcome")
L += ["", "## Outcome x path", ""]
paths = sorted({r["path"] for r in rows})
L += table(Counter((r["outcome"], r["path"]) for r in rows), OUTCOMES, paths, "outcome")
L += ["", "## Outcome x day (UTC)", ""]
days = sorted({r["day"] for r in rows})
L += table(Counter((r["day"], r["outcome"]) for r in rows), days, OUTCOMES, "day")
L += ["", "## Reasons (blind spots are the `unknown` rows)", "", "| outcome | reason | count |", "|---|---|---|"]
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
rs_ = Counter((r["outcome"], re.sub(r"\d+", "N", UUID.sub("S", r["reason"] or ""))) for r in rows)
for (o, why), n in sorted(rs_.items(), key=lambda kv: (OUTCOMES.index(kv[0][0]), -kv[1], kv[0][1])):
    L.append(f"| {o} | {why} | {n} |")
L += ["", "## Receipt match method (rows with a receipt)", "", "| method | count |", "|---|---|"]
for k, n in sorted(Counter(m for r in rows for m in r["receipt_match"][:1]).items()):
    L.append(f"| {k} | {n} |")
L += ["", "## Pane evidence outside the ledger", "",
      "Pane records that no ledger row matched. These are mostly dispatch briefs and spawn "
      "prompts, which are typed by `dispatch`/`spawn` rather than queued, so they are counted "
      "here instead of labeled.", "",
      "| pane record | cli | subkind / reason | total | matched a ledger row | unmatched |",
      "|---|---|---|---|---|---|"]
pc = Counter()
pm = Counter()
for i, p in enumerate(panes):
    if p["type"] not in ("pending_input", "modal", "death"):
        continue
    d = p["detail"]
    k = (p["type"], d.get("cli") or "unknown", d.get("subkind") or d.get("reason") or "-")
    pc[k] += 1
    if i in pane_matched:
        pm[k] += 1
for k in sorted(pc):
    L.append(f"| {k[0]} | {k[1]} | {k[2]} | {pc[k]} | {pm[k]} | {pc[k]-pm[k]} |")
L += ["", "## Excluded from the ledger", "", "| why | count |", "|---|---|"]
for k, n in sorted(skipped.items()):
    L.append(f"| {k} | {n} |")
L += ["", "## Spot check", "",
      f"Sample: {len(sample)} random `received` rows (seed 20260930) and all {len(lost)} "
      "`lost-silent` rows, listed in `out/spotcheck.sample.jsonl`. `spotcheck.py` re-checks "
      "each against the RAW sources: it recovers the full body from the snapshot queue line "
      "or the transcript argv, then searches every one of the CLI session files that hold "
      "receipts (codex rollouts, claude projects and history, grok updates) and the "
      "recipient's pane log for start/middle/end needles. Verdicts are in "
      "`spotcheck.judgments.json`. `unverifiable` = the session file was deleted after "
      "extraction (claude-config removed at team teardown); those rows are left out of the "
      "rate.", ""]


def spot_block(title, smp, jd):
    out = [f"### {title}", ""]
    rec = [r for r in smp if r["outcome"] == "received"]
    los = [r for r in smp if r["outcome"] == "lost-silent"]
    chk = [r for r in smp if r["id"] in jd and jd[r["id"]]["verdict"] != "unverifiable"]
    dis = [r for r in chk if jd[r["id"]]["verdict"] != "agree"]
    unv = [r for r in smp if r["id"] in jd and jd[r["id"]]["verdict"] == "unverifiable"]
    out.append(f"Checked {len(chk)} of {len(smp)} ({len(unv)} unverifiable); disagreements "
               f"**{len(dis)} ({100.0*len(dis)/max(1,len(chk)):.1f}%)**.")
    for grp, name in ((rec, "received"), (los, "lost-silent")):
        c = [r for r in grp if r["id"] in jd and jd[r["id"]]["verdict"] != "unverifiable"]
        dd = [r for r in c if jd[r["id"]]["verdict"] != "agree"]
        out.append(f"- `{name}`: {len(dd)}/{len(c)} disagree")
    out += ["", "| id | agent | label | verdict | raw-source note |", "|---|---|---|---|---|"]
    for r in sorted(smp, key=lambda r: (r["outcome"], r["id"])):
        if r["id"] in jd:
            j = jd[r["id"]]
            out.append(f"| {r['id']} | {r['agent']} | {r['outcome']} | {j['verdict']} | {j.get('note','')} |")
    return out + [""]


p1s = load("spotcheck.pass1.sample.jsonl")
p1j = {}
if os.path.exists(os.path.join(HERE, "spotcheck.pass1.judgments.json")):
    with open(os.path.join(HERE, "spotcheck.pass1.judgments.json"), encoding="utf-8") as f:
        p1j = json.load(f)
if p1s and p1j:
    L += spot_block("Pass 1 (before the containment rule)", p1s, p1j)
    L += ["Pass 1 found two systematic errors, both fixed by `contained_receipt()`: bodies "
          "that begin with a shell variable (the literal lies past the 80-character receipt "
          "prefix), and a message submitted in the same turn as earlier unsubmitted composer "
          "text (tm-082, 09-24). The rows it fixed are now `received` with match "
          "`contained` or `contained-merged`.", ""]
cur_ids = {r["id"] for r in sample + lost}
if judg and cur_ids <= set(judg):
    L += spot_block("Pass 2 (current labels)", sample + lost, judg)
else:
    L.append("Pass 2: judgments not yet regenerated for the current sample; run spotcheck.py.")
with open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(L) + "\n")
print(json.dumps({"rows": len(rows), "outcomes": dict(sorted(oc.items())),
                  "sample": len(sample), "lost_silent": len(lost)}, sort_keys=True))
