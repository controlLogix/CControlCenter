"""hub.db - the one store behind the protocol. See docs/PROTOCOL.md section 8.

Only the hub process opens this file. Every method here runs on the hub's single
writer thread, so there is exactly one writing connection; every write transaction
is BEGIN IMMEDIATE so contention surfaces at BEGIN, never as a mid-transaction BUSY.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time

from . import names

APP_ID = 0x414D5548  # 'AMUH'

TERMINAL_DELIVERY = ("acked", "dead")


def now() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ulid_lock = threading.Lock()
_ulid_last = [0, 0]


def ulid() -> str:
    """Time-ordered, and strictly increasing within this process even inside one ms."""
    with _ulid_lock:
        ms = int(time.time() * 1000)
        if ms <= _ulid_last[0]:
            ms = _ulid_last[0]
            rnd = _ulid_last[1] + 1
        else:
            rnd = int.from_bytes(secrets.token_bytes(10), "big") >> 1
        _ulid_last[0], _ulid_last[1] = ms, rnd
        n = (ms << 80) | (rnd & ((1 << 80) - 1))
        return "".join(_B32[(n >> (5 * i)) & 31] for i in reversed(range(26)))


MIGRATIONS = [
    # 1: the initial schema.
    """
    CREATE TABLE repos (
      repo TEXT PRIMARY KEY CHECK (repo GLOB '[a-z0-9_]*' AND length(repo) BETWEEN 1 AND 32),
      title TEXT, created TEXT NOT NULL
    ) STRICT;
    CREATE TABLE repo_aliases (alias TEXT PRIMARY KEY, repo TEXT NOT NULL REFERENCES repos) STRICT;
    CREATE TABLE repo_paths (repo TEXT NOT NULL REFERENCES repos, path TEXT NOT NULL, kind TEXT NOT NULL,
      PRIMARY KEY (repo, path)) STRICT;
    CREATE TABLE groups (grp TEXT NOT NULL, repo TEXT NOT NULL REFERENCES repos, PRIMARY KEY (grp, repo)) STRICT;

    CREATE TABLE agents (
      session TEXT PRIMARY KEY,
      repo TEXT NOT NULL REFERENCES repos, role TEXT NOT NULL, agent TEXT NOT NULL,
      cli TEXT NOT NULL,
      role_snapshot TEXT NOT NULL CHECK (json_valid(role_snapshot)),
      transport TEXT NOT NULL, handle TEXT, pane_pid INTEGER,
      token_sha TEXT,
      state TEXT NOT NULL CHECK (state IN ('starting','ready','busy','blocked','dead')),
      state_note TEXT,
      last_seen TEXT, last_output TEXT, last_bell TEXT,
      created TEXT NOT NULL,
      UNIQUE (repo, role, agent)
    ) STRICT;
    CREATE TABLE legacy_names (legacy TEXT PRIMARY KEY, session TEXT NOT NULL) STRICT;

    CREATE TABLE teams (repo TEXT NOT NULL REFERENCES repos, team TEXT NOT NULL,
      lead_role TEXT NOT NULL DEFAULT 'lead', created TEXT NOT NULL, PRIMARY KEY (repo, team)) STRICT;
    CREATE TABLE team_members (repo TEXT NOT NULL, team TEXT NOT NULL, session TEXT NOT NULL REFERENCES agents,
      PRIMARY KEY (repo, team, session)) STRICT;

    CREATE TABLE message_kinds (kind TEXT PRIMARY KEY, ack_timeout_s INTEGER NOT NULL DEFAULT 300,
      max_attempts INTEGER NOT NULL DEFAULT 12) STRICT;
    INSERT INTO message_kinds (kind) VALUES ('request'),('reply'),('note'),('handoff'),('result'),('control'),
      ('claim'),('release'),('decompose'),('work'),('review');

    CREATE TABLE messages (
      id TEXT PRIMARY KEY, sender TEXT NOT NULL, target TEXT NOT NULL,
      kind TEXT NOT NULL REFERENCES message_kinds,
      ref TEXT, work_id TEXT, body TEXT, body_ref TEXT, body_sha TEXT NOT NULL,
      idem_key TEXT, created TEXT NOT NULL, expires TEXT,
      meta TEXT CHECK (meta IS NULL OR json_valid(meta)),
      UNIQUE (sender, idem_key)
    ) STRICT;
    CREATE VIRTUAL TABLE messages_fts USING fts5(body, content='messages', content_rowid='rowid');
    CREATE TRIGGER messages_fts_ai AFTER INSERT ON messages BEGIN
      INSERT INTO messages_fts(rowid, body) VALUES (new.rowid, new.body);
    END;
    CREATE TRIGGER messages_fts_ad AFTER DELETE ON messages BEGIN
      INSERT INTO messages_fts(messages_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
    END;

    CREATE TABLE deliveries (
      message_id TEXT NOT NULL REFERENCES messages, recipient TEXT NOT NULL,
      state TEXT NOT NULL CHECK (state IN ('queued','offered','typed','submitted','received','acked','dead')),
      attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, last_error TEXT,
      evidence TEXT CHECK (evidence IS NULL OR json_valid(evidence)),
      updated TEXT NOT NULL,
      PRIMARY KEY (message_id, recipient)
    ) STRICT;
    CREATE INDEX deliveries_live ON deliveries (recipient, message_id) WHERE state NOT IN ('acked','dead');

    CREATE TABLE work_items (
      id TEXT PRIMARY KEY, parent_id TEXT REFERENCES work_items,
      task_key TEXT, repo TEXT NOT NULL REFERENCES repos,
      target TEXT NOT NULL,
      target_kind TEXT GENERATED ALWAYS AS (substr(target, 1, instr(target, ':') - 1)) VIRTUAL,
      title TEXT NOT NULL, body TEXT, created_by TEXT NOT NULL,
      requirements TEXT CHECK (requirements IS NULL OR json_valid(requirements)),
      priority INTEGER NOT NULL DEFAULT 100,
      state TEXT NOT NULL CHECK (state IN ('ready','claimed','waiting_children','blocked','done','failed','cancelled')),
      claimed_by TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
      result TEXT, blocked_reason TEXT, created TEXT NOT NULL, updated TEXT NOT NULL
    ) STRICT;
    CREATE INDEX work_ready ON work_items (target, priority, created) WHERE state = 'ready';
    CREATE INDEX work_leased ON work_items (lease_until) WHERE state = 'claimed';
    CREATE INDEX work_kind ON work_items (target_kind, state);

    CREATE TABLE claims (repo TEXT NOT NULL, path TEXT NOT NULL, holder TEXT NOT NULL, work_id TEXT,
      lease_until TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY (repo, path)) STRICT;

    CREATE TABLE events (seq INTEGER PRIMARY KEY, at TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
      event TEXT NOT NULL, actor TEXT, detail TEXT CHECK (detail IS NULL OR json_valid(detail))) STRICT;
    CREATE INDEX events_entity ON events (entity, entity_id, seq);

    CREATE TRIGGER deliveries_audit AFTER UPDATE OF state ON deliveries WHEN old.state <> new.state BEGIN
      INSERT INTO events (at, entity, entity_id, event, detail)
      VALUES (new.updated, 'delivery', new.message_id || '>' || new.recipient, new.state,
              json_object('from', old.state, 'attempts', new.attempts, 'error', new.last_error));
    END;
    CREATE TRIGGER deliveries_audit_ins AFTER INSERT ON deliveries BEGIN
      INSERT INTO events (at, entity, entity_id, event) VALUES (new.updated, 'delivery', new.message_id || '>' || new.recipient, new.state);
    END;
    CREATE TRIGGER work_audit AFTER UPDATE OF state ON work_items WHEN old.state <> new.state BEGIN
      INSERT INTO events (at, entity, entity_id, event, actor, detail)
      VALUES (new.updated, 'work', new.id, new.state, new.claimed_by,
              json_object('from', old.state, 'attempts', new.attempts));
    END;
    CREATE TRIGGER work_audit_ins AFTER INSERT ON work_items BEGIN
      INSERT INTO events (at, entity, entity_id, event, actor, detail)
      VALUES (new.created, 'work', new.id, new.state, new.created_by, json_object('target', new.target));
    END;
    CREATE TRIGGER agents_audit AFTER UPDATE OF state ON agents WHEN old.state <> new.state BEGIN
      INSERT INTO events (at, entity, entity_id, event, detail)
      VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'), 'agent', new.session, new.state, json_object('from', old.state, 'note', new.state_note));
    END;

    CREATE TABLE nats_outbox (seq INTEGER PRIMARY KEY, subject TEXT NOT NULL, payload TEXT NOT NULL,
      created TEXT NOT NULL, sent TEXT) STRICT;
    """,
]


class HubError(Exception):
    """A refusal the caller should see verbatim."""


class Store:
    def __init__(self, path: str):
        self.path = path
        real = os.path.realpath(path)
        if real.startswith("/mnt/") or _is_9p(os.path.dirname(real)):
            raise HubError(f"hub.db must be on the Linux filesystem, not {real} (WAL needs shared memory; R-HOME-1)")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        for p in ("journal_mode = WAL", "synchronous = NORMAL", "foreign_keys = ON", "busy_timeout = 5000",
                  "wal_autocheckpoint = 1000", "temp_store = MEMORY"):
            self.db.execute(f"PRAGMA {p}")
        self.db.create_function("hub_meets", 2, _meets, deterministic=True)
        self._migrate()

    # -- plumbing ---------------------------------------------------------------------
    def _migrate(self):
        aid = self.db.execute("PRAGMA application_id").fetchone()[0]
        ver = self.db.execute("PRAGMA user_version").fetchone()[0]
        if aid not in (0, APP_ID):
            raise HubError(f"{self.path} is not a hub database (application_id {aid:#x})")
        for i, sql in enumerate(MIGRATIONS[ver:], start=ver + 1):
            self.db.execute("BEGIN IMMEDIATE")
            try:
                # Statement by statement, not executescript(): that would COMMIT
                # mid-migration and lose the all-or-nothing guarantee.
                for stmt in _split_sql(sql):
                    self.db.execute(stmt)
                self.db.execute(f"PRAGMA application_id = {APP_ID}")
                self.db.execute(f"PRAGMA user_version = {i}")
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def tx(self):
        return _Tx(self.db)

    def q(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def q1(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def event(self, entity, entity_id, event, actor=None, detail=None):
        self.db.execute("INSERT INTO events (at, entity, entity_id, event, actor, detail) VALUES (?,?,?,?,?,?)",
                        (now(), entity, entity_id, event, actor, json.dumps(detail) if detail is not None else None))

    def checkpoint(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("PRAGMA optimize")

    def backup(self, dest: str):
        d = sqlite3.connect(dest)
        with d:
            self.db.backup(d)
        d.close()

    # -- registry ---------------------------------------------------------------------
    def repo_add(self, repo, title=None, paths=(), aliases=(), groups=()):
        names.check_part(repo, "repo")
        with self.tx():
            self.db.execute("INSERT INTO repos (repo, title, created) VALUES (?,?,?) "
                            "ON CONFLICT(repo) DO UPDATE SET title = coalesce(excluded.title, title)",
                            (repo, title, now()))
            for p in paths:
                self.db.execute("INSERT OR IGNORE INTO repo_paths VALUES (?,?,?)", (repo, p, "checkout"))
            for a in aliases:
                self.db.execute("INSERT INTO repo_aliases VALUES (?,?) ON CONFLICT(alias) DO UPDATE SET repo=excluded.repo",
                                (a, repo))
            for g in groups:
                names.check_part(g, "group")
                self.db.execute("INSERT OR IGNORE INTO groups VALUES (?,?)", (g, repo))
        return self.q1("SELECT * FROM repos WHERE repo=?", (repo,))

    def repo_for_path(self, path):
        rows = self.q("SELECT repo, path FROM repo_paths")
        best = None
        for r in rows:
            p = r["path"].rstrip("/")
            if path == p or path.startswith(p + "/"):
                if best is None or len(p) > len(best[1]):
                    best = (r["repo"], p)
        return best[0] if best else None

    def register(self, repo, role, agent, cli, role_snapshot, transport="tmux", handle=None, pane_pid=None,
                 legacy=None, token_sha=None):
        session = names.session_name(repo, role, agent)
        if not self.q1("SELECT 1 FROM repos WHERE repo=?", (repo,)):
            raise HubError(f"unknown repo {repo!r}: register it first (agentmux hub repo add {repo} <path>)")
        with self.tx():
            cur = self.q1("SELECT state FROM agents WHERE session=?", (session,))
            if cur and cur["state"] != "dead":
                raise HubError(f"session {session} is already registered and {cur['state']} (R-NAME-2)")
            if cur:
                # A dead name may be reused only after its leases went back to the queue.
                self._return_leases(session, "reregistered")
                # Mail for the dead incarnation is not the new one's to read: it would
                # act on a request made to an agent that no longer exists (R-NAME-2).
                self.db.execute("UPDATE deliveries SET state='dead', last_error='recipient re-registered', "
                                "updated=? WHERE recipient=? AND state NOT IN ('acked','dead')", (now(), session))
                self.db.execute("DELETE FROM team_members WHERE session=?", (session,))
                self.db.execute("DELETE FROM agents WHERE session=?", (session,))
            self.db.execute(
                "INSERT INTO agents (session, repo, role, agent, cli, role_snapshot, transport, handle, pane_pid, "
                "token_sha, state, created, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,'starting',?,?)",
                (session, repo, role, agent, cli, json.dumps(role_snapshot), transport, handle, pane_pid,
                 token_sha, now(), now()))
            if legacy:
                self.db.execute("INSERT OR REPLACE INTO legacy_names VALUES (?,?)", (legacy, session))
            self.event("agent", session, "registered", detail={"cli": cli, "handle": handle})
        return session

    def set_handle(self, session, handle, pane_pid):
        with self.tx():
            self.db.execute("UPDATE agents SET handle=?, pane_pid=?, last_seen=? WHERE session=?",
                            (handle, pane_pid, now(), session))

    def set_state(self, session, state, note=None):
        with self.tx():
            self.db.execute("UPDATE agents SET state=?, state_note=?, last_seen=? WHERE session=?",
                            (state, note, now(), session))
            if state == "dead":
                self._return_leases(session, "agent dead")

    def touch_output(self, session):
        self.db.execute("UPDATE agents SET last_output=?, last_seen=? WHERE session=?", (now(), now(), session))

    def agents(self, live_only=False):
        sql = "SELECT * FROM agents" + (" WHERE state <> 'dead'" if live_only else "") + " ORDER BY session"
        return self.q(sql)

    def agent(self, session):
        a = self.q1("SELECT * FROM agents WHERE session=?", (session,))
        if not a:
            leg = self.q1("SELECT session FROM legacy_names WHERE legacy=?", (session,))
            if leg:
                a = self.q1("SELECT * FROM agents WHERE session=?", (leg["session"],))
        return a

    def team_add(self, repo, team, members=(), lead_role="lead"):
        names.check_part(team, "team")
        with self.tx():
            self.db.execute("INSERT INTO teams (repo, team, lead_role, created) VALUES (?,?,?,?) "
                            "ON CONFLICT DO UPDATE SET lead_role=excluded.lead_role", (repo, team, lead_role, now()))
            for s in members:
                if not self.q1("SELECT 1 FROM agents WHERE session=?", (s,)):
                    raise HubError(f"unknown session {s}")
                self.db.execute("INSERT OR IGNORE INTO team_members VALUES (?,?,?)", (repo, team, s))
        return self.team(repo, team)

    def team(self, repo, team):
        t = self.q1("SELECT * FROM teams WHERE repo=? AND team=?", (repo, team))
        if t:
            t["members"] = [r["session"] for r in self.q(
                "SELECT session FROM team_members WHERE repo=? AND team=? ORDER BY session", (repo, team))]
        return t

    # -- addressing -------------------------------------------------------------------
    def eligible_targets(self, session):
        """Every address this agent satisfies, for claims and role/team messages."""
        a = self.agent(session)
        if not a:
            return []
        repo, role = a["repo"], a["role"]
        t = [f"agent:{session}", f"role:{repo}/{role}", f"role:*/{role}"]
        t += [f"role:group:{g['grp']}/{role}" for g in self.q("SELECT grp FROM groups WHERE repo=?", (repo,))]
        for m in self.q("SELECT tm.repo, tm.team, t.lead_role FROM team_members tm JOIN teams t "
                        "USING (repo, team) WHERE tm.session=?", (session,)):
            t.append(f"role:team:{m['repo']}/{m['team']}/{role}")
            if role == m["lead_role"]:
                t.append(f"team:{m['repo']}/{m['team']}")
        return t

    def recipients(self, target: str):
        """Live sessions a MESSAGE to this address goes to. Direct -> one; role -> every
        live holder in scope (a broadcast; use work items for first-claim); team -> leads."""
        addr = names.parse_address(target)
        if addr.kind == "virtual":
            return [f"virtual:{addr.name}"]
        if addr.kind == "agent":
            a = self.agent(addr.name)
            if not a:
                raise HubError(f"no such agent {addr.name}")
            return [a["session"]]
        out = []
        for a in self.agents(live_only=True):
            if str(addr) in self.eligible_targets(a["session"]):
                out.append(a["session"])
        if not out:
            raise HubError(f"no live agent satisfies {target}")
        return out

    # -- messages ---------------------------------------------------------------------
    def post(self, sender, target, kind, body, ref=None, work_id=None, idem_key=None, body_ref=None,
             body_sha=None, meta=None):
        import hashlib
        if not self.q1("SELECT 1 FROM message_kinds WHERE kind=?", (kind,)):
            kinds = [r["kind"] for r in self.q("SELECT kind FROM message_kinds ORDER BY kind")]
            raise HubError(f"unknown kind {kind!r}; known: {', '.join(kinds)}")
        if idem_key:
            prev = self.q1("SELECT id FROM messages WHERE sender=? AND idem_key=?", (sender, idem_key))
            if prev:
                return {"id": prev["id"], "duplicate": True, "recipients": self._recips_of(prev["id"])}
        recips = self.recipients(target)
        mid = ulid()
        sha = body_sha or hashlib.sha256((body or "").encode()).hexdigest()
        with self.tx():
            self.db.execute(
                "INSERT INTO messages (id, sender, target, kind, ref, work_id, body, body_ref, body_sha, idem_key, "
                "created, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, sender, target, kind, ref, work_id, body, body_ref, sha, idem_key, now(),
                 json.dumps(meta) if meta else None))
            for r in recips:
                self.db.execute("INSERT INTO deliveries (message_id, recipient, state, updated) VALUES (?,?,?,?)",
                                (mid, r, "queued", now()))
            self._outbox(target, mid)
        return {"id": mid, "duplicate": False, "recipients": recips}

    def _recips_of(self, mid):
        return [r["recipient"] for r in self.q("SELECT recipient FROM deliveries WHERE message_id=?", (mid,))]

    def _outbox(self, target, mid):
        # Transactional outbox for the future NATS bridge. Written in the same
        # transaction as the state change, so a bridge can never miss or invent one.
        try:
            subj = names.nats_subject(names.parse_address(target), "local")
        except Exception:
            subj = "am.local.unroutable"
        self.db.execute("INSERT INTO nats_outbox (subject, payload, created) VALUES (?,?,?)",
                        (subj, json.dumps({"message_id": mid}), now()))

    def inbox(self, session, limit=20, mark=True):
        rows = self.q(
            "SELECT m.id, m.sender, m.target, m.kind, m.ref, m.work_id, m.body, m.body_ref, m.body_sha, m.created, "
            "d.state, d.attempts FROM deliveries d JOIN messages m ON m.id = d.message_id "
            "WHERE d.recipient=? AND d.state NOT IN ('acked','dead') ORDER BY m.id LIMIT ?", (session, limit))
        if mark and rows:
            with self.tx():
                for r in rows:
                    self.db.execute("UPDATE deliveries SET state='received', updated=? WHERE message_id=? AND "
                                    "recipient=? AND state NOT IN ('acked','dead','received')", (now(), r["id"], session))
        return rows

    def ack(self, session, ids):
        done = []
        with self.tx():
            for i in ids:
                c = self.db.execute("UPDATE deliveries SET state='acked', updated=? WHERE message_id=? AND recipient=? "
                                    "AND state <> 'acked'", (now(), i, session)).rowcount
                if c or self.q1("SELECT 1 FROM deliveries WHERE message_id=? AND recipient=? AND state='acked'", (i, session)):
                    done.append(i)
        return done

    def delivery_report(self, mid, recipient, state, evidence=None, error=None):
        with self.tx():
            self.db.execute(
                "UPDATE deliveries SET state=?, evidence=?, last_error=?, updated=? WHERE message_id=? AND "
                "recipient=? AND state NOT IN ('acked','dead','received')",
                (state, json.dumps(evidence) if evidence else None, error, now(), mid, recipient))

    def pending_for(self, session):
        return self.q("SELECT d.*, m.kind, m.sender FROM deliveries d JOIN messages m ON m.id=d.message_id "
                      "WHERE d.recipient=? AND d.state NOT IN ('acked','dead') ORDER BY d.message_id", (session,))

    def bump_attempt(self, session, error, max_attempts=12):
        """One doorbell attempt counted against every pending delivery for session."""
        with self.tx():
            self.db.execute("UPDATE deliveries SET attempts=attempts+1, last_error=?, updated=? WHERE recipient=? "
                            "AND state NOT IN ('acked','dead')", (error, now(), session))
            dead = self.db.execute(
                "UPDATE deliveries SET state='dead', updated=? WHERE recipient=? AND state NOT IN ('acked','dead') "
                "AND attempts >= ? RETURNING message_id", (now(), session, max_attempts)).fetchall()
        return [d[0] for d in dead]

    # -- work -------------------------------------------------------------------------
    def work_create(self, created_by, repo, target, title, body=None, task_key=None, requirements=None,
                    priority=100, parent_id=None, max_attempts=3):
        names.parse_address(target)
        if not self.q1("SELECT 1 FROM repos WHERE repo=?", (repo,)):
            raise HubError(f"unknown repo {repo!r}")
        if target.startswith("agent:"):
            a = self.agent(target[6:])
            if not a or a["state"] == "dead":
                raise HubError(f"{target} is not a live agent; route to a role instead (R-LIVE-2)")
        wid = "W-" + ulid()[-10:]
        with self.tx():
            self.db.execute(
                "INSERT INTO work_items (id, parent_id, task_key, repo, target, title, body, created_by, requirements, "
                "priority, state, max_attempts, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,'ready',?,?,?)",
                (wid, parent_id, task_key, repo, target, title, body, created_by,
                 json.dumps(requirements) if requirements else None, priority, max_attempts, now(), now()))
            if parent_id:
                self.db.execute("UPDATE work_items SET state='waiting_children', updated=? WHERE id=? AND "
                                "state='claimed'", (now(), parent_id))
            self._outbox(target, wid)
        return self.q1("SELECT * FROM work_items WHERE id=?", (wid,))

    def claimable(self, session):
        a = self.agent(session)
        if not a or a["state"] == "dead":
            return []
        tg = json.dumps(self.eligible_targets(session))
        caps = json.dumps(_caps(a))
        return self.q("SELECT id, target, title, priority FROM work_items WHERE state='ready' AND target IN "
                      "(SELECT value FROM json_each(?)) AND (requirements IS NULL OR hub_meets(requirements, ?)=1) "
                      "ORDER BY priority, created", (tg, caps))

    def claim(self, session, lease_s=None, work_id=None):
        """First claim wins. One statement, under BEGIN IMMEDIATE."""
        a = self.agent(session)
        if not a or a["state"] == "dead":
            raise HubError(f"{session} is not a live registered agent")
        snap = json.loads(a["role_snapshot"])
        lease_s = int(snap.get("lease_s", 900) if lease_s is None else lease_s)
        active = self.q1("SELECT count(*) n FROM work_items WHERE claimed_by=? AND state='claimed'", (session,))["n"]
        if active >= int(snap.get("max_active", 1)) and not work_id:
            return {"claimed": None, "reason": f"at max_active ({active}); finish or release current work first",
                    "active": self.q("SELECT id, title FROM work_items WHERE claimed_by=? AND state='claimed'", (session,))}
        tg = json.dumps(self.eligible_targets(session))
        with self.tx():
            row = self.db.execute(
                "UPDATE work_items SET state='claimed', claimed_by=?, attempts=attempts+1, "
                "lease_until=strftime('%Y-%m-%dT%H:%M:%fZ','now','+' || ? || ' seconds'), updated=? "
                "WHERE id = (SELECT id FROM work_items WHERE state='ready' AND target IN (SELECT value FROM json_each(?)) "
                "AND (requirements IS NULL OR hub_meets(requirements, ?)=1) AND (? IS NULL OR id = ?) "
                "ORDER BY priority, created LIMIT 1) RETURNING *",
                (session, lease_s, now(), tg, json.dumps(_caps(a)), work_id, work_id)).fetchone()
        return {"claimed": dict(row) if row else None}

    def heartbeat(self, session, lease_s=None):
        a = self.agent(session)
        snap = json.loads(a["role_snapshot"]) if a else {}
        lease_s = int(snap.get("lease_s", 900) if lease_s is None else lease_s)
        with self.tx():
            n = self.db.execute("UPDATE work_items SET lease_until=strftime('%Y-%m-%dT%H:%M:%fZ','now','+' || ? || "
                                "' seconds'), updated=? WHERE claimed_by=? AND state='claimed'",
                                (lease_s, now(), session)).rowcount
            self.db.execute("UPDATE agents SET last_seen=? WHERE session=?", (now(), session))
        return n

    def release(self, session, work_id, outcome, result=None):
        if outcome not in ("done", "failed", "returned", "blocked"):
            raise HubError("outcome must be done|failed|returned|blocked")
        w = self.q1("SELECT * FROM work_items WHERE id=?", (work_id,))
        if not w:
            raise HubError(f"no such work item {work_id}")
        if w["claimed_by"] != session:
            raise HubError(f"{work_id} is held by {w['claimed_by']}, not {session}")
        if w["state"] not in ("claimed", "waiting_children"):
            raise HubError(f"{work_id} is {w['state']}, not claimed")
        if outcome == "done":
            open_kids = self.q1("SELECT count(*) n FROM work_items WHERE parent_id=? AND state NOT IN "
                                "('done','failed','cancelled')", (work_id,))["n"]
            if open_kids:
                raise HubError(f"{work_id} still has {open_kids} open child item(s)")
        new = {"done": "done", "failed": "failed", "returned": "ready", "blocked": "blocked"}[outcome]
        with self.tx():
            self.db.execute("UPDATE work_items SET state=?, result=coalesce(?, result), updated=?, lease_until=NULL, "
                            "claimed_by=CASE WHEN ?='ready' THEN NULL ELSE claimed_by END, "
                            "blocked_reason=CASE WHEN ?='blocked' THEN ? ELSE blocked_reason END WHERE id=?",
                            (new, result, now(), new, new, result, work_id))
            self.db.execute("DELETE FROM claims WHERE work_id=?", (work_id,))
        return self.q1("SELECT * FROM work_items WHERE id=?", (work_id,))

    def cancel(self, work_id, reason):
        """Operator-only: end an item (and its open children) that nobody should do."""
        with self.tx():
            rows = self.db.execute(
                "UPDATE work_items SET state='cancelled', result=?, lease_until=NULL, updated=? WHERE (id=? OR parent_id=?) "
                "AND state NOT IN ('done','failed','cancelled') RETURNING id", (reason, now(), work_id, work_id)).fetchall()
            self.db.execute("DELETE FROM claims WHERE work_id=?", (work_id,))
        return [r[0] for r in rows]

    def work(self, work_id=None, state=None, repo=None):
        if work_id:
            w = self.q1("SELECT * FROM work_items WHERE id=?", (work_id,))
            if w:
                w["children"] = self.q("SELECT id, target, title, state, claimed_by FROM work_items WHERE parent_id=? "
                                       "ORDER BY created", (work_id,))
            return w
        sql, args = "SELECT * FROM work_items WHERE 1=1", []
        if state:
            sql += " AND state=?"; args.append(state)
        if repo:
            sql += " AND repo=?"; args.append(repo)
        return self.q(sql + " ORDER BY created", args)

    def _return_leases(self, session, why):
        rows = self.db.execute(
            "UPDATE work_items SET state=CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'ready' END, "
            "claimed_by=NULL, lease_until=NULL, updated=?, blocked_reason=? WHERE claimed_by=? AND state='claimed' "
            "RETURNING id, state", (now(), why, session)).fetchall()
        self.db.execute("DELETE FROM claims WHERE holder=?", (session,))
        return [dict(r) for r in rows]

    def sweep_leases(self):
        with self.tx():
            rows = self.db.execute(
                "UPDATE work_items SET state=CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'ready' END, "
                "claimed_by=NULL, lease_until=NULL, updated=?, blocked_reason='lease expired' "
                "WHERE state='claimed' AND lease_until < strftime('%Y-%m-%dT%H:%M:%fZ','now') RETURNING id, state",
                (now(),)).fetchall()
            self.db.execute("DELETE FROM claims WHERE lease_until < strftime('%Y-%m-%dT%H:%M:%fZ','now')")
        return [dict(r) for r in rows]

    # -- resource claims (replaces claims/*.json) --------------------------------------
    def claim_path(self, session, repo, path, work_id=None, lease_s=1800):
        with self.tx():
            self.db.execute("DELETE FROM claims WHERE repo=? AND path=? AND lease_until < "
                            "strftime('%Y-%m-%dT%H:%M:%fZ','now')", (repo, path))
            cur = self.q1("SELECT holder FROM claims WHERE repo=? AND path=?", (repo, path))
            if cur and cur["holder"] != session:
                raise HubError(f"{repo}:{path} is claimed by {cur['holder']}")
            self.db.execute("INSERT INTO claims VALUES (?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now','+' || ? || ' seconds'),?) "
                            "ON CONFLICT DO UPDATE SET lease_until=excluded.lease_until",
                            (repo, path, session, work_id, lease_s, now()))
        return {"repo": repo, "path": path, "holder": session}

    # -- status -----------------------------------------------------------------------
    def status(self):
        return {
            "agents": self.q("SELECT session, cli, state, state_note, last_output, last_bell FROM agents ORDER BY session"),
            "deliveries": {r["state"]: r["n"] for r in self.q("SELECT state, count(*) n FROM deliveries GROUP BY state")},
            "work": {r["state"]: r["n"] for r in self.q("SELECT state, count(*) n FROM work_items GROUP BY state")},
            "dead": self.q("SELECT message_id, recipient, last_error FROM deliveries WHERE state='dead' ORDER BY updated DESC LIMIT 20"),
            "repos": [r["repo"] for r in self.q("SELECT repo FROM repos ORDER BY repo")],
            "teams": self.q("SELECT repo, team, lead_role FROM teams ORDER BY repo, team"),
        }

    def events(self, since=0, limit=200, entity=None):
        sql, args = "SELECT * FROM events WHERE seq > ?", [since]
        if entity:
            sql += " AND entity=?"; args.append(entity)
        return self.q(sql + " ORDER BY seq LIMIT ?", args + [limit])


class _Tx:
    def __init__(self, db):
        self.db = db
        self.nested = False

    def __enter__(self):
        self.nested = self.db.in_transaction
        if not self.nested:
            self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        if self.nested:
            return False
        self.db.execute("ROLLBACK" if et else "COMMIT")
        return False


def _caps(agent_row):
    snap = json.loads(agent_row["role_snapshot"])
    return {"capabilities": snap.get("capabilities", []), "cli": agent_row["cli"], "role": agent_row["role"]}


def _meets(req_json, caps_json):
    try:
        req, caps = json.loads(req_json), json.loads(caps_json)
    except Exception:
        return 0
    need = set(req.get("capabilities", []))
    if need - set(caps.get("capabilities", [])):
        return 0
    if req.get("cli") and caps.get("cli") not in req["cli"]:
        return 0
    return 1


def _split_sql(script):
    """Split a migration into statements, keeping trigger bodies (BEGIN...END;) whole."""
    out, buf, depth = [], [], 0
    for line in script.splitlines():
        s = line.strip()
        if not s:
            continue
        buf.append(line)
        u = s.upper()
        if u.startswith("CREATE TRIGGER"):
            depth = 1
        if depth and u == "END;":
            depth = 0
            out.append("\n".join(buf)); buf = []
            continue
        if not depth and s.endswith(";"):
            out.append("\n".join(buf)); buf = []
    if buf:
        out.append("\n".join(buf))
    return out


def _is_9p(d):
    try:
        with open("/proc/mounts") as f:
            mounts = [l.split() for l in f]
    except OSError:
        return False
    best = ("", "")
    for m in mounts:
        if len(m) >= 3 and (d == m[1] or d.startswith(m[1].rstrip("/") + "/")) and len(m[1]) > len(best[0]):
            best = (m[1], m[2])
    return best[1] in ("9p", "drvfs", "v9fs")
