"""TM-218: two hubs on two nodes, federated through a real nats-server.

Acceptance: (1) two hubs exchange a direct message; (2) a federated role item is
claimed exactly once across two nodes. Skipped when nats-server is not installed.
Run (WSL):  python3 -m unittest hub.tests.test_nats_federation -v   from the repo root
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from hub.store import Store  # noqa: E402

NATS = shutil.which("nats-server") or os.path.expanduser("~/.local/bin/nats-server")
ROLE = {"capabilities": ["python"], "max_active": 5, "lease_s": 900}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(sock, verb, args=None, as_=None):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(sock)
    req = {"verb": verb, "args": args or {}}
    if as_:
        req["as"] = as_
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    return json.loads(buf)


def wait(pred, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    return pred()


@unittest.skipUnless(os.path.exists(NATS), "nats-server not installed")
class TwoNodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nport = free_port()
        cls.nats = subprocess.Popen([NATS, "-a", "127.0.0.1", "-p", str(cls.nport)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.hubs = {}
        for node, agents in (("node_a", ["a1"]), ("node_b", ["b1"])):
            home = tempfile.mkdtemp(prefix=f"hubnats-{node}-", dir="/tmp")
            os.makedirs(os.path.join(home, "hub"))
            os.makedirs(os.path.join(home, "calc"))
            with open(os.path.join(home, "hub", "config.toml"), "w") as f:
                f.write(f'node = "{node}"\nnats_url = "nats://127.0.0.1:{cls.nport}"\n')
            s = Store(os.path.join(home, "hub", "hub.db"))
            s.repo_add("calc", paths=[os.path.join(home, "calc")])
            for a in agents:
                sess = s.register("calc", "worker", a, "codex", ROLE)
                s.set_state(sess, "ready")
            s.db.close()
            env = {**os.environ, "AGENTMUX_HOME": home, "AGENTMUX_SOCKET": "hubnats-none", "AGENTMUX_BIN": "/bin/true"}
            p = subprocess.Popen([sys.executable, os.path.join(ROOT, "hub", "server.py")], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            cls.hubs[node] = {"home": home, "proc": p, "sock": os.path.join(home, "hub", "hub.sock")}
        for h in cls.hubs.values():
            wait(lambda: os.path.exists(h["sock"]))
        # both bridges connected and subscribed to calc worker work
        for h in cls.hubs.values():
            ok = wait(lambda: (lambda b: b["connected"] and "am.work.calc.worker" in b["role_subjects"])(
                call(h["sock"], "status", {"bridge": True})["result"]), 15)
            assert ok, "bridge did not connect"

    @classmethod
    def tearDownClass(cls):
        for h in cls.hubs.values():
            try:
                call(h["sock"], "shutdown")
            except Exception:
                pass
            h["proc"].wait(timeout=10)
        cls.nats.terminate()
        cls.nats.wait(timeout=10)

    def A(self, *a, **k):
        return call(self.hubs["node_a"]["sock"], *a, **k)

    def B(self, *a, **k):
        return call(self.hubs["node_b"]["sock"], *a, **k)

    def test_direct_message_crosses_nodes(self):
        r = self.A("post", {"to": "agent:calc-worker-b1", "kind": "request", "body": "hello from node_a"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["result"]["remote"])
        got = wait(lambda: [m for m in self.B("inbox", {"session": "calc-worker-b1"})["result"]["messages"]
                            if m["body"] == "hello from node_a"])
        self.assertEqual(len(got), 1, "delivered on node_b")
        self.assertEqual(got[0]["sender"], "virtual:operator")
        # node_a itself never delivered it locally (it has no such agent)
        self.assertEqual([m for m in self.A("inbox", {"session": "calc-worker-b1"})["result"]["messages"]], [])

    def test_federated_role_item_claimed_exactly_once(self):
        ids = []
        for i in range(6):
            r = self.A("work_add", {"to": "role:calc/worker", "title": f"fed {i}", "federate": True})
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["claimed_by"], "nats:federated")
            ids.append(r["result"]["id"])
        origins = {f"node_a:{i}" for i in ids}

        def landed():
            rows = [(n, w) for n, h in (("node_a", self.A), ("node_b", self.B))
                    for w in h("work_list", {})["result"] if w.get("origin") in origins]
            return rows if len(rows) >= len(ids) else None
        rows = wait(landed, 15)
        time.sleep(1.5)                                    # give a duplicate the chance to show up
        rows = landed()
        per_origin = {}
        for n, w in rows:
            per_origin.setdefault(w["origin"], []).append(n)
        self.assertEqual(sorted(per_origin), sorted(origins))
        self.assertTrue(all(len(v) == 1 for v in per_origin.values()), per_origin)   # exactly once
        # the winning hub's worker claims and finishes each; results come home
        for n, w in rows:
            hub, agent = (self.A, "calc-worker-a1") if n == "node_a" else (self.B, "calc-worker-b1")
            c = hub("claim", {"work_id": w["id"]}, as_=agent)["result"]["claimed"]
            self.assertEqual(c["id"], w["id"])
            hub("release", {"work_id": w["id"], "outcome": "done", "result": f"done on {n}"}, as_=agent)
        for wid in ids:
            w = wait(lambda: (lambda x: x if x["state"] == "done" else None)(self.A("work_show", {"work_id": wid})["result"]), 10)
            self.assertIsNotNone(w, wid)
            self.assertTrue(w["result"].startswith("done on "))
            self.assertTrue(w["claimed_by"].startswith("nats:"))


if __name__ == "__main__":
    unittest.main()
