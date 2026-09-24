#!/usr/bin/env python3
"""A four-verb MQTT broker, for tests that need something real to talk to.

    python3 dashboard/stub_broker.py [--port N] [--quiet]

WHY THIS EXISTS. There is no MQTT broker on this machine, and a topic browser
asserted against a mock of itself proves nothing. This speaks exactly enough of
MQTT 3.1.1 to be connected to and subscribed to - CONNACK, SUBACK, PUBLISH,
PINGRESP - and then publishes a small, predictable plant-shaped topic tree on a
timer so a test can watch it appear.

It is deliberately dumb. It does not check the client's framing beyond the packet
type, it never disconnects a client, and it holds every connection open until it
is killed. Anything it cannot do is something the tests must not rely on.

The topics it publishes are fixed so a test can assert on them by name:

    plant/line1/temp     a changing value,  not retained
    plant/line1/state    RUN / IDLE,        RETAINED
    plant/line2/press    a JSON payload,    not retained

The retained one is retained on purpose: "is this value live or did the broker
replay it at connect" is the distinction the browser has to get right, so there
has to be one of each on the wire.
"""

import argparse
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mqtt                                      # noqa: E402

TOPICS = [
    ("plant/line1/temp", lambda n: f"{20 + n % 10}.5", False),
    ("plant/line1/state", lambda n: "RUN" if n % 2 else "IDLE", True),
    ("plant/line2/press", lambda n: '{"bar": %d}' % (n % 7), False),
]


class StubBroker:
    def __init__(self, port=0, interval=0.3, quiet=False):
        self.interval = interval
        self.quiet = quiet
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()

    def serve_forever(self):
        if not self.quiet:
            print(f"stub broker on 127.0.0.1:{self.port}", flush=True)
        while not self.stop.is_set():
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(sock,), daemon=True).start()

    def close(self):
        self.stop.set()
        try:
            self.listener.close()
        except OSError:
            pass

    @staticmethod
    def _read(sock):
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
            if kind != mqtt.CONNECT:
                return
            sock.sendall(bytes([mqtt.CONNACK << 4, 2, 0, 0]))
            kind, body = self._read(sock)
            if kind != mqtt.SUBSCRIBE:
                return
            packet_id = struct.unpack("!H", body[:2])[0]
            # One granted-QoS byte per requested filter, which is what the client
            # counts to decide whether any of them were refused.
            filters = 0
            offset = 2
            while offset < len(body):
                size = struct.unpack("!H", body[offset:offset + 2])[0]
                offset += 2 + size + 1
                filters += 1
            sock.sendall(bytes([mqtt.SUBACK << 4, 2 + filters])
                         + struct.pack("!H", packet_id) + bytes(filters))
            count = 0
            while not self.stop.is_set():
                for topic, value, retain in TOPICS:
                    raw = topic.encode()
                    payload = struct.pack("!H", len(raw)) + raw + value(count).encode()
                    sock.sendall(bytes([(mqtt.PUBLISH << 4) | (0x01 if retain else 0)])
                                 + mqtt._remaining_length(len(payload)) + payload)
                count += 1
                time.sleep(self.interval)
        except (OSError, ConnectionError, IndexError, struct.error):
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0.3)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    broker = StubBroker(args.port, args.interval, args.quiet)
    try:
        broker.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        broker.close()


if __name__ == "__main__":
    main()
