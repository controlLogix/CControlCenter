#!/usr/bin/env python3
"""Verify the MQTT endpoints against a stub broker, and the BOOTP parser.

    python3 dashboard/test_mqtt.py        # needs the dashboard running on 8787

There is no MQTT broker on this machine, so rather than claim an untested publish
works, this starts a minimal MQTT 3.1.1 server on a loopback port and asserts on
the bytes it actually receives. The stub is deliberately dumb: it speaks only
enough of the protocol to prove the client's framing is correct.
"""

import json
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mqtt                                      # noqa: E402
# taskmgmt/ is a plain directory, not a package, so load the module by path.
import importlib.util                            # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "bootp_probe", Path(__file__).resolve().parent.parent / "taskmgmt" / "bootp_probe.py")
bootp_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootp_probe)

BASE = "http://127.0.0.1:8787"
passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label:<44} {actual!r}")
        passed += 1
    else:
        print(f"  FAIL  {label:<44} got {actual!r} want {expected!r}")
        failed += 1


def post(path, body, ctype="application/json", origin=None):
    """Returns (status, parsed-json-or-None)."""
    data = json.dumps(body).encode()
    request = urllib.request.Request(f"{BASE}/{path}", data=data, method="POST")
    if ctype:
        request.add_header("Content-Type", ctype)
    if origin:
        request.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, None
    except urllib.error.URLError as err:
        return 0, {"error": str(err)}


def get_status(path):
    try:
        with urllib.request.urlopen(f"{BASE}/{path}", timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code


# ───────────────────────────────── stub broker ─────────────────────────────────

class StubBroker(threading.Thread):
    """Minimal MQTT 3.1.1 server. Records what the client sent."""

    daemon = True

    def __init__(self, publish_on_subscribe=None, connack_code=0):
        super().__init__()
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self.publish_on_subscribe = publish_on_subscribe
        self.connack_code = connack_code
        self.received = []          # list of (kind, flags, body)
        self.error = None

    def run(self):
        try:
            while True:
                conn, _ = self.listener.accept()
                threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
        except OSError:
            pass

    def _serve(self, conn):
        conn.settimeout(10)
        buf = b""

        def need(count):
            nonlocal buf
            while len(buf) < count:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError("client closed")
                buf += chunk
            out, buf = buf[:count], buf[count:]
            return out

        try:
            while True:
                header = need(1)[0]
                length, shift = 0, 0
                while True:
                    byte = need(1)[0]
                    length |= (byte & 0x7F) << shift
                    if not byte & 0x80:
                        break
                    shift += 7
                body = need(length) if length else b""
                kind, flags = header >> 4, header & 0x0F
                self.received.append((kind, flags, body))

                if kind == mqtt.CONNECT:
                    conn.sendall(bytes([mqtt.CONNACK << 4, 2, 0, self.connack_code]))
                    if self.connack_code:
                        return
                elif kind == mqtt.SUBSCRIBE:
                    packet_id = body[:2]
                    conn.sendall(bytes([mqtt.SUBACK << 4, 3]) + packet_id + bytes([0]))
                    if self.publish_on_subscribe:
                        topic, payload = self.publish_on_subscribe
                        raw = topic.encode()
                        packet = (struct.pack("!H", len(raw)) + raw + payload.encode())
                        conn.sendall(bytes([mqtt.PUBLISH << 4, len(packet)]) + packet)
                elif kind == mqtt.DISCONNECT:
                    return
        except (OSError, ConnectionError, IndexError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        try:
            self.listener.close()
        except OSError:
            pass

    def packets(self, kind):
        return [p for p in self.received if p[0] == kind]


def wait_for(predicate, timeout=3.0):
    """Poll a predicate about the broker thread. Returns whether it became true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def decode_publish_body(body):
    topic_len = struct.unpack("!H", body[:2])[0]
    return body[2:2 + topic_len].decode(), body[2 + topic_len:].decode()


# ──────────────────────────────────── tests ────────────────────────────────────

print("--- guards (no broker needed) ---")
check("GET publish", 405, get_status("api/mqtt/publish"))
check("GET subscribe", 405, get_status("api/mqtt/subscribe"))
check("no JSON content type", 415,
      post("api/mqtt/publish", {"host": "h", "port": 1883, "topic": "t", "payload": ""},
           ctype=None)[0])
check("cross-origin Origin", 403,
      post("api/mqtt/publish", {"host": "h", "port": 1883, "topic": "t", "payload": ""},
           origin="https://evil.example")[0])
check("unknown field", 400,
      post("api/mqtt/publish", {"host": "h", "port": 1883, "topic": "t", "wat": 1})[0])

print("--- input validation (must reject before opening a socket) ---")
for label, body, want in [
    ("bad host", {"host": "a b", "port": 1883, "topic": "t", "payload": ""}, "invalid host"),
    ("host with scheme", {"host": "tcp://h", "port": 1883, "topic": "t", "payload": ""},
     "invalid host"),
    ("port 0", {"host": "h", "port": 0, "topic": "t", "payload": ""}, "invalid port"),
    ("port as string", {"host": "h", "port": "1883", "topic": "t", "payload": ""},
     "invalid port"),
    ("port too big", {"host": "h", "port": 70000, "topic": "t", "payload": ""},
     "invalid port"),
    ("empty topic", {"host": "h", "port": 1883, "topic": "", "payload": ""},
     "invalid topic"),
    ("wildcard publish +", {"host": "h", "port": 1883, "topic": "a/+", "payload": ""},
     "cannot publish to a wildcard topic"),
    ("wildcard publish #", {"host": "h", "port": 1883, "topic": "a/#", "payload": ""},
     "cannot publish to a wildcard topic"),
    ("oversize payload", {"host": "h", "port": 1883, "topic": "t", "payload": "x" * 5000},
     None),
]:
    status, payload = post("api/mqtt/publish", body)
    if want is None:
        # 5000 bytes of payload exceeds the body cap, so this is rejected at the
        # HTTP layer before the payload check ever runs. Either is a correct reject.
        check(label, True, status in (400, 413))
    else:
        check(label, (400, want), (status, (payload or {}).get("error")))

print("--- wildcards ARE allowed on subscribe ---")
status, payload = post("api/mqtt/subscribe", {"host": "127.0.0.1", "port": 1, "topic": "a/#"})
check("wildcard subscribe reaches the broker step", 502, status)

print("--- unreachable broker: 502 with a reason, no hang ---")
status, payload = post("api/mqtt/publish",
                       {"host": "127.0.0.1", "port": 1, "topic": "t", "payload": "x"})
check("unreachable -> 502", 502, status)
check("names a reason", True,
      bool((payload or {}).get("error")) and "127.0.0.1:1" in payload["error"])

print("--- a rejected request must not leak a slot ---")
# Nine 400s were just issued. With a 4-slot pool, an acquire placed before
# validation exhausts it and every later request 503s. Proving a slot is still
# available here is the regression guard.
broker0 = StubBroker()
broker0.start()
status, _ = post("api/mqtt/publish",
                 {"host": "127.0.0.1", "port": broker0.port, "topic": "t", "payload": "x"})
check("slot still available after 9 rejections", 200, status)
broker0.stop()

print("--- publish against a stub broker ---")
broker = StubBroker()
broker.start()
status, payload = post("api/mqtt/publish",
                       {"host": "127.0.0.1", "port": broker.port,
                        "topic": "plant/line1/temp", "payload": "21.5"})
check("publish -> 200", 200, status)
check("detail says unacknowledged", True, "unacknowledged" in (payload or {}).get("detail", ""))
connects = broker.packets(mqtt.CONNECT)
check("broker got exactly one CONNECT", 1, len(connects))
if connects:
    body = connects[0][2]
    check("protocol name is MQTT", b"MQTT", body[2:6])
    check("protocol level is 4 (3.1.1)", 4, body[6])
    check("clean-session flag set", 0x02, body[7])
    check("keepalive is 15s", 15, struct.unpack("!H", body[8:10])[0])
publishes = broker.packets(mqtt.PUBLISH)
check("broker got exactly one PUBLISH", 1, len(publishes))
if publishes:
    check("PUBLISH flags are QoS 0", 0, publishes[0][1])
    check("topic and payload round-trip", ("plant/line1/temp", "21.5"),
          decode_publish_body(publishes[0][2]))
check("client sent DISCONNECT", True,
      wait_for(lambda: len(broker.packets(mqtt.DISCONNECT)) == 1))
broker.stop()

print("--- subscribe against a stub broker ---")
broker2 = StubBroker(publish_on_subscribe=("plant/line1/temp", "22.0"))
broker2.start()
status, payload = post("api/mqtt/subscribe",
                       {"host": "127.0.0.1", "port": broker2.port, "topic": "plant/#"})
check("subscribe -> 200", 200, status)
# qos/retain/bytes came in with the topic monitor, which needs to show whether a
# value is a live publish or a retained one the broker replayed at connect. The
# bounded subscribe shares the decoder, so it reports them too.
check("delivered the broker's message",
      [{"topic": "plant/line1/temp", "payload": "22.0",
        "qos": 0, "retain": False, "bytes": 4}], (payload or {}).get("messages"))
subs = broker2.packets(mqtt.SUBSCRIBE)
check("broker got one SUBSCRIBE", 1, len(subs))
if subs:
    check("SUBSCRIBE flags are 0x02 (required)", 0x02, subs[0][1])
check("client sent UNSUBSCRIBE", True,
      wait_for(lambda: len(broker2.packets(mqtt.UNSUBSCRIBE)) == 1))
broker2.stop()

print("--- broker refusal is reported, not swallowed ---")
broker3 = StubBroker(connack_code=5)          # not authorised
broker3.start()
status, payload = post("api/mqtt/publish",
                       {"host": "127.0.0.1", "port": broker3.port, "topic": "t",
                        "payload": "x"})
check("CONNACK 5 -> 502", 502, status)
check("reports 'not authorised'", True, "not authorised" in (payload or {}).get("error", ""))
check("no PUBLISH was sent after refusal", 0, len(broker3.packets(mqtt.PUBLISH)))
broker3.stop()

print("--- control characters are stripped from inbound payloads ---")
broker4 = StubBroker(publish_on_subscribe=("t/\x1b[31m", "val\x1b[0m\x07"))
broker4.start()
status, payload = post("api/mqtt/subscribe",
                       {"host": "127.0.0.1", "port": broker4.port, "topic": "t/#"})
messages = (payload or {}).get("messages") or [{}]
check("escape bytes removed from payload", "val[0m", messages[0].get("payload"))
check("escape bytes removed from topic", "t/[31m", messages[0].get("topic"))
broker4.stop()

print("--- BOOTP parser (no root needed) ---")


def dhcp_discover(mac="00:1d:9c:c7:b0:1a", hostname="wago-750", requested="10.0.0.42"):
    packet = bytearray(240)
    packet[0] = 1                                        # BOOTREQUEST
    packet[1] = 1                                        # ethernet
    packet[2] = 6                                        # hlen
    packet[4:8] = struct.pack("!I", 0xDEADBEEF)          # xid
    packet[28:34] = bytes(int(b, 16) for b in mac.split(":"))
    options = bytearray(bootp_probe.DHCP_MAGIC)
    options += bytes([bootp_probe.OPT_MESSAGE_TYPE, 1, 1])
    options += bytes([bootp_probe.OPT_HOSTNAME, len(hostname)]) + hostname.encode()
    options += bytes([bootp_probe.OPT_REQUESTED_IP, 4]) + socket.inet_aton(requested)
    options += bytes([bootp_probe.OPT_END])
    return bytes(packet[:236]) + bytes(options)


record = bootp_probe.parse_packet(dhcp_discover())
check("op", "BOOTREQUEST", record["op"])
check("mac", "00:1d:9c:c7:b0:1a", record["mac"])
check("xid", "0xdeadbeef", record["xid"])
check("dhcp type", "DISCOVER", record["dhcp_type"])
check("hostname", "wago-750", record["hostname"])
check("requested ip", "10.0.0.42", record["requested_ip"])
check("short datagram rejected", None, bootp_probe.parse_packet(b"\x01\x01\x06\x00"))
check("truncated option field survives", None,
      bootp_probe.parse_packet(bytes(236) + bootp_probe.DHCP_MAGIC + bytes([12, 40, 65]))
      ["hostname"])

print("--- the probe refuses to escalate and never replies ---")
source = Path("taskmgmt/bootp_probe.py").read_text(encoding="utf-8")
check("no sendto anywhere", 0, source.count("sendto"))
check("no sendall anywhere", 0, source.count("sendall"))
check("names the privilege it needs", True, "needs root" in source)
result = subprocess.run([sys.executable, "taskmgmt/bootp_probe.py", "--timeout", "1"],
                        capture_output=True, text=True, timeout=30)
check("unprivileged bind exits non-zero", True, result.returncode != 0)
# TWO WAYS THAT BIND FAILS, AND WHICH ONE YOU GET IS A PROPERTY OF THE MACHINE.
#
# EACCES when the port is free and we are not root - that is the path the "needs
# root" message serves. EADDRINUSE when something already holds UDP 67, which a DHCP
# client on the Windows host is enough to cause; inside WSL `ss -lunp` cannot even
# see the holder, so it looks like nothing is there.
#
# Asserting the privilege wording unconditionally made this suite pass or fail on the
# environment rather than on the probe: measured here as
# "cannot bind UDP 67: [Errno 98] Address already in use", failing identically on the
# pre-reset commit. What the probe owes the operator in EITHER case is the port and a
# reason, so that is what is checked. The privilege wording itself is already pinned
# by the source check above, which covers the EACCES branch without needing a machine
# that can reach it.
check("says which port it could not bind", True, "cannot bind UDP 67" in result.stderr)
check("and gives a reason for it", True,
      "needs root" in result.stderr or "[Errno" in result.stderr)

print("--- concurrency cap (grok finding 3) ---")


class SilentBroker(threading.Thread):
    """Accepts TCP and never answers. Makes the handler block on READ_TIMEOUT,
    which is what a black-holed broker does and what the slot cap exists for."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(32)
        self.port = self.listener.getsockname()[1]
        self.held = []

    def run(self):
        try:
            while True:
                conn, _ = self.listener.accept()
                self.held.append(conn)       # accept, then say nothing at all
        except OSError:
            pass

    def stop(self):
        for conn in self.held:
            try:
                conn.close()
            except OSError:
                pass
        try:
            self.listener.close()
        except OSError:
            pass


silent = SilentBroker()
silent.start()
codes = []
codes_lock = threading.Lock()


def hammer():
    status, _ = post("api/mqtt/publish",
                     {"host": "127.0.0.1", "port": silent.port, "topic": "t", "payload": "x"})
    with codes_lock:
        codes.append(status)


threads = [threading.Thread(target=hammer) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=40)
silent.stop()

# 4 slots, 10 requests, each slot held ~5s on the read timeout: the excess must be
# refused fast rather than piling up handler threads.
check("some requests were refused (503)", True, codes.count(503) > 0)
check("no request succeeded against a silent broker", 0, codes.count(200))
check("every request got an answer", 10, len(codes))
check("refusals + broker errors account for all", True,
      all(c in (502, 503) for c in codes))
print(f"        status codes: {sorted(codes)}")

print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
