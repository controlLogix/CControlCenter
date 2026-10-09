"""agentmux-hub: the one process that owns hub.db. See docs/PROTOCOL.md 7-9.

Run:  python3 hub/server.py [--foreground]      (normally via `agentmux hub start`)

Concurrency model: asyncio for the socket and the loops; every Store call runs on ONE
dedicated thread (the only writing connection); blocking terminal I/O (doorbells)
runs on a small pool, at most one in flight per agent.

Identity (R-ID-1): a caller is identified by walking its process ancestry to a
registered agent's pane pid (SO_PEERCRED on the unix socket). $AGENTMUX_AGENT is never
consulted - the codex shared daemon proved an env var is not an identity (C8).
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import hashlib
import hmac
import json
import os
import secrets
import signal
import socket
import struct
import subprocess
import sys
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hub import deliver, names, profiles  # noqa: E402
from hub.store import HubError, Store, now  # noqa: E402
from hub.bridge import Bridge  # noqa: E402
from hub.fed.runtime import Federation  # noqa: E402
from hub.receipts import ReceiptScanner  # noqa: E402
from hub.transport import TmuxTransport  # noqa: E402

ROOT = os.environ.get("AGENTMUX_HOME") or os.path.expanduser("~/.agentmux")
HUBDIR = os.path.join(ROOT, "hub")
SOCK = os.path.join(HUBDIR, "hub.sock")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ROLES = {
    "lead": {"description": "Owns a team's work: decomposes team items into role items and integrates results.",
             "capabilities": ["plan", "review", "python", "bash"], "may_claim": ["team", "work"], "max_active": 3,
             "lease_s": 1800,
             "instructions": "As a lead: when you claim a team item, split it into work items for roles in your team "
                             "(agentmux hub work add --to role:team:<repo>/<team>/<role> --parent <id> ...), wait for "
                             "their results to arrive in your inbox, integrate/verify, then `agentmux hub done <id>`."},
    "worker": {"description": "Implements a work item.", "capabilities": ["python", "bash", "code"], "max_active": 1,
               "lease_s": 1200,
               "instructions": "As a worker: claim one item, do exactly what it says in the repo checkout, run its "
                               "tests, then `agentmux hub done <id> --result \"<what changed, test result>\"`."},
    "reviewer": {"description": "Reviews a submission against its acceptance criteria.",
                 "capabilities": ["review", "python", "bash"], "max_active": 1, "lease_s": 900,
                 "instructions": "As a reviewer: claim a review item, inspect the named change, run the tests, then "
                                 "`agentmux hub done <id> --result \"APPROVE: ...\"` or \"REJECT: <reasons>\"."},
    "researcher": {"description": "Answers a question with sources.", "capabilities": ["research"], "max_active": 1,
                   "lease_s": 1200, "instructions": "As a researcher: answer the item's question and cite sources."},
}

DEFAULT_CONFIG = {"node": "local", "bell_every_s": 90, "poll_s": 1.5, "max_attempts": 12,
                  "operator": "virtual:operator",
                  # TM-217: hourly online backups (24 kept), daily retention pass.
                  "backup_every_s": 3600, "backup_keep": 24,
                  "prune_every_s": 86400, "retention_events_days": 14, "retention_messages_days": 30,
                  # TM-218: set nats_url (e.g. "nats://127.0.0.1:4222") to federate this hub.
                  "nats_url": ""}


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def load_toml(p):
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def parent_pid(pid):
    """Parent of `pid`, or None. /proc on Linux; macOS has none, so ask ps."""
    try:
        if os.path.isdir("/proc"):
            with open(f"/proc/{pid}/stat") as f:
                return int(f.read().rsplit(")", 1)[1].split()[1])
        return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=5).stdout.strip())
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def ancestors(pid):
    out, seen = [], set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        out.append(pid)
        pid = parent_pid(pid)
    return out


def toml_dump(d):
    lines = []
    for k, v in d.items():
        lines.append(f"{k} = {json.dumps(v)}")
    return "\n".join(lines) + "\n"


class Hub:
    def __init__(self):
        os.makedirs(HUBDIR, exist_ok=True)
        self.cfg = {**DEFAULT_CONFIG, **load_toml(os.path.join(HUBDIR, "config.toml"))}
        self.dbx = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hubdb")
        self.io = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="hubio")
        self.store: Store = self.dbx.submit(Store, os.path.join(HUBDIR, "hub.db")).result()
        self.tp = TmuxTransport(logdir=os.path.join(ROOT, "logs"))
        self.inflight: set[str] = set()
        self.bell: dict[str, dict] = {}         # session -> {sig, at, next_check}
        self.marks: dict[str, int] = {}
        self.started: dict[str, float] = {}
        self.stop = asyncio.Event()
        self.subscribers = 0
        self.operator_sha = self._operator_token()
        self.receipts = ReceiptScanner()
        self.awaiting: dict[str, dict] = {}     # session -> first unreceived bell (TM-213)
        self.bridge = Bridge(self, self.cfg["nats_url"], names.check_part(self.cfg["node"], "node"), log) \
            if self.cfg.get("nats_url") else None
        # EP-032: cross-user federation (docs/FEDERATION.md). Always constructed so its
        # verbs answer; it only connects when federation.toml says enabled.
        self.fed = Federation(self, HUBDIR, log)
        self._seed_roles()

    def _operator_token(self):
        p = os.path.join(HUBDIR, "operator.token")
        if not os.path.exists(p):
            write_secret(p, secrets.token_urlsafe(32))
        with open(p) as f:
            return hashlib.sha256(f.read().strip().encode()).hexdigest()

    async def db(self, fn, *a, **kw):
        return await asyncio.get_running_loop().run_in_executor(self.dbx, lambda: fn(*a, **kw))

    # -- roles --------------------------------------------------------------------------
    def _seed_roles(self):
        d = os.path.join(ROOT, "roles")
        os.makedirs(d, exist_ok=True)
        for name, spec in DEFAULT_ROLES.items():
            p = os.path.join(d, f"{name}.toml")
            if not os.path.exists(p):
                with open(p, "w") as f:
                    f.write(toml_dump({"name": name, **spec}))

    def resolve_role(self, repo, role):
        g = load_toml(os.path.join(ROOT, "roles", f"{role}.toml"))
        o = load_toml(os.path.join(ROOT, "repos", repo, "roles", f"{role}.toml"))
        if not g and not o:
            raise HubError(f"unknown role {role!r}: create {ROOT}/roles/{role}.toml")
        return {**g, **o, "name": role, "override": bool(o)}

    # -- identity ------------------------------------------------------------------------
    def peer(self, sock: socket.socket):
        if hasattr(socket, "SO_PEERCRED"):
            creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", creds)
            return pid, uid
        # macOS has no SO_PEERCRED. The kernel still vouches, in two calls at SOL_LOCAL (0):
        # LOCAL_PEERPID (2) for the pid, LOCAL_PEERCRED (1) for a struct xucred whose
        # second field is the uid. Python names only the latter, so both are spelled out.
        pid = struct.unpack("i", sock.getsockopt(0, 2, struct.calcsize("i")))[0]
        _version, uid = struct.unpack("2I", sock.getsockopt(0, socket.LOCAL_PEERCRED, 76)[:8])
        return pid, uid

    def identify(self, pid):
        """(session|None, in_pane:bool). A caller inside ANY tmux pane that is not a
        registered agent is 'unregistered' - it may not act as the operator."""
        chain = set(ancestors(pid))
        by_pid = {a["pane_pid"]: a["session"] for a in self.store.agents(live_only=True) if a["pane_pid"]}
        for p in chain:
            if p in by_pid:
                return by_pid[p], True
        try:
            out = subprocess.run(["tmux", "-L", self.tp.socket, "list-panes", "-a", "-F", "#{pane_pid}"],
                                 capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=5).stdout
            pane_pids = {int(x) for x in out.split()}
        except Exception:
            pane_pids = set()
        return None, bool(chain & pane_pids)

    # -- socket server ------------------------------------------------------------------
    async def caller_of(self, req, writer, tcp):
        """Who is calling. Unix socket: the kernel vouches (process ancestry, R-ID-1).
        TCP: nothing vouches, so a token is required and `as` is never honored."""
        if tcp:
            tok = req.get("token") or ""
            if not tok:
                raise HubError("token required on TCP (agentmux hub token shows where yours is)")
            sha = hashlib.sha256(tok.encode()).hexdigest()
            if hmac.compare_digest(sha, self.operator_sha):
                return "operator"
            row = await self.db(self.store.q1, "SELECT session FROM agents WHERE token_sha=? AND state<>'dead'", (sha,))
            if not row:
                raise HubError("invalid or revoked token")
            return row["session"]
        pid, uid = self.peer(writer.get_extra_info("socket"))
        if uid != os.getuid():
            raise HubError("wrong uid")
        session, in_pane = await self.db(self.identify, pid)
        if req.get("as"):
            if in_pane:
                raise HubError("--as is only for the operator, not from inside an agent pane (R-ID-1)")
            return req["as"]
        if session:
            return session
        return "unregistered" if in_pane else "operator"

    async def handle_conn(self, reader, writer, tcp=False):
        caller = None
        try:
            raw = await asyncio.wait_for(reader.readline(), 30)
            req = json.loads(raw or b"{}")
            caller = await self.caller_of(req, writer, tcp)
            if req.get("verb") == "subscribe":
                return await self.subscribe(writer, caller, req.get("args", {}))
            res = await self.dispatch(req.get("verb", ""), req.get("args", {}), caller)
            resp = {"ok": True, "caller": caller, "result": res}
        except HubError as e:
            resp = {"ok": False, "error": str(e)}
        except Exception as e:  # never kill the hub on one bad request
            log("error", type(e).__name__, e)
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        writer.write((json.dumps(resp, default=str) + "\n").encode())
        try:
            await writer.drain()
        finally:
            writer.close()

    async def subscribe(self, writer, caller, a):
        """A long-lived stream: one JSON line per event, until the client hangs up.
          mail   (default) new deliveries for the caller, plus claimable-work changes
          events the audit trail (operator only) - what the dashboard follows
        The first line acknowledges the subscription. Nothing is marked received by a
        subscription: only `inbox` (the agent reading its mail) is evidence of that."""
        stream = a.get("stream", "mail")
        who = "virtual:operator" if caller == "operator" else caller
        if caller == "unregistered":
            raise HubError("unregistered pane")
        if stream == "events" and caller != "operator":
            raise HubError("the events stream is operator-only")
        self.subscribers += 1

        async def send(obj):
            writer.write((json.dumps(obj, default=str) + "\n").encode())
            await writer.drain()

        try:
            await send({"ok": True, "caller": caller, "subscribed": stream})
            if stream == "events":
                since = int(a.get("since", 0))
                while not self.stop.is_set():
                    for e in await self.db(self.store.events, since, 500):
                        since = e["seq"]
                        await send({"event": e})
                    await asyncio.sleep(0.5)
            else:
                seen, claim_sig = set(), None
                while not self.stop.is_set():
                    for d in await self.db(self.store.pending_for, who):
                        if d["message_id"] not in seen:
                            seen.add(d["message_id"])
                            m = await self.db(self.store.q1, "SELECT id, sender, kind, ref, body, body_ref, created "
                                              "FROM messages WHERE id=?", (d["message_id"],))
                            await send({"message": m})
                    if not who.startswith("virtual:"):
                        cl = await self.db(self.store.claimable, who)
                        sig = tuple(c["id"] for c in cl)
                        if sig != claim_sig:
                            claim_sig = sig
                            await send({"claimable": cl})
                    await asyncio.sleep(0.5)
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            self.subscribers -= 1
            try:
                writer.close()
            except Exception:
                pass

    def need_agent(self, caller):
        if caller in ("operator", "unregistered") or caller.startswith("virtual:"):
            raise HubError(f"this verb needs a registered agent; caller is {caller}")
        return caller

    def need_operator(self, caller):
        if caller != "operator":
            raise HubError(f"operator-only verb; caller is {caller}")

    def sender_of(self, caller):
        if caller == "unregistered":
            raise HubError("unregistered pane: spawn agents with `agentmux hub spawn` (or adopt them)")
        if caller == "operator":
            return "virtual:operator"
        return caller if caller.startswith("virtual:") else f"agent:{caller}"

    async def dispatch(self, verb, a, caller):
        s = self.store
        if verb.startswith("fed_"):
            return await self.fed.dispatch(verb, a, caller)
        if verb == "ping":
            return {"pong": now(), "caller": caller}
        if verb == "token":
            # Where the caller's own token lives - never the token itself over the wire.
            if caller == "operator":
                return {"path": os.path.join(HUBDIR, "operator.token")}
            ag = await self.db(s.agent, self.need_agent(caller))
            return {"path": os.path.join(ROOT, "repos", ag["repo"], "agents", f"{ag['role']}-{ag['agent']}", "run", "token")}
        if verb == "whoami":
            ag = await self.db(s.agent, caller) if caller not in ("operator", "unregistered") else None
            return {"caller": caller, "agent": ag,
                    "eligible": await self.db(s.eligible_targets, caller) if ag else []}
        if verb == "status" and a.get("bridge"):
            b = self.bridge
            return {"node": self.cfg["node"], "nats_url": self.cfg.get("nats_url") or None,
                    "connected": bool(b and b.connected), "stats": b.stats if b else {},
                    "role_subjects": sorted(b.role_subs) if b else []}
        if verb == "status":
            return await self.db(s.status)
        if verb == "events":
            return await self.db(s.events, int(a.get("since", 0)), int(a.get("limit", 200)), a.get("entity"),
                                 bool(a.get("tail")))
        if verb == "repo_add":
            self.need_operator(caller)
            repo = names.check_part(a["repo"], "repo", a.get("accept_normalized", False))
            paths = [os.path.realpath(p) for p in a.get("paths", [])]
            aliases = list(a.get("aliases", []))
            for p in paths:
                rem = subprocess.run(["git", "-C", p, "remote", "get-url", "origin"], capture_output=True, text=True)
                if rem.returncode == 0 and rem.stdout.strip():
                    aliases.append(normalize_remote(rem.stdout.strip()))
            r = await self.db(s.repo_add, repo, a.get("title"), paths, aliases, a.get("groups", []))
            os.makedirs(os.path.join(ROOT, "repos", repo, "agents"), exist_ok=True)
            os.makedirs(os.path.join(ROOT, "repos", repo, "roles"), exist_ok=True)
            os.makedirs(os.path.join(ROOT, "repos", repo, "teams"), exist_ok=True)
            with open(os.path.join(ROOT, "repos", repo, "repo.toml"), "w") as f:
                f.write(toml_dump({"repo": repo, "title": a.get("title") or repo, "paths": paths,
                                   "aliases": sorted(set(aliases)), "groups": a.get("groups", [])}))
            return r
        if verb == "team_add":
            if caller != "operator":
                me = await self.db(s.agent, caller)
                if not me or me["role"] != "lead":
                    raise HubError("only the operator or a lead may create teams")
            t = await self.db(s.team_add, a["repo"], a["team"], a.get("members", []), a.get("lead_role", "lead"))
            with open(os.path.join(ROOT, "repos", a["repo"], "teams", f"{a['team']}.toml"), "w") as f:
                f.write(toml_dump({"team": t["team"], "lead_role": t["lead_role"], "members": t["members"]}))
            return t
        if verb == "spawn":
            self.need_operator(caller)
            return await self.spawn(a)
        if verb == "kill":
            self.need_operator(caller)
            ag = await self.db(s.agent, a["session"])
            if not ag:
                raise HubError(f"no such agent {a['session']}")
            sess = ag["session"]
            await asyncio.get_running_loop().run_in_executor(self.io, self.harness, "kill", term(ag))
            await self.db(s.set_state, sess, "dead", "killed by operator")
            await self.db(s.event, "agent", sess, "kill", "operator", {"reason": a.get("reason", "operator")})
            return {"killed": sess}
        if verb == "agents":
            return await self.db(s.agents, bool(a.get("live")))
        if verb == "resolve":
            return {"address": a["address"], "recipients": await self.db(s.recipients, a["address"])}
        if verb == "adopt":
            self.need_operator(caller)
            return await self.adopt(a)
        if verb == "retire_courier":
            self.need_operator(caller)
            return await self.retire_courier(bool(a.get("dry_run")))
        if verb == "post" and str(a.get("to", "")).startswith("peer:"):
            # Another person's agent, role or operator: the federation messages plugin.
            return await self.fed.guarded(self.fed.plugins["messages"].send(
                self.fed, caller, a["to"], a.get("kind", "note"), a.get("body", ""), a.get("ref")))
        if verb == "post":
            sender = self.sender_of(caller)
            a = {**a, "to": await self.db(s.canonical_target, a["to"], self.virtual_names())}
            body = a.get("body", "")
            body_ref = None
            if len(body.encode()) > int(self.cfg.get("inline_max", 4096)):
                body_ref = self._write_brief(a["to"], body)
            r = await self.db(s.post, sender, a["to"], a.get("kind", "note"), body, a.get("ref"), a.get("work_id"),
                              a.get("idem_key"), body_ref, remote_ok=self.bridge is not None,
                              node=self.cfg["node"])
            return r
        if verb == "inbox":
            who = a.get("session") if caller == "operator" and a.get("session") else caller
            if who == "operator":
                who = "virtual:operator"
            if who == "unregistered":
                raise HubError("unregistered pane")
            # An operator peeking at an agent's inbox must not mark it received: only
            # the agent reading its own mail is evidence it got the message.
            peek = caller == "operator" and who != "virtual:operator"
            msgs = await self.db(s.inbox, who, int(a.get("limit", 20)), not peek)
            if peek:
                a = {**a, "ack": False}
            acked = []
            if a.get("ack") and msgs:
                acked = await self.db(s.ack, who, [m["id"] for m in msgs])
            out = {"session": who, "messages": msgs, "acked": acked}
            if not who.startswith("virtual:"):
                out["claimable"] = await self.db(s.claimable, who)
                out["active"] = await self.db(s.q, "SELECT id, title, lease_until FROM work_items WHERE claimed_by=? "
                                              "AND state IN ('claimed','waiting_children')", (who,))
            return out
        if verb == "ack":
            who = "virtual:operator" if caller == "operator" else self.need_agent(caller)
            return {"acked": await self.db(s.ack, who, a["ids"])}
        if verb == "work_add" and a.get("federate") and self.fed.enabled:
            # EP-032 supersedes the TM-218 queue group when federation is configured.
            req = a.get("requirements")
            return await self.fed.guarded(self.fed.plugins["work"].add(
                self.fed, caller, a["to"], a["title"], a.get("body"), a.get("task_key"), req,
                int(a.get("priority", 100))))
        if verb == "work_add":
            sender = self.sender_of(caller)
            repo = a.get("repo") or self._repo_of_target(a["to"], caller)
            return await self.db(s.work_create, sender, repo, a["to"], a["title"], a.get("body"), a.get("task_key"),
                                 a.get("requirements"), int(a.get("priority", 100)), a.get("parent"),
                                 int(a.get("max_attempts", 3)), federate=bool(a.get("federate")),
                                 node=self.cfg["node"])
        if verb == "claim":
            me = self.need_agent(caller)
            return await self.db(s.claim, me, a.get("lease_s"), a.get("work_id"))
        if verb == "heartbeat":
            return {"renewed": await self.db(s.heartbeat, self.need_agent(caller), a.get("lease_s"))}
        if verb == "release":
            me = self.need_agent(caller)
            w = await self.db(s.release, me, a["work_id"], a["outcome"], a.get("result"), self.cfg["node"])
            await self._notify_work_owner(w, me)
            await self.fed.local_event("work_released", w)
            return w
        if verb == "work_cancel":
            self.need_operator(caller)
            return {"cancelled": await self.db(s.cancel, a["work_id"], a.get("reason") or "cancelled by operator")}
        if verb == "work_show":
            return await self.db(s.work, a["work_id"])
        if verb == "work_list":
            return await self.db(s.work, None, a.get("state"), a.get("repo"))
        if verb == "claim_path":
            me = self.need_agent(caller)
            ag = await self.db(s.agent, me)
            return await self.db(s.claim_path, me, a.get("repo") or ag["repo"], a["path"], a.get("work_id"))
        if verb == "shutdown":
            self.need_operator(caller)
            self.stop.set()
            return {"stopping": True}
        raise HubError(f"unknown verb {verb!r}")

    def _repo_of_target(self, target, caller):
        ad = names.parse_address(target)
        if ad.kind == "agent":
            return names.split_session(ad.name)[0]
        if ad.kind == "team":
            return ad.scope
        if ad.kind == "role":
            sc = ad.scope
            if sc.startswith("team:"):
                return sc[5:].split("/")[0]
            if not sc.startswith("group:") and sc != "*":
                return sc
        if caller not in ("operator", "unregistered"):
            return names.split_session(caller)[0]
        raise HubError("cannot infer repo for this target; pass --repo")

    async def _notify_work_owner(self, w, me):
        """When an item finishes, tell whoever created it - and the parent's holder."""
        if not w:
            return
        body = f"work {w['id']} \"{w['title']}\" is {w['state']} (by {me})"
        if w.get("result"):
            body += f"\nresult: {w['result']}"
        targets = set()
        if w["created_by"] and w["created_by"] != f"agent:{me}":
            targets.add(w["created_by"])
        if w.get("parent_id"):
            p = await self.db(self.store.work, w["parent_id"])
            if p and p.get("claimed_by") and p["claimed_by"] != me:
                targets.add(f"agent:{p['claimed_by']}")
        for t in targets:
            if t.startswith("peer:"):
                continue                    # federated: the work plugin sends the result envelope
            try:
                await self.db(self.store.post, "virtual:hub", t, "result", body, w["id"], w["id"],
                              f"result:{w['id']}:{w['state']}:{t}")
            except HubError as e:
                log("notify failed", t, e)

    def _write_brief(self, to, body):
        import hashlib
        h = hashlib.sha256(body.encode()).hexdigest()[:16]
        d = os.path.join(ROOT, "briefs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{h}.md")
        with open(p, "w") as f:
            f.write(body)
        return p

    def harness(self, verb, *args):
        """Tear down through `agentmux kill` / `agentmux reap`, never raw tmux: those
        also remove the run/<name>.* sidecars, which is what the dashboard lists agents
        from. A raw kill-session left 27 stale tiles after one evening of evals.
        Falls back to the transport's kill if the harness is unavailable."""
        cmd = [os.environ.get("AGENTMUX_BIN", os.path.expanduser("~/.local/bin/agentmux")), verb, *args]
        env = {k: v for k, v in os.environ.items() if k != "AGENTMUX_AGENT"}
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=120)
            ok = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok and verb == "kill" and args:
            self.tp.kill(args[0])
        return ok

    def virtual_names(self):
        return tuple(x for x in os.environ.get("AGENTMUX_VIRTUAL_AGENTS", "orchestrator").split(",") if x)

    # -- courier retirement (TM-214, PROTOCOL section 10) ---------------------------------
    async def adopt(self, a):
        legacy = a["legacy"]
        h = await asyncio.get_running_loop().run_in_executor(self.io, self.tp.handle, legacy)
        if not h:
            raise HubError(f"no live tmux session named {legacy!r} to adopt")
        repo = names.check_part(a["repo"], "repo")
        role = names.check_part(a["role"], "role")
        agent = names.check_part(a["agent"], "agent", a.get("accept_normalized", False))
        cli = a.get("cli")
        if not cli:
            try:
                with open(os.path.join(ROOT, "run", f"{legacy}.cli")) as f:
                    cli = f.read().strip() or "shell"
            except OSError:
                cli = "shell"
        snap = self.resolve_role(repo, role)
        token = secrets.token_urlsafe(32)
        session = await self.db(self.store.adopt, legacy, repo, role, agent, cli, snap, h[0], h[1],
                                hashlib.sha256(token.encode()).hexdigest())
        adir = os.path.join(ROOT, "repos", repo, "agents", f"{role}-{agent}")
        for sub in ("run", "logs", "briefs", "cli"):
            os.makedirs(os.path.join(adir, sub), exist_ok=True)
        write_secret(os.path.join(adir, "run", "token"), token)
        lp = os.path.join(adir, "logs", "pane.log")
        if not os.path.lexists(lp):
            os.symlink(os.path.join(ROOT, "logs", f"{legacy}.log"), lp)
        self.started[session] = 0
        cwd = (await self.db(self.store.q1, "SELECT path FROM repo_paths WHERE repo=? ORDER BY path", (repo,)) or {}).get("path", "")
        await self.db(self.store.post, "virtual:hub", f"agent:{session}", "control",
                      welcome(session, repo, role, cwd, snap) + f"\n(You were adopted: your tmux session is still "
                      f"'{legacy}', and messages to '{legacy}' reach you.)", None, None, f"welcome:{session}")
        return {"session": session, "legacy": legacy, "handle": h[0], "cli": cli}

    async def retire_courier(self, dry_run=False):
        """Hand the courier's undelivered backlog to the hub, then stop the courier for
        good. Idempotent: every imported line carries an idem key built from its outbox
        inode and byte offset, so a second run imports nothing twice."""
        qdir, cdir = os.path.join(ROOT, "queue"), os.path.join(ROOT, "courier")
        report = {"imported": 0, "duplicate": 0, "unresolved": [], "no_cursor": [], "outboxes": 0}
        todo = []
        for fn in sorted(os.listdir(qdir)) if os.path.isdir(qdir) else []:
            if not fn.endswith(".jsonl") or fn == "courier.jsonl":
                continue
            path, sender = os.path.join(qdir, fn), fn[:-6]
            report["outboxes"] += 1
            try:
                st = os.lstat(path)
                with open(os.path.join(cdir, f"{sender}.cursor")) as f:
                    cur = json.load(f)
            except (OSError, ValueError):
                report["no_cursor"].append(sender)       # the courier never read it: leave it be
                continue
            off = int(cur["offset"]) if int(cur.get("ino", -1)) == st.st_ino else 0
            with open(path, "rb") as f:
                f.seek(off)
                pos = off
                for raw in f:
                    todo.append((sender, st.st_ino, pos, raw))
                    pos += len(raw)
        try:
            with open(os.path.join(cdir, "pending.jsonl"), "rb") as f:
                for i, raw in enumerate(f):
                    todo.append(("pending", 0, i, raw))
        except OSError:
            pass
        for sender, ino, pos, raw in todo:
            try:
                rec = json.loads(raw)
                rec = rec.get("message", rec) if isinstance(rec, dict) else {}
            except ValueError:
                continue
            rcpt, src = rec.get("recipient"), rec.get("sender") or sender
            if not rcpt:
                continue
            try:
                to = await self.db(self.store.canonical_target, rcpt, self.virtual_names())
            except HubError:
                report["unresolved"].append(f"{src}->{rcpt}")
                continue
            src_ag = await self.db(self.store.agent, src)
            frm = f"agent:{src_ag['session']}" if src_ag else f"virtual:legacy_{names.normalize(src) or 'unknown'}"
            kind = rec.get("kind") if await self.db(self.store.q1, "SELECT 1 FROM message_kinds WHERE kind=?",
                                                    (rec.get("kind"),)) else "note"
            if dry_run:
                report["imported"] += 1
                continue
            r = await self.db(self.store.post, frm, to, kind, rec.get("body") or "", rec.get("ref"), None,
                              f"import:{sender}:{ino}:{pos}")
            report["duplicate" if r["duplicate"] else "imported"] += 1
        if not dry_run:
            report["courier_stopped"] = await asyncio.get_running_loop().run_in_executor(
                self.io, self.harness, "courier", "stop")
            with open(os.path.join(HUBDIR, "courier-retired"), "w") as f:
                json.dump({**report, "at": now()}, f)
        return report

    # -- spawn --------------------------------------------------------------------------
    async def spawn(self, a):
        repo = names.check_part(a["repo"], "repo")
        role = names.check_part(a["role"], "role")
        agent = names.check_part(a["agent"], "agent", a.get("accept_normalized", False))
        cli = a.get("cli", "codex")
        paths = await self.db(self.store.q, "SELECT path FROM repo_paths WHERE repo=? ORDER BY path", (repo,))
        if not paths:
            raise HubError(f"repo {repo} has no checkout path")
        cwd = a.get("cwd") or paths[0]["path"]
        snap = self.resolve_role(repo, role)
        # A per-agent token for callers the kernel cannot vouch for (TCP, later NATS).
        # Only its sha256 is stored; the token itself goes to a 0600 file the agent owns.
        token = secrets.token_urlsafe(32)
        session = await self.db(self.store.register, repo, role, agent, cli, snap,
                                token_sha=hashlib.sha256(token.encode()).hexdigest())
        adir = os.path.join(ROOT, "repos", repo, "agents", f"{role}-{agent}")
        for sub in ("run", "logs", "briefs", "cli"):
            os.makedirs(os.path.join(adir, sub), exist_ok=True)
        write_secret(os.path.join(adir, "run", "token"), token)
        with open(os.path.join(adir, "agent.toml"), "w") as f:
            f.write(toml_dump({"session": session, "repo": repo, "role": role, "agent": agent, "cli": cli,
                               "model": a.get("model", ""), "cwd": cwd}))
        cmd = [os.environ.get("AGENTMUX_BIN", os.path.expanduser("~/.local/bin/agentmux")), "spawn", session,
               "--cli", cli, "--cwd", cwd]
        if a.get("model"):
            cmd += ["--model", a["model"]]
        env = {**os.environ, "AGENTMUX_IDLE_MINUTES": "0"}
        env.pop("AGENTMUX_AGENT", None)
        r = await asyncio.get_running_loop().run_in_executor(
            self.io, lambda: subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                                            timeout=120))
        if r.returncode != 0:
            await self.db(self.store.set_state, session, "dead", "spawn failed")
            raise HubError(f"spawn failed: {(r.stderr or r.stdout).strip()[-400:]}")
        h = await asyncio.get_running_loop().run_in_executor(self.io, self.tp.handle, session)
        if not h:
            await self.db(self.store.set_state, session, "dead", "no pane after spawn")
            raise HubError("spawned but no pane found")
        await self.db(self.store.set_handle, session, h[0], h[1])
        self.started[session] = time.time()
        with open(os.path.join(adir, "run", "handle"), "w") as f:
            f.write(f"{h[0]} {h[1]}\n")
        lp = os.path.join(adir, "logs", "pane.log")
        if not os.path.lexists(lp):
            os.symlink(os.path.join(ROOT, "logs", f"{session}.log"), lp)
        for t in a.get("teams", []):
            await self.db(self.store.team_add, repo, t, [session])
        await self.db(self.store.post, "virtual:hub", f"agent:{session}", "control",
                      welcome(session, repo, role, cwd, snap), None, None, f"welcome:{session}:{int(time.time())}")
        return {"session": session, "handle": h[0], "pane_pid": h[1], "cwd": cwd, "spawn_out": r.stdout[-300:]}

    # -- loops --------------------------------------------------------------------------
    async def bell_loop(self):
        while not self.stop.is_set():
            try:
                await self._bell_pass()
            except Exception as e:
                log("bell loop error", type(e).__name__, e)
            await asyncio.sleep(float(self.cfg["poll_s"]))

    async def _bell_pass(self):
        s = self.store
        for ag in await self.db(s.agents, True):
            sess = ag["session"]
            if not ag["handle"] or sess in self.inflight or ag["state"] == "dead":
                continue
            st = self.bell.setdefault(sess, {"sig": None, "at": 0.0, "next": 0.0, "blocked_note": None})
            if time.time() < st["next"]:
                continue
            pend = await self.db(s.pending_for, sess)
            claim = await self.db(s.claimable, sess)
            snap = json.loads(ag["role_snapshot"])
            active = await self.db(s.q, "SELECT count(*) n FROM work_items WHERE claimed_by=? AND state='claimed'", (sess,))
            if active[0]["n"] >= int(snap.get("max_active", 1)):
                claim = []          # at capacity: offering more work is noise
            unrung = [p for p in pend if p["state"] in ("queued", "offered")]
            unacked = [p for p in pend if p["state"] != "acked"]
            if not unacked and not claim:
                continue
            sig = (pend[-1]["message_id"] if pend else None, tuple(c["id"] for c in claim))
            fresh = sig != st["sig"] and (unrung or claim)
            stale = time.time() - st["at"] > float(self.cfg["bell_every_s"])
            if not (fresh or stale):
                continue
            self.inflight.add(sess)
            asyncio.create_task(self._ring(ag, len(unacked), len(claim), sig, rering=bool(stale and not fresh)))

    async def _ring(self, ag, n_msg, n_claim, sig, rering=False):
        sess = ag["session"]
        st = self.bell[sess]
        prof = profiles.get(ag["cli"])
        text = prof.bell(n_msg=n_msg, n_claim=n_claim, session=sess)
        try:
            rc = await asyncio.get_running_loop().run_in_executor(
                self.io, lambda: deliver.deliver_line(self.tp, prof, term(ag), ag["handle"], text,
                                                       started_at=self.started.get(sess)))
            ev = rc.as_dict()
            await self.db(self.store.event, "bell", sess, rc.outcome, "hub", ev)
            if rc.outcome == "submitted":
                if rering:
                    # An attempt is spent only when a doorbell was SUBMITTED and the mail
                    # still sat unacked - never while the agent was busy or blocked.
                    dead = await self.db(self.store.bump_attempt, sess, "doorbell submitted, not acked",
                                         int(self.cfg["max_attempts"]))
                    if dead:
                        await self._tell_operator(f"{len(dead)} message(s) to {sess} went dead: never acked",
                                                  f"dead:{sess}:{dead[0]}")
                st.update(sig=sig, at=time.time(), next=time.time() + 2, blocked_note=None)
                # Only the messages this bell COUNTED. One posted while the bell was in
                # flight has not been announced yet and must stay queued for the next ring.
                upto = sig[0] or ""
                for p in await self.db(self.store.pending_for, sess):
                    if p["state"] in ("queued", "offered", "typed") and p["message_id"] <= upto:
                        await self.db(self.store.delivery_report, p["message_id"], sess, "submitted", ev)
                await self.db(self.store.db.execute, "UPDATE agents SET last_bell=?, state='busy' WHERE session=?",
                              (now(), sess))
                if ag["cli"] in ("codex", "claude", "grok"):
                    # Now wait for the CLI's own log to show it (TM-213). Keep the EARLIEST
                    # unreceived bell time: a hold is measured from the first unseen bell.
                    aw = self.awaiting.get(sess)
                    self.awaiting[sess] = {"at": aw["at"] if aw else time.time(), "upto": upto, "alerted": False}
            elif rc.outcome == "deferred":
                st["next"] = time.time() + (5 if rc.reason == "busy" else 3)
            elif rc.outcome == "blocked":
                st["next"] = time.time() + 30
                if st.get("blocked_note") != rc.reason:
                    st["blocked_note"] = rc.reason
                    await self.db(self.store.set_state, sess, "blocked", rc.reason)
                    await self._tell_operator(f"{sess} is blocked: {rc.reason}. Look at it: agentmux attach {sess}",
                                              f"blocked:{sess}:{rc.reason}:{int(time.time() // 600)}")
            elif rc.outcome == "dead":
                await self.db(self.store.set_state, sess, "dead", rc.reason)
            else:
                st["next"] = time.time() + 10
                await self.db(self.store.bump_attempt, sess, f"doorbell {rc.outcome}: {rc.reason}",
                              int(self.cfg["max_attempts"]))
        except Exception as e:
            log("ring error", sess, type(e).__name__, e)
            st["next"] = time.time() + 10
        finally:
            self.inflight.discard(sess)

    async def _tell_operator(self, body, idem):
        try:
            await self.db(self.store.post, "virtual:hub", "virtual:operator", "note", body, None, None, idem)
        except HubError as e:
            log("operator note failed", e)

    async def live_loop(self):
        while not self.stop.is_set():
            try:
                for ag in await self.db(self.store.agents, True):
                    sess = ag["session"]
                    if not ag["handle"]:
                        # Registered but still being spawned: the row exists before the
                        # terminal does. Orchestration 5 lost a healthy claude to this -
                        # declared dead 70 ms after register, while tmux was creating it.
                        # spawn() itself marks it dead if the terminal never appears.
                        continue
                    alive = await asyncio.get_running_loop().run_in_executor(self.io, self.tp.alive, term(ag))
                    if not alive:
                        await self.db(self.store.set_state, sess, "dead", "terminal gone")
                        await asyncio.get_running_loop().run_in_executor(self.io, self.harness, "reap")
                        await self._tell_operator(f"{sess} died (terminal gone); its leases went back to the queue",
                                                  f"died:{sess}:{ag['created']}")
                        continue
                    mark = self.tp.output_mark(term(ag))
                    if mark is not None and mark != self.marks.get(sess):
                        self.marks[sess] = mark
                        await self.db(self.store.touch_output, sess)
                    if ag["state"] == "starting" and time.time() - self.started.get(sess, 0) > 3:
                        await self.db(self.store.set_state, sess, "ready")
                    if ag["state"] == "blocked" and not self.bell.get(sess, {}).get("blocked_note"):
                        await self.db(self.store.set_state, sess, "ready")
                # PROTOCOL 5.3: team work with no live lead is reported, never left to rot.
                for w in await self.db(self.store.q, "SELECT id, target, created FROM work_items WHERE state='ready' "
                                       "AND target LIKE 'team:%'"):
                    repo, team = w["target"][5:].split("/", 1)
                    t = await self.db(self.store.team, repo, team)
                    leads = [m for m in (t or {}).get("members", [])
                             if (await self.db(self.store.agent, m) or {}).get("state") not in (None, "dead")
                             and (await self.db(self.store.agent, m))["role"] == (t or {}).get("lead_role")]
                    if not leads:
                        await self._tell_operator(f"work {w['id']} for {w['target']} has no live lead to take it",
                                                  f"nolead:{w['id']}")
            except Exception as e:
                log("live loop error", type(e).__name__, e)
            await asyncio.sleep(3)

    async def receipt_loop(self):
        """TM-213 / C15. Promote submitted deliveries to received when the CLI's own log
        shows the bell, and tell the operator once when a submitted bell has sat unseen
        longer than hold_alert_s - the grok pager-queue hold, made visible."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.io, self.receipts.prime)
        while not self.stop.is_set():
            try:
                for sess, cli, ref in await loop.run_in_executor(self.io, self.receipts.scan):
                    aw = self.awaiting.pop(sess, None)
                    if aw is None:
                        continue                  # a bell we did not send this run, or a quoted one
                    got = await self.db(self.store.mark_received, sess, aw["upto"],
                                        {"cli_receipt": ref, "cli": cli, "after_s": round(time.time() - aw["at"], 1)})
                    log("cli receipt", sess, cli, len(got), "delivery(ies)")
                await self.check_holds(time.time())
            except Exception as e:
                log("receipt loop error", type(e).__name__, e)
            await asyncio.sleep(3)

    async def check_holds(self, t_now):
        limit = float(self.cfg.get("hold_alert_s", 300))
        for sess, aw in list(self.awaiting.items()):
            pend = [p for p in await self.db(self.store.pending_for, sess) if p["message_id"] <= aw["upto"]]
            if not pend:
                self.awaiting.pop(sess, None)     # the agent read and acked: received, by definition
                continue
            if not aw["alerted"] and t_now - aw["at"] > limit:
                aw["alerted"] = True
                await self.db(self.store.event, "agent", sess, "cli_hold", "hub",
                              {"held_s": round(t_now - aw["at"]), "pending": len(pend)})
                await self._tell_operator(
                    f"{sess}: a doorbell was submitted {int(t_now - aw['at'])} s ago but its CLI log shows no user "
                    f"turn yet - the CLI is holding input (C15). {len(pend)} message(s) wait.",
                    f"hold:{sess}:{int(aw['at'])}")

    async def lease_loop(self):
        last_ck = time.time()
        # Back up once at startup, so a hub that never lives an hour still has one.
        last_bk = 0.0
        last_prune = time.time()
        bdir = os.path.join(HUBDIR, "backups")
        while not self.stop.is_set():
            try:
                back = await self.db(self.store.sweep_leases)
                for w in back:
                    log("lease expired", w)
                if time.time() - last_ck > 600:
                    await self.db(self.store.checkpoint)
                    last_ck = time.time()
                if time.time() - last_bk >= float(self.cfg["backup_every_s"]):
                    p = await self.db(self.store.backup_to, bdir, int(self.cfg["backup_keep"]), "hourly")
                    log("backup", p)
                    last_bk = time.time()
                if time.time() - last_prune >= float(self.cfg["prune_every_s"]):
                    n = await self.db(self.store.prune, self.cfg["retention_events_days"],
                                      self.cfg["retention_messages_days"])
                    log("pruned", n)
                    last_prune = time.time()
            except Exception as e:
                log("lease loop error", type(e).__name__, e)
            await asyncio.sleep(5)

    async def main(self):
        if os.path.exists(SOCK):
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(SOCK)
                probe.close()
                raise SystemExit(f"hub already running on {SOCK}")
            except (ConnectionRefusedError, FileNotFoundError):
                os.unlink(SOCK)
        old = os.umask(0o077)
        server = await asyncio.start_unix_server(self.handle_conn, path=SOCK)
        os.umask(old)
        tcp = None
        port = int(self.cfg.get("tcp_port", 0) or 0)
        if port:
            # Loopback only, token-authenticated (caller_of). For Windows-side tools,
            # which reach WSL's 127.0.0.1 through localhost forwarding and cannot use
            # the unix socket or process ancestry.
            tcp = await asyncio.start_server(lambda r, w: self.handle_conn(r, w, tcp=True), "127.0.0.1", port)
            log("tcp listening 127.0.0.1:%d" % port)
        with open(os.path.join(HUBDIR, "hub.pid"), "w") as f:
            f.write(str(os.getpid()))
        # agents alive from a previous hub run: recover their handles and boot clocks
        for ag in await self.db(self.store.agents, True):
            self.started[ag["session"]] = 0
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        log("hub up", SOCK, "db", self.store.path)
        loops = [self.bell_loop(), self.live_loop(), self.lease_loop(), self.receipt_loop()]
        if self.bridge:
            loops.append(self.bridge.run())
        loops.append(self.fed.run())
        tasks = [asyncio.create_task(c) for c in loops]
        async with server:
            await self.stop.wait()
        if tcp:
            tcp.close()
        for t in tasks:
            t.cancel()
        await self.db(self.store.checkpoint)
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        log("hub down")


def term(ag):
    """The tmux session an agent really lives in: its protocol name, or - for an agent
    adopted from before the protocol - the legacy name it was spawned under."""
    return ag.get("term_name") or ag["session"]


def write_secret(path, value):
    """Create a 0600 file holding a secret; never world- or group-readable, even briefly."""
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.replace(path + ".tmp", path)


def normalize_remote(url):
    u = url.strip()
    for pre in ("https://", "http://", "ssh://", "git://"):
        if u.startswith(pre):
            u = u[len(pre):]
    u = u.split("@", 1)[-1].replace(":", "/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.lower()


def welcome(session, repo, role, cwd, snap):
    return f"""Welcome, {session}. You are an agent in repo '{repo}' (checkout: {cwd}), role '{role}'.
The agentmux hub is how you receive messages and work. Run these in your shell:
  agentmux hub inbox --ack                 read and acknowledge your messages (do this whenever you see a [hub] line)
  agentmux hub claim                       take the next work item offered to you or your role
  agentmux hub work show <id>              show a work item and its children
  agentmux hub done <id> --result "..."    finish a claimed item  (also: fail / return / block <id> --result "why")
  agentmux hub post --to <address> --kind request|reply|note [--ref <id>] "text"
      addresses: agent:<session>   role:<repo>/<role>   team:<repo>/<team>   virtual:operator
  agentmux hub work add --to <address> --title "..." --body "..." [--parent <id>]
  agentmux hub whoami
Rules: acknowledge every message; claim work before doing it; finish with done/fail. Do not reply to this welcome.
If nothing is claimable after reading your inbox, stop and wait - a [hub] line will tell you when there is more.
{snap.get('instructions', '')}"""


if __name__ == "__main__":
    asyncio.run(Hub().main())
