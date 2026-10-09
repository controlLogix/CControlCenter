"""code: share work in progress as git refs (FEDERATION.md 9.5) - a Claim Check.

The payload stays in git: `code share` pushes a commit to the repo's shared remote as
refs/agentmux/<peer>/<slug> and publishes only the pointer (ref, sha, base, files,
stat, log) to am.code.<me>.<rid>. `code fetch` brings the ref into the receiver's
checkout under the same name and verifies the sha before saying it worked.
"""
from __future__ import annotations

import os
import re
import subprocess

from hub.fed import envelope
from hub.fed.plugin import Param, Plugin, Verb
from hub.fed.policy import normalize_remote, rid_for_remote
from hub.store import HubError, now


def git(path, *args, timeout=60):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=timeout, env=env,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise HubError(f"git {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def slugify(s):
    return re.sub(r"[^a-z0-9_]+", "_", (s or "wip").lower()).strip("_")[:40] or "wip"


class Code(Plugin):
    name = "code"
    handles = ("code",)
    tables = [
        "CREATE TABLE IF NOT EXISTS p_code_shares (id TEXT PRIMARY KEY, rid TEXT NOT NULL, repo TEXT, "
        "from_peer TEXT NOT NULL, author TEXT, ref TEXT NOT NULL, sha TEXT NOT NULL, base TEXT, files TEXT, "
        "stat TEXT, log TEXT, note TEXT, untrusted INTEGER NOT NULL DEFAULT 0, fetched TEXT, at TEXT NOT NULL) STRICT",
    ]

    def verbs(self):
        P = Param
        return {
            "share": Verb(self.v_share, "push a commit to the shared remote as refs/agentmux/<you>/<slug> and "
                                        "tell the circle (optionally hand it to someone)", {
                "repo": P(help="local repo (default: yours)"), "ref": P(help="commit-ish (default HEAD)"),
                "note": P(positional=True, help="what it is and what you want done"),
                "to": P(help="peer:<peer>[/<repo>/<role>[/<agent>]] - also send a handoff message"),
                "slug": P(help="name for the ref (default: branch name)"),
                "path": P(help="checkout to push from (default: the caller's cwd)")}),
            "fetch": Verb(self.v_fetch, "fetch a shared ref into your checkout and verify its sha", {
                "id": P(required=True, positional=True), "path": P(help="checkout (default: the caller's cwd)")}),
            "list": Verb(self.v_list, "code shared with you", {"repo": P()}),
        }

    async def _io(self, ctx, fn, *a):
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(ctx.hub.io, fn, *a)

    async def _checkout(self, ctx, repo, path, rid):
        """The checkout to use, proven to belong to this rid by its own remote."""
        cands = [path] if path else []
        cands += [r["path"] for r in await ctx.db(ctx.store.q, "SELECT path FROM repo_paths WHERE repo=?", (repo,))]
        remote = ctx.fcfg.get("code_remote") or "origin"
        for p in cands:
            if not p or not os.path.isdir(p):
                continue
            try:
                top = await self._io(ctx, git, p, "rev-parse", "--show-toplevel")
                url = await self._io(ctx, git, top, "remote", "get-url", remote)
            except HubError:
                continue
            if rid_for_remote(url) == rid:
                return top, remote, url
        raise HubError(f"no checkout of {repo} whose '{remote}' remote matches the shared repo "
                       f"(pass --path, or set code_remote in federation.toml)")

    async def v_share(self, ctx, a, caller):
        s = ctx.sender_of(caller)
        repo = a.get("repo") or s.get("repo")
        if not repo:
            raise HubError("code share needs --repo")
        rid = ctx.policy.rid_of(repo)
        if not rid:
            raise HubError(f"repo {repo!r} is not shared (agentmux hub fed share {repo})")
        if a.get("to"):
            # Validate the handoff address BEFORE pushing and publishing: a bad address used
            # to leave one published share per retry (live demo, 2026-10-07).
            from hub.fed.plugins.messages import parse_peer_address
            tpeer, trepo, _, _ = parse_peer_address(a["to"])
            if trepo:
                ctx.resolve_repo(tpeer, trepo)
        top, remote, url = await self._checkout(ctx, repo, a.get("path") or a.get("cwd"), rid)
        ref = a.get("ref") or "HEAD"
        sha = await self._io(ctx, git, top, "rev-parse", "--verify", f"{ref}^{{commit}}")
        branch = await self._io(ctx, git, top, "rev-parse", "--abbrev-ref", ref) if ref == "HEAD" else ref
        slug = f"{slugify(a.get('slug') or branch)}_{sha[:8]}"
        dest = f"refs/agentmux/{ctx.me}/{slug}"
        await self._io(ctx, git, top, "push", "--no-verify", remote, f"+{sha}:{dest}")
        base = None
        for cand in (f"{remote}/HEAD", f"{remote}/main", f"{remote}/master"):
            try:
                base = await self._io(ctx, git, top, "merge-base", sha, cand)
                break
            except HubError:
                continue
        rng = f"{base}..{sha}" if base else f"{sha}~1..{sha}"
        files, stat, log = [], "", ""
        try:
            files = (await self._io(ctx, git, top, "diff", "--name-only", rng)).splitlines()[:200]
            stat = await self._io(ctx, git, top, "diff", "--shortstat", rng)
            log = "\n".join((await self._io(ctx, git, top, "log", "--oneline", rng)).splitlines()[:20])
        except HubError:
            pass
        author = "operator" if s.get("operator") else f"{s['role']}/{s['agent']}"
        data = {"ref": dest, "sha": sha, "base": base, "files": files, "stat": stat, "log": log,
                "note": a.get("note") or "", "slug": slug, "author": author, "remote": normalize_remote(url)}
        env = envelope.make("code", ctx.me, ctx.node, rid, "*", data)

        def tx():
            with ctx.store.tx():
                clean, _ = ctx.stage(env, envelope.subject("code", ctx.me, rid), repo, "*")
                self._store(ctx, clean, repo, False)
        await ctx.db(tx)
        out = {"id": env["id"], "ref": dest, "sha": sha, "files": len(files), "stat": stat}
        if a.get("to"):
            msgs = ctx.plugins["messages"]
            out["handoff"] = await msgs.send(ctx, caller, a["to"], "handoff",
                                             (a.get("note") or f"code {slug}") + f"\n{stat}", None, env["id"])
        return out

    def _store(self, ctx, env, repo, untrusted):
        d = env["data"]
        ctx.store.db.execute(
            "INSERT OR IGNORE INTO p_code_shares (id, rid, repo, from_peer, author, ref, sha, base, files, stat, log, "
            "note, untrusted, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (env["id"], env["rid"], repo, env["from"], d.get("author"), d["ref"], d["sha"], d.get("base"),
             "\n".join(d.get("files") or []), d.get("stat"), d.get("log"), d.get("note"), int(untrusted),
             env.get("at") or now()))

    async def on_envelope(self, ctx, env, dec):
        d = env["data"]
        if not re.fullmatch(r"[0-9a-f]{40}", d.get("sha", "")) or not str(d.get("ref", "")).startswith(
                f"refs/agentmux/{env['from']}/"):
            return "dropped"            # a peer may only point at its own namespace

        def tx():
            with ctx.store.tx():
                self._store(ctx, env, dec.local_repo, dec.untrusted)
        await ctx.db(tx)
        return "delivered"

    async def v_fetch(self, ctx, a, caller):
        r = await ctx.db(ctx.store.q1, "SELECT * FROM p_code_shares WHERE id=?", (a["id"],))
        if not r:
            raise HubError(f"no code share {a['id']} (agentmux hub fed code list)")
        repo = r["repo"] or ctx.policy.local_of(r["rid"])
        top, remote, _ = await self._checkout(ctx, repo, a.get("path") or a.get("cwd"), r["rid"])
        await self._io(ctx, git, top, "fetch", "--no-tags", remote, f"+{r['ref']}:{r['ref']}")
        got = await self._io(ctx, git, top, "rev-parse", "--verify", r["ref"])
        if got != r["sha"]:
            raise HubError(f"sha mismatch for {r['ref']}: announced {r['sha'][:12]}, fetched {got[:12]} - "
                           f"the ref moved; ask {r['from_peer']} to share again")

        def mark():
            with ctx.store.tx():
                ctx.store.db.execute("UPDATE p_code_shares SET fetched=? WHERE id=?", (now(), a["id"]))
        await ctx.db(mark)
        return {"ref": r["ref"], "sha": got, "checkout": top, "verified": True, "files": r["files"].split("\n"),
                "next": [f"git -C {top} diff {r['base'] or r['sha'] + '~1'}..{r['ref']}",
                         f"git -C {top} switch -c {r['ref'].split('/')[-1]} {r['ref']}"]}

    async def v_list(self, ctx, a, caller):
        return await ctx.db(ctx.store.q, "SELECT id, repo, from_peer, author, ref, substr(sha,1,12) sha, stat, note, "
                            "fetched, at FROM p_code_shares WHERE (? IS NULL OR repo=?) ORDER BY at DESC LIMIT 50",
                            (a.get("repo"), a.get("repo")))

    def panel(self, ctx):
        rows = ctx.store.q("SELECT id, repo, from_peer, author, ref, sha, stat, note, fetched, at FROM p_code_shares "
                           "ORDER BY at DESC LIMIT 20")
        return {"title": "Code", "columns": ["at", "from", "ref", "sha", "stat", "note", "fetched"],
                "rows": [[r["at"][:19], f"{r['from_peer']} {r['author'] or ''}", r["ref"], r["sha"][:10], r["stat"],
                          (r["note"] or "")[:60], "yes" if r["fetched"] else ""] for r in rows],
                "actions": [{"verb": "fed_code_fetch", "label": "fetch", "params": ["id"]}]}


PLUGIN = Code()
