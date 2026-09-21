#!/usr/bin/env python3
"""agentmux task CLI - the scripted half of the Atlassian integration.

MCP serves the agents (they call Jira from inside a conversation). This serves
the SCRIPTS: agentmux.sh and the dashboard reaper cannot reach an MCP server, so
create-on-spawn, transition-on-exit and Confluence publishing go through here.

    task.py whoami
    task.py create  --summary "Fix the thing" [--desc TEXT] [--label a --label b]
    task.py comment ABC-123 --text "..."         | --from-log <agent>
    task.py done    ABC-123 [--from-log <agent>] [--transition "Done"]
    task.py report  <agent> [--title "..."]      -> Confluence page
    task.py transitions ABC-123                  -> what this issue can move to

Global: --dry-run prints the request instead of sending it. Exit 0 on success,
1 on a handled error, 2 on bad usage. Stdout carries the issue key or page URL so
a shell caller can capture it; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import html
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import atlassian as atl  # noqa: E402

LOG_DIR = pathlib.Path.home() / ".agentmux" / "logs"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")

# Matches ANSI CSI/OSC escapes. Agent logs are raw terminal output; Jira and
# Confluence must never receive escape bytes.
ANSI_RE = re.compile(r"\x1b\[[0-9;:?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Za-z0-9]|\x1b[=>]")


def err(msg: str) -> None:
    print(f"task.py: {msg}", file=sys.stderr)


def read_agent_log(agent: str, max_bytes: int = 8000) -> str:
    """Tail of an agent's pane log, ANSI-stripped and CR-normalised."""
    if not NAME_RE.match(agent):
        raise atl.AtlassianError(f"invalid agent name: {agent!r}")
    path = LOG_DIR / f"{agent}.log"
    resolved = path.resolve()
    if resolved.parent != LOG_DIR.resolve():
        raise atl.AtlassianError("log path escapes the log directory")
    if not resolved.is_file():
        raise atl.AtlassianError(f"no log for agent {agent!r}")
    # Same hardening as the dashboard: refuse a hardlinked log, which could point
    # at a credential file.
    if resolved.stat().st_nlink > 1:
        raise atl.AtlassianError("log has st_nlink > 1; refusing to read a hardlink")
    with open(resolved, "rb") as fh:
        size = resolved.stat().st_size
        if size > max_bytes:
            fh.seek(size - max_bytes)
        raw = fh.read()
    text = ANSI_RE.sub("", raw.decode("utf-8", "replace")).replace("\r", "")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def pick_transition(cfg, key, wanted: str | None):
    """Resolve a transition id. Jira transitions are per-project and per-workflow,
    so a hardcoded id would break on any other project."""
    data = atl.jira_transitions(cfg, key)
    options = data.get("transitions") or []
    if not options:
        raise atl.AtlassianError(f"{key} has no available transitions")
    pattern = wanted or cfg.get("done_transition") or r"done|closed|complete|resolve"
    for t in options:
        if re.search(pattern, t.get("name", ""), re.I):
            return t["id"], t["name"]
    names = ", ".join(t.get("name", "?") for t in options)
    raise atl.AtlassianError(
        f"no transition on {key} matched /{pattern}/i. Available: {names}\n"
        f'Set "done_transition" in ~/.agentmux/atlassian.json to one of those.'
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="task.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the request instead of sending it")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami")

    c = sub.add_parser("create")
    c.add_argument("--summary", required=True)
    c.add_argument("--desc", default="")
    c.add_argument("--label", action="append", default=[])
    c.add_argument("--type", default="Task")

    cm = sub.add_parser("comment")
    cm.add_argument("key")
    g = cm.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--from-log", metavar="AGENT")

    d = sub.add_parser("done")
    d.add_argument("key")
    d.add_argument("--from-log", metavar="AGENT")
    d.add_argument("--transition", help="regex or exact name; overrides config")

    r = sub.add_parser("report")
    r.add_argument("agent")
    r.add_argument("--title")
    r.add_argument("--parent")

    t = sub.add_parser("transitions")
    t.add_argument("key")

    args = ap.parse_args(argv)
    dry = args.dry_run

    try:
        cfg = atl.load_config()
    except atl.AtlassianError as exc:
        err(str(exc))
        return 1

    def need_key(k):
        if not KEY_RE.match(k):
            raise atl.AtlassianError(f"not a Jira issue key: {k!r}")
        return k

    try:
        if args.cmd == "whoami":
            me = atl.whoami(cfg, dry_run=dry)
            print(me.get("displayName") or me.get("emailAddress") or me)

        elif args.cmd == "create":
            out = atl.jira_create(cfg, args.summary, args.desc, args.type,
                                  args.label, dry_run=dry)
            if dry:
                print(out)
            else:
                key = out.get("key")
                if not key:
                    raise atl.AtlassianError(f"create returned no key: {out}")
                print(key)            # stdout = the key, for shell capture

        elif args.cmd == "comment":
            key = need_key(args.key)
            text = args.text if args.text is not None else \
                f"agentmux log tail for `{args.from_log}`:\n\n{read_agent_log(args.from_log)}"
            atl.jira_comment(cfg, key, text, dry_run=dry)
            print(f"commented on {key}")

        elif args.cmd == "done":
            key = need_key(args.key)
            if args.from_log:
                atl.jira_comment(
                    cfg, key,
                    f"agentmux agent `{args.from_log}` finished. Log tail:\n\n"
                    f"{read_agent_log(args.from_log)}",
                    dry_run=dry)
            if dry:
                print(f"[dry-run] would resolve a transition for {key} and apply it")
            else:
                tid, tname = pick_transition(cfg, key, args.transition)
                atl.jira_transition(cfg, key, tid)
                print(f"{key} -> {tname}")

        elif args.cmd == "report":
            body = read_agent_log(args.agent, max_bytes=60000)
            title = args.title or f"agentmux run - {args.agent}"
            # Escape first, then wrap: the log is arbitrary text and Confluence
            # storage format is XML.
            page = ("<p>Captured from <code>~/.agentmux/logs/"
                    f"{html.escape(args.agent)}.log</code>.</p>"
                    f"<ac:structured-macro ac:name=\"code\">"
                    f"<ac:plain-text-body><![CDATA[{body.replace(']]>', ']] >')}]]>"
                    f"</ac:plain-text-body></ac:structured-macro>")
            out = atl.confluence_upsert(cfg, title, page,
                                        parent_id=args.parent, dry_run=dry)
            if dry:
                print(out)
            else:
                link = ((out.get("_links") or {}).get("webui") or "")
                print(f"{cfg['base_url']}/wiki{link}" if link else out.get("id", "ok"))

        elif args.cmd == "transitions":
            key = need_key(args.key)
            data = atl.jira_transitions(cfg, key, dry_run=dry)
            if dry:
                print(data)
            else:
                for tr in data.get("transitions") or []:
                    print(f"{tr['id']:>6}  {tr.get('name')}")

    except atl.AtlassianError as exc:
        err(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
