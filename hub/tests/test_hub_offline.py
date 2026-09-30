"""Offline tier: protocol semantics and delivery guards, no tmux, no agent CLI.

Run (WSL):  python3 -m unittest discover -s hub/tests -v     from the repo root
Each test names the failure class (C#) or requirement (R-*) it pins.
"""
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from hub import deliver, names, profiles  # noqa: E402
from hub.store import HubError, Store  # noqa: E402
from hub.transport import FakeTransport  # noqa: E402

ROLE = {"capabilities": ["python"], "max_active": 1, "lease_s": 900}
LEAD = {"capabilities": ["plan"], "max_active": 3, "lease_s": 900}


def fresh_store():
    d = tempfile.mkdtemp(prefix="hubtest-", dir="/tmp")
    s = Store(os.path.join(d, "hub.db"))
    s.repo_add("alpha", paths=["/tmp/alpha"], groups=["g1"])
    s.repo_add("beta", paths=["/tmp/beta"], groups=["g1"])
    return s


def reg(s, repo, role, agent, snap=ROLE, cli="codex"):
    sess = s.register(repo, role, agent, cli, snap)
    s.set_state(sess, "ready")
    return sess


class Names(unittest.TestCase):
    def test_normalize_and_refuse(self):  # R-NAME-1
        self.assertEqual(names.normalize("Agora Rev #2"), "agora_rev_2")
        self.assertEqual(names.normalize("TM-210", "team"), "tm_210")
        with self.assertRaises(names.NameError_) as e:
            names.check_part("my-repo", "repo")
        self.assertEqual(e.exception.suggestion, "my_repo")
        self.assertEqual(names.check_part("my-repo", "repo", accept_normalized=True), "my_repo")

    def test_session_roundtrip(self):
        s = names.session_name("agora", "reviewer", "codex_1")
        self.assertEqual(s, "agora-reviewer-codex_1")
        self.assertEqual(names.split_session(s), ("agora", "reviewer", "codex_1"))
        with self.assertRaises(ValueError):
            names.split_session("agora-web-reviewer-x")

    def test_addresses_and_subjects(self):
        a = names.parse_address("role:group:g1/reviewer")
        self.assertEqual(str(a), "role:group:g1/reviewer")
        self.assertEqual(names.nats_subject(names.parse_address("agent:alpha/worker/w1"), "n1"), "am.n1.alpha.worker.w1")
        self.assertEqual(names.nats_subject(a, "n1"), "am.work.g_g1.reviewer")
        with self.assertRaises(ValueError):
            names.parse_address("nobody")


class Messaging(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()
        self.w1 = reg(self.s, "alpha", "worker", "w1")
        self.w2 = reg(self.s, "alpha", "worker", "w2")
        self.r1 = reg(self.s, "beta", "reviewer", "r1")

    def test_duplicate_live_name_refused(self):  # R-NAME-2 / C8
        with self.assertRaises(HubError):
            self.s.register("alpha", "worker", "w1", "codex", ROLE)

    def test_reregistered_name_does_not_inherit_mail(self):  # R-NAME-2
        self.s.post("virtual:operator", f"agent:{self.w1}", "request", "for the old one")
        self.s.set_state(self.w1, "dead", "terminal gone")
        again = reg(self.s, "alpha", "worker", "w1")
        self.assertEqual(again, self.w1)
        self.assertEqual(self.s.inbox(self.w1), [])
        self.assertEqual(self.s.status()["dead"][0]["last_error"], "recipient re-registered")

    def test_direct_inbox_ack(self):  # R-DLV-1
        r = self.s.post("virtual:operator", f"agent:{self.w1}", "request", "hello")
        self.assertEqual(r["recipients"], [self.w1])
        box = self.s.inbox(self.w1)
        self.assertEqual([m["body"] for m in box], ["hello"])
        self.assertEqual(self.s.pending_for(self.w1)[0]["state"], "received")
        self.s.ack(self.w1, [r["id"]])
        self.assertEqual(self.s.inbox(self.w1), [])

    def test_idempotent_post(self):  # R-MSG-1 / C1 re-sends
        a = self.s.post("virtual:operator", f"agent:{self.w1}", "note", "x", idem_key="k1")
        b = self.s.post("virtual:operator", f"agent:{self.w1}", "note", "x", idem_key="k1")
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(len(self.s.inbox(self.w1)), 1)

    def test_order_preserved(self):  # R-DLV-4 / C9 ordering
        ids = [self.s.post("virtual:operator", f"agent:{self.w1}", "note", f"m{i}")["id"] for i in range(50)]
        self.assertEqual([m["id"] for m in self.s.inbox(self.w1, limit=100)], ids)

    def test_role_broadcast_and_cross_repo_group(self):
        r = self.s.post("virtual:operator", "role:alpha/worker", "note", "all workers")
        self.assertEqual(sorted(r["recipients"]), sorted([self.w1, self.w2]))
        r = self.s.post("virtual:operator", "role:group:g1/reviewer", "note", "cross-repo")
        self.assertEqual(r["recipients"], [self.r1])

    def test_unknown_kind_lists_known(self):  # R-MSG-2 / C9 bug #38
        with self.assertRaises(HubError) as e:
            self.s.post("virtual:operator", f"agent:{self.w1}", "bogus", "x")
        self.assertIn("request", str(e.exception))

    def test_no_live_recipient_refused(self):  # C4: never queue into the void silently
        self.s.set_state(self.r1, "dead")
        with self.assertRaises(HubError):
            self.s.post("virtual:operator", "role:beta/reviewer", "note", "nobody home")

    def test_virtual_operator_inbox(self):  # C9: a recipient with no pane
        self.s.post(f"agent:{self.w1}", "virtual:operator", "reply", "done")
        self.assertEqual(self.s.inbox("virtual:operator")[0]["body"], "done")

    def test_attempts_to_dead(self):
        self.s.post("virtual:operator", f"agent:{self.w1}", "note", "x")
        dead = []
        for _ in range(3):
            dead = self.s.bump_attempt(self.w1, "not acked", max_attempts=3)
        self.assertEqual(len(dead), 1)
        self.assertEqual(self.s.status()["deliveries"].get("dead"), 1)

    def test_fts_and_audit(self):
        self.s.post("virtual:operator", f"agent:{self.w1}", "note", "the quick brown fox")
        hits = self.s.q("SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'brown'")
        self.assertEqual(len(hits), 1)
        self.assertTrue(any(e["entity"] == "delivery" for e in self.s.events()))
        self.assertEqual(len(self.s.q("SELECT * FROM nats_outbox")), 1)


def _claimer(path, session, q):
    s = Store(path)
    time.sleep(0.05)
    q.put((session, (s.claim(session) or {}).get("claimed")))


class Work(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()
        self.ws = [reg(self.s, "alpha", "worker", f"w{i}") for i in range(8)]

    def test_first_claim_wins_across_processes(self):  # role pickup, BEGIN IMMEDIATE
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "only one")
        q = mp.Queue()
        ps = [mp.Process(target=_claimer, args=(self.s.path, w, q)) for w in self.ws]
        [p.start() for p in ps]
        [p.join() for p in ps]
        got = [q.get() for _ in ps]
        winners = [g for g in got if g[1]]
        self.assertEqual(len(winners), 1, got)

    def test_capacity_and_lease_expiry(self):  # R-LIVE-2
        w = self.ws[0]
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "a")
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "b")
        c = self.s.claim(w, lease_s=0)["claimed"]
        self.assertIsNotNone(c)
        self.assertIsNone(self.s.claim(w)["claimed"])            # max_active 1
        time.sleep(0.05)
        back = self.s.sweep_leases()
        self.assertEqual([b["id"] for b in back], [c["id"]])
        self.assertEqual(self.s.work(c["id"])["state"], "ready")

    def test_dead_agent_returns_leases(self):  # C4
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "a")
        c = self.s.claim(self.ws[1])["claimed"]
        self.s.set_state(self.ws[1], "dead", "terminal gone")
        self.assertEqual(self.s.work(c["id"])["state"], "ready")
        self.assertIsNotNone(self.s.claim(self.ws[2])["claimed"])

    def test_direct_to_dead_refused(self):
        self.s.set_state(self.ws[3], "dead")
        with self.assertRaises(HubError):
            self.s.work_create("virtual:operator", "alpha", f"agent:{self.ws[3]}", "x")

    def test_requirements(self):
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "needs codesys",
                           requirements={"capabilities": ["codesys"]})
        self.assertIsNone(self.s.claim(self.ws[0])["claimed"])
        self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "needs python",
                           requirements={"capabilities": ["python"], "cli": ["codex"]})
        self.assertEqual(self.s.claim(self.ws[0])["claimed"]["title"], "needs python")

    def test_team_lead_decomposes(self):
        lead = reg(self.s, "alpha", "lead", "l1", LEAD)
        self.s.team_add("alpha", "t1", [lead, self.ws[0], self.ws[1]])
        parent = self.s.work_create("virtual:operator", "alpha", "team:alpha/t1", "feature")
        self.assertIsNone(self.s.claim(self.ws[0])["claimed"])      # workers cannot take team items
        p = self.s.claim(lead)["claimed"]
        self.assertEqual(p["id"], parent["id"])
        kid = self.s.work_create(f"agent:{lead}", "alpha", "role:team:alpha/t1/worker", "part 1", parent_id=p["id"])
        self.assertEqual(self.s.work(p["id"])["state"], "waiting_children")
        self.assertIsNone(self.s.claim(self.ws[5])["claimed"])      # not on the team
        k = self.s.claim(self.ws[1])["claimed"]
        self.assertEqual(k["id"], kid["id"])
        with self.assertRaises(HubError):
            self.s.release(lead, p["id"], "done")                   # open child
        self.s.release(self.ws[1], k["id"], "done", "ok")
        self.assertEqual(self.s.release(lead, p["id"], "done", "shipped")["state"], "done")

    def test_cancel_takes_open_children(self):
        p = self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "parent")
        k = self.s.work_create("virtual:operator", "alpha", "role:alpha/worker", "kid", parent_id=p["id"])
        self.assertEqual(sorted(self.s.cancel(p["id"], "orphaned")), sorted([p["id"], k["id"]]))
        self.assertIsNone(self.s.claim(self.ws[0])["claimed"])

    def test_path_claims_are_per_repo(self):  # R-HOME-2
        self.s.claim_path(self.ws[0], "alpha", "README.md")
        self.s.claim_path(self.ws[1], "beta", "README.md")          # same path, other repo: fine
        with self.assertRaises(HubError):
            self.s.claim_path(self.ws[1], "alpha", "README.md")


def screen(prompt="› ", above="codex ready"):
    return f"{above}\n\n{prompt}"


class Deliver(unittest.TestCase):
    def setUp(self):
        self.t = FakeTransport()
        self.p = profiles.get("codex")

    def run_line(self, sess, **kw):
        return deliver.deliver_line(self.t, self.p, sess, sess, "[hub] 1 new message(s). Run: agentmux hub inbox --ack", **kw)

    def keys(self, sess):
        return [x[2] for x in self.t.sent if x[0] == sess and x[1] == "key"]

    def test_clean_submit(self):
        self.t.add("a", screen())
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())
        self.assertEqual(rc.stages["typed"], "ok")

    def test_update_modal_answered_safely(self):  # C2: never Enter on 'Update now'
        self.t.add("a", "✨ Update available! 0.159 -> 0.160\n› 1. Update now (runs `npm install -g @openai/codex`)\n  2. Skip\n")
        s = self.t.sessions["a"]

        orig = self.t.send_key

        def key(h, k):
            orig(h, k)
            if k == "2":
                s["screen"] = screen()
        self.t.send_key = key
        rc = self.run_line("a")
        self.assertEqual(self.keys("a")[0], "2", self.t.sent)
        self.assertNotEqual(self.keys("a")[0], "Enter")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())

    def test_login_modal_blocks_without_keys(self):  # C2
        self.t.add("a", "Welcome to Codex\nSign in with ChatGPT\n› 1. Sign in with ChatGPT\n")
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "blocked")
        self.assertEqual(self.t.sent, [])

    def test_unknown_prompt_blocks(self):  # C2: generic guard
        self.t.add("a", "Something new?\nPress enter to continue\n")
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "blocked")
        self.assertEqual(self.t.sent, [])

    def test_copy_mode_left_first(self):  # C7 / D02
        self.t.add("a", screen(), mode="copy")
        rc = self.run_line("a")
        self.assertEqual(self.t.sent[0][2], "cancel-mode")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())

    def test_busy_defers_without_keys(self):
        self.t.add("a", "Working (12s • esc to interrupt)\n› ")
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "deferred")
        self.assertEqual(self.t.sent, [])

    def test_booting_defers(self):  # C5
        self.t.add("a", screen())
        rc = self.run_line("a", started_at=time.time())
        self.assertEqual((rc.outcome, rc.reason), ("deferred", "booting"))
        self.assertEqual(self.t.sent, [])

    def test_placeholder_gets_second_enter(self):  # C1
        self.t.add("a", screen())
        s = self.t.sessions["a"]
        n = {"enter": 0}

        def on_submit(scr):
            n["enter"] += 1
            return "› [Pasted Content 1024 chars]" if n["enter"] == 1 else "working (esc to interrupt)\n› "
        s["on_submit"] = on_submit
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())
        self.assertGreaterEqual(rc.enters, 2)

    def test_stale_line_resubmitted_not_retyped(self):  # C1 recovery
        self.t.add("a", "› [hub] 1 new message(s). Run: agentmux hub inbox --ack")
        rc = self.run_line("a")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())
        self.assertFalse(any(k == "text" for _, k, _p in self.t.sent))

    def test_handle_mismatch_refused(self):  # R-ID-2 / C8
        self.t.add("a", screen())
        rc = deliver.deliver_line(self.t, self.p, "a", "%99", "x")
        self.assertEqual(rc.outcome, "failed")
        self.assertEqual(self.t.sent, [])

    def test_hint_text_cleared_first(self):
        self.t.add("a", "› Ask Codex to do anything")
        rc = self.run_line("a")
        self.assertEqual(self.keys("a")[0], "C-u")
        self.assertEqual(rc.outcome, "submitted", rc.as_dict())


class Profiles(unittest.TestCase):
    def test_claude_idle_prompt_is_not_a_modal(self):
        p = profiles.get("claude")
        idle = "────────\n❯ \n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)"
        self.assertIsNone(p.modal(idle))
        self.assertTrue(p.is_ready(idle))

    def test_claude_bypass_consent_answer(self):
        p = profiles.get("claude")
        m = p.modal("WARNING: Claude Code running in Bypass Permissions mode\n❯ 1. No, exit\n  2. Yes, I accept")
        self.assertEqual(m.kind, "bypass")
        self.assertEqual(m.answer, {"select": r"^Yes, I accept"})


class MenuByLabel(unittest.TestCase):
    """C2, measured 2026-09-29: claude 2.1.285's folder-trust dialog preselects 'No, exit'.
    A positional Enter killed a team lead 9 s after spawn. Answers go by label."""

    def menu(self, opts, sel):
        head = ("Accessing workspace:\n /home/nick/hubdemo/calc\n Quick safety check: Is this a project you "
                "created or one you trust?\n")
        body = "\n".join((" ❯ " if i == sel else "   ") + o for i, o in enumerate(opts))
        return head + body + "\n Enter to confirm · Esc to cancel"

    def test_trust_selects_yes_even_when_no_is_preselected(self):
        t = FakeTransport()
        opts, state = ["No, exit", "Yes, I trust this folder"], {"sel": 0, "chosen": None}
        t.add("c", self.menu(opts, 0))
        orig = t.send_key

        def key(h, k):
            t.sent.append((h, "key", k))
            if k == "Down":
                state["sel"] = min(state["sel"] + 1, len(opts) - 1)
            elif k == "Up":
                state["sel"] = max(state["sel"] - 1, 0)
            elif k == "Enter" and state["chosen"] is None:
                state["chosen"] = opts[state["sel"]]
                t.sessions[h]["screen"] = "────\n❯ \n────\n  ⏵⏵ bypass permissions on"
                return
            elif k == "Enter":
                return orig(h, k)
            t.sessions[h]["screen"] = self.menu(opts, state["sel"])
        t.send_key = key
        rc = deliver.deliver_line(t, profiles.get("claude"), "c", "c", "[hub] 1 new message(s). Run: agentmux hub inbox --ack")
        self.assertEqual(state["chosen"], "Yes, I trust this folder", t.sent)
        self.assertEqual(rc.modal_answers[0]["keys"], ["Down", "Enter"])

    def test_missing_safe_option_blocks(self):
        t = FakeTransport()
        t.add("c", self.menu(["No, exit", "Maybe later"], 0))
        rc = deliver.deliver_line(t, profiles.get("claude"), "c", "c", "x")
        self.assertEqual(rc.outcome, "blocked")
        self.assertNotIn("Enter", [k for _, kind, k in t.sent if kind == "key"])


if __name__ == "__main__":
    unittest.main()
