"""work: federated role items across people (FEDERATION.md 9.3).

`work add --federate` publishes to am.work.<me>.<rid>.<role>.v3 on the AM_WORK work-queue
stream. Every hub that can serve (rid, role) pulls from ONE shared durable consumer per
publisher, `work3_<from>_<rid>_<role>` - Competing Consumers - and only when it has an
idle agent for it, so exactly one hub gets each item and exactly one local agent claims
it after the origin grants a durable reservation. Redelivery can reach another hub,
but that hub cannot execute without its own matching grant. A hub pulls only from
publishers it trusts at auto or flag (and itself): a hub that
would quarantine the item must not take it from a hub that would do it (assumption A19).
The finished item goes back to its origin as a `result` envelope.
"""
from __future__ import annotations

import hashlib
import json

from hub import names
from hub.fed import envelope, guard
from hub.fed.plugin import Param, Plugin, Verb
from hub.store import HubError, now, ulid

PENDING = "fed:pending"


def offer_digest(env):
    data = {k: v for k, v in env["data"].items() if k != "offer_digest"}
    record = {k: env.get(k) for k in ("v", "id", "from", "node", "rid", "to", "type")}
    return digest({**record, "data": data})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def result_digest(data):
    return digest({"state": data.get("state"), "result": data.get("result")})


def reference(flags):
    return {"origin_id": flags["origin_id"], "origin_node": flags["origin_node"], "offer_id": flags["env"],
            "offer_digest": flags["offer_digest"], "execution_id": flags["execution_id"]}


def valid_reference(flags, env):
    d = env["data"]
    return bool(flags.get("outgoing") and flags.get("protocol") == 3 and
                flags.get("env") == d.get("offer_id") and flags.get("rid") == env.get("rid") and
                flags.get("origin_node") == d.get("origin_node") and
                flags.get("offer_digest") == d.get("offer_digest"))


def matches_offer(flags, env):
    return bool(flags.get("outgoing") and flags.get("env") == env["id"] and flags.get("rid") == env["rid"] and
                flags.get("origin_node") == env["node"] and flags.get("offer_digest") == env["data"]["offer_digest"])


def valid_work_data(env):
    d = env["data"]
    keys = ("origin_id", "offer_digest") if env["type"] == "work" else (
        "origin_id", "origin_node", "offer_id", "offer_digest", "execution_id")
    if any(not isinstance(d.get(k), str) or not 1 <= len(d[k]) <= 128 for k in keys):
        return False
    if len(d["offer_digest"]) != 64 or any(c not in "0123456789abcdef" for c in d["offer_digest"]):
        return False
    if env["type"] != "work" and not envelope.TOKEN.fullmatch(d["origin_node"]):
        return False
    if env["type"] == "work":
        return isinstance(d.get("title"), str) and bool(d["title"].strip())
    if env["type"] == "work_grant":
        return (type(d.get("selected")) is bool and
                all(isinstance(d.get(k), str) and envelope.TOKEN.fullmatch(d[k])
                    for k in ("executor_peer", "executor_node")))
    if env["type"] == "result":
        return (d.get("state") in ("done", "failed") and
                (d.get("result") is None or isinstance(d["result"], str)) and
                isinstance(d.get("by_sender", {}), dict))
    return True


class Work(Plugin):
    name = "work"
    handles = ("work", "work_claim", "work_grant", "result")

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
        sender = ctx.sender_of(caller)

        def create():
            with ctx.store.tx():
                w = ctx.store.work_create(created_by, repo, to, title, body, task_key, requirements, priority)
                data = {"origin_id": w["id"], "title": title, "body": body, "task_key": task_key,
                        "requirements": requirements, "priority": priority, "role": role,
                        "sender": {k: v for k, v in sender.items() if k != "repo"}}
                env = envelope.make("work", ctx.me, ctx.node, rid, "*", data)
                # Bind the actual redacted offer, not different local-only content.
                env, _ = guard.outbound(ctx.policy, env, repo, "*")
                env["data"]["offer_digest"] = offer_digest(env)
                flags = {"env": env["id"], "rid": rid, "origin_node": ctx.node, "outgoing": True,
                         "offer_digest": env["data"]["offer_digest"], "role": role, "protocol": 3}
                ctx.store.db.execute("UPDATE work_items SET state='claimed', claimed_by=?, updated=?, fed_flags=? "
                                     "WHERE id=?", (PENDING, now(), json.dumps(flags), w["id"]))
                ctx.stage(env, envelope.subject("work", ctx.me, rid, role), repo, "*")
                return {**ctx.store.work(w["id"]), "federated": env["id"]}
        return await ctx.db(create)

    async def on_local_event(self, ctx, kind, w):
        if kind == "work_released" and w and w.get("origin_peer"):
            await ctx.db(self._stage_result, ctx, w["id"])

    def _stage_result(self, ctx, work_id):
        """Completion commits return intent in Store; this retryable step stages it."""
        with ctx.store.tx():
            w = ctx.store.work(work_id)
            if not w or w["state"] not in ("done", "failed") or not w.get("origin_peer"):
                return
            flags = json.loads(w.get("fed_flags") or "{}")
            if not flags.get("result_pending"):
                return
            if not flags.get("grant_id"):
                raise HubError("legacy federated completion needs operator reconciliation: no executor grant")
            try:
                by_sender = {k: v for k, v in ctx.sender_of(w.get("claimed_by") or "operator").items() if k != "repo"}
            except HubError:
                by_sender = {"operator": True}
            data = reference(flags)
            data.update(state=w["state"], result=w.get("result"), by=w.get("claimed_by"),
                        by_sender=by_sender, grant_id=flags["grant_id"])
            env = envelope.make("result", ctx.me, ctx.node, flags["rid"], w["origin_peer"], data)
            env["id"] = flags["result_id"]
            env, _ = guard.outbound(ctx.policy, env, None, w["origin_peer"])
            env["data"]["result_digest"] = result_digest(env["data"])
            ctx.stage(env, envelope.subject("msg", ctx.me, w["origin_peer"]), None, w["origin_peer"])
            flags["result_pending"] = False
            ctx.store.db.execute("UPDATE work_items SET fed_flags=? WHERE id=?", (json.dumps(flags), work_id))

    async def recover_results(self, ctx):
        rows = await ctx.db(ctx.store.q, "SELECT id FROM work_items WHERE origin_peer IS NOT NULL "
                            "AND state IN ('done','failed') AND json_extract(fed_flags,'$.result_pending')=1 "
                            "AND json_extract(fed_flags,'$.grant_id') IS NOT NULL")
        for row in rows:
            try:
                await ctx.db(self._stage_result, ctx, row["id"])
            except Exception as exc:
                # A refused result stays pending and cannot starve other completions.
                ctx.log("fed: result remains pending", row["id"], type(exc).__name__, str(exc))

    # -- inbound ---------------------------------------------------------------------------
    async def on_connect(self, ctx):
        self.subs = {}

    async def on_tick(self, ctx):
        from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
        import nats.errors
        await self.recover_results(ctx)
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
            waiting = await ctx.db(ctx.store.q1, "SELECT count(*) n FROM work_items WHERE (state='ready' OR "
                                   "(state='blocked' AND blocked_reason='awaiting origin grant')) AND target=?",
                                   (f"role:{repo}/{role}",))
            room = free - waiting["n"]
            for frm in sorted(publishers):
                if frm != ctx.me and not ctx.policy.may_receive(rid, frm):
                    continue
                if room <= 0:
                    break
                key = (frm, rid, role)
                if key not in self.subs:
                    self.subs[key] = await ctx.js.pull_subscribe(
                        envelope.subject("work", frm, rid, role), durable=f"work3_{frm}_{rid}_{role}", stream="AM_WORK",
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
        if env.get("v") != 3:
            raise HubError("federated work requires protocol v3; reconcile legacy in-flight work before upgrade")
        if not valid_work_data(env):
            return "invalid_work"
        if env["type"] == "result":
            return await self._on_result(ctx, env)
        if env["type"] == "work_claim":
            return await ctx.db(self._claim, ctx, env)
        if env["type"] == "work_grant":
            return await ctx.db(self._grant, ctx, env)
        d, frm = env["data"], env["from"]
        local = dec.local_repo or ctx.policy.local_of(env.get("rid") or "")
        if not local:
            return "not_shared"
        if not d.get("origin_id") or d.get("offer_digest") != offer_digest(env):
            raise HubError("offer has no valid immutable task identity")

        def ingest():
            with ctx.store.tx():
                # Reopen only the exact originating node's placeholder.
                if frm == ctx.me and env["node"] == ctx.node:
                    w = ctx.store.work(d["origin_id"])
                    flags = json.loads((w or {}).get("fed_flags") or "{}")
                    if not matches_offer(flags, env):
                        return "stale"
                    if flags.get("executor") or w["claimed_by"] != PENDING:
                        return "duplicate"
                    flags["executor"] = {"peer": ctx.me, "node": ctx.node, "execution_id": w["id"], "local": True}
                    ctx.store.db.execute("UPDATE work_items SET state='ready', claimed_by=NULL, updated=?, fed_flags=? "
                                         "WHERE id=?", (now(), json.dumps(flags), w["id"]))
                    return "local"
                dup = ctx.store.q1("SELECT id FROM work_items WHERE origin_peer=? AND "
                                  "json_extract(fed_flags,'$.origin_node')=? AND json_extract(fed_flags,'$.env')=?",
                                  (frm, env["node"], env["id"]))
                if dup:
                    return "duplicate"
                body = guard.wrap(d.get("body") or "", frm, dec.trust, dec.untrusted) if d.get("body") else None
                sender = ctx.address_of(frm, d.get("sender") or {})
                w = ctx.store.work_create(sender, local, f"role:{local}/{d['role']}", d["title"], body,
                                          d.get("task_key"), d.get("requirements"), int(d.get("priority") or 100))
                flags = {"origin_id": d["origin_id"], "origin_node": env["node"], "env": env["id"], "rid": env["rid"],
                         "offer_digest": d["offer_digest"], "execution_id": ulid(), "protocol": 3,
                         "untrusted": dec.untrusted, "privileged_ok": bool(dec.privileged_ok), "approved": dec.approved}
                ctx.store.db.execute("UPDATE work_items SET origin_peer=?, fed_flags=?, state='blocked', "
                                     "blocked_reason='awaiting origin grant' WHERE id=?", (frm, json.dumps(flags), w["id"]))
                claim = envelope.make("work_claim", ctx.me, ctx.node, env["rid"], frm, reference(flags))
                ctx.stage(claim, envelope.subject("msg", ctx.me, frm), local, frm)
                return "delivered"
        return await ctx.db(ingest)

    def _claim(self, ctx, env):
        d = env["data"]
        if d.get("origin_node") != ctx.node:
            return "other_node"
        with ctx.store.tx():
            w = ctx.store.work(d.get("origin_id")) if d.get("origin_id") else None
            flags = json.loads((w or {}).get("fed_flags") or "{}")
            if not valid_reference(flags, env) or not w:
                return "unbound_claim"
            if not d.get("execution_id"):
                return "unbound_claim"
            selected = flags.get("executor")
            contender = {"peer": env["from"], "node": env["node"], "execution_id": d["execution_id"]}
            if selected is None and w["claimed_by"] == PENDING:
                selected = {**contender, "grant_id": ulid()}
                flags["executor"] = selected
                ctx.store.db.execute("UPDATE work_items SET fed_flags=? WHERE id=?", (json.dumps(flags), w["id"]))
            selected = selected or {}
            accepted = bool(selected.get("grant_id") and w["claimed_by"] == PENDING and
                            all(selected.get(k) == v for k, v in contender.items()))
            grant = envelope.make("work_grant", ctx.me, ctx.node, env["rid"], env["from"],
                                  {**d, "executor_peer": env["from"], "executor_node": env["node"],
                                   "selected": accepted, "grant_id": selected.get("grant_id") if accepted else None})
            # One immutable grant per selected executor; retries cannot create a new permission.
            if accepted:
                grant["id"] = selected["grant_id"]
            ctx.stage(grant, envelope.subject("msg", ctx.me, env["from"]), w["repo"], env["from"])
            return "reserved" if accepted else "already_reserved"

    def _grant(self, ctx, env):
        d = env["data"]
        if d.get("executor_peer") != ctx.me or d.get("executor_node") != ctx.node:
            return "other_node"
        with ctx.store.tx():
            w = ctx.store.q1("SELECT * FROM work_items WHERE origin_peer=? AND json_extract(fed_flags,'$.env')=? "
                             "AND json_extract(fed_flags,'$.execution_id')=?",
                             (env["from"], d.get("offer_id"), d.get("execution_id")))
            if not w:
                return "unbound_grant"
            flags = json.loads(w["fed_flags"])
            if env["node"] != flags["origin_node"] or env["rid"] != flags["rid"] or reference(flags) != {k: d.get(k) for k in reference(flags)}:
                return "unbound_grant"
            if w["state"] != "blocked" or w["blocked_reason"] != "awaiting origin grant":
                return "duplicate"
            if d.get("selected") is not True:
                ctx.store.db.execute("UPDATE work_items SET state='cancelled', result='reserved by another executor', "
                                     "updated=? WHERE id=?", (now(), w["id"]))
                return "not_selected"
            if not d.get("grant_id") or env["id"] != d["grant_id"]:
                return "unbound_grant"
            flags["grant_id"] = d["grant_id"]
            ctx.store.db.execute("UPDATE work_items SET state='ready', blocked_reason=NULL, fed_flags=?, updated=? "
                                 "WHERE id=?", (json.dumps(flags), now(), w["id"]))
            return "delivered"

    async def _on_result(self, ctx, env):
        d = env["data"]
        if d.get("origin_node") != ctx.node:
            return "other_node"
        def close():
            with ctx.store.tx():
                w = ctx.store.work(d.get("origin_id")) if d.get("origin_id") else None
                flags = json.loads((w or {}).get("fed_flags") or "{}")
                selected = flags.get("executor") or {}
                if not w or not valid_reference(flags, env) or any(selected.get(k) != v for k, v in
                        {"peer": env["from"], "node": env["node"], "execution_id": d.get("execution_id"),
                         "grant_id": d.get("grant_id")}.items()) or not selected.get("grant_id"):
                    return "unbound_result", None
                if w["claimed_by"] != PENDING:
                    return "stale", None
                if d.get("state") not in ("done", "failed") or d.get("result_digest") != result_digest(d):
                    return "invalid_result", None
                by = ctx.address_of(env["from"], d.get("by_sender") or {})
                flags["accepted_result"] = {"envelope_id": env["id"], "digest": d["result_digest"], "at": now()}
                ctx.store.db.execute("UPDATE work_items SET state=?, result=?, claimed_by=?, updated=?, fed_flags=? WHERE id=?",
                                     (d["state"], d.get("result"), by, now(), json.dumps(flags), w["id"]))
                return "delivered", ctx.store.work(w["id"])
        outcome, w2 = await ctx.db(close)
        if w2:
            await ctx.hub._notify_work_owner(w2, w2["claimed_by"])
            await ctx.local_event("fed_result", {**w2, "from_peer": env["from"]})
        return outcome

    async def on_revoke(self, ctx, peer):
        def cancel():
            with ctx.store.tx():
                return ctx.store.db.execute("UPDATE work_items SET state='cancelled', result='withdrawn by ' || ?, "
                                            "updated=? WHERE origin_peer=? AND (state='ready' OR (state='blocked' AND blocked_reason='awaiting origin grant'))",
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
