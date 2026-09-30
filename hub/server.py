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
import json
import os
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
                  "operator": "virtual:operator"}


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def load_toml(p):
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def ancestors(pid):
    out, seen = [], set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        out.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
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
        self._seed_roles()

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
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, _gid = struct.unpack("3i", creds)
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
    async def handle_conn(self, reader, writer):
        sock = writer.get_extra_info("socket")
        try:
            raw = await asyncio.wait_for(reader.readline(), 30)
            req = json.loads(raw or b"{}")
            pid, uid = self.peer(sock)
            if uid != os.getuid():
                raise HubError("wrong uid")
            session, in_pane = await self.db(self.identify, pid)
            caller = session
            if req.get("as"):
                if in_pane:
                    raise HubError("--as is only for the operator, not from inside an agent pane (R-ID-1)")
                caller = req["as"]
            elif not session:
                if in_pane:
                    caller = "unregistered"
                else:
                    caller = "operator"
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
        if verb == "ping":
            return {"pong": now(), "caller": caller}
        if verb == "whoami":
            ag = await self.db(s.agent, caller) if caller not in ("operator", "unregistered") else None
            return {"caller": caller, "agent": ag,
                    "eligible": await self.db(s.eligible_targets, caller) if ag else []}
        if verb == "status":
            return await self.db(s.status)
        if verb == "events":
            return await self.db(s.events, int(a.get("since", 0)), int(a.get("limit", 200)), a.get("entity"))
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
            return 
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
            sess = a["session"]
            await asyncio.get_running_loop().run_in_executor(self.io, self.tp.kill, sess)
            await self.db(s.set_state, sess, "dead", "killed by operator")
            await self.db(s.event, "agent", sess, "kill", "operator", {"reason": a.get("reason", "operator")})
            return {"killed": sess}
        if verb == "agents":
            return await self.db(s.agents, bool(a.get("live")))
        if verb == "resolve":
            return {"address": a["address"], "recipients": await self.db(s.recipients, a["address"])}
        if verb == "post":
            sender = self.sender_of(caller)
            body = a.get("body", "")
            body_ref = None
            if len(body.encode()) > int(self.cfg.get("inline_max", 4096)):
                body_ref = self._write_brief(a["to"], body)
            r = await self.db(s.post, sender, a["to"], a.get("kind", "note"), body, a.get("ref"), a.get("work_id"),
                              a.get("idem_key"), body_ref)
            return 
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
        if verb == "work_add":
            sender = self.sender_of(caller)
            repo = a.get("repo") or self._repo_of_target(a["to"], caller)
            return await self.db(s.work_create, sender, repo, a["to"], a["title"], a.get("body"), a.get("task_key"),
                                 a.get("requirements"), int(a.get("priority", 100)), a.get("parent"),
                                 int(a.get("max_attempts", 3)))
        if verb == "claim":
            me = self.need_agent(caller)
            return await self.db(s.claim, me, a.get("lease_s"), a.get("work_id"))
        if verb == "heartbeat":
            return {"renewed": await self.db(s.heartbeat, self.need_agent(caller), a.get("lease_s"))}
        if verb == "release":
            me = self.need_agent(caller)
            w = await self.db(s.release, me, a["work_id"], a["outcome"], a.get("result"))
            await self._notify_work_owner(w, me)
            return w
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
        session = await self.db(self.store.register, repo, role, agent, cli, snap)
        adir = os.path.join(ROOT, "repos", repo, "agents", f"{role}-{agent}")
        for sub in ("run", "logs", "briefs", "cli"):
            os.makedirs(os.path.join(adir, sub), exist_ok=True)
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
                self.io, lambda: deliver.deliver_line(self.tp, prof, sess, ag["handle"], text,
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
                    alive = await asyncio.get_running_loop().run_in_executor(self.io, self.tp.alive, sess)
                    if not alive:
                        await self.db(self.store.set_state, sess, "dead", "terminal gone")
                        await self._tell_operator(f"{sess} died (terminal gone); its leases went back to the queue",
                                                  f"died:{sess}:{ag['created']}")
                        continue
                    mark = self.tp.output_mark(sess)
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

    async def lease_loop(self):
        last_ck = time.time()
        while not self.stop.is_set():
            try:
                back = await self.db(self.store.sweep_leases)
                for w in back:
                    log("lease expired", w)
                if time.time() - last_ck > 600:
                    await self.db(self.store.checkpoint)
                    last_ck = time.time()
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
        with open(os.path.join(HUBDIR, "hub.pid"), "w") as f:
            f.write(str(os.getpid()))
        # agents alive from a previous hub run: recover their handles and boot clocks
        for ag in await self.db(self.store.agents, True):
            self.started[ag["session"]] = 0
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        log("hub up", SOCK, "db", self.store.path)
        tasks = [asyncio.create_task(c) for c in (self.bell_loop(), self.live_loop(), self.lease_loop())]
        async with server:
            await self.stop.wait()
        for t in tasks:
            t.cancel()
        await self.db(self.store.checkpoint)
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        log("hub down")


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
