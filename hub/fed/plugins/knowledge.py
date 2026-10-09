"""knowledge: a shared stream of findings, searchable offline (FEDERATION.md 9.4, assumption A11).

Explicit: `fed know share`. Auto-capture (capture = true): an item released done with
a result, a handoff, and a federated result coming home. Every hub indexes the AM_SHARE
stream for the repos it shares into p_knowledge_items + FTS5, and rings the repo's live
agents with a one-line note (never the body) when a peer's finding arrives.
"""
from __future__ import annotations

import json

from hub.fed import envelope
from hub.fed.plugin import Param, Plugin, Verb
from hub.store import HubError, now


class Knowledge(Plugin):
    name = "knowledge"
    handles = ("knowledge",)
    tables = [
        "CREATE TABLE IF NOT EXISTS p_knowledge_items (id TEXT PRIMARY KEY, rid TEXT NOT NULL, repo TEXT, "
        "from_peer TEXT NOT NULL, author TEXT, title TEXT NOT NULL, body TEXT NOT NULL, tags TEXT, ref TEXT, "
        "source TEXT NOT NULL DEFAULT 'explicit', trust TEXT, untrusted INTEGER NOT NULL DEFAULT 0, "
        "withdrawn TEXT, at TEXT NOT NULL) STRICT",
        "CREATE VIRTUAL TABLE IF NOT EXISTS p_knowledge_fts USING fts5(title, body, tags, "
        "content='p_knowledge_items', content_rowid='rowid')",
        "CREATE TRIGGER IF NOT EXISTS p_knowledge_ai AFTER INSERT ON p_knowledge_items BEGIN "
        "INSERT INTO p_knowledge_fts(rowid, title, body, tags) VALUES (new.rowid, new.title, new.body, new.tags); END",
    ]

    def verbs(self):
        P = Param
        return {
            "share": Verb(self.v_share, "publish a finding to everyone the repo is shared with", {
                "repo": P(help="local repo (default: yours)"), "title": P(required=True),
                "body": P(required=True, positional=True), "tags": P("array"), "ref": P()}),
            "search": Verb(self.v_search, "full-text search of every finding shared with you (works offline)", {
                "query": P(required=True, positional=True), "repo": P(), "limit": P("integer")}),
            "recent": Verb(self.v_recent, "newest findings", {"repo": P(), "limit": P("integer")}),
            "show": Verb(self.v_show, "one finding", {"id": P(required=True, positional=True)}),
        }

    async def v_share(self, ctx, a, caller):
        repo = a.get("repo") or ctx.sender_of(caller).get("repo")
        if not repo:
            raise HubError("know share needs --repo")
        tags = a.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        return await self.share(ctx, caller, repo, a["title"], a["body"], tags, a.get("ref"), "explicit")

    async def share(self, ctx, caller, repo, title, body, tags=(), ref=None, source="explicit"):
        rid = ctx.policy.rid_of(repo)
        if not rid:
            raise HubError(f"repo {repo!r} is not shared (agentmux hub fed share {repo})")
        s = ctx.sender_of(caller)
        author = "operator" if s.get("operator") else f"{s['role']}/{s['agent']}"
        env = envelope.make("knowledge", ctx.me, ctx.node, rid, "*",
                            {"title": title, "body": body, "tags": list(tags), "ref": ref, "author": author,
                             "source": source})

        def tx():
            with ctx.store.tx():
                clean, kinds = ctx.stage(env, envelope.subject("know", ctx.me, rid), repo, "*")
                self._index(ctx, clean, repo, "self", False)
                return clean, kinds
        clean, kinds = await ctx.db(tx)
        return {"id": env["id"], "repo": repo, "title": clean["data"]["title"], "redacted": sorted(set(kinds))}

    def _index(self, ctx, env, repo, trust, untrusted):
        d = env["data"]
        ctx.store.db.execute(
            "INSERT OR IGNORE INTO p_knowledge_items (id, rid, repo, from_peer, author, title, body, tags, ref, source, "
            "trust, untrusted, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (env["id"], env["rid"], repo, env["from"], d.get("author"), d.get("title") or "(untitled)",
             d.get("body") or "", " ".join(d.get("tags") or []), d.get("ref"), d.get("source") or "explicit",
             trust, int(untrusted), env.get("at") or now()))

    async def on_envelope(self, ctx, env, dec):
        repo = dec.local_repo

        def tx():
            with ctx.store.tx():
                self._index(ctx, env, repo, dec.trust, dec.untrusted)
        await ctx.db(tx)
        if ctx.fcfg.get("notify_findings", True) and repo:
            d = env["data"]
            note = (f"[fed] finding from {env['from']} on {repo}: {(d.get('title') or '')[:100]}"
                    f"{' (untrusted data)' if dec.untrusted else ''}\n  agentmux hub fed know show {env['id']}")
            for ag in await ctx.db(ctx.store.agents, True):
                if ag["repo"] == repo:
                    await ctx.post_local(f"peer:{env['from']}", f"agent:{ag['session']}", "finding", note, d.get("ref"),
                                         f"know:{env['id']}:{ag['session']}")
        return "delivered"

    async def on_local_event(self, ctx, kind, data):
        if not ctx.fcfg.get("capture", True):
            return
        if kind == "work_released" and data and data.get("state") == "done" and data.get("result"):
            repo = data.get("repo")
            if not ctx.policy.rid_of(repo or ""):
                return
            caller = data.get("claimed_by") or "operator"
            if caller.startswith(("fed:", "peer:", "nats:")):
                return
            await self.share(ctx, caller, repo, f"done: {data['title']}", data["result"],
                             ["auto", "work"], data.get("task_key") or data["id"], "auto:work")
        elif kind == "handoff_sent" and data.get("repo"):
            await self.share(ctx, data["by"], data["repo"], f"handoff to {data['to']}", data["body"],
                             ["auto", "handoff"], data.get("ref"), "auto:handoff")
        elif kind == "fed_result" and data and data.get("result"):
            repo = data.get("repo")
            if ctx.policy.rid_of(repo or ""):
                await self.share(ctx, "operator", repo, f"result from {data['from_peer']}: {data['title']}",
                                 data["result"], ["auto", "result"], data.get("task_key") or data["id"], "auto:result")

    async def v_search(self, ctx, a, caller):
        q = a["query"]
        fts = " ".join(f'"{w}"' for w in q.replace('"', " ").split() if w)
        if not fts:
            raise HubError("empty query")
        rows = await ctx.db(ctx.store.q,
                            "SELECT k.id, k.repo, k.from_peer, k.author, k.title, snippet(p_knowledge_fts, 1, '[', ']', "
                            "' … ', 16) AS snippet, k.tags, k.ref, k.at, k.untrusted, k.withdrawn "
                            "FROM p_knowledge_fts JOIN p_knowledge_items k ON k.rowid = p_knowledge_fts.rowid "
                            "WHERE p_knowledge_fts MATCH ? AND (? IS NULL OR k.repo = ?) ORDER BY rank LIMIT ?",
                            (fts, a.get("repo"), a.get("repo"), int(a.get("limit") or 10)))
        return rows

    async def v_recent(self, ctx, a, caller):
        return await ctx.db(ctx.store.q, "SELECT id, repo, from_peer, author, title, source, tags, ref, at, untrusted, "
                            "withdrawn FROM p_knowledge_items WHERE (? IS NULL OR repo=?) ORDER BY at DESC LIMIT ?",
                            (a.get("repo"), a.get("repo"), int(a.get("limit") or 20)))

    async def v_show(self, ctx, a, caller):
        r = await ctx.db(ctx.store.q1, "SELECT * FROM p_knowledge_items WHERE id=?", (a["id"],))
        if not r:
            raise HubError(f"no finding {a['id']}")
        return r

    async def on_revoke(self, ctx, peer):
        def tx():
            with ctx.store.tx():
                ctx.store.db.execute("UPDATE p_knowledge_items SET withdrawn=? WHERE from_peer=? AND withdrawn IS NULL",
                                     (f"{peer} revoked its shares {now()}", peer))
        await ctx.db(tx)

    def panel(self, ctx):
        rows = ctx.store.q("SELECT id, repo, from_peer, author, title, source, at, untrusted, withdrawn "
                           "FROM p_knowledge_items ORDER BY at DESC LIMIT 30")
        return {"title": "Knowledge", "columns": ["at", "repo", "from", "title", "source", "flags"],
                "rows": [[r["at"][:19], r["repo"], f"{r['from_peer']} {r['author'] or ''}", r["title"], r["source"],
                          ("untrusted " if r["untrusted"] else "") + ("withdrawn" if r["withdrawn"] else "")]
                         for r in rows]}


PLUGIN = Knowledge()
