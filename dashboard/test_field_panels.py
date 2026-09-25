#!/usr/bin/env python3
"""The IIOT field services: MQTT monitor, segment scanner, PROFINET schema, GitHub auth.

    python3 dashboard/test_field_panels.py

SELF-CONTAINED ON PURPOSE. This starts its own HTTP server on an ephemeral port
with its own throwaway AGENTMUX_HOME, so it never touches the operator's
dashboard on 8787, never writes to their cc.db, and can run while that dashboard
is up. The MQTT half brings up a real (if minimal) broker on loopback and asserts
on the bytes that actually cross it, the same way test_mqtt.py does - claiming a
topic browser works without a broker to browse would be claiming nothing.

WHAT IS DELIBERATELY NOT TESTED HERE. github_auth's interactive sign-in drives
`gh` over a PTY and finishes on GitHub's servers; there is no honest way to fake
that, so what is asserted is the part that matters from a safety point of view -
that no endpoint returns a token, that a write is refused without an actor and an
explicit confirmation, and that the argument vector a write builds cannot be
influenced by the request.
"""

import http.client
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

HOME = tempfile.mkdtemp(prefix="agentmux-field-")
os.environ["AGENTMUX_HOME"] = HOME

import mqtt                                      # noqa: E402
import mqtt_monitor                              # noqa: E402
import netscan                                   # noqa: E402
import profinet                                  # noqa: E402
import github_auth                               # noqa: E402
import server                                    # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label:<52} {actual!r}")
        passed += 1
    else:
        print(f"  FAIL  {label:<52} got {actual!r} want {expected!r}")
        failed += 1


def ok(label, condition, detail=""):
    check(label, True, bool(condition)) if condition else check(label, True, detail or False)


# ── a server of our own ──────────────────────────────────────────────────────

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
PORT = httpd.server_port


# The write guard allows this server's OWN origin, which is now derived from the
# port it actually bound rather than a hardcoded 8787 - so the default here is the
# ephemeral port this suite is running on.
SELF_ORIGIN = f"http://127.0.0.1:{PORT}"


def request(method, path, body=None, origin=SELF_ORIGIN):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
            if origin:
                headers["Origin"] = origin
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        raw = response.read()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, None
    finally:
        conn.close()


def get(path):
    return request("GET", path)


def post(path, body, origin=SELF_ORIGIN):
    return request("POST", path, body, origin)


# ── a broker that says just enough ───────────────────────────────────────────

class StubBroker:
    """CONNACK, SUBACK, then publish. Records what the client actually sent."""

    def __init__(self, connack=0, refuse=False):
        self.connack = connack
        self.refuse = refuse
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self.seen = []
        self.connections = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def start(self):
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def close(self):
        self.stop.set()
        try:
            self.listener.close()
        except OSError:
            pass

    def _accept(self):
        while not self.stop.is_set():
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            with self.lock:
                self.connections += 1
            threading.Thread(target=self._session, args=(sock,), daemon=True).start()

    def _read(self, sock):
        head = sock.recv(1)
        if not head:
            raise ConnectionError
        length, shift = 0, 0
        while True:
            byte = sock.recv(1)[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        body = b""
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                raise ConnectionError
            body += chunk
        return head[0] >> 4, body

    def _session(self, sock):
        try:
            kind, _ = self._read(sock)
            with self.lock:
                self.seen.append(kind)
            sock.sendall(bytes([mqtt.CONNACK << 4, 2, 0, self.connack]))
            if self.connack:
                return
            kind, body = self._read(sock)
            with self.lock:
                self.seen.append(kind)
            packet_id = struct.unpack("!H", body[:2])[0]
            granted = 0x80 if self.refuse else 0
            sock.sendall(bytes([mqtt.SUBACK << 4, 3]) + struct.pack("!H", packet_id)
                         + bytes([granted]))
            if self.refuse:
                time.sleep(5)
                return
            for index in range(6):
                for topic, value, retain in [
                        ("plant/line1/temp", f"{20 + index}.0", False),
                        ("plant/line1/state", "RUN", True)]:
                    raw = topic.encode()
                    payload = struct.pack("!H", len(raw)) + raw + value.encode()
                    sock.sendall(bytes([(mqtt.PUBLISH << 4) | (0x01 if retain else 0)])
                                 + mqtt._remaining_length(len(payload)) + payload)
                time.sleep(0.15)
            while not self.stop.is_set():
                time.sleep(0.2)
        except (OSError, ConnectionError, IndexError):
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass


def until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


# ═══════════════════════════════════════════════════════════ MQTT monitor ════

print("--- MQTT monitor: validation happens before a socket is opened ---")
for label, body, message in [
        ("no host", {}, "invalid host"),
        ("host with a scheme", {"host": "tcp://x"}, "invalid host"),
        ("port out of range", {"host": "b", "port": 70000}, "invalid port"),
        ("unknown field", {"host": "b", "wat": 1}, "unknown fields: wat"),
        ("too many filters", {"host": "b", "filters": [str(i) for i in range(20)]},
         "filters must be a list of 1 to 16 topic filters"),
        ("duplicate filter", {"host": "b", "filters": ["a/#", "a/#"]}, "duplicate topic filter"),
        ("bad client id", {"host": "b", "client_id": "a b"},
         "client_id must be 1-23 characters of A-Z a-z 0-9 . _ : -")]:
    status, payload = post("/api/mqtt/monitor", body)
    check(f"{label} -> 400", 400, status)
    check(f"{label} says why", message, (payload or {}).get("error"))

check("wildcards ARE allowed as a monitor filter", "#",
      mqtt_monitor.validate({"host": "b"})["filters"][0])

print("--- MQTT monitor: a real session, a topic tree, and retained flags ---")
broker = StubBroker().start()
status, payload = post("/api/mqtt/monitor",
                       {"host": "127.0.0.1", "port": broker.port, "filters": ["plant/#"]})
check("monitor accepted -> 200", 200, status)
ok("the session starts before the request returns", payload["state"] in ("connecting", "connected"))

ok("the broker is reached", until(lambda: get("/api/mqtt/monitor")[1]["state"] == "connected"))
ok("messages arrive", until(lambda: get("/api/mqtt/monitor")[1]["received"] >= 8))
snapshot = get("/api/mqtt/monitor?limit=50")[1]
check("both topics are in the tree", 2, snapshot["topic_count"])
check("the filter was granted", {"plant/#": "qos 0"}, snapshot["granted"])
topics = {row["topic"]: row for row in snapshot["topics"]}
check("a retained publish is reported as retained", True, topics["plant/line1/state"]["retain"])
check("a live publish is not", False, topics["plant/line1/temp"]["retain"])
ok("each topic counts its own messages", topics["plant/line1/temp"]["count"] >= 4)
ok("the latest value is the latest one published",
   topics["plant/line1/temp"]["value"] in [f"{20 + i}.0" for i in range(6)])
ok("every value carries when it arrived", topics["plant/line1/temp"]["at"] > 0)

tree = snapshot["tree"]
check("the tree folds on '/'", "plant", tree[0]["segment"])
check("and keeps a count per branch", 2, tree[0]["count"])
check("leaves sit under their branch", ["state", "temp"],
      sorted(node["segment"] for node in tree[0]["children"][0]["children"]))
check("a branch node carries no value of its own", None, tree[0]["leaf"])

check("the log is newest first", True,
      snapshot["messages"][0]["seq"] > snapshot["messages"][-1]["seq"])
ok("the log filters by topic",
   all("temp" in row["topic"] for row in get("/api/mqtt/monitor?q=temp")[1]["messages"]))

print("--- MQTT monitor: clearing, stopping, and what a restart does ---")
status, payload = post("/api/mqtt/monitor/clear", {})
check("clear -> 200", 200, status)
check("the topic tree is emptied", 0, payload["topic_count"])
check("but the session is still up", "connected", payload["state"])
status, payload = post("/api/mqtt/monitor/stop", {})
check("stop -> 200", 200, status)
check("and the monitor reports it", "stopped", payload["state"])
before = broker.connections
time.sleep(1.5)
check("a stopped monitor opens no further connections", before, broker.connections)

print("--- MQTT monitor: a broker that refuses is reported, not retried silently ---")
refuser = StubBroker(connack=5).start()
post("/api/mqtt/monitor", {"host": "127.0.0.1", "port": refuser.port})
# Paho's own wording for the MQTT 3.1.1 CONNACK codes - "Not authorized" for 5,
# "Bad user name or password" for 4. Asserted as the client actually spells it
# rather than as this file would have phrased it, because the operator reads the
# client's words, not ours.
ok("CONNACK 5 surfaces as the broker's own reason",
   until(lambda: "Not authorized" in (get("/api/mqtt/monitor")[1]["error"] or "")),
   get("/api/mqtt/monitor")[1]["error"])
ok("and it is reported as a refusal, not a transport error",
   "refused the connection" in (get("/api/mqtt/monitor")[1]["error"] or ""))
post("/api/mqtt/monitor/stop", {})
refuser.close()

rejector = StubBroker(refuse=True).start()
post("/api/mqtt/monitor", {"host": "127.0.0.1", "port": rejector.port, "filters": ["a/#"]})
ok("a refused subscription is reported per filter",
   until(lambda: get("/api/mqtt/monitor")[1]["granted"].get("a/#") == "refused"
         or "refused every topic filter" in (get("/api/mqtt/monitor")[1]["error"] or "")))
post("/api/mqtt/monitor/stop", {})
rejector.close()
broker.close()

print("--- MQTT monitor: the caps bound the DISPLAY, never the session ---")


class FakeMessage:
    """What Paho hands on_message. Only the four fields the monitor reads."""

    def __init__(self, topic, payload, qos=0, retain=False):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else payload.encode()
        self.qos = qos
        self.retain = retain


monitor = mqtt_monitor.Monitor(Path(HOME) / "unused.json", autostart=False)
for index in range(mqtt_monitor.MAX_TOPICS + 5):
    monitor._on_message(None, None, FakeMessage(f"t/{index}", "x"))
snapshot = monitor.snapshot()
check("the topic tree stops at the cap", mqtt_monitor.MAX_TOPICS, snapshot["topic_count"])
check("and says how many it refused", 5, snapshot["dropped_topics"])
monitor.close()

# A fresh monitor: the one above is deliberately at its topic cap, so a new topic
# would be refused rather than recorded.
#
# THE POINT OF THIS SECTION. The old hand-written client capped the PACKET at 64
# KiB and raised when a broker exceeded it - which a real zigbee2mqtt bridge does,
# with a 217 KB retained message, on every single re-subscribe. The cap now bounds
# only what is STORED FOR DISPLAY, so an oversized message costs detail and never
# the session.
truncating = mqtt_monitor.Monitor(Path(HOME) / "unused2.json", autostart=False)
oversized = "y" * 300_000
truncating._on_message(None, None, FakeMessage("big", oversized))
record = truncating.snapshot(topic_filter="big")["topics"][0]
check("a 300 KB payload is accepted, not refused", 1, record["count"])
check("it is flagged as truncated", True, record["truncated"])
check("cut to the display cap", mqtt_monitor.MAX_VALUE_BYTES, len(record["value"]))
check("while the real size is still reported", len(oversized), record["bytes"])
check("and the monitor is still usable afterwards", 2, (
    truncating._on_message(None, None, FakeMessage("after", "ok")) or
    truncating.snapshot()["topic_count"]))
truncating.close()

print("--- MQTT monitor: QoS and retain survive the round trip ---")
flags = mqtt_monitor.Monitor(Path(HOME) / "unused3.json", autostart=False)
flags._on_message(None, None, FakeMessage("a/live", "1", qos=0, retain=False))
flags._on_message(None, None, FakeMessage("a/stored", "2", qos=1, retain=True))
rows = {r["topic"]: r for r in flags.snapshot()["topics"]}
check("a live publish is not retained", False, rows["a/live"]["retain"])
check("a stored one is", True, rows["a/stored"]["retain"])
check("and its QoS is carried through", 1, rows["a/stored"]["qos"])
flags.close()

print("--- MQTT monitor: topic filters are checked against MQTT's own rules ---")
for bad, why in [("a/#/b", "'#' must be the last level"),
                 ("a/#b", "'#' must be the last level"),
                 ("a/b+/c", "'+' must occupy a whole level"),
                 ("", "may not be empty")]:
    try:
        mqtt_monitor.check_topic_filter(bad)
        check(f"{bad!r} is refused", True, False)
    except mqtt_monitor.Invalid as err:
        ok(f"{bad!r} is refused", why in str(err), str(err))
for good in ("#", "a/#", "a/+/b", "+/+", "plant/line1/temp"):
    ok(f"{good!r} is accepted", mqtt_monitor.check_topic_filter(good) == good)

print("--- MQTT monitor: credentials are read from disk, never from a request ---")
secret = Path(HOME) / "mqtt-auth.json"
secret.write_text(json.dumps({"broker.example:8883": {
    "username": "ccc", "password": "hunter2", "tls": True}}), encoding="utf-8")
if os.name != "nt":
    os.chmod(secret, 0o600)
store = mqtt_monitor.AuthStore(secret)
described = store.describe("broker.example", 8883)
check("the panel is told a credential EXISTS", True, described["username"])
check("and that a password is set", True, described["password"])
ok("but never its value", "hunter2" not in json.dumps(described))
entry, problem = store.for_broker("broker.example", 8883)
check("the client itself can read it", "hunter2", entry["password"])
check("an unconfigured broker reports nothing", False,
      store.describe("other.example", 1883)["configured"])
status, payload = post("/api/mqtt/monitor", {"host": "b", "port": 1883,
                                             "username": "x", "password": "y"})
check("a request may not carry credentials at all", 400, status)
ok("and is told so", "unknown fields" in (payload or {}).get("error", ""),
   (payload or {}).get("error"))
if os.name != "nt":
    os.chmod(secret, 0o644)
    check("a world-readable credential file is refused, not used", {},
          mqtt_monitor.AuthStore(secret).for_broker("broker.example", 8883)[0])
    ok("and says how to fix it",
       "chmod 600" in (mqtt_monitor.AuthStore(secret).for_broker("broker.example", 8883)[1] or ""))
    secret.unlink()

# ═══════════════════════════════════════════════════════════════ scanner ═════

print("--- scanner: MAC addresses, and saying where they came from ---")
table, source = netscan.neighbour_table()
ok("a neighbour table is readable", isinstance(table, dict), table)
ok("and its source is named", isinstance(source, str) and source, source)
check("the IEEE registry is loaded from the vendored file", True,
      len(netscan._oui_registry()) > 30000)
# Host portion is deliberately 00:00:01 - the OUI is public IEEE data, a full MAC
# off somebody's network is a device fingerprint and this repo is public.
check("a consumer OUI resolves", "CANON", netscan.vendor_for("dc:c2:c9:00:00:01"))
check("an industrial override still wins over the registry", "WAGO",
      netscan.vendor_for("00:30:de:11:22:33"))
check("an unassigned OUI is not guessed at", None, netscan.vendor_for("ff:ff:ff:00:00:00"))
check("and no MAC means no vendor", None, netscan.vendor_for(None))
check("a short string is not indexed into", None, netscan.vendor_for("00:11"))

print("--- scanner: the range guard runs before any socket opens ---")
for label, body, fragment in [
        ("a public range", {"range": "8.8.8.0/24", "actor": "nick"}, "only private ranges"),
        ("a range too large", {"range": "10.0.0.0/8", "actor": "nick"}, "exceeds the 1024"),
        ("no actor", {"range": "127.0.0.0/30"}, "operator name is required"),
        ("a bad actor", {"range": "127.0.0.0/30", "actor": "nick; rm -rf /"},
         "operator name is required"),
        ("nonsense", {"range": "not-a-network", "actor": "nick"}, "not a network"),
        ("IPv6", {"range": "fd00::/120", "actor": "nick"}, "IPv4 only"),
        ("an unknown field", {"range": "127.0.0.0/30", "actor": "nick", "x": 1}, "unknown fields"),
        ("a bad port", {"range": "127.0.0.0/30", "actor": "nick", "ports": [0]},
         "each port must be an integer"),
        ("too many ports", {"range": "127.0.0.0/30", "actor": "nick",
                            "ports": list(range(1, 30))}, "ports must be a list")]:
    status, payload = post("/api/netscan/start", body)
    check(f"{label} -> 400", 400, status)
    ok(f"{label} says why", fragment in (payload or {}).get("error", ""),
       (payload or {}).get("error"))

for allowed in ("10.1.2.0/30", "172.16.5.0/30", "192.168.9.0/30", "169.254.1.0/30",
                "100.64.0.0/30", "127.0.0.1/32"):
    ok(f"{allowed} is scannable", bool(netscan.check_range(allowed)))

print("--- scanner: a real sweep of loopback finds this very server ---")
status, payload = post("/api/netscan/start",
                       {"range": "127.0.0.1/32", "ports": [PORT, 9], "actor": "nick"})
check("scan accepted -> 200", 200, status)
check("and reports what it was asked to do", str(PORT),
      str(payload["request"]["ports"][0]))
ok("the scan finishes", until(lambda: get("/api/netscan")[1]["state"] == "done", 30))
result = get("/api/netscan")[1]
check("one host answered", 1, len(result["hosts"]))
check("on exactly the open port", [PORT], [p["port"] for p in result["hosts"][0]["ports"]])
check("and the closed one is absent", False, 9 in [p["port"] for p in result["hosts"][0]["ports"]])
check("progress is complete", (1, 1), (result["scanned"], result["total"]))

status, payload = post("/api/netscan/start", {"range": "127.0.0.1/32", "actor": "nick"})
ok("a second scan is allowed once the first has finished", status == 200)
ok("but not two at once", post("/api/netscan/start",
   {"range": "127.0.0.1/32", "actor": "nick"})[1]["error"].startswith("a scan is already"))
post("/api/netscan/stop", {})

check("the scan reports how many MACs it resolved", True,
      "resolved" in get("/api/netscan")[1])
check("and whether it is behind a NAT", True, "under_wsl" in get("/api/netscan")[1])

# ══════════════════════════════════════════════════════════════ PROFINET ═════

print("--- PROFINET: the schema refuses what it exists to detect ---")
for label, body, fragment in [
        ("a station with no MAC", {"stations": [{"name": "a"}]}, "MAC address like"),
        ("a malformed MAC", {"stations": [{"mac": "zz:zz"}]}, "MAC address like"),
        ("an invalid station name", {"stations": [{"mac": "00:11:22:33:44:55", "name": "Bad_Name"}]},
         "is not a valid PROFINET station name"),
        ("a bad IP", {"stations": [{"mac": "00:11:22:33:44:55", "ip": "300.1.1.1"}]},
         "is not an IPv4 address"),
        ("a duplicate MAC", {"stations": [{"mac": "00:11:22:33:44:55"},
                                          {"mac": "00:11:22:33:44:55"}]}, "duplicate MAC"),
        ("two stations with one name",
         {"stations": [{"mac": "00:11:22:33:44:55", "name": "x"},
                       {"mac": "00:11:22:33:44:66", "name": "x"}]}, "share a station name"),
        ("an unknown field", {"stations": [], "wat": 1}, "unknown fields")]:
    status, payload = post("/api/profinet/schema", body)
    check(f"{label} -> 400", 400, status)
    ok(f"{label} says why", fragment in (payload or {}).get("error", ""),
       (payload or {}).get("error"))

schema = {"segment": "cell-3", "stations": [
    {"mac": "00:1B:1B:00:00:01", "name": "drive-a", "ip": "192.168.1.11", "role": "drive"},
    {"mac": "00:0f:8f:00:00:02", "name": "io-b", "ip": "192.168.1.12"}]}
status, payload = post("/api/profinet/schema", schema)
check("a valid schema is accepted", 200, status)
check("MACs are normalised to lower case", "00:1b:1b:00:00:01",
      payload["schema"]["stations"][0]["mac"])

print("--- PROFINET: reconciliation joins on MAC, and orders by what needs doing ---")
status, payload = post("/api/profinet/snapshot", {"actor": "nick", "records": [
    {"kind": "dcp-identify", "mac": "00:1b:1b:00:00:01", "name": "drive-a",
     "ip": "192.168.1.99"},
    {"kind": "dcp-identify", "mac": "aa:bb:cc:dd:ee:ff", "name": "stranger"}]})
check("the snapshot is accepted", 200, status)
check("counts are per status", {"mismatch": 1, "missing": 1, "unexpected": 1, "match": 0},
      payload["reconciliation"]["counts"])
rows = payload["reconciliation"]["rows"]
check("what needs attention is first", ["mismatch", "missing", "unexpected"],
      [row["status"] for row in rows])
check("and the differing field is named", ["ip"], rows[0]["differences"])
ok("the import records who and when", payload["imported_by"] == "nick"
   and payload["imported_at"] > 0)

status, payload = post("/api/profinet/snapshot", {"records": [{"kind": "wrong", "mac": "a"}]})
check("a non-DCP record is refused", 400, status)
ok("and named by line", "record 1" in payload["error"], payload["error"])

# A renamed device must read as a MISMATCH, not as one missing plus one unexpected:
# joining on the station name would produce exactly that, which is the failure this
# panel exists to make obvious.
post("/api/profinet/snapshot", {"records": [
    {"kind": "dcp-identify", "mac": "00:1b:1b:00:00:01", "name": "drive-typo",
     "ip": "192.168.1.11"}]})
rows = get("/api/profinet")[1]["reconciliation"]["rows"]
renamed = [row for row in rows if row["mac"] == "00:1b:1b:00:00:01"]
check("a renamed station is one mismatch, not two rows", 1, len(renamed))
check("and the name is the difference", ["name"], renamed[0]["differences"])

print("--- PROFINET: the schema survives a restart ---")
reloaded = profinet.Schema(Path(HOME) / "profinet-stations.json")
check("stations are persisted", 2, len(reloaded.state()["schema"]["stations"]))
check("and so is the last import", 1, len(reloaded.state()["snapshot"]))

# ════════════════════════════════════════════════════════════════ GitHub ═════

print("--- GitHub: reads never carry a credential ---")
status, payload = get("/api/github/auth")
check("the account endpoint answers", 200, status)
blob = json.dumps(payload)
ok("no token-shaped string is returned", not any(
    marker in blob for marker in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_")))
ok("no field is called token", "token" not in blob.lower())
for key in ("cli", "authenticated", "can_login", "scopes", "hostname"):
    ok(f"the account reports {key}", key in payload["account"])
for key in ("state", "code", "url", "available", "command"):
    ok(f"the sign-in reports {key}", key in payload["login"])

print("--- GitHub: writes need an actor and an explicit confirmation ---")
for label, path, body, fragment in [
        ("repo with no actor", "/api/github/repo", {"name": "x", "confirm": True},
         "operator name is required"),
        ("repo with no confirmation", "/api/github/repo", {"name": "x", "actor": "nick"},
         "requires an explicit confirmation"),
        ("repo with a bad name", "/api/github/repo",
         {"name": "x y", "actor": "nick", "confirm": True}, "repository name may use"),
        ("repo with an injected flag", "/api/github/repo",
         {"name": "--public", "actor": "nick", "confirm": True}, "repository name may use"),
        ("repo with a bad owner", "/api/github/repo",
         {"name": "x", "owner": "a/b", "actor": "nick", "confirm": True}, "owner must be"),
        ("repo with a bad visibility", "/api/github/repo",
         {"name": "x", "visibility": "secret", "actor": "nick", "confirm": True},
         "visibility must be"),
        ("repo with an unknown field", "/api/github/repo",
         {"name": "x", "actor": "nick", "confirm": True, "wat": 1}, "unknown fields"),
        ("issue with no repo", "/api/github/issue",
         {"title": "t", "actor": "nick", "confirm": True}, "owner/name"),
        ("issue with a bare repo name", "/api/github/issue",
         {"repo": "justname", "title": "t", "actor": "nick", "confirm": True}, "owner/name"),
        ("issue with no title", "/api/github/issue",
         {"repo": "a/b", "actor": "nick", "confirm": True}, "title of 1 to 250"),
        ("issue with a bad label", "/api/github/issue",
         {"repo": "a/b", "title": "t", "labels": ["--bad;"], "actor": "nick", "confirm": True},
         "a label may use")]:
    status, payload = post(path, body, origin=None)
    check(f"{label} -> 400", 400, status)
    ok(f"{label} says why", fragment in (payload or {}).get("error", ""),
       (payload or {}).get("error"))

print("--- GitHub: sign-in needs an actor, and a GET cannot start one ---")
status, payload = post("/api/github/login", {})
ok("an unnamed sign-in is refused", status in (400, 503), (status, payload))
check("GET on a write endpoint is 405", 405, get("/api/github/repo")[0])
check("GET on the scanner's start verb is 405", 405, get("/api/netscan/start")[0])
check("GET on the schema write is 405", 405, get("/api/profinet/schema")[0])

print("--- every write endpoint still enforces the same-origin JSON preflight ---")
for path in ("/api/mqtt/monitor", "/api/netscan/start", "/api/profinet/schema",
             "/api/github/repo"):
    status, _ = post(path, {}, origin="http://evil.example")
    check(f"{path} rejects a foreign origin", 403, status)
    # Another loopback port is still a DIFFERENT origin, and must be refused. This
    # is the check that keeps "derive the origin from the bound port" honest: a
    # guard that accepted any 127.0.0.1 origin would let a page served by some other
    # local process drive this one.
    status, _ = post(path, {}, origin="http://127.0.0.1:1")
    check(f"{path} rejects another local port", 403, status)

status, _ = post("/api/profinet/schema", {"stations": []}, origin=f"http://localhost:{PORT}")
check("but localhost on the same port is the same origin", 200, status)
status, _ = post("/api/profinet/schema", {"stations": []}, origin=None)
check("and a request with no Origin at all is allowed", 200, status)

httpd.shutdown()
httpd.server_close()
if server._mqtt_monitor is not None:
    server._mqtt_monitor.close()
# Leave nothing behind: check_test_residue.sh exists because a suite that writes
# into the operator's home and says nothing is worse than one that fails.
shutil.rmtree(HOME, ignore_errors=True)
print(f"\npassed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
