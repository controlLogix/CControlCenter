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
    # 2 (TM-214): retire the courier onto the hub. The courier's own kinds, so any
    # `agentmux post --kind` still works; and term_name, the tmux session an ADOPTED
    # legacy agent really lives in (its protocol name is only an alias for it).
    """
    INSERT OR IGNORE INTO message_kinds (kind) VALUES ('plan'),('status'),('finding'),('error');
    ALTER TABLE agents ADD COLUMN term_name TEXT;
    """,
    # 3 (TM-218): federation over NATS. origin = "<node>:<work id>" for an item that
    # arrived from another hub, so its result can be sent back there.
    """
    ALTER TABLE work_items ADD COLUMN origin TEXT;
    CREATE INDEX outbox_unsent ON nats_outbox (seq) WHERE sent IS NULL;
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
        if 0 < ver < len(MIGRATIONS):
            # Every schema change is preceded by a restorable copy (PROTOCOL 8.1).
            self.backup_to(os.path.join(os.path.dirname(self.path), "backups"), keep=10, label=f"premigrate-v{ver}")
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

    def backup_to(self, dest_dir: str, keep: int = 24, label: str = "hourly") -> str:
        """Online backup (consistent under WAL, no long lock) into dest_dir, keeping the
        newest `keep` per label. Written to a temp name and renamed, so a crash mid-copy
        never leaves a truncated file that looks like a good backup."""
        import glob
        os.makedirs(dest_dir, mode=0o700, exist_ok=True)
        os.chmod(dest_dir, 0o700)                       # backups hold every message body
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1000) % 1000:03d}Z"
        final = os.path.join(dest_dir, f"hub-{label}-{stamp}.db")
        tmp = final + ".tmp"
        os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
        self.backup(tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, final)
        for old in sorted(glob.glob(os.path.join(dest_dir, f"hub-{label}-*.db")))[:-max(1, int(keep))]:
            os.remove(old)
        return final

    def prune(self, events_days: float = 14, messages_days: float = 30) -> dict:
        """Retention. Removes only what is finished: events older than events_days, and
        messages older than messages_days whose every delivery is terminal (acked/dead).
        Undelivered mail is never pruned, however old - that is the at-least-once rule."""
        ev_cut = f"-{float(events_days) * 86400:.0f} seconds"
        msg_cut = f"-{float(messages_days) * 86400:.0f} seconds"
        with self.tx():
            n_ev = self.db.execute("DELETE FROM events WHERE at < strftime('%Y-%m-%dT%H:%M:%fZ','now',?)",
                                   (ev_cut,)).rowcount
            ids = [r[0] for r in self.db.execute(
                "SELECT id FROM messages m WHERE created < strftime('%Y-%m-%dT%H:%M:%fZ','now',?) AND NOT EXISTS "
                "(SELECT 1 FROM deliveries d WHERE d.message_id = m.id AND d.state NOT IN ('acked','dead'))",
                (msg_cut,)).fetchall()]
            for i in ids:
                self.db.execute("DELETE FROM deliveries WHERE message_id=?", (i,))
                self.db.execute("DELETE FROM messages WHERE id=?", (i,))
            n_out = self.db.execute("DELETE FROM nats_outbox WHERE sent IS NOT NULL AND created < "
                                    "strftime('%Y-%m-%dT%H:%M:%fZ','now',?)", (msg_cut,)).rowcount
        return {"events": n_ev, "messages": len(ids), "outbox": n_out}

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

    def canonical_target(self, to: str, virtual=("orchestrator",)):
        """Accept what `agentmux post` users type. A full address passes through; a bare
        name is a registered session, a legacy alias (legacy_names), or a virtual
        recipient. Resolved ONCE, at post time, so the stored target is canonical."""
        if ":" in to:
            return to
        a = self.agent(to)
        if a:
            return f"agent:{a['session']}"
        if to in virtual:
            return f"virtual:{names.normalize(to)}"
        raise HubError(f"'{to}' is not a registered agent, a legacy alias or a virtual recipient")

    def adopt(self, legacy, repo, role, agent, cli, role_snapshot, handle, pane_pid, token_sha=None):
        """Bring a live pre-protocol agent under the hub WITHOUT renaming its tmux
        session (PROTOCOL 10.3): a protocol session name, the old name as an alias,
        and term_name so the transport still finds the real terminal."""
        session = self.register(repo, role, agent, cli, role_snapshot, handle=handle, pane_pid=pane_pid,
                                legacy=legacy, token_sha=token_sha)
        with self.tx():
            self.db.execute("UPDATE agents SET term_name=?, state='ready' WHERE session=?", (legacy, session))
        return session

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
             body_sha=None, meta=None, remote_ok=False, node=None):
        """remote_ok (TM-218): a direct message to an agent this hub does not have goes
        out through the NATS outbox instead of being refused. It has no local delivery
        rows - the hub that owns the recipient delivers and acks it."""
        import hashlib
        if not self.q1("SELECT 1 FROM message_kinds WHERE kind=?", (kind,)):
            kinds = [r["kind"] for r in self.q("SELECT kind FROM message_kinds ORDER BY kind")]
            raise HubError(f"unknown kind {kind!r}; known: {', '.join(kinds)}")
        if idem_key:
            prev = self.q1("SELECT id FROM messages WHERE sender=? AND idem_key=?", (sender, idem_key))
            if prev:
                return {"id": prev["id"], "duplicate": True, "recipients": self._recips_of(prev["id"])}
        remote = False
        try:
            recips = self.recipients(target)
        except HubError:
            if not (remote_ok and target.startswith("agent:")):
                raise
            names.split_session(target[6:])            # only a well-formed protocol name may leave this node
            recips, remote = [], True
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
            if remote:
                self._outbox(names.nats_subject(names.parse_address(target), node or "local"),
                             {"type": "message", "id": mid, "sender": sender, "target": target, "kind": kind,
                              "ref": ref, "body": body, "origin": node})
        return {"id": mid, "duplicate": False, "recipients": recips, "remote": remote}

    def _recips_of(self, mid):
        return [r["recipient"] for r in self.q("SELECT recipient FROM deliveries WHERE message_id=?", (mid,))]

    def _outbox(self, subject, payload):
        # Transactional outbox for the NATS bridge (TM-218). Written in the SAME
        # transaction as the state change it announces, so a crash can never publish
        # something that did not happen, or lose something that did.
        self.db.execute("INSERT INTO nats_outbox (subject, payload, created) VALUES (?,?,?)",
                        (subject, json.dumps(payload, default=str), now()))

    def outbox_pending(self, limit=200):
        return self.q("SELECT seq, subject, payload FROM nats_outbox WHERE sent IS NULL ORDER BY seq LIMIT ?", (limit,))

    def outbox_sent(self, seqs):
        with self.tx():
            for s in seqs:
                self.db.execute("UPDATE nats_outbox SET sent=? WHERE seq=?", (now(), s))

    # -- inbound from other nodes (TM-218) ------------------------------------------------
    def ingest_message(self, env):
        """A direct message another hub published. Delivered only if the recipient is
        one of OURS; idempotent on the sender's message id (NATS may redeliver)."""
        target = env.get("target", "")
        a = self.agent(target[6:]) if target.startswith("agent:") else None
        if not a or a["state"] == "dead":
            return None
        return self.post(env.get("sender") or "virtual:remote", f"agent:{a['session']}", env.get("kind") or "note",
                         env.get("body") or "", env.get("ref"), idem_key=f"nats:{env.get('id')}",
                         meta={"origin": env.get("origin")})

    def ingest_work(self, env):
        """A federated work item this hub won from its queue group: becomes a normal local
        item (local first-claim follows), remembering where to send the result."""
        w = env["work"]
        dup = self.q1("SELECT id FROM work_items WHERE origin=?", (env["origin"],))
        if dup:
            return self.q1("SELECT * FROM work_items WHERE id=?", (dup["id"],))
        item = self.work_create(w["created_by"], w["repo"], w["target"], w["title"], w.get("body"),
                                w.get("task_key"), json.loads(w["requirements"]) if w.get("requirements") else None,
                                int(w.get("priority") or 100))
        with self.tx():
            self.db.execute("UPDATE work_items SET origin=? WHERE id=?", (env["origin"], item["id"]))
        return self.q1("SELECT * FROM work_items WHERE id=?", (item["id"],))

    def ingest_result(self, env):
        """The remote hub finished our federated item: close the local placeholder."""
        wid = env["origin_id"]
        w = self.q1("SELECT * FROM work_items WHERE id=?", (wid,))
        if not w or w["state"] != "claimed" or not (w["claimed_by"] or "").startswith("nats:"):
            return None
        with self.tx():
            self.db.execute("UPDATE work_items SET state=?, result=?, claimed_by=?, updated=? WHERE id=?",
                            (env["state"], env.get("result"), f"nats:{env.get('node')}:{env.get('by')}", now(), wid))
        return self.q1("SELECT * FROM work_items WHERE id=?", (wid,))

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

    def mark_received(self, session, upto, evidence):
        """The CLI's own log shows the bell as a user turn (TM-213): every delivery that
        bell announced is received, whether or not the agent has run inbox yet."""
        with self.tx():
            rows = self.db.execute(
                "UPDATE deliveries SET state='received', evidence=?, updated=? WHERE recipient=? AND message_id<=? "
                "AND state IN ('queued','offered','typed','submitted') RETURNING message_id",
                (json.dumps(evidence), now(), session, upto or "")).fetchall()
            self.event("agent", session, "cli_receipt", "hub", evidence)
        return [r[0] for r in rows]

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
                    priority=100, parent_id=None, max_attempts=3, federate=False, node=None):
        """federate (TM-218): offer a role item to EVERY hub on the NATS network, not
        just this one. The local row becomes a placeholder, claimed by 'nats:federated',
        until the hub that won the item's queue group reports the result back."""
        addr = names.parse_address(target)
        if federate and addr.kind != "role":
            raise HubError("only role items can be federated (a direct or team item has one home)")
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
            if federate:
                self.db.execute("UPDATE work_items SET state='claimed', claimed_by='nats:federated' WHERE id=?", (wid,))
                row = dict(self.db.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone())
                self._outbox(names.nats_subject(addr, node or "local"),
                             {"type": "work", "origin": f"{node}:{wid}", "origin_node": node, "origin_id": wid,
                              "work": {k: row[k] for k in ("repo", "target", "title", "body", "task_key",
                                                            "requirements", "priority", "created_by")}})
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

    def release(self, session, work_id, outcome, result=None, node=None):
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
            if w.get("origin") and new in ("done", "failed"):
                # A federated item: report back to the hub that owns it (TM-218).
                origin_node, _, origin_id = w["origin"].partition(":")
                self._outbox(f"am.result.{origin_node}", {"type": "result", "origin_id": origin_id, "state": new,
                                                         "result": result, "by": session, "node": node})
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

    def events(self, since=0, limit=200, entity=None, tail=False):
        # tail=True: the NEWEST `limit` rows after `since`, still oldest-first. Forward
        # paging from since=0 returns the oldest rows, which once the table outgrows
        # one page is never what a person asking "what just happened" wants.
        sql, args = "SELECT * FROM events WHERE seq > ?", [since]
        if entity:
            sql += " AND entity=?"; args.append(entity)
        if tail:
            return self.q(f"SELECT * FROM ({sql} ORDER BY seq DESC LIMIT ?) ORDER BY seq", args + [limit])
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
