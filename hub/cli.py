"""agentmux hub <verb> - the client side of the protocol. See docs/PROTOCOL.md 7.

Talks newline-delimited JSON to hub/hub.sock. The hub, not this client, decides who
the caller is (process ancestry); this client never sends an identity of its own
except the operator-only --as.

Output is written for two readers: an agent CLI that must act on it (the default
text form, which ends with the exact next command), and scripts (--json).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.environ.get("AGENTMUX_HOME") or os.path.expanduser("~/.agentmux")
SOCK = os.path.join(ROOT, "hub", "hub.sock")

USAGE = """usage: agentmux hub <verb> [args]
  daemon     start | stop | status | ping
  agent      whoami | inbox [--ack] | ack <id>... | claim [<work_id>] | heartbeat
             done|fail|return|block <work_id> [--result TEXT]
             post --to ADDR [--kind K] [--ref R] [--idem KEY] TEXT|-
             work add --to ADDR --title T [--body B | --body-file F] [--parent ID] [--priority N]
                      [--require CAP]... [--repo R] [--task-key K]
             work show <id> | work list [--state S] [--repo R]
  operator   repo add <repo> <path>... [--title T] [--group G]... [--accept-normalized]
             team add <repo> <team> [--member SESSION]...
             spawn <repo> <role> <agent> [--cli codex|claude|grok|shell] [--model M] [--team T] [--cwd P]
             kill <session> | agents [--live] | events [--since N] [--entity E] | resolve ADDR
  global     --json   --as SESSION (operator only; testing)
addresses: agent:<repo>-<role>-<agent>  role:<repo>/<role>  role:*/<role>  role:group:<g>/<role>
           role:team:<repo>/<team>/<role>  team:<repo>/<team>  virtual:operator"""


class Fail(SystemExit):
    pass


def call(verb, args=None, as_=None, timeout=30):
    req = {"verb": verb, "args": args or {}}
    if as_:
        req["as"] = as_
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except (FileNotFoundError, ConnectionRefusedError):
        raise Fail("agentmux hub: the hub is not running (agentmux hub start)")
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    resp = json.loads(buf or b"{}")
    if not resp.get("ok"):
        raise Fail(f"agentmux hub {verb}: {resp.get('error', 'no response')}")
    return resp


def opt(argv, name, default=None, multi=False, flag=False):
    vals, out, i = [], [], 0
    while i < len(argv):
        if argv[i] == name:
            if flag:
                vals.append(True); i += 1; continue
            if i + 1 >= len(argv):
                raise Fail(f"{name} needs a value")
            vals.append(argv[i + 1]); i += 2; continue
        out.append(argv[i]); i += 1
    argv[:] = out
    if flag:
        return bool(vals)
    if multi:
        return vals
    return vals[-1] if vals else default


def show_msgs(r):
    sess = r["session"]
    lines = []
    msgs = r["messages"]
    if not msgs:
        lines.append(f"No new messages for {sess}.")
    else:
        lines.append(f"{len(msgs)} message(s) for {sess}:")
    for m in msgs:
        lines.append(f"--- {m['id']}  from {m['sender']}  kind={m['kind']}" + (f"  ref={m['ref']}" if m['ref'] else ""))
        if m.get("body_ref"):
            lines.append(f"(body is in {m['body_ref']} - read that file; sha256 {m['body_sha'][:16]})")
        if m.get("body"):
            lines.append(m["body"])
    lines.append("---")
    if r.get("acked"):
        lines.append(f"Acknowledged {len(r['acked'])} message(s).")
    elif msgs:
        lines.append("Acknowledge with: agentmux hub ack " + " ".join(m["id"] for m in msgs))
    act = r.get("active") or []
    for a in act:
        lines.append(f"Your active work: {a['id']} \"{a['title']}\" (lease until {a['lease_until']})")
    cl = r.get("claimable") or []
    if cl:
        lines.append(f"Claimable work ({len(cl)}): " + "; ".join(f"{c['id']} \"{c['title']}\" [{c['target']}]" for c in cl[:5]))
        lines.append("Take the next one with: agentmux hub claim")
    elif not act and not msgs:
        lines.append("Nothing to do right now. Stop and wait for the next [hub] line.")
    return "\n".join(lines)


def show_work(w):
    if not w:
        return "no such work item"
    out = [f"{w['id']}  [{w['state']}]  {w['title']}",
           f"  target {w['target']}  repo {w['repo']}  priority {w['priority']}  by {w['created_by']}"
           + (f"  parent {w['parent_id']}" if w.get("parent_id") else "") + (f"  task {w['task_key']}" if w.get("task_key") else "")]
    if w.get("claimed_by"):
        out.append(f"  claimed by {w['claimed_by']} until {w['lease_until']}")
    if w.get("body"):
        out.append("  ---\n" + "\n".join("  " + l for l in w["body"].splitlines()))
    if w.get("result"):
        out.append(f"  result: {w['result']}")
    for c in w.get("children") or []:
        out.append(f"  child {c['id']} [{c['state']}] {c['title']} -> {c['target']}" + (f" ({c['claimed_by']})" if c['claimed_by'] else ""))
    return "\n".join(out)


def start():
    try:
        call("ping", timeout=3)
        print("hub already running")
        return
    except Fail:
        pass
    os.makedirs(os.path.join(ROOT, "hub"), exist_ok=True)
    logf = open(os.path.join(ROOT, "hub", "hub.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(REPO, "hub", "server.py")], stdout=logf, stderr=logf,
                     stdin=subprocess.DEVNULL, start_new_session=True, cwd=ROOT)
    for _ in range(50):
        time.sleep(0.2)
        try:
            call("ping", timeout=2)
            print(f"hub started ({SOCK})")
            return
        except Fail:
            continue
    raise Fail("hub did not come up; see " + os.path.join(ROOT, "hub", "hub.log"))


def main(argv):
    as_ = opt(argv, "--as")
    js = opt(argv, "--json", flag=True)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE); return
    verb, rest = argv[0], argv[1:]

    def out(resp, text=None):
        if js:
            print(json.dumps(resp["result"], indent=2, default=str))
        else:
            print(text if text is not None else json.dumps(resp["result"], indent=2, default=str))

    if verb == "start":
        return start()
    if verb == "stop":
        call("shutdown"); print("hub stopping"); return
    if verb in ("ping", "status", "whoami"):
        r = call(verb, as_=as_)
        if verb == "whoami" and not js:
            a = r["result"].get("agent")
            print(f"{r['caller']}" + (f"  repo={a['repo']} role={a['role']} cli={a['cli']} state={a['state']}\n"
                                      f"eligible: {', '.join(r['result']['eligible'])}" if a else ""))
            return
        if verb == "status" and not js:
            st = r["result"]
            print(f"repos: {', '.join(st['repos']) or '-'}")
            print("deliveries: " + ", ".join(f"{k}={v}" for k, v in sorted(st["deliveries"].items())) or "-")
            print("work: " + ", ".join(f"{k}={v}" for k, v in sorted(st["work"].items())))
            for a in st["agents"]:
                print(f"  {a['session']:<40} {a['cli']:<7} {a['state']:<8} {a['state_note'] or ''}")
            for d in st["dead"]:
                print(f"  DEAD {d['message_id']} -> {d['recipient']}: {d['last_error']}")
            return
        return out(r)
    if verb == "inbox":
        ack = opt(rest, "--ack", flag=True)
        sess = opt(rest, "--session")
        r = call("inbox", {"ack": ack, "session": sess, "limit": int(opt(rest, "--limit", 20))}, as_=as_)
        return out(r, show_msgs(r["result"]))
    if verb == "ack":
        r = call("ack", {"ids": rest}, as_=as_)
        return out(r, f"acked {len(r['result']['acked'])}")
    if verb == "claim":
        r = call("claim", {"work_id": rest[0] if rest else None}, as_=as_)
        c = r["result"].get("claimed")
        if not c:
            return out(r, "Nothing claimable for you right now" + (f" ({r['result']['reason']})" if r['result'].get('reason') else "")
                       + ". Stop and wait for the next [hub] line.")
        return out(r, "You claimed:\n" + show_work(c) +
                   f"\nWhen finished: agentmux hub done {c['id']} --result \"<summary>\"   (or fail/return/block)")
    if verb in ("done", "fail", "return", "block"):
        if not rest:
            raise Fail(f"{verb} needs a work id")
        result = opt(rest, "--result")
        outcome = {"fail": "failed", "return": "returned", "block": "blocked"}.get(verb, "done")
        r = call("release", {"work_id": rest[0], "outcome": outcome, "result": result}, as_=as_)
        return out(r, f"{rest[0]} -> {r['result']['state']}")
    if verb == "heartbeat":
        return out(call("heartbeat", as_=as_))
    if verb == "post":
        to = opt(rest, "--to"); kind = opt(rest, "--kind", "note"); ref = opt(rest, "--ref")
        idem = opt(rest, "--idem")
        if not to:
            raise Fail("post needs --to ADDRESS")
        body = " ".join(rest)
        if body == "-":
            body = sys.stdin.read()
        r = call("post", {"to": to, "kind": kind, "ref": ref, "idem_key": idem, "body": body}, as_=as_)
        res = r["result"]
        return out(r, f"posted {res['id']} to {', '.join(res['recipients'])}" + (" (duplicate idem key)" if res["duplicate"] else ""))
    if verb == "work":
        sub = rest[0] if rest else "list"
        rest = rest[1:]
        if sub == "add":
            body_file = opt(rest, "--body-file")
            body = open(body_file).read() if body_file else opt(rest, "--body")
            req = opt(rest, "--require", multi=True)
            a = {"to": opt(rest, "--to"), "title": opt(rest, "--title"), "body": body, "parent": opt(rest, "--parent"),
                 "priority": int(opt(rest, "--priority", 100)), "repo": opt(rest, "--repo"),
                 "task_key": opt(rest, "--task-key"), "requirements": {"capabilities": req} if req else None}
            if not a["to"] or not a["title"]:
                raise Fail("work add needs --to and --title")
            r = call("work_add", a, as_=as_)
            return out(r, f"created {r['result']['id']} -> {r['result']['target']}")
        if sub == "show":
            r = call("work_show", {"work_id": rest[0]}, as_=as_)
            return out(r, show_work(r["result"]))
        if sub == "list":
            r = call("work_list", {"state": opt(rest, "--state"), "repo": opt(rest, "--repo")}, as_=as_)
            return out(r, "\n".join(f"{w['id']} [{w['state']:<16}] {w['title'][:50]:<50} {w['target']} {w['claimed_by'] or ''}"
                                    for w in r["result"]) or "no work items")
        raise Fail(f"unknown work subcommand {sub}")
    if verb == "repo":
        if not rest or rest[0] != "add" or len(rest) < 3:
            raise Fail("usage: agentmux hub repo add <repo> <path>...")
        rest = rest[1:]
        title = opt(rest, "--title"); groups = opt(rest, "--group", multi=True)
        acc = opt(rest, "--accept-normalized", flag=True)
        r = call("repo_add", {"repo": rest[0], "paths": rest[1:], "title": title, "groups": groups,
                              "accept_normalized": acc}, as_=as_)
        return out(r, f"repo {r['result']['repo']} registered")
    if verb == "team":
        if not rest or rest[0] != "add" or len(rest) < 3:
            raise Fail("usage: agentmux hub team add <repo> <team> [--member S]...")
        rest = rest[1:]
        mem = opt(rest, "--member", multi=True)
        r = call("team_add", {"repo": rest[0], "team": rest[1], "members": mem}, as_=as_)
        return out(r, f"team {rest[0]}/{rest[1]}: {', '.join(r['result']['members'])}")
    if verb == "spawn":
        cli = opt(rest, "--cli", "codex"); model = opt(rest, "--model"); teams = opt(rest, "--team", multi=True)
        cwd = opt(rest, "--cwd"); acc = opt(rest, "--accept-normalized", flag=True)
        if len(rest) != 3:
            raise Fail("usage: agentmux hub spawn <repo> <role> <agent> [--cli C]")
        r = call("spawn", {"repo": rest[0], "role": rest[1], "agent": rest[2], "cli": cli, "model": model,
                           "teams": teams, "cwd": cwd, "accept_normalized": acc}, as_=as_, timeout=180)
        return out(r, f"spawned {r['result']['session']} ({r['result']['handle']}) in {r['result']['cwd']}")
    if verb == "kill":
        return out(call("kill", {"session": rest[0]}, as_=as_))
    if verb == "agents":
        r = call("agents", {"live": opt(rest, "--live", flag=True)}, as_=as_)
        return out(r, "\n".join(f"{a['session']:<40} {a['cli']:<7} {a['state']:<8} {a['handle'] or '-':<5} "
                                f"out={a['last_output'] or '-'}" for a in r["result"]) or "no agents")
    if verb == "events":
        r = call("events", {"since": int(opt(rest, "--since", 0)), "entity": opt(rest, "--entity"),
                            "limit": int(opt(rest, "--limit", 200))}, as_=as_)
        return out(r, "\n".join(f"{e['seq']:>5} {e['at']} {e['entity']:<8} {e['entity_id'][:48]:<48} {e['event']:<12} "
                                f"{e['actor'] or ''} {(e['detail'] or '')[:120]}" for e in r["result"]))
    if verb == "resolve":
        return out(call("resolve", {"address": rest[0]}, as_=as_))
    raise Fail(f"unknown verb {verb!r}\n{USAGE}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Fail as e:
        print(e, file=sys.stderr)
        sys.exit(1)
