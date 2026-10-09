"""The EP-032 demo: two people's agents finish a task together with no human relay.

  python -m hub.fed.demo up       fresh demo: reset the cluster's streams, three hubs, a shared repo
  python -m hub.fed.demo run      the narrated walkthrough (needs `up`)
  python -m hub.fed.demo down     stop the demo hubs
(deploy/nats/demo.sh wraps these and starts a dashboard on nick's hub.)

People (assumption A15: three AGENTMUX_HOMEs on one machine stand in for three people):
  nick     falcon       lead claude_1           trusts alice (auto)
  alice    falcon_fork  worker claude_1, reviewer claude_2     trusts nick (auto)
  mallory  falcon       worker mal_1            trusted by nobody (default: approve)
The agents are registered in each hub and acted for with --as, so every step is
deterministic; `demo.sh live` puts real claude sessions behind the same addresses.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from hub.tests.fedharness import Circle, Person, call, sh, shared_repo, wait  # noqa: E402

# Short on purpose: a hub's unix socket path must fit AF_UNIX's 104 bytes on macOS.
DEMO = os.environ.get("AGENTMUX_FED_DEMO_DIR") or os.path.expanduser("~/.agentmux-demo")
STATE = os.path.join(DEMO, "demo.json")
NICK_LEAD = "falcon-lead-claude_1"
ALICE_W, ALICE_R = "falcon_fork-worker-claude_1", "falcon_fork-reviewer-claude_2"
MAL = "falcon-worker-mal_1"

B, D, G, Y, R, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def say(who, text):
    color = {"nick": "\033[36m", "alice": "\033[35m", "mallory": R, "demo": Y}.get(who, "")
    print(f"{color}{B}{who:>8}{X} {text}", flush=True)


def check(ok, text):
    print(f"         {G + '✓' if ok else R + '✗'}{X} {text}", flush=True)
    if not ok:
        raise SystemExit(f"demo step failed: {text}")


class Hub:
    """A demo hub that is already running (started by `up`)."""

    def __init__(self, peer, home):
        self.peer, self.home, self.sock = peer, home, os.path.join(home, "hub", "hub.sock")

    def __call__(self, verb, args=None, as_=None):
        r = call(self.sock, verb, args, as_)
        if not r.get("ok"):
            raise RuntimeError(f"{self.peer} {verb}: {r.get('error')}")
        return r["result"]

    def maybe(self, verb, args=None, as_=None):
        return call(self.sock, verb, args, as_)

    def inbox(self, session, needle, timeout=20):
        return wait(lambda: [m for m in self("inbox", {"session": session})["messages"] if needle in m["body"]], timeout)


def up():
    if os.path.exists(STATE):
        down(quiet=True)
    shutil.rmtree(DEMO, ignore_errors=True)
    os.makedirs(DEMO)
    os.chmod(DEMO, 0o700)
    say("demo", "resetting the cluster's streams and buckets (a fresh demo)")
    circle = Circle(peers=("nick", "alice", "mallory"))
    say("demo", f"circle at {circle.url} ({'kind cluster, TLS, 3 replicas' if circle.kind else 'local nats-server'})")
    bare, clone = shared_repo(os.path.join(DEMO, "git"))
    paths = {p: clone(os.path.join(DEMO, "work", p, "falcon")) for p in ("nick", "alice", "mallory")}
    homes = {p: os.path.join(DEMO, "homes", p) for p in paths}
    nick = Person("nick", circle, {"falcon": paths["nick"]}, [("falcon", "lead", "claude_1", ["plc_write"])],
                  {"alice": "auto"}, home=homes["nick"], live=True)
    alice = Person("alice", circle, {"falcon_fork": paths["alice"]},
                   [("falcon_fork", "worker", "claude_1"), ("falcon_fork", "reviewer", "claude_2")],
                   {"nick": "auto"}, home=homes["alice"], live=True)
    mallory = Person("mallory", circle, {"falcon": paths["mallory"]}, [("falcon", "worker", "mal_1")], {},
                     home=homes["mallory"], live=True)
    for p in (nick, alice, mallory):
        p.log.close()
    with open(STATE, "w") as f:
        json.dump({"url": circle.url, "kind": circle.kind, "homes": homes, "paths": paths, "bare": bare,
                   "circle_pid": circle.proc.pid if circle.proc else None,
                   "pids": {p.peer: p.proc.pid for p in (nick, alice, mallory)}}, f, indent=1)
    say("demo", f"three hubs up: {', '.join(homes)} (homes under {DEMO}/homes)")


def load():
    if not os.path.exists(STATE):
        raise SystemExit("no demo running: python -m hub.fed.demo up")
    with open(STATE) as f:
        st = json.load(f)
    return st, {p: Hub(p, h) for p, h in st["homes"].items()}


def run():
    st, hubs = load()
    nick, alice, mallory = hubs["nick"], hubs["alice"], hubs["mallory"]
    t0 = time.time()
    print(f"\n{B}EP-032 cross-user federation demo{X}  {D}{st['url']}{X}\n")

    print(f"{B}0. Who is here{X}")
    peers = wait(lambda: (lambda ps: ps if len({p["peer"] for p in ps}) >= 3 else None)(nick("fed_peers")), 30)
    for p in peers:
        say("nick", f"sees {p['peer']}@{p['node']} trust={p['trust']} repos="
                    f"{[r['repo'] + '→' + str(r['local']) for r in p['repos']]} agents={[a['role'] + '/' + a['agent'] for a in p['agents']]}")
    rid = nick("fed_status")["shared"]["falcon"]
    check(alice("fed_status")["shared"]["falcon_fork"] == rid,
          f"nick's 'falcon' and alice's 'falcon_fork' are the same repo: {rid} (matched on the git remote)")

    print(f"\n{B}1. nick's lead plans the work on the shared board{X}")
    card = nick("fed_board_add", {"repo": "falcon", "title": "Parser rejects files with a UTF-8 BOM",
                                  "body": "Files saved by Notepad start with \\ufeff; the tokenizer chokes.",
                                  "labels": ["bug", "parser"]}, as_=NICK_LEAD)
    say("nick", f"board add -> {card['key']} (minted by compare-and-set in KV am_board)")
    seen = wait(lambda: [c for c in alice("fed_board_list", {}) if c["key"] == card["key"]], 15)
    check(bool(seen), f"alice's hub mirrors {card['key']} under her own repo name ({seen[0]['repo']})")

    print(f"\n{B}2. nick shares his half-done branch and hands it to alice's worker{X}")
    p = st["paths"]["nick"]
    sh("git", "-C", p, "checkout", "-qb", "bom_fix")
    with open(os.path.join(p, "parser.py"), "w") as f:
        f.write("def tokenize(s):\n    # TODO(alice): strip the BOM\n    return s.split()\n")
    sh("git", "-C", p, "add", ".")
    sh("git", "-C", p, "commit", "-qm", "parser: tokenizer skeleton")
    cs = nick("fed_code_share", {"note": f"{card['key']}: skeleton is in, please finish the BOM handling",
                                 "to": "peer:alice/falcon/worker/claude_1", "cwd": p}, as_=NICK_LEAD)
    say("nick", f"code share -> pushed {cs['ref']} ({cs['sha'][:10]}), pointer sent; handoff to alice's worker")
    w = nick("work_add", {"to": "role:falcon/worker", "title": f"Finish the BOM fix ({card['key']})",
                          "body": f"Fetch code share {cs['id']}, strip the BOM, add a test, share it back.",
                          "task_key": card["key"], "federate": True}, as_=NICK_LEAD)
    say("nick", f"work add --federate -> {w['id']} (placeholder claimed_by {w['claimed_by']})")

    print(f"\n{B}3. alice's hub pulls the item; her worker picks it up{X}")
    msg = alice.inbox(ALICE_W, "code fetch")
    say("alice", f"worker inbox: handoff from {msg[0]['sender']}")
    item = wait(lambda: alice("claim", {}, as_=ALICE_W)["claimed"], 30)
    check(bool(item) and item["task_key"] == card["key"], f"alice's worker claimed {item['id']} \"{item['title']}\"")
    alice("fed_board_claim", {"key": card["key"]}, as_=ALICE_W)
    say("alice", f"board claim {card['key']} -> doing, assignee = her worker")
    ap = st["paths"]["alice"]
    got = alice("fed_code_fetch", {"id": cs["id"], "cwd": ap}, as_=ALICE_W)
    check(got["verified"], f"fetched {got['ref']} into her clone, sha verified ({got['sha'][:10]})")
    sh("git", "-C", ap, "switch", "-qc", "bom_fix", got["ref"])
    with open(os.path.join(ap, "parser.py"), "w") as f:
        f.write("def tokenize(s):\n    return s.lstrip('\\ufeff').split()\n")
    with open(os.path.join(ap, "test_parser.py"), "w") as f:
        f.write("from parser import tokenize\n\ndef test_bom():\n    assert tokenize('\\ufeffa b') == ['a', 'b']\n")
    test = subprocess.run([sys.executable, "-c", "import test_parser; test_parser.test_bom(); print('1 passed')"],
                          cwd=ap, capture_output=True, text=True)
    say("alice", f"implements the fix; test: {test.stdout.strip() or test.stderr.strip()}")
    sh("git", "-C", ap, "add", ".")
    sh("git", "-C", ap, "commit", "-qm", "parser: strip the UTF-8 BOM before tokenizing")
    back = alice("fed_code_share", {"note": f"{card['key']} done: BOM stripped, test added",
                                    "to": "peer:nick/falcon_fork/lead/claude_1", "cwd": ap}, as_=ALICE_W)
    say("alice", f"code share -> {back['ref']} ({back['stat']})")
    alice("fed_knowledge_share", {"title": "Notepad writes a UTF-8 BOM",
                                  "body": "Text from Windows editors can start with U+FEFF; strip it before "
                                          "tokenizing (parser.tokenize does now).", "tags": ["parser", "windows"]},
          as_=ALICE_W)
    alice("fed_board_move", {"key": card["key"], "status": "review"}, as_=ALICE_W)
    alice("fed_board_comment", {"key": card["key"], "text": f"Fixed in {back['ref']}; ready for review"},
          as_=ALICE_W)
    alice("release", {"work_id": item["id"], "outcome": "done",
                      "result": f"BOM stripped in parser.tokenize, test added; code {back['id']}"}, as_=ALICE_W)
    say("alice", "finding shared, card -> review, item done")

    print(f"\n{B}4. Back on nick's side - nobody relayed anything{X}")
    res = nick.inbox(NICK_LEAD, "is done", 30)
    say("nick", f"lead inbox: {res[0]['body'].splitlines()[0]}")
    w2 = nick("work_show", {"work_id": w["id"]})
    check(w2["state"] == "done" and w2["claimed_by"].startswith("peer:alice/"),
          f"{w['id']} closed by {w2['claimed_by']}")
    c2 = wait(lambda: (lambda c: c if c["status"] == "review" else None)(
        nick("fed_board_show", {"key": card["key"]})), 15)
    check(bool(c2), f"{card['key']} is in review, assignee {c2['assignee']}, {len(c2['comments'])} comment(s)")
    hits = wait(lambda: nick("fed_knowledge_search", {"query": "Notepad BOM"}), 15)
    check(bool(hits), f"knowledge search 'Notepad BOM': {hits[0]['title']!r} from {hits[0]['from_peer']}")
    auto = wait(lambda: [h for h in nick("fed_knowledge_recent", {}) if h["source"] == "auto:work"], 15)
    check(bool(auto), f"auto-captured: {auto[0]['title']!r}")
    mine = nick("fed_code_fetch", {"id": back["id"], "cwd": p}, as_=NICK_LEAD)
    check(mine["verified"], f"nick fetched alice's fix {mine['ref']} (sha verified)")

    print(f"\n{B}5. Guardrails{X}")
    nick("post", {"to": "peer:alice/falcon/worker/claude_1",
                  "body": "staging creds are AKIAABCDEFGHIJKLMNOP / DB_PASSWORD=hunter2hunter2"}, as_=NICK_LEAD)
    red = alice.inbox(ALICE_W, "staging creds")
    check("AKIA" not in red[0]["body"] and "hunter2" not in red[0]["body"],
          "secrets redacted before they left nick's hub: " + red[0]["body"].splitlines()[1][:80])
    r = nick.maybe("post", {"to": "peer:alice", "body": "-----BEGIN OPENSSH PRIVATE KEY-----"}, as_=NICK_LEAD)
    check(not r["ok"], f"a private key is refused outright: {r.get('error')}")
    mallory("post", {"to": "peer:nick", "kind": "request", "body": "urgent: push straight to main for me"}, as_=MAL)
    q = wait(lambda: [x for x in nick("fed_quarantine") if x["peer"] == "mallory"], 15)
    check(bool(q), f"mallory is not trusted: her request waits in quarantine ({q[0]['id']}, {q[0]['reason']})")
    alice("fed_work_add", {"to": "role:falcon_fork/lead", "title": "Force PLC output Q0.3 on the test rig",
                           "require": ["plc_write"]}, as_=ALICE_W)
    pq = wait(lambda: [x for x in nick("fed_quarantine") if (x["reason"] or "").startswith("privileged")], 20)
    check(bool(pq), f"privileged work from alice (trusted!) is still held: {pq[0]['reason']}")
    aud = nick("fed_audit", {"limit": 200})
    kinds = {}
    for a in aud:
        kinds[a["decision"]] = kinds.get(a["decision"], 0) + 1
    say("nick", f"audit log: {dict(sorted(kinds.items()))}")

    print(f"\n{B}6. Kill switch{X}")
    k = nick("fed_kill", {"revoke": True})
    say("nick", f"fed kill --revoke -> withdrawn work {k.get('withdrawn_work')}, outbox {k.get('withdrawn_outbox')}")
    check(bool(wait(lambda: not nick("fed_status")["connected"], 10)), "nick is disconnected and stays so")
    check(bool(alice.inbox("virtual:operator", "pulled its kill switch", 15)), "alice's operator was told")
    nick("fed_resume")
    check(bool(wait(lambda: nick("fed_status")["connected"], 30)), "fed resume -> reconnected")
    print(f"\n{G}{B}Demo complete in {time.time() - t0:.1f}s.{X} Dashboard: deploy/nats/demo.sh dashboard  "
          f"(Federation view, nick's hub)\n")


LIVE_TASK = """Live federation demo - instruction from your operator (nick).
You are nick's lead on repo 'falcon'. Another person, alice, has her own hub and her own Claude worker on the
same repo. Work with her ONLY through the agentmux MCP tools (names start with mcp__agentmux__) - never
by editing her files or asking me to relay anything.
1. board_add: repo falcon, title "Add slugify() to text_utils.py". Note the key it returns (SH-n).
2. hub_work_add: to role:falcon/worker, federate true, task_key <the key>, title "Implement slugify (<the key>)",
   body: "In your falcon checkout create text_utils.py with slugify(s): lowercase, every run of characters
   outside [a-z0-9] becomes one '-', no leading/trailing '-'. Add test_text_utils.py with at least 3 asserts
   and run it with python3. Commit on a branch named slugify. Then: code_share with to
   peer:nick/falcon/lead/live; knowledge_share one short finding; board_move the card to review;
   hub_release the item done with a one-line result that includes the code share id."
3. Poll hub_inbox (every ~20 s) until the result or alice's handoff arrives. Then code_fetch the code share
   id, run python3 test_text_utils.py in your checkout on that ref (git switch -c review <ref>) to verify,
   board_comment the card with what you verified, and hub_post a short thank-you reply to the sender address.
Then stop and wait."""


def _tmux(*a):
    return subprocess.run(["tmux", "-L", "agentmux", *a], capture_output=True, text=True)


def _start_claude(peer, home, cwd):
    """A claude pane on the DEFAULT config (macOS keeps the login in the Keychain under a
    name derived from the config dir, so the harness's per-agent mirrors are logged out),
    with every settings source off - no operator hooks, plugins or MCP servers - plus
    bypass permissions and the agentmux MCP server pointed at this person's hub."""
    import shlex
    mcp = json.dumps({"mcpServers": {"agentmux": {"command": "python3", "args": [os.path.join(ROOT, "hub", "cli.py"), "mcp"],
                                                   "env": {"AGENTMUX_HOME": home}}}})
    settings = json.dumps({"permissions": {"defaultMode": "bypassPermissions"}})
    cmd = (f"export AGENTMUX_HOME={shlex.quote(home)} PATH=$HOME/.local/bin:$PATH; exec claude "
           f"--dangerously-skip-permissions --setting-sources '' --settings {shlex.quote(settings)} "
           f"--mcp-config {shlex.quote(mcp)}")
    name = f"demo_{peer}"
    _tmux("kill-session", "-t", f"={name}")
    r = _tmux("new-session", "-d", "-s", name, "-x", "220", "-y", "50", "-c", cwd, "bash", "-lc", cmd)
    if r.returncode:
        raise SystemExit(f"tmux: {r.stderr}")
    for _ in range(60):                                  # first-run dialogs
        time.sleep(1)
        screen = _tmux("capture-pane", "-p", "-t", name).stdout
        if "Yes, I accept" in screen or "Yes, I trust this folder" in screen:
            # Both dialogs default to the refusing option ("No, exit"): move to Yes first.
            _tmux("send-keys", "-t", name, "Down")
            time.sleep(0.3)
            _tmux("send-keys", "-t", name, "Enter")
            time.sleep(1)
        elif "bypass permissions on" in screen.lower() or "? for shortcuts" in screen:
            return name
    raise SystemExit(f"claude in {name} did not reach its prompt:\n{screen[-800:]}")


def live(timeout_s=1500):
    """Real claude sessions behind the same addresses: nick's lead and alice's worker."""
    st, hubs = load()
    nick, alice = hubs["nick"], hubs["alice"]
    print(f"\n{B}Live mode: real Claude sessions on both sides{X}\n", flush=True)
    for hub, peer, repo, role in ((alice, "alice", "falcon_fork", "worker"), (nick, "nick", "falcon", "lead")):
        pane = _start_claude(peer, st["homes"][peer], st["paths"][peer])
        r = hub("adopt", {"legacy": pane, "repo": repo, "role": role, "agent": "live", "cli": "claude"})
        say(peer, f"claude is up in tmux '{pane}' ({st['paths'][peer]}), adopted as {r['session']}")
    time.sleep(15)                                          # let both read their welcome
    nick("post", {"to": "agent:falcon-lead-live", "kind": "request", "body": LIVE_TASK})
    say("nick", "operator -> falcon-lead-live: the task (everything after this is the two Claude sessions)")
    t0 = time.time()
    done = False
    while time.time() - t0 < timeout_s:
        items = [w for w in nick("work_list", {}) if (w.get("title") or "").startswith("Implement slugify")]
        cards = nick("fed_board_list", {"repo": "falcon"})
        # The audit log, not the inbox: alice's claude acks its own mail, and inbox only shows unread.
        replies = [r for r in alice("fed_audit", {"limit": 200, "peer": "nick"})
                   if r["plane"] == "msg" and r["dir"] == "in" and r["decision"] == "delivered"
                   and r["at"] > items[0]["updated"]] if items and items[0]["state"] == "done" else []
        line = (f"{int(time.time() - t0):>4}s  item={items[0]['state'] if items else '-'}  "
                f"cards={[(c['key'], c['status']) for c in cards]}  reply={'yes' if replies else 'no'}")
        print(f"{D}{line}{X}", flush=True)
        if items and items[0]["state"] == "done" and replies:
            done = True
            break
        time.sleep(20)
    print()
    w = [x for x in nick("work_list", {}) if (x.get("title") or "").startswith("Implement slugify")]
    check(bool(w) and w[0]["state"] == "done", f"alice's Claude finished nick's item: {w[0]['result'] if w else '-'}")
    know = nick("fed_knowledge_recent", {})
    say("nick", f"findings: {[k['title'] for k in know][:4]}")
    say("nick", f"code: {[(c['from_peer'], c['ref'], c['fetched']) for c in nick('fed_code_list', {})]}")
    card = nick("fed_board_list", {"repo": "falcon"})
    say("nick", f"board: {[(c['key'], c['status'], c['assignee'], c['comments']) for c in card]}")
    check(done, "nick's Claude verified the fix and replied to alice's Claude")


def down(quiet=False):
    try:
        st, hubs = load()
    except SystemExit:
        return
    for p, h in hubs.items():
        try:
            call(h.sock, "shutdown")
        except OSError:
            pass
    if st.get("circle_pid"):
        try:
            os.kill(st["circle_pid"], 15)
        except OSError:
            pass
    os.remove(STATE)
    if not quiet:
        say("demo", "demo hubs stopped")


if __name__ == "__main__":
    {"up": up, "run": run, "live": live, "down": down}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
