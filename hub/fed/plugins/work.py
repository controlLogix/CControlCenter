"""work: federated role items across people (FEDERATION.md 9.3).

`work add --federate` publishes to am.work.<me>.<rid>.<role> on the AM_WORK work-queue
stream. Every hub that can serve (rid, role) pulls from ONE shared durable consumer per
publisher, `work_<from>_<rid>_<role>` - Competing Consumers - and only when it has an
idle agent for it, so exactly one hub gets each item and exactly one local agent claims
it. A hub pulls only from publishers it trusts at auto or flag (and itself): a hub that
would quarantine the item must not take it from a hub that would do it (assumption A19).
The finished item goes back to its origin as a `result` envelope.
"""
from __future__ import annotations

import json

from hub import names
from hub.fed import envelope, guard
from hub.fed.plugin import Param, Plugin, Verb
from hub.store import HubError, now

PENDING = "fed:pending"


class Work(Plugin):
    name = "work"
    handles = ("work", "result")

    def __init__(self):
        self.subs = {}

    def verbs(self):
        return {
            "add": Verb(self.v_add, "offer a role item to every hub in the circle that serves that repo and role", {
                "to": Param(required=True, help="role:<repo>/<role>"),
                "title": Param(required=True), "body": Param(positional=True),
                "task_key": Param(help="board card key (local TM-x or shared SH-x)"),
                "require": Param("array", help="required capabilities"),
                "priority": Param("integer")}),
            "list": Verb(self.v_list, "federated items: outgoing (waiting on a peer) and incoming (from peers)"),
        }

    # -- outbound --------------------------------------------------------------------------
    async def v_add(self, ctx, a, caller):
        req = {"capabilities": a["require"]} if a.get("require") else None
        return await self.add(ctx, caller, a["to"], a["title"], a.get("body"), a.get("task_key"), req,
                              int(a.get("priority") or 100))

    async def add(self, ctx, caller, to, title, body=None, task_key=None, requirements=None, priority=100):
        ad = names.parse_address(to)
        if ad.kind != "role" or ad.scope in ("*",) or ad.scope.startswith(("group:", "team:")):
            raise HubError("a federated item targets role:<repo>/<role>")
        repo, role = ad.scope, ad.name
        rid = ctx.policy.rid_of(repo)
        if rid is None:
            raise HubError(f"repo {repo!r} is not shared (agentmux hub fed share {repo})")
        created_by = ctx.hub.sender_of(caller)
        w = await ctx.db(ctx.store.work_create, created_by, repo, to, title, body, task_key, requirements, priority)
        sender = ctx.sender_of(caller)
        data = {"origin_id": w["id"], "title": title, "body": body, "task_key": task_key,
                "requirements": requirements, "priority": priority, "role": role,
                "sender": {k: v for k, v in sender.items() if k != "repo"}}
        env = envelope.make("work", ctx.me, ctx.node, rid, "*", data)

        def tx():
            with ctx.store.tx():
                ctx.store.db.execute("UPDATE work_items SET state='claimed', claimed_by=?, updated=?, fed_flags=? "
                                     "WHERE id=?", (PENDING, now(), json.dumps({"env": env["id"], "rid": rid,
                                                                                 "outgoing": True}), w["id"]))
                ctx.stage(env, envelope.subject("work", ctx.me, rid, role), repo, "*")
        try:
            await ctx.db(tx)
        except guard.Refused:
            await ctx.db(ctx.store.cancel, w["id"], "refused by the federation guard")
            raise
        return {**(await ctx.db(ctx.store.work, w["id"])), "federated": env["id"]}

    async def on_local_event(self, ctx, kind, w):
        if kind != "work_released" or not w or not w.get("origin_peer"):
            return
        if w["state"] not in ("done", "failed"):
            return
        flags = json.loads(w.get("fed_flags") or "{}")
        try:
            by = {k: v for k, v in ctx.sender_of(w.get("claimed_by") or "operator").items() if k != "repo"}
        except Exception:  # noqa: BLE001 - a non-agent holder is reported as the operator
            by = {"operator": True}
        data = {"origin_id": flags.get("origin_id"), "state": w["state"], "result": w.get("result"),
                "by": w.get("claimed_by"), "by_sender": by, "title": w.get("title"), "task_key": w.get("task_key")}
        env = envelope.make("result", ctx.me, ctx.node, flags.get("rid"), w["origin_peer"], data)
        await ctx.publish(env, envelope.subject("msg", ctx.me, w["origin_peer"]), None, w["origin_peer"])

    # -- inbound ---------------------------------------------------------------------------
    async def on_connect(self, ctx):
        self.subs = {}

    async def on_tick(self, ctx):
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
        import nats.errors
        shared = ctx.policy.shared()
        if not shared:
            return
        want = {}
        for a in await ctx.db(ctx.store.agents, True):
            if a["repo"] not in shared or a["state"] in ("dead", "starting", "blocked"):
                continue
            snap = json.loads(a["role_snapshot"])
            active = await ctx.db(ctx.store.q1, "SELECT count(*) n FROM work_items WHERE claimed_by=? AND "
                                  "state='claimed'", (a["session"],))
            free = max(0, int(snap.get("max_active", 1)) - active["n"])
            key = (shared[a["repo"]], a["role"], a["repo"])
            want[key] = want.get(key, 0) + free
        publishers = {ctx.me} | {p for p in ctx.peer_ids if ctx.policy.trust(p) in ("auto", "flag")}
        for (rid, role, repo), free in want.items():
            waiting = await ctx.db(ctx.store.q1, "SELECT count(*) n FROM work_items WHERE state='ready' AND target=?",
                                   (f"role:{repo}/{role}",))
            room = free - waiting["n"]
            for frm in sorted(publishers):
                if room <= 0:
                    break
                key = (frm, rid, role)
                if key not in self.subs:
                    self.subs[key] = await ctx.js.pull_subscribe(
                        f"am.work.{frm}.{rid}.{role}", durable=f"work_{frm}_{rid}_{role}", stream="AM_WORK",
                        config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, ack_wait=60,
                                              deliver_policy=DeliverPolicy.ALL, max_deliver=20))
                try:
                    msgs = await self.subs[key].fetch(min(room, 5), timeout=0.2)
                except (nats.errors.TimeoutError, TimeoutError):
                    continue
                for m in msgs:
                    if await ctx.receive(m.subject, m.data, m) in ("delivered", "local"):
                        room -= 1

    async def on_envelope(self, ctx, env, dec):
        if env["type"] == "result":
            return await self._on_result(ctx, env)
        d, frm = env["data"], env["from"]
        local = dec.local_repo or ctx.policy.local_of(env.get("rid") or "")
        if not local:
            return "not_shared"
        if frm == ctx.me:
            # Our own item, pulled by our own hub: fulfil it here.
            def reopen():
                with ctx.store.tx():
                    return ctx.store.db.execute("UPDATE work_items SET state='ready', claimed_by=NULL, updated=? "
                                                "WHERE id=? AND claimed_by=?", (now(), d["origin_id"], PENDING)).rowcount
            return "local" if await ctx.db(reopen) else "stale"
        dup = await ctx.db(ctx.store.q1, "SELECT id FROM work_items WHERE origin_peer=? AND "
                           "json_extract(fed_flags,'$.origin_id')=?", (frm, d["origin_id"]))
        if dup:
            return "duplicate"
        untrusted = dec.untrusted
        body = guard.wrap(d.get("body") or "", frm, dec.trust, untrusted) if d.get("body") else None
        sender = ctx.address_of(frm, d.get("sender") or {})
        w = await ctx.db(ctx.store.work_create, sender, local, f"role:{local}/{d['role']}", d["title"], body,
                         d.get("task_key"), d.get("requirements"), int(d.get("priority") or 100))
        flags = {"origin_id": d["origin_id"], "env": env["id"], "rid": env["rid"], "untrusted": untrusted,
                 "privileged_ok": bool(dec.privileged_ok), "approved": dec.approved}

        def mark():
            with ctx.store.tx():
                ctx.store.db.execute("UPDATE work_items SET origin_peer=?, fed_flags=? WHERE id=?",
                                     (frm, json.dumps(flags), w["id"]))
        await ctx.db(mark)
        return "delivered"

    async def _on_result(self, ctx, env):
        d = env["data"]
        w = await ctx.db(ctx.store.work, d.get("origin_id"))
        if not w or w.get("claimed_by") != PENDING:
            return "stale"
        state = d.get("state") if d.get("state") in ("done", "failed") else "failed"
        by = ctx.address_of(env["from"], d.get("by_sender") or {})

        def close():
            with ctx.store.tx():
                ctx.store.db.execute("UPDATE work_items SET state=?, result=?, claimed_by=?, updated=? WHERE id=?",
                                     (state, d.get("result"), by, now(), w["id"]))
            return ctx.store.work(w["id"])
        w2 = await ctx.db(close)
        await ctx.hub._notify_work_owner(w2, by)
        await ctx.local_event("fed_result", {**w2, "from_peer": env["from"]})
        return "delivered"

    async def on_revoke(self, ctx, peer):
        def cancel():
            with ctx.store.tx():
                return ctx.store.db.execute("UPDATE work_items SET state='cancelled', result='withdrawn by ' || ?, "
                                            "updated=? WHERE origin_peer=? AND state='ready'",
                                            (peer, now(), peer)).rowcount
        n = await ctx.db(cancel)
        ctx.log(f"fed: cancelled {n} unclaimed item(s) from {peer}")

    async def v_list(self, ctx, a, caller):
        return await ctx.db(self._rows, ctx)

    def _rows(self, ctx):
        return ctx.store.q("SELECT id, title, state, claimed_by, origin_peer, task_key, target, result, updated "
                           "FROM work_items WHERE origin_peer IS NOT NULL OR claimed_by=? OR claimed_by LIKE 'peer:%' "
                           "ORDER BY updated DESC LIMIT 50", (PENDING,))

    def panel(self, ctx):
        rows = self._rows(ctx)
        return {"title": "Federated work", "columns": ["id", "title", "state", "from / by", "task_key", "result"],
                "rows": [[r["id"], r["title"], r["state"],
                          (f"from {r['origin_peer']}" if r["origin_peer"] else (r["claimed_by"] or "")),
                          r["task_key"] or "", (r["result"] or "")[:80]] for r in rows]}


PLUGIN = Work()
