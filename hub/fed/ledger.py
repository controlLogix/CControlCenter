"""hub.db side of federation: outbox, idempotency, audit, quarantine, state (FEDERATION.md 7-8).

Every function takes the Store and runs on the hub's single db thread. Functions that
write the outbox never open a transaction themselves: the caller's state change and the
outbox row commit together (Transactional Client), or neither does.
"""
from __future__ import annotations

import hashlib
import json

from hub.store import now, ulid


def _j(v):
    return json.dumps(v, default=str, separators=(",", ":"))


# -- outbox --------------------------------------------------------------------------
def outbox_add(s, msg_id, subject, payload: dict):
    s.db.execute("INSERT OR IGNORE INTO fed_outbox (msg_id, subject, payload, created) VALUES (?,?,?,?)",
                 (msg_id, subject, _j(payload), now()))


def outbox_pending(s, limit=100):
    return s.q("SELECT seq, msg_id, subject, payload, attempts FROM fed_outbox WHERE sent IS NULL "
               "ORDER BY seq LIMIT ?", (limit,))


def outbox_sent(s, seq):
    with s.tx():
        s.db.execute("UPDATE fed_outbox SET sent=?, last_error=NULL WHERE seq=?", (now(), seq))


def outbox_failed(s, seq, err):
    with s.tx():
        s.db.execute("UPDATE fed_outbox SET attempts=attempts+1, last_error=? WHERE seq=?", (str(err)[:500], seq))


def outbox_withdraw(s):
    """Kill switch --revoke: unsent rows are not sent later either."""
    with s.tx():
        return s.db.execute("UPDATE fed_outbox SET sent='withdrawn' WHERE sent IS NULL").rowcount


def outbox_stats(s):
    r = s.q1("SELECT sum(sent IS NULL) pending, sum(sent IS NOT NULL) sent, max(attempts) worst FROM fed_outbox")
    return {k: (v or 0) for k, v in r.items()}


# -- idempotency -----------------------------------------------------------------------
def seen(s, msg_id) -> bool:
    return s.q1("SELECT 1 FROM fed_seen WHERE msg_id=?", (msg_id,)) is not None


def mark_seen(s, msg_id):
    s.db.execute("INSERT OR IGNORE INTO fed_seen (msg_id, at) VALUES (?,?)", (msg_id, now()))


# -- audit (Wire Tap + Message Store) ------------------------------------------------------
def audit(s, direction, plane, peer, rid, subject, msg_id, payload, decision, detail=None):
    raw = payload if isinstance(payload, (bytes, bytearray)) else _j(payload).encode()
    s.db.execute("INSERT INTO fed_audit (at, dir, plane, peer, rid, subject, msg_id, sha, size, decision, detail) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (now(), direction, plane, peer, rid, subject, msg_id, hashlib.sha256(raw).hexdigest(), len(raw),
                  decision, _j(detail) if detail else None))


def audit_tail(s, limit=50, peer=None, since=0):
    if peer:
        return s.q("SELECT * FROM fed_audit WHERE peer=? AND seq>? ORDER BY seq DESC LIMIT ?", (peer, since, limit))
    return s.q("SELECT * FROM fed_audit WHERE seq>? ORDER BY seq DESC LIMIT ?", (since, limit))


# -- quarantine ------------------------------------------------------------------------
def quarantine_add(s, env, subject, plane, peer, reason):
    qid = "Q-" + ulid()[-10:]
    s.db.execute("INSERT INTO fed_quarantine (id, at, peer, plane, reason, subject, envelope) VALUES (?,?,?,?,?,?,?)",
                 (qid, now(), peer, plane, reason, subject, _j(env)))
    return qid


def quarantine_list(s, state="held"):
    rows = s.q("SELECT * FROM fed_quarantine WHERE (? IS NULL OR state=?) ORDER BY at DESC LIMIT 200", (state, state))
    for r in rows:
        env = json.loads(r.pop("envelope"))
        d = env.get("data") or {}
        r["type"] = env.get("type")
        r["summary"] = (d.get("title") or d.get("body") or "")[:160]
        r["requirements"] = d.get("requirements")
    return rows


def quarantine_get(s, qid):
    r = s.q1("SELECT * FROM fed_quarantine WHERE id=?", (qid,))
    if r:
        r["envelope"] = json.loads(r["envelope"])
    return r


def quarantine_decide(s, qid, state, by):
    with s.tx():
        n = s.db.execute("UPDATE fed_quarantine SET state=?, decided=?, decided_by=? WHERE id=? AND state='held'",
                         (state, now(), by, qid)).rowcount
    return n == 1


# -- state -----------------------------------------------------------------------------
def state_get(s, k, default=None):
    r = s.q1("SELECT v FROM fed_state WHERE k=?", (k,))
    return json.loads(r["v"]) if r else default


def state_set(s, k, v):
    with s.tx():
        s.db.execute("INSERT INTO fed_state (k, v) VALUES (?,?) ON CONFLICT (k) DO UPDATE SET v=excluded.v", (k, _j(v)))
