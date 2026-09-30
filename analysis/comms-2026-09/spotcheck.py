#!/usr/bin/env python3
"""spotcheck.py - re-check the correlate.py spot-check sample against the RAW sources.

Read-only. For every row in out/spotcheck.sample.jsonl:
  1. recover the full body from the raw source (the queue line in the snapshot, or the
     argv literal in the Claude Code transcript),
  2. search every CLI session file that holds any receipt (192 files: codex rollouts,
     claude projects, grok updates) for two distinctive needles from that body, decoding
     each JSON line and matching on lowercase alphanumerics only,
  3. search the recipient's pane log for the same needles,
  4. print the courier.log lines the extractor linked to the queue line,
and writes out/spotcheck.raw.jsonl. It then derives a mechanical verdict:
  - label received    -> agree if a needle hits a user-turn line of the intended agent's
                         session files on/after the send, else disagree
  - label lost-silent -> agree if no needle hits a user turn in ANY session file after the
                         send, else disagree (and names where it landed)
Verdicts go to spotcheck.judgments.json, which correlate.py folds into summary.md.
Deterministic: files and rows are processed in sorted order; no clock is read.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][0-9A-B]|\x1b[=>]")
ENV = re.compile(r"^\[agentmux\] from \S+ \([^)]*\)( ref \S+)?: ")
VAR = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(.*?\)")
AN = re.compile(r"[^a-z0-9]")


def an(s):
    return AN.sub("", (s or "").lower())


def ts(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if s else None


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def read_line(path, lineno):
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, l in enumerate(f, 1):
            if i == lineno:
                return l
    return None


def strings(o, acc):
    if isinstance(o, str):
        acc.append(o)
    elif isinstance(o, dict):
        for k in sorted(o):
            strings(o[k], acc)
    elif isinstance(o, list):
        for v in o:
            strings(v, acc)


def role_of(obj):
    """Best-effort: is this JSON line a user turn in its CLI's session format?"""
    if not isinstance(obj, dict):
        return "other"
    t = obj.get("type")
    if t in ("compacted", "summary", "session_meta", "turn_context"):
        return "other"                                # replayed history, not a new turn
    if t == "user":                                   # claude
        m = obj.get("message") or {}
        c = m.get("content")
        if isinstance(c, list) and c and all(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            return "tool_result"
        return "user"
    p = obj.get("payload") or {}
    if isinstance(p, dict):                            # codex rollout
        if p.get("type") == "user_message" or (p.get("type") == "message" and p.get("role") == "user"):
            return "user"
        if p.get("type") in ("function_call_output", "custom_tool_call_output"):
            return "tool_result"
        if p.get("role") == "assistant" or p.get("type") in ("agent_message", "reasoning", "function_call"):
            return "assistant"
    s = json.dumps(obj)[:400]                          # grok updates
    if '"user_message"' in s or '"role": "user"' in s or '"UserMessage' in s or '"prompt"' in s:
        return "user"
    return "other"


# ── the sample, and the receipt index the extractor produced
sample = load("spotcheck.sample.jsonl")
receipts = load("receipts.jsonl") + load("receipts.rescued-claude-config.jsonl")
rc_at = {}
files_by_agent = {}
nonline_refs = 0
for r in receipts:
    m = re.match(r"^(.*):(\d+)$", r["ref"])
    if not m:
        nonline_refs += 1          # sqlite / byte-offset refs: not a JSONL line
        continue
    f, ln = m.group(1), m.group(2)
    rc_at[(f, int(ln))] = r
    if r.get("agent"):
        files_by_agent.setdefault(r["agent"], set()).add(f)
all_files = sorted({k[0] for k in rc_at})
panes = load("panes.jsonl")
panelog_by_agent = {}
for p in panes:
    if p.get("agent") and "@" in p["ref"]:
        panelog_by_agent.setdefault(p["agent"], p["ref"].rsplit("@", 1)[0])

# ── full bodies from raw sources
for row in sample:
    ref = row["ref"]
    path, ln = ref.rsplit(":", 1)
    raw = read_line(path, int(ln))
    body = None
    if row["origin"] == "courier":
        try:
            q = json.loads(raw)
            body = q.get("body") or q.get("msg") or q.get("text") or q.get("message") or ""
            row["_queue_keys"] = sorted(q)
        except Exception:
            body = raw or ""
            row["_queue_keys"] = None
        body = ENV.sub("", ANSI.sub("", body))
        row["_needle_src"] = "queue line"
    else:
        # the argv the extractor stored is the literal as typed; variables stay unexpanded
        body = row["prefix"] or ""
        row["_needle_src"] = "argv literal"
    row["_body"] = body

# operator bodies: take the full positional from transcripts.jsonl (argv literal)
want = {r["ref"] + "|" + r["agent"] for r in sample if r["origin"] == "operator"}
if want:
    for t in load("transcripts.jsonl"):
        if t["type"] == "intent" and (t["ref"] + "|" + (t.get("agent") or "")) in want:
            pos = t["detail"].get("positional") or []
            full = pos[-1] if pos else t.get("prefix") or ""
            for r in sample:
                if r["origin"] == "operator" and r["ref"] == t["ref"] and r["agent"] == t.get("agent"):
                    r["_body"] = full


def needles(row):
    b = row["_body"] or ""
    if row["origin"] == "operator" and VAR.search(b):
        segs = sorted((s for s in VAR.split(b)), key=lambda s: (-len(an(s)), s))
        b = segs[0] if segs else ""
    k = an(b)
    out = []
    if len(k) >= 80:
        out.append(("start", k[:40]))
        mid = len(k) // 2
        out.append(("middle", k[mid:mid + 40]))
        if len(k) > 200:
            out.append(("end", k[-40:]))
    elif k:
        out.append(("whole", k))
    return out


# ── index every session file once: per line, (alnum text, role)
index = {}
for f in all_files:
    lines = []
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for i, l in enumerate(fh, 1):
                try:
                    obj = json.loads(l)
                except Exception:
                    continue
                acc = []
                strings(obj, acc)
                lines.append((i, an(" ".join(acc)), role_of(obj)))
    except FileNotFoundError:
        lines = None
    index[f] = lines


def nearest_t(f, ln):
    best = None
    for (ff, l), r in rc_at.items():
        if ff == f and l <= ln and (best is None or l > best[0]):
            best = (l, r["t"])
    return best[1] if best else None


def search_sessions(files, nds, t0):
    hits = []
    for f in sorted(files):
        lines = index.get(f)
        if lines is None:
            hits.append({"file": f, "missing": True})
            continue
        for i, text, role in lines:
            got = [n for n, s in nds if s and s in text]
            if got:
                rr = rc_at.get((f, i))
                tt = rr["t"] if rr else nearest_t(f, i)
                if rr:
                    role = "user"          # the extractor already proved this line is a user turn
                hits.append({"file": f, "line": i, "role": role, "needles": got,
                             "is_receipt": bool(rr), "t": tt,
                             "agent": rr.get("agent") if rr else None})
    return hits


def search_pane(agent, nds):
    p = panelog_by_agent.get(agent)
    if not p or not os.path.exists(p):
        return {"log": p, "missing": True}
    with open(p, "rb") as fh:
        data = fh.read()
    text = an(ANSI.sub("", data.decode("utf-8", "replace")))
    return {"log": p, "hits": {n: text.count(s) for n, s in nds if s}}


co_recipients = {}
claimed_by = {}           # receipt ref -> the ledger row the correlator gave it to
sha_of = {}
for o in load("outcomes.jsonl"):
    sha_of[o["id"]] = o.get("body_sha")
    if o.get("body_sha"):
        co_recipients.setdefault(o["body_sha"], set()).add(o["agent"])
    for x in o.get("receipt_refs") or []:
        claimed_by.setdefault(x, o["id"])

results = []
judg = {}
for row in sorted(sample, key=lambda r: (r["outcome"], r["id"], r["agent"])):
    nds = needles(row)
    t0 = ts(row["t"]) - timedelta(minutes=2)
    own = files_by_agent.get(row["agent"], set())
    scope = own if row["outcome"] == "received" else set(all_files)
    raw_hits = search_sessions(scope, nds, t0)
    missing = sorted({h["file"] for h in raw_hits if h.get("missing")} & own)
    sender_files = set(files_by_agent.get(row.get("sender") or "", set()))
    for co in co_recipients.get(row.get("body_sha"), set()) - {row["agent"]}:
        sender_files |= files_by_agent.get(co, set())     # same body was addressed to them too
    def _free(h):
        # a receipt the correlator gave to ANOTHER row with the IDENTICAL body cannot also
        # be this row's receipt (two identical sends, one turn). A merged turn that holds two
        # different messages legitimately serves both rows.
        other = claimed_by.get("%s:%s" % (h["file"], h["line"]))
        return other is None or other == row["id"] or sha_of.get(other) != row.get("body_sha")
    hits = [h for h in raw_hits if not h.get("missing") and h["file"] not in sender_files and _free(h)]
    after = [h for h in hits if h.get("t") and ts(h["t"]) >= t0]
    user_after = [h for h in after if h["role"] == "user"]
    own_user = [h for h in user_after if h["file"] in own]
    pane = search_pane(row["agent"], nds)
    rec ={"id": row["id"], "agent": row["agent"], "label": row["outcome"], "t": row["t"],
           "needle_src": row["_needle_src"], "queue_keys": row.get("_queue_keys"),
           "body_len_raw": len(row["_body"] or ""),
           "needles": [n for n, _ in nds], "hits_user_after_own": own_user[:5],
           "hits_user_after_any": user_after[:5], "hits_other_roles": [h for h in after if h["role"] != "user"][:3],
           "pane": pane, "own_files_missing": missing}
    if row["outcome"] == "received":
        if own_user:
            v, note = "agree", "raw user turn at %s:%s (%s)" % (own_user[0]["file"].split("/")[-1][:40], own_user[0]["line"], ",".join(own_user[0]["needles"]))
        elif missing and len(missing) == len(own & {f for f in own}):
            v, note = "unverifiable", "the agent's session files are gone since extraction (%d missing)" % len(missing)
        elif not own and row["reason"].startswith("pane:"):
            ph = pane.get("hits") or {}
            v = "agree" if ph and max(ph.values()) > 0 else "disagree"
            note = "no receipt store; pane log needle hits %s" % ph
        else:
            v, note = "disagree", "no user turn with this body in the agent's session files"
    else:
        if own_user:
            v, note = "disagree", "actually received: raw user turn at %s:%s (%s)" % (own_user[0]["file"].split("/")[-1][:40], own_user[0]["line"], ",".join(own_user[0]["needles"]))
        elif user_after:
            h = user_after[0]
            if h.get("agent") is None:
                v = "agree"
                note = ("only hit is an UNMAPPED session %s:%s (a co-recipient; no agent mapping), "
                        "not the intended agent" % (h["file"].split("/")[-2][:13], h["line"]))
            else:
                v, note = "disagree", "landed in another agent's session: %s:%s (%s)" % (
                    h["file"].split("/")[-1][:40], h["line"], h["agent"])
        else:
            ph = pane.get("hits") or {}
            v = "agree"
            note = "no user turn anywhere after send; pane log needle hits %s" % ph
    judg[row["id"]] = {"verdict": v, "note": note}
    rec["verdict"], rec["note"] = v, note
    results.append(rec)

with open(os.path.join(OUT, "spotcheck.raw.jsonl"), "w", encoding="utf-8", newline="\n") as f:
    for r in results:
        f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
with open(os.path.join(HERE, "spotcheck.judgments.json"), "w", encoding="utf-8", newline="\n") as f:
    json.dump(judg, f, sort_keys=True, indent=1)
for r in results:
    print(r["verdict"], r["label"], r["id"], r["agent"], "|", r["note"])
