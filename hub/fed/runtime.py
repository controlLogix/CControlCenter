"""Federation runtime: one connection, the core consumers, the outbox, presence, the
kill switch, and the plugins (docs/FEDERATION.md).

Runs inside the hub's event loop next to the TM-218 bridge. Everything that touches
hub.db goes through hub.db() (the single db thread), so the runtime adds no locking.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import time

from hub import names
from hub.fed import config, conn, envelope, guard, ledger
from hub.fed.plugin import Param, Verb
from hub.fed.policy import Policy, normalize_remote
from hub.store import HubError, now

BUILTIN = ("messages", "work", "board", "knowledge", "code")


class Federation:
    def __init__(self, hub, hubdir, log):
        self.hub, self.hubdir, self.log = hub, hubdir, log
        self.node = hub.cfg.get("node", "local")
        self.cfg = config.load(hubdir)
        self.nc = self.js = None
        self.connected = False
        self.last_error = ""
        self.wake: asyncio.Event | None = None
        self.loop = None
        self.stats = {"published": 0, "received": 0, "delivered": 0, "dropped": 0, "quarantined": 0,
                      "duplicates": 0, "errors": 0}
        self.plugins = {}
        self.routes = {}
        self._load_plugins()
        self.verbs = self._core_verbs()
        for p in self.plugins.values():
            for vn, v in p.verbs().items():
                self.verbs[f"fed_{p.name}_{vn}"] = v
        hub.dbx.submit(self._init_db).result()
        self.policy = Policy(self.cfg, {})
        hub.dbx.submit(self._refresh_policy_sync).result()
        self._last_presence = 0.0
        self.peer_ids: set[str] = set(p for p in self.cfg.get("peers", {}) if p != "*")
        self.presence: dict[str, list] = {}         # peer -> its nodes' presence docs (last seen)

    # -- setup ---------------------------------------------------------------------------
    @property
    def fcfg(self):
        return self.cfg["federation"]

    @property
    def me(self):
        return self.fcfg.get("peer", "")

    @property
    def enabled(self):
        return bool(self.fcfg.get("enabled") and self.me and self.fcfg.get("url"))

    def _load_plugins(self):
        for name in self.fcfg.get("plugins", list(BUILTIN)):
            mod = importlib.import_module(f"hub.fed.plugins.{name}" if name in BUILTIN else name)
            p = mod.PLUGIN
            names.check_part(p.name, "plugin")
            self.plugins[p.name] = p
            for t in p.handles:
                self.routes[t] = p

    def _init_db(self):
        s = self.hub.store
        for p in self.plugins.values():
            for sql in p.tables:
                head = sql.split("(")[0]
                if f"p_{p.name}_" not in head:
                    raise HubError(f"plugin {p.name}: table must be named p_{p.name}_* ({head.strip()})")
                s.db.execute(sql)

    def _refresh_policy_sync(self):
        rows = self.hub.store.q("SELECT repo, alias FROM repo_aliases WHERE alias LIKE '%/%' ORDER BY rowid")
        remotes = {}
        for r in rows:
            remotes.setdefault(r["repo"], normalize_remote(r["alias"]))
        self.policy = Policy(self.cfg, remotes)
        return self.policy

    async def refresh_policy(self):
        return await self.db(self._refresh_policy_sync)

    def save_cfg(self):
        config.save(self.hubdir, self.cfg)

    # -- plumbing for plugins (the Facade they get as ctx) -----------------------------------
    @property
    def store(self):
        return self.hub.store

    async def db(self, fn, *a, **kw):
        return await self.hub.db(fn, *a, **kw)

    def kick(self):
        if self.loop and self.wake:
            self.loop.call_soon_threadsafe(self.wake.set)

    def stage(self, env, subject, local_repo=None, to_peer=None):
        """DB thread, INSIDE the caller's transaction: guard, then outbox + audit rows that
        commit (or roll back) with the caller's own state change."""
        plane = subject.split(".")[1]
        try:
            clean, kinds = guard.outbound(self.policy, env, local_repo, to_peer)
        except guard.Refused as e:
            e.audit = ("out", plane, to_peer, env.get("rid"), subject, env.get("id"), env)
            raise
        ledger.outbox_add(self.store, clean["id"], subject, clean)
        ledger.audit(self.store, "out", plane, to_peer, clean.get("rid"), subject, clean["id"], clean,
                     "redacted" if kinds else "staged", {"kinds": sorted(set(kinds))} if kinds else None)
        self.kick()
        return clean, kinds

    async def publish(self, env, subject, local_repo=None, to_peer=None):
        def run():
            with self.store.tx():
                return self.stage(env, subject, local_repo, to_peer)
        return await self.db(run)

    async def kv(self, bucket):
        if not self.connected:
            raise HubError("federation is not connected (agentmux hub fed status)")
        return await self.js.key_value(bucket)

    async def post_local(self, sender, target, kind, body, ref=None, idem=None, meta=None):
        try:
            return await self.db(self.store.post, sender, target, kind, body, ref, None, idem, meta=meta)
        except HubError as e:
            self.log("fed: local post failed", target, e)
            return None

    def sender_of(self, caller):
        """Who is speaking, as the wire describes it: rid/role/agent for a shared repo's
        agent, or the operator."""
        if caller in ("operator", "virtual:operator"):
            return {"operator": True}
        if caller == "unregistered":
            raise HubError("unregistered pane: spawn agents with `agentmux hub spawn`")
        sess = caller[6:] if caller.startswith("agent:") else caller
        repo, role, agent = names.split_session(sess)
        return {"repo": repo, "rid": self.policy.rid_of(repo), "role": role, "agent": agent}

    def resolve_repo(self, peer, name):
        """The rid for a repo segment in a peer: address. Accepts MY local name, a rid, or
        the PEER's own name for it (from presence) - an agent copying an address from the
        other side must not have to translate it (found in the live demo, 2026-10-07)."""
        rid = self.policy.rid_of(name)
        if rid:
            return rid
        if self.policy.local_of(name):
            return name
        for doc in self.presence.get(peer, []):
            for r in doc.get("repos", []):
                if r.get("repo") == name and self.policy.local_of(r.get("rid", "")):
                    return r["rid"]
        mine = ", ".join(self.policy.shared()) or "none"
        raise HubError(f"repo {name!r} is not shared with {peer} under that name (your shared repos: {mine}; "
                       f"you may also use {peer}'s own name for it, or its rid)")

    def address_of(self, frm, sender: dict) -> str:
        """A reply-able local address for a remote sender."""
        if not sender or sender.get("operator"):
            return f"peer:{frm}"
        repo = self.policy.local_of(sender.get("rid") or "") or sender.get("rid") or "_"
        return f"peer:{frm}/{repo}/{sender.get('role')}/{sender.get('agent')}"

    async def notify_operator(self, body, idem):
        if self.fcfg.get("primary", True):
            await self.post_local("virtual:hub", "virtual:operator", "note", body, idem=idem)

    # -- the loop --------------------------------------------------------------------------
    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.wake = asyncio.Event()
        for p in self.plugins.values():
            await p.start(self)
        backoff = 1
        while not self.hub.stop.is_set():
            killed = await self.db(ledger.state_get, self.store, "killed")
            if not self.enabled or killed:
                self.last_error = "killed" if killed else "disabled"
                await self._nap(2)
                continue
            try:
                self.nc = await asyncio.wait_for(conn.connect(
                    self.fcfg["url"], self.fcfg.get("creds"), self.fcfg.get("ca"), f"agentmux-{self.me}-{self.node}",
                    reconnect=True, error_cb=self._on_error, disconnected_cb=self._on_disc,
                    reconnected_cb=self._on_reconn), 20)
            except Exception as e:  # noqa: BLE001 - every failure is a retry with backoff
                self.last_error = f"connect: {type(e).__name__}: {e}"
                self.log("fed: cannot connect -", self.last_error, f"(retry in {backoff}s)")
                await self._nap(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 1
            self.js = self.nc.jetstream()
            self.connected, self.last_error = True, ""
            self.log("fed: connected", self.fcfg["url"], "as", self.me, "node", self.node)
            tasks = []
            try:
                tasks = await self._bind_core()
                for p in self.plugins.values():
                    await p.on_connect(self)
                while not self.hub.stop.is_set() and not self.nc.is_closed:
                    if await self.db(ledger.state_get, self.store, "killed"):
                        break
                    if self.nc.is_connected:
                        await self._drain_outbox()
                        await self._presence()
                        for p in self.plugins.values():
                            try:
                                await p.on_tick(self)
                            except Exception as e:  # noqa: BLE001
                                self.log(f"fed: {p.name} tick error", type(e).__name__, e)
                    for t in tasks:
                        if t.done() and t.exception():
                            raise t.exception()
                    await self._nap(0.5)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                self.log("fed: session error -", self.last_error)
            finally:
                for t in tasks:
                    t.cancel()
                self.connected = False
                await conn.close(self.nc)
                self.nc = self.js = None
            await self._nap(1)

    async def _nap(self, s):
        try:
            await asyncio.wait_for(self.wake.wait(), s)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    async def _on_error(self, e):
        self.last_error = f"{type(e).__name__}: {e}"
        self.log("fed: nats error -", self.last_error)

    async def _on_disc(self):
        self.log("fed: disconnected")

    async def _on_reconn(self):
        self.log("fed: reconnected")

    async def _bind_core(self):
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
        cc = dict(ack_policy=AckPolicy.EXPLICIT, ack_wait=60, deliver_policy=DeliverPolicy.ALL, max_deliver=20)
        msg = await self.js.pull_subscribe(f"am.msg.*.{self.me}", durable=f"msg_{self.me}_{self.node}",
                                           stream="AM_MSG", config=ConsumerConfig(**cc))
        share = await self.js.pull_subscribe("am.>", durable=f"share_{self.me}_{self.node}", stream="AM_SHARE",
                                             config=ConsumerConfig(**cc))
        await self.nc.subscribe("am.ctl.>", cb=self._on_ctl)
        return [asyncio.create_task(self.consume(msg, "AM_MSG")), asyncio.create_task(self.consume(share, "AM_SHARE"))]

    async def consume(self, psub, label, batch=20):
        import nats.errors
        while True:
            try:
                msgs = await psub.fetch(batch, timeout=1)
            except (nats.errors.TimeoutError, asyncio.TimeoutError):
                continue
            except (nats.errors.ConnectionClosedError, asyncio.CancelledError):
                return
            except Exception as e:  # noqa: BLE001 - e.g. mid-reconnect; the durable consumer keeps our place
                self.log(f"fed: {label} fetch error -", type(e).__name__, e)
                await asyncio.sleep(1)
                continue
            for m in msgs:
                await self.receive(m.subject, m.data, m)

    async def receive(self, subject, data, msg=None):
        """The inbound half of the guard pipeline, plus audit, quarantine and idempotency."""
        self.stats["received"] += 1
        plane = subject.split(".")[1] if subject.count(".") >= 2 else "?"
        try:
            env = json.loads(data)
        except ValueError:
            await self.db(self._audit_tx, "in", plane, None, None, subject, None, data, "dropped", {"why": "not json"})
            await _ack(msg)
            return "dropped"
        frm = subject.split(".")[2] if subject.count(".") >= 2 else None
        mid = str(env.get("id", "")) if isinstance(env, dict) else ""
        if mid and await self.db(ledger.seen, self.store, mid):
            self.stats["duplicates"] += 1
            await _ack(msg)
            return "duplicate"
        dec = guard.inbound(self.policy, subject, env)
        return await self.apply(subject, env, dec, msg, plane, frm)

    async def apply(self, subject, env, dec, msg=None, plane=None, frm=None):
        plane = plane or subject.split(".")[1]
        frm = frm or env.get("from")
        rid = env.get("rid") if isinstance(env, dict) else None
        if dec.action == "drop":
            self.stats["dropped"] += 1
            if dec.reason != "self":
                await self.db(self._audit_tx, "in", plane, frm, rid, subject, env.get("id"), env, "dropped",
                              {"why": dec.reason})
            await _ack(msg)
            return "dropped"
        if dec.action == "quarantine":
            def q():
                with self.store.tx():
                    qid = ledger.quarantine_add(self.store, env, subject, plane, frm, dec.reason)
                    ledger.audit(self.store, "in", plane, frm, rid, subject, env["id"], env, "quarantined",
                                 {"why": dec.reason, "quarantine": qid})
                    ledger.mark_seen(self.store, env["id"])
                return qid
            qid = await self.db(q)
            self.stats["quarantined"] += 1
            await _ack(msg)
            d = env.get("data") or {}
            await self.notify_operator(
                f"[fed] quarantined {env['type']} from {frm} ({dec.reason}): {(d.get('title') or d.get('body') or '')[:120]}"
                f"\n  agentmux hub fed approve {qid}    |    agentmux hub fed deny {qid}", f"fedq:{qid}")
            return "quarantined"
        plugin = self.routes.get(env["type"])
        if plugin is None:
            await self.db(self._audit_tx, "in", plane, frm, rid, subject, env["id"], env, "dropped",
                          {"why": f"no plugin handles {env['type']}"})
            await _ack(msg)
            return "dropped"
        try:
            outcome = await plugin.on_envelope(self, env, dec) or "delivered"
        except Exception as e:  # noqa: BLE001 - redelivered later; the ingest is idempotent
            self.stats["errors"] += 1
            self.log(f"fed: {plugin.name} failed on {env['id']}:", type(e).__name__, e)
            await self.db(self._audit_tx, "in", plane, frm, rid, subject, env["id"], env, "error", {"error": str(e)})
            if msg is not None:
                await msg.nak(delay=5)
            return "error"
        decision = outcome if outcome != "delivered" else ("flagged" if dec.untrusted else "delivered")

        def done():
            with self.store.tx():
                ledger.audit(self.store, "in", plane, frm, rid, subject, env["id"], env, decision,
                             {"trust": dec.trust, "approved": dec.approved} if dec.trust != "auto" or dec.approved else None)
                ledger.mark_seen(self.store, env["id"])
        await self.db(done)
        self.stats["delivered"] += 1
        await _ack(msg)
        return decision

    def _audit_tx(self, *a):
        with self.store.tx():
            ledger.audit(self.store, *a)

    async def _drain_outbox(self):
        rows = await self.db(ledger.outbox_pending, self.store)
        for r in rows:
            try:
                await self.js.publish(r["subject"], r["payload"].encode(), timeout=5,
                                      headers={"Nats-Msg-Id": r["msg_id"]})
            except Exception as e:  # noqa: BLE001 - stays in the outbox; retried next pass
                await self.db(ledger.outbox_failed, self.store, r["seq"], f"{type(e).__name__}: {e}")
                self.last_error = f"publish {r['subject']}: {type(e).__name__}: {e}"
                return
            await self.db(ledger.outbox_sent, self.store, r["seq"])
            self.stats["published"] += 1

    async def _presence(self, force=False):
        if not force and time.time() - self._last_presence < float(self.fcfg.get("presence_every_s", 20)):
            return
        self._last_presence = time.time()
        shared = self.policy.shared()
        agents = []
        for a in await self.db(self.store.agents, True):
            if a["repo"] in shared:
                agents.append({"repo": a["repo"], "rid": shared[a["repo"]], "role": a["role"], "agent": a["agent"],
                               "state": a["state"], "cli": a["cli"]})
        doc = {"peer": self.me, "node": self.node, "at": now(), "agents": agents,
               "repos": [{"repo": r, "rid": rid} for r, rid in shared.items()]}
        try:
            kv = await self.js.key_value("am_presence")
            await kv.put(f"{self.me}.{self.node}", json.dumps(doc).encode())
            try:
                keys = await kv.keys()
            except Exception:  # noqa: BLE001 - nats-py raises on an empty bucket
                keys = []
            online, presence = set(), {}
            for k in keys:
                online.add(k.split(".")[0])
                try:
                    presence.setdefault(k.split(".")[0], []).append(json.loads((await kv.get(k)).value))
                except Exception:  # noqa: BLE001 - expired between keys() and get()
                    pass
            self.presence = presence
            self.peer_ids = (online | {p for p in self.cfg.get("peers", {}) if p != "*"}) - {self.me}
        except Exception as e:  # noqa: BLE001
            self.last_error = f"presence: {type(e).__name__}: {e}"

    async def _on_ctl(self, m):
        try:
            env = json.loads(m.data)
            frm = m.subject.split(".")[2]
        except (ValueError, IndexError):
            return
        if frm == self.me or env.get("from") != frm or env.get("type") != "revoke":
            return
        self.log("fed: peer", frm, "revoked its shares")
        await self.db(self._audit_tx, "in", "ctl", frm, None, m.subject, env.get("id"), env, "revoke", None)
        for p in self.plugins.values():
            try:
                await p.on_revoke(self, frm)
            except Exception as e:  # noqa: BLE001
                self.log(f"fed: {p.name} on_revoke error", e)
        await self.notify_operator(f"[fed] peer {frm} pulled its kill switch: its unclaimed work was withdrawn",
                                   f"fedrevoke:{env.get('id')}")

    # -- events from the hub ---------------------------------------------------------------
    async def local_event(self, kind, data):
        for p in self.plugins.values():
            try:
                await p.on_local_event(self, kind, data)
            except HubError as e:
                self.log(f"fed: {p.name} {kind}:", e)
            except guard.Refused as e:
                await self._audit_refusal(e)
                self.log(f"fed: {p.name} {kind} refused:", e)
            except Exception as e:  # noqa: BLE001
                self.log(f"fed: {p.name} {kind} error", type(e).__name__, e)

    async def guarded(self, coro):
        """For hub verbs that call into a plugin directly (post to peer:, work add
        --federate): a guard refusal is audited and becomes the caller's error."""
        try:
            return await coro
        except guard.Refused as e:
            await self._audit_refusal(e)
            raise HubError(str(e)) from None

    async def _audit_refusal(self, e):
        a = getattr(e, "audit", None)
        if a:
            # a = (dir, plane, peer, rid, subject, msg_id, payload); the refused payload is
            # hashed and sized in the audit row, never stored.
            await self.db(self._audit_tx, *a, e.decision, {"reason": str(e), "kinds": sorted(set(e.kinds))})

    # -- verbs -----------------------------------------------------------------------------
    async def dispatch(self, verb, a, caller):
        v = self.verbs.get(verb)
        if v is None:
            raise HubError(f"unknown federation verb {verb!r} (agentmux hub fed help)")
        if v.operator_only and caller != "operator":
            raise HubError(f"{verb} is operator-only")
        for pn, p in v.params.items():
            if p.required and a.get(pn) in (None, "", []):
                raise HubError(f"{verb.removeprefix('fed_').replace('_', ' ')} needs --{pn}")
        try:
            return await v.fn(self, a, caller)
        except guard.Refused as e:
            await self._audit_refusal(e)
            raise HubError(str(e)) from None

    def _core_verbs(self):
        V, P = Verb, Param
        return {
            "fed_status": V(_v_status, "connection, identity, shares, trust, outbox and counters"),
            "fed_peers": V(_v_peers, "who is online in the circle, and which agents and repos they offer"),
            "fed_share": V(_v_share, "opt a local repo in (per-repo opt-in)", {
                "repo": P(required=True, positional=True, help="local repo name"),
                "peers": P("array", help="peer ids, or * for the whole circle (default *)"),
                "remote": P(help="normalized remote to match on, if the repo has no origin alias"),
                "board_prefix": P(help="shared board key prefix (default SH)")}, operator_only=True),
            "fed_unshare": V(_v_unshare, "opt a repo out", {"repo": P(required=True, positional=True)},
                             operator_only=True),
            "fed_trust": V(_v_trust, "set a peer's trust: auto | flag | approve | deny", {
                "peer": P(required=True, positional=True, help="peer id or *"),
                "level": P(required=True, help="auto | flag | approve | deny")}, operator_only=True),
            "fed_kill": V(_v_kill, "KILL SWITCH: disconnect now and stay disconnected; --revoke also withdraws "
                                   "unclaimed work and tells peers", {"revoke": P("boolean")}, operator_only=True),
            "fed_resume": V(_v_resume, "undo the kill switch", operator_only=True),
            "fed_quarantine": V(_v_quarantine, "list inbound items held for approval",
                                {"state": P(help="held (default) | approved | denied | all")}),
            "fed_approve": V(_v_approve, "release a quarantined item", {
                "id": P(required=True, positional=True),
                "privileged": P("boolean", help="also allow privileged tools for this remote work")},
                operator_only=True),
            "fed_deny": V(_v_deny, "discard a quarantined item", {"id": P(required=True, positional=True)},
                          operator_only=True),
            "fed_audit": V(_v_audit, "the cross-user audit log, newest first", {
                "limit": P("integer"), "peer": P(), "since": P("integer")}),
            "fed_gate": V(_v_gate, "does this agent hold remote-origin work? (privileged-tool hook)",
                          {"session": P(help="operator only: ask about another session")}),
            "fed_verbs": V(_v_verbs, "the verb registry (drives the CLI and the MCP tools)"),
            "fed_panel": V(_v_panel, "everything the dashboard's Federation view shows"),
        }


async def _ack(msg):
    if msg is not None:
        try:
            await msg.ack()
        except Exception:  # noqa: BLE001 - redelivery is absorbed by fed_seen
            pass


# -- core verb implementations ---------------------------------------------------------
async def _v_status(fed, a, caller):
    killed = await fed.db(ledger.state_get, fed.store, "killed")
    pol = await fed.refresh_policy()
    return {"enabled": fed.enabled, "peer": fed.me, "node": fed.node, "url": fed.fcfg.get("url") or None,
            "connected": fed.connected, "killed": killed, "last_error": fed.last_error or None,
            "shared": pol.shared(), "unmatched": pol.unmatched(),
            "trust": {p: t.get("trust") for p, t in fed.cfg.get("peers", {}).items()},
            "plugins": list(fed.plugins), "outbox": await fed.db(ledger.outbox_stats, fed.store),
            "stats": fed.stats}


async def _v_peers(fed, a, caller):
    if not fed.connected:
        raise HubError("not connected")
    kv = await fed.js.key_value("am_presence")
    out = []
    try:
        keys = await kv.keys()
    except Exception:  # noqa: BLE001 - nats-py raises when the bucket is empty
        keys = []
    for k in keys:
        try:
            e = await kv.get(k)
            d = json.loads(e.value)
        except Exception:  # noqa: BLE001
            continue
        d["trust"] = fed.policy.trust(d.get("peer", "")) if d.get("peer") != fed.me else "self"
        for r in d.get("repos", []):
            r["local"] = fed.policy.local_of(r["rid"])
        out.append(d)
    return sorted(out, key=lambda d: (d.get("peer") != fed.me, d.get("peer"), d.get("node")))


async def _v_share(fed, a, caller):
    repo = a["repo"]
    if not await fed.db(fed.store.q1, "SELECT 1 FROM repos WHERE repo=?", (repo,)):
        raise HubError(f"unknown repo {repo!r} (agentmux hub repo add {repo} <path>)")
    peers = a.get("peers") or ["*"]
    if isinstance(peers, str):
        peers = [p for p in peers.replace(",", " ").split() if p]
    t = {"peers": peers}
    if a.get("remote"):
        t["remote"] = normalize_remote(a["remote"])
    if a.get("board_prefix"):
        t["board_prefix"] = a["board_prefix"].upper()
    fed.cfg["repos"][repo] = t
    fed.save_cfg()
    pol = await fed.refresh_policy()
    if repo not in pol.shared():
        raise HubError(f"{repo} has no git remote to match on: pass --remote <url> (it is saved; fix and re-share)")
    await fed._presence(force=True) if fed.connected else None
    return {"repo": repo, "rid": pol.rid_of(repo), "peers": peers}


async def _v_unshare(fed, a, caller):
    fed.cfg["repos"].pop(a["repo"], None)
    fed.save_cfg()
    await fed.refresh_policy()
    return {"unshared": a["repo"]}


async def _v_trust(fed, a, caller):
    level = a["level"]
    if level not in config.TRUST_LEVELS:
        raise HubError(f"trust must be one of {', '.join(config.TRUST_LEVELS)}")
    peer = a["peer"]
    if peer != "*":
        names.check_part(peer, "peer")
    fed.cfg["peers"].setdefault(peer, {})["trust"] = level
    fed.save_cfg()
    await fed.refresh_policy()
    return {"peer": peer, "trust": level}


async def _v_kill(fed, a, caller):
    revoke = bool(a.get("revoke"))
    report = {"killed": True, "revoke": revoke, "at": now()}
    if revoke and fed.connected:
        report["withdrawn_work"] = await _withdraw_work(fed)
        try:
            kv = await fed.js.key_value("am_presence")
            await kv.delete(f"{fed.me}.{fed.node}")
        except Exception as e:  # noqa: BLE001
            report["presence_error"] = str(e)
        env = envelope.make("revoke", fed.me, fed.node, None, "*", {"reason": a.get("reason") or "kill switch"})
        await fed.nc.publish(f"am.ctl.{fed.me}", json.dumps(env).encode())
        await fed.nc.flush(timeout=3)
    if revoke:
        report["withdrawn_outbox"] = await fed.db(ledger.outbox_withdraw, fed.store)
    await fed.db(ledger.state_set, fed.store, "killed", report)
    await fed.db(fed._audit_tx, "local", "ctl", fed.me, None, None, None, report, "killed", report)
    if fed.nc is not None:
        await conn.close(fed.nc)
    fed.kick()
    return report


async def _withdraw_work(fed):
    """Delete this peer's not-yet-taken items from the AM_WORK work queue."""
    n = 0
    try:
        info = await fed.js.stream_info("AM_WORK")
        first, last = info.state.first_seq, info.state.last_seq
        for seq in range(first, min(last, first + 10000) + 1):
            try:
                m = await fed.js.get_msg("AM_WORK", seq)
            except Exception:  # noqa: BLE001 - already consumed or deleted
                continue
            if m.subject.startswith(f"am.work.{fed.me}."):
                await fed.js.delete_msg("AM_WORK", seq)
                n += 1
    except Exception as e:  # noqa: BLE001
        fed.log("fed: withdraw failed", e)
    return n


async def _v_resume(fed, a, caller):
    await fed.db(ledger.state_set, fed.store, "killed", None)
    await fed.db(fed._audit_tx, "local", "ctl", fed.me, None, None, None, {}, "resumed", None)
    fed.kick()
    return {"resumed": True}


async def _v_quarantine(fed, a, caller):
    st = a.get("state") or "held"
    return await fed.db(ledger.quarantine_list, fed.store, None if st == "all" else st)


async def _v_approve(fed, a, caller):
    q = await fed.db(ledger.quarantine_get, fed.store, a["id"])
    if not q or q["state"] != "held":
        raise HubError(f"no held quarantine item {a['id']}")
    env = q["envelope"]
    dec = guard.Decision("deliver", "approved by operator", fed.policy.trust(q["peer"]), untrusted=True,
                         local_repo=fed.policy.local_of(env.get("rid") or ""), approved=True,
                         privileged_ok=bool(a.get("privileged")))
    plugin = fed.routes.get(env["type"])
    if plugin is None:
        raise HubError(f"no plugin handles {env['type']}")
    out = await plugin.on_envelope(fed, env, dec) or "delivered"
    await fed.db(ledger.quarantine_decide, fed.store, a["id"], "approved", caller)
    await fed.db(fed._audit_tx, "in", q["plane"], q["peer"], env.get("rid"), q["subject"], env["id"], env,
                 "approved", {"quarantine": a["id"], "privileged": bool(a.get("privileged")), "outcome": out})
    return {"approved": a["id"], "outcome": out}


async def _v_deny(fed, a, caller):
    q = await fed.db(ledger.quarantine_get, fed.store, a["id"])
    if not q or not await fed.db(ledger.quarantine_decide, fed.store, a["id"], "denied", caller):
        raise HubError(f"no held quarantine item {a['id']}")
    await fed.db(fed._audit_tx, "in", q["plane"], q["peer"], q["envelope"].get("rid"), q["subject"],
                 q["envelope"]["id"], q["envelope"], "denied", {"quarantine": a["id"]})
    return {"denied": a["id"]}


async def _v_audit(fed, a, caller):
    rows = await fed.db(ledger.audit_tail, fed.store, int(a.get("limit") or 50), a.get("peer"), int(a.get("since") or 0))
    for r in rows:
        if r.get("detail"):
            r["detail"] = json.loads(r["detail"])
    return rows


async def _v_gate(fed, a, caller):
    who = a.get("session") if caller == "operator" and a.get("session") else caller
    rows = await fed.db(fed.store.q, "SELECT id, title, origin_peer, fed_flags FROM work_items WHERE claimed_by=? "
                        "AND state IN ('claimed','waiting_children') AND origin_peer IS NOT NULL", (who,))
    remote = []
    for r in rows:
        flags = json.loads(r["fed_flags"] or "{}")
        remote.append({"id": r["id"], "title": r["title"], "peer": r["origin_peer"],
                       "privileged_ok": bool(flags.get("privileged_ok"))})
    return {"session": who, "remote_work": remote,
            "privileged_allowed": all(r["privileged_ok"] for r in remote)}


async def _v_verbs(fed, a, caller):
    out = []
    for name, v in sorted(fed.verbs.items()):
        out.append({"verb": name, "help": v.help, "operator_only": v.operator_only,
                    "params": {k: {"type": p.type, "required": p.required, "help": p.help, "positional": p.positional}
                               for k, p in v.params.items()}})
    return out


async def _v_panel(fed, a, caller):
    st = await _v_status(fed, a, caller)
    try:
        peers = await _v_peers(fed, a, caller) if fed.connected else []
    except HubError:
        peers = []

    def sync():
        out = []
        for p in fed.plugins.values():
            try:
                pan = p.panel(fed)
            except Exception as e:  # noqa: BLE001
                pan = {"title": p.name, "error": str(e)}
            if pan:
                out.append({"plugin": p.name, **pan})
        return out
    panels = await fed.db(sync)
    return {"status": st, "peers": peers, "quarantine": await _v_quarantine(fed, {}, caller),
            "audit": await _v_audit(fed, {"limit": 40}, caller), "panels": panels}
