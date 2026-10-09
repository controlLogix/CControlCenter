"""board: the shared central board for shared repos (FEDERATION.md 9.6, assumptions A9/A10/A17).

Cards live in the JetStream KV bucket am_board under <rid>.card.<KEY>; keys are minted
from <rid>.seq.<PREFIX> by compare-and-set, and every change is a CAS on the card's
revision (re-read, re-apply, retry). Every hub watches the bucket and mirrors the cards
of the repos it shares into p_board_cards, so reads are local and work offline; writes
need the connection.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request

from hub.fed import redact
from hub.fed.plugin import Param, Plugin, Verb
from hub.fed.plugins.messages import parse_peer_address
from hub.store import HubError, now

STATUSES = ("todo", "doing", "review", "done", "blocked")
BUCKET = "am_board"
RETRIES = 3


class Conflict(HubError):
    pass


class Board(Plugin):
    name = "board"
    tables = [
        "CREATE TABLE IF NOT EXISTS p_board_cards (rid TEXT NOT NULL, key TEXT NOT NULL, repo TEXT, "
        "card TEXT NOT NULL CHECK (json_valid(card)), rev INTEGER NOT NULL, status TEXT, assignee TEXT, "
        "updated_by TEXT, updated_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (rid, key)) STRICT",
    ]

    def __init__(self):
        self.watch_task = None

    def verbs(self):
        P = Param
        return {
            "add": Verb(self.v_add, "put a new card on the shared board of a shared repo", {
                "repo": P(required=True, help="local repo name"), "title": P(), "body": P(positional=True),
                "labels": P("array"), "assign": P(help="peer:<peer>[/<repo>/<role>[/<agent>]]"),
                "from": P(help="copy title and body from a local board card (TM-x)")}),
            "list": Verb(self.v_list, "shared cards (from the local mirror)", {"repo": P(), "status": P()}),
            "show": Verb(self.v_show, "one shared card with comments and history",
                         {"key": P(required=True, positional=True), "repo": P()}),
            "move": Verb(self.v_move, "change a card's status: todo | doing | review | done | blocked",
                         {"key": P(required=True, positional=True), "status": P(required=True), "repo": P()}),
            "assign": Verb(self.v_assign, "assign a card to a person, role or agent anywhere in the circle",
                           {"key": P(required=True, positional=True), "to": P(required=True), "repo": P()}),
            "comment": Verb(self.v_comment, "comment on a card",
                            {"key": P(required=True), "text": P(required=True, positional=True), "repo": P()}),
            "claim": Verb(self.v_claim, "assign the card to yourself and move it to doing, in one CAS",
                          {"key": P(required=True, positional=True), "repo": P()}),
        }

    # -- helpers ---------------------------------------------------------------------------
    def _me(self, ctx, caller):
        s = ctx.sender_of(caller)
        if s.get("operator"):
            return f"peer:{ctx.me}"
        return f"peer:{ctx.me}/{s['repo']}/{s['role']}/{s['agent']}"

    async def _resolve(self, ctx, key, repo=None):
        if repo:
            rid = ctx.policy.rid_of(repo)
            if not rid:
                raise HubError(f"repo {repo!r} is not shared")
            return rid, repo
        rows = await ctx.db(ctx.store.q, "SELECT rid, repo FROM p_board_cards WHERE key=? AND deleted=0", (key,))
        rows = [r for r in rows if ctx.policy.local_of(r["rid"])]
        if not rows:
            raise HubError(f"no shared card {key} (agentmux hub fed board list)")
        if len(rows) > 1:
            raise HubError(f"{key} exists in several shared repos; pass --repo")
        return rows[0]["rid"], ctx.policy.local_of(rows[0]["rid"])

    def _clean(self, ctx, card, rid):
        try:
            clean, kinds = redact.scrub(card)
        except redact.Blocked as e:
            from hub.fed import guard
            err = guard.Refused(str(e), "blocked", e.kinds)
            err.audit = ("out", "board", "*", rid, f"$KV.{BUCKET}", card.get("key"), card)
            raise err from None
        return clean, kinds

    async def _write(self, ctx, rid, key, mutate, caller, what):
        """CAS loop: read, mutate, update(last=rev); on a lost race re-read and re-apply."""
        import nats.js.errors as jse
        kv = await ctx.kv(BUCKET)
        k = f"{rid}.card.{key}"
        for attempt in range(RETRIES):
            try:
                e = await kv.get(k)
            except jse.KeyNotFoundError:
                raise HubError(f"no shared card {key}") from None
            card = json.loads(e.value)
            mutate(card)
            by = self._me(ctx, caller)
            card["updated_by"], card["updated_at"] = by, now()
            card.setdefault("history", []).append({"by": by, "at": card["updated_at"], "what": what})
            card["history"] = card["history"][-50:]
            clean, kinds = self._clean(ctx, card, rid)
            try:
                rev = await kv.update(k, json.dumps(clean).encode(), last=e.revision)
            except jse.KeyWrongLastSequenceError:
                await asyncio.sleep(0.05 * (attempt + 1))
                continue
            await self._audit_out(ctx, rid, k, clean, kinds, what)
            await ctx.db(self._mirror, ctx, rid, key, clean, rev)
            return {**clean, "rev": rev, "attempts": attempt + 1}
        raise Conflict(f"{key}: lost {RETRIES} compare-and-set races in a row; re-read and try again")

    async def _audit_out(self, ctx, rid, k, card, kinds, what):
        from hub.fed import ledger

        def tx():
            with ctx.store.tx():
                ledger.audit(ctx.store, "out", "board", "*", rid, f"$KV.{BUCKET}.{k}", card.get("key"), card,
                             "redacted" if kinds else "written", {"what": what, "kinds": sorted(set(kinds))})
        await ctx.db(tx)

    def _mirror(self, ctx, rid, key, card, rev, deleted=False):
        with ctx.store.tx():
            ctx.store.db.execute(
                "INSERT INTO p_board_cards (rid, key, repo, card, rev, status, assignee, updated_by, updated_at, deleted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (rid, key) DO UPDATE SET repo=excluded.repo, card=excluded.card, "
                "rev=excluded.rev, status=excluded.status, assignee=excluded.assignee, updated_by=excluded.updated_by, "
                "updated_at=excluded.updated_at, deleted=excluded.deleted WHERE excluded.rev >= p_board_cards.rev",
                (rid, key, ctx.policy.local_of(rid), json.dumps(card), rev, card.get("status"), card.get("assignee"),
                 card.get("updated_by"), card.get("updated_at"), int(deleted)))

    # -- verbs -----------------------------------------------------------------------------
    async def v_add(self, ctx, a, caller):
        import nats.js.errors as jse
        repo = a["repo"]
        rid = ctx.policy.rid_of(repo)
        if not rid:
            raise HubError(f"repo {repo!r} is not shared (agentmux hub fed share {repo})")
        title, body, link = a.get("title"), a.get("body") or "", None
        if a.get("from"):
            src = _local_card(a["from"])
            title = title or src.get("title")
            body = body or src.get("body") or src.get("description") or ""
            link = a["from"]
        if not title:
            raise HubError("board add needs --title (or --from TM-x)")
        if a.get("assign"):
            parse_peer_address(a["assign"])
        kv = await ctx.kv(BUCKET)
        prefix = ctx.policy.board_prefix(repo)
        seqk = f"{rid}.seq.{prefix}"
        for _ in range(10):                       # mint: CAS on the counter
            try:
                e = await kv.get(seqk)
                n = int(e.value) + 1
                await kv.update(seqk, str(n).encode(), last=e.revision)
                break
            except jse.KeyNotFoundError:
                try:
                    await kv.create(seqk, b"1")
                    n = 1
                    break
                except jse.KeyWrongLastSequenceError:
                    continue
            except jse.KeyWrongLastSequenceError:
                continue
        else:
            raise Conflict("could not mint a card key after 10 races")
        key = f"{prefix}-{n}"
        by = self._me(ctx, caller)
        card = {"key": key, "rid": rid, "title": title, "body": body, "status": "todo",
                "assignee": a.get("assign"), "labels": list(a.get("labels") or []), "comments": [],
                "history": [{"by": by, "at": now(), "what": "created" + (f" from {link}" if link else "")}],
                "created_by": by, "created_at": now(), "updated_by": by, "updated_at": now(),
                "links": {"local": link} if link else {}}
        clean, kinds = self._clean(ctx, card, rid)
        rev = await kv.create(f"{rid}.card.{key}", json.dumps(clean).encode())
        await self._audit_out(ctx, rid, f"{rid}.card.{key}", clean, kinds, "created")
        await ctx.db(self._mirror, ctx, rid, key, clean, rev)
        return {**clean, "rev": rev}

    async def v_list(self, ctx, a, caller):
        rows = await ctx.db(ctx.store.q, "SELECT rid, key, repo, card, rev FROM p_board_cards WHERE deleted=0 "
                            "ORDER BY updated_at DESC")
        out = []
        for r in rows:
            local = ctx.policy.local_of(r["rid"])
            if not local or (a.get("repo") and a["repo"] != local):
                continue
            c = json.loads(r["card"])
            if a.get("status") and c.get("status") != a["status"]:
                continue
            out.append({"key": c["key"], "repo": local, "status": c.get("status"), "title": c.get("title"),
                        "assignee": c.get("assignee"), "updated_by": c.get("updated_by"),
                        "comments": len(c.get("comments", [])), "rev": r["rev"], "withdrawn": c.get("withdrawn")})
        return out

    async def v_show(self, ctx, a, caller):
        rid, repo = await self._resolve(ctx, a["key"], a.get("repo"))
        r = await ctx.db(ctx.store.q1, "SELECT card, rev FROM p_board_cards WHERE rid=? AND key=?", (rid, a["key"]))
        return {**json.loads(r["card"]), "repo": repo, "rev": r["rev"]}

    async def v_move(self, ctx, a, caller):
        st = a["status"]
        if st not in STATUSES:
            raise HubError(f"status must be one of {', '.join(STATUSES)}")
        rid, _ = await self._resolve(ctx, a["key"], a.get("repo"))
        return await self._write(ctx, rid, a["key"], lambda c: c.__setitem__("status", st), caller, f"status -> {st}")

    async def v_assign(self, ctx, a, caller):
        parse_peer_address(a["to"])
        rid, _ = await self._resolve(ctx, a["key"], a.get("repo"))
        return await self._write(ctx, rid, a["key"], lambda c: c.__setitem__("assignee", a["to"]), caller,
                                 f"assigned -> {a['to']}")

    async def v_comment(self, ctx, a, caller):
        rid, _ = await self._resolve(ctx, a["key"], a.get("repo"))
        by = self._me(ctx, caller)
        return await self._write(ctx, rid, a["key"], lambda c: c.setdefault("comments", []).append(
            {"by": by, "at": now(), "text": a["text"]}), caller, "comment")

    async def v_claim(self, ctx, a, caller):
        rid, _ = await self._resolve(ctx, a["key"], a.get("repo"))
        me = self._me(ctx, caller)

        def m(c):
            if c.get("assignee") and c["assignee"] != me and c.get("status") == "doing":
                raise HubError(f"{a['key']} is already being done by {c['assignee']}")
            c["assignee"], c["status"] = me, "doing"
        return await self._write(ctx, rid, a["key"], m, caller, f"claimed by {me}")

    # -- the watcher -----------------------------------------------------------------------
    async def on_connect(self, ctx):
        if self.watch_task:
            self.watch_task.cancel()
        self.watch_task = asyncio.create_task(self._watch(ctx))

    async def _watch(self, ctx):
        import nats.errors
        kv = await ctx.js.key_value(BUCKET)
        w = await kv.watch("*.card.*")
        while True:
            try:
                e = await w.updates(timeout=5)
            except (nats.errors.TimeoutError, asyncio.TimeoutError):
                continue
            except (nats.errors.ConnectionClosedError, asyncio.CancelledError):
                return
            if e is None:
                continue
            try:
                await self._on_entry(ctx, e)
            except Exception as ex:  # noqa: BLE001 - one bad card must not stop the mirror
                ctx.log("fed: board mirror error", type(ex).__name__, ex)

    async def _on_entry(self, ctx, e):
        rid, _, key = e.key.split(".", 2)
        if not ctx.policy.local_of(rid):
            return
        if e.operation in ("DEL", "PURGE"):
            await ctx.db(ctx.store.db.execute, "UPDATE p_board_cards SET deleted=1 WHERE rid=? AND key=?", (rid, key))
            return
        card = json.loads(e.value)
        writer = (card.get("updated_by") or "peer:?").split(":", 1)[1].split("/")[0]
        if writer != ctx.me and ctx.policy.trust(writer) == "deny":
            return
        prev = await ctx.db(ctx.store.q1, "SELECT assignee, rev FROM p_board_cards WHERE rid=? AND key=?", (rid, key))
        if prev and prev["rev"] >= e.revision:
            return
        await ctx.db(self._mirror, ctx, rid, key, card, e.revision)
        if writer != ctx.me:
            from hub.fed import ledger

            def tx():
                with ctx.store.tx():
                    ledger.audit(ctx.store, "in", "board", writer, rid, f"$KV.{BUCKET}.{e.key}", key, card, "mirrored",
                                 {"rev": e.revision, "what": (card.get("history") or [{}])[-1].get("what")})
            await ctx.db(tx)
        a = card.get("assignee") or ""
        if a and a != (prev or {}).get("assignee") and writer != ctx.me and a.startswith(f"peer:{ctx.me}"):
            await self._notify_assignee(ctx, rid, card, writer)

    async def _notify_assignee(self, ctx, rid, card, writer):
        peer, _repo, role, agent = parse_peer_address(card["assignee"])
        local = ctx.policy.local_of(rid)      # the card's rid, in OUR naming - whoever wrote the address
        if agent:
            target = f"agent:{local}-{role}-{agent}"
        elif role:
            target = f"role:{local}/{role}"
        else:
            target = "virtual:operator"
        body = (f"[fed] shared card {card['key']} ({local}) was assigned to you by {writer}: {card.get('title')}\n"
                f"  agentmux hub fed board show {card['key']}    agentmux hub fed board claim {card['key']}")
        r = await ctx.post_local(f"peer:{writer}", target, "note", body, card["key"],
                                 f"board:{rid}:{card['key']}:{card.get('updated_at')}")
        if r is None and target != "virtual:operator":
            await ctx.post_local(f"peer:{writer}", "virtual:operator", "note", body, card["key"],
                                 f"board:{rid}:{card['key']}:{card.get('updated_at')}")

    async def on_revoke(self, ctx, peer):
        def mark():
            with ctx.store.tx():
                for r in ctx.store.q("SELECT rid, key, card FROM p_board_cards WHERE card LIKE ?", (f'%"peer:{peer}%',)):
                    c = json.loads(r["card"])
                    if (c.get("created_by") or "").startswith(f"peer:{peer}"):
                        c["withdrawn"] = f"{peer} revoked its shares"
                        ctx.store.db.execute("UPDATE p_board_cards SET card=? WHERE rid=? AND key=?",
                                             (json.dumps(c), r["rid"], r["key"]))
        await ctx.db(mark)

    def panel(self, ctx):
        rows = ctx.store.q("SELECT rid, card FROM p_board_cards WHERE deleted=0 ORDER BY updated_at DESC LIMIT 100")
        out = []
        for r in rows:
            local = ctx.policy.local_of(r["rid"])
            if not local:
                continue
            c = json.loads(r["card"])
            out.append([c["key"], local, c.get("status"), c.get("title"), c.get("assignee") or "",
                        c.get("updated_by") or "", len(c.get("comments", []))])
        return {"title": "Shared board", "columns": ["key", "repo", "status", "title", "assignee", "updated by",
                                                      "comments"], "rows": out, "group_by": 2,
                "actions": [{"verb": "fed_board_move", "label": "move", "params": ["key", "status"]}]}


def _local_card(key):
    url = os.environ.get("AGENTMUX_DASHBOARD", "http://127.0.0.1:8787")
    try:
        with urllib.request.urlopen(f"{url}/api/board/entity?id={key}", timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        raise HubError(f"cannot read local card {key} from the dashboard at {url} ({e})") from None


PLUGIN = Board()
