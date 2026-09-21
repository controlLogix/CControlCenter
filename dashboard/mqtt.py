"""Minimal MQTT 3.1.1 client on the Python standard library.

WHY THIS EXISTS: the dashboard is stdlib-only (no pip, so no paho-mqtt), and the
IIOT view needs to publish a value and watch a topic. That is a small enough
subset of MQTT to implement honestly: CONNECT, PUBLISH at QoS 0, SUBSCRIBE at
QoS 0, UNSUBSCRIBE, DISCONNECT. Nothing else is claimed.

WHAT THIS IS NOT:
  - No TLS. Credentials and payloads cross the wire in the clear. The UI says so.
  - No username/password. Accepting them would mean a secret travelling from the
    browser, which this project does not do.
  - No QoS 1/2, no retained-message handling, no session resumption, no
    persistent subscription. `subscribe()` is a bounded poll that connects,
    listens for a few seconds, and disconnects - a long-lived broker socket per
    browser tab is not something an HTTP request handler should own.

Every call is bounded in time and in bytes: a hung or hostile broker must not
hold a server thread or grow memory without limit.
"""

import re
import socket
import struct
import time

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK = 1, 2, 3, 8, 9
UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP, DISCONNECT = 10, 11, 12, 13, 14

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 5.0
MAX_TOPIC_BYTES = 256
MAX_PAYLOAD_BYTES = 4096
MAX_PACKET_BYTES = 65536      # a single inbound packet we are willing to buffer
MAX_MESSAGES = 50
SUBSCRIBE_WINDOW = 3.0

# A hostname label or an IP literal. Deliberately strict: this string becomes the
# target of an outbound connection, so nothing shell-like, no scheme, no path, no
# userinfo, no port smuggled in.
HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?\Z")

CONNACK_REASONS = {
    0: "accepted",
    1: "broker refused: unacceptable protocol version",
    2: "broker refused: client id rejected",
    3: "broker refused: service unavailable",
    4: "broker refused: bad username or password",
    5: "broker refused: not authorised",
}


class MqttError(Exception):
    """A broker-level or protocol-level failure. Maps to HTTP 502."""


def _remaining_length(value):
    """Encode MQTT's 7-bit variable-length integer."""
    out = bytearray()
    while True:
        byte = value % 128
        value //= 128
        if value:
            byte |= 0x80
        out.append(byte)
        if not value:
            return bytes(out)


def _string(text):
    raw = text.encode("utf-8")
    if len(raw) > 0xFFFF:
        raise MqttError("string too long for MQTT")
    return struct.pack("!H", len(raw)) + raw


def _packet(kind, flags, body):
    return bytes([(kind << 4) | flags]) + _remaining_length(len(body)) + body


class Connection:
    """One short-lived MQTT session. Use as a context manager."""

    def __init__(self, host, port, client_id="ccc-dashboard"):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.sock = None
        self._buf = b""
        self._packet_id = 0

    # ------------------------------------------------------------ lifecycle --
    def __enter__(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), CONNECT_TIMEOUT)
        except socket.gaierror as err:
            raise MqttError(f"cannot resolve {self.host}") from err
        except (ConnectionRefusedError, TimeoutError, socket.timeout) as err:
            raise MqttError(f"cannot reach {self.host}:{self.port} ({type(err).__name__})") from err
        except OSError as err:
            raise MqttError(f"connect failed: {err.strerror or err}") from err
        self.sock.settimeout(READ_TIMEOUT)
        self._connect()
        return self

    def __exit__(self, *_):
        # Best-effort DISCONNECT: if the socket is already gone the broker will
        # time the session out on its own, so a failure here is not worth raising
        # over a result the caller has already obtained.
        try:
            if self.sock:
                self.sock.sendall(_packet(DISCONNECT, 0, b""))
        except OSError:
            pass
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        return False

    def _connect(self):
        body = (_string("MQTT")            # protocol name
                + bytes([4])               # protocol level: 3.1.1
                + bytes([0x02])            # flags: clean session, no will, no auth
                + struct.pack("!H", 15)    # keepalive seconds
                + _string(self.client_id))
        self._send(_packet(CONNECT, 0, body))
        kind, _flags, payload = self._read_packet()
        if kind != CONNACK or len(payload) < 2:
            raise MqttError("broker did not answer CONNECT with a valid CONNACK")
        code = payload[1]
        if code != 0:
            raise MqttError(CONNACK_REASONS.get(code, f"broker refused: CONNACK code {code}"))

    # ------------------------------------------------------------ operations --
    def publish(self, topic, payload):
        """PUBLISH at QoS 0. Returns the number of payload bytes written.

        QoS 0 is fire-and-forget: the broker sends no acknowledgement, so the
        honest claim is "written to the socket", not "delivered". Callers must not
        upgrade that to a delivery guarantee.
        """
        raw = payload.encode("utf-8")
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise MqttError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        self._send(_packet(PUBLISH, 0, _string(topic) + raw))
        return len(raw)

    def subscribe(self, topic, window=SUBSCRIBE_WINDOW, limit=MAX_MESSAGES):
        """SUBSCRIBE, collect for a bounded window, UNSUBSCRIBE. Returns a list."""
        self._packet_id = (self._packet_id + 1) & 0xFFFF or 1
        packet_id = self._packet_id
        self._send(_packet(SUBSCRIBE, 0x02,
                           struct.pack("!H", packet_id) + _string(topic) + bytes([0])))

        messages = []
        deadline = time.monotonic() + window
        while len(messages) < limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self.sock.settimeout(remaining)
                kind, flags, payload = self._read_packet()
            except (TimeoutError, socket.timeout):
                break
            if kind == SUBACK:
                if len(payload) >= 3 and payload[2] == 0x80:
                    raise MqttError(f"broker refused the subscription to {topic}")
                continue
            if kind == PINGREQ:
                self._send(_packet(PINGRESP, 0, b""))
                continue
            if kind != PUBLISH:
                continue
            messages.append(self._decode_publish(flags, payload))

        try:
            self._packet_id = (self._packet_id + 1) & 0xFFFF or 1
            self.sock.settimeout(READ_TIMEOUT)
            self._send(_packet(UNSUBSCRIBE, 0x02,
                               struct.pack("!H", self._packet_id) + _string(topic)))
        except (OSError, MqttError):
            pass   # we are about to disconnect anyway
        return messages

    @staticmethod
    def _decode_publish(flags, payload):
        if len(payload) < 2:
            raise MqttError("truncated PUBLISH")
        topic_len = struct.unpack("!H", payload[:2])[0]
        offset = 2 + topic_len
        if offset > len(payload):
            raise MqttError("PUBLISH topic length exceeds the packet")
        topic = payload[2:offset].decode("utf-8", "replace")
        qos = (flags >> 1) & 0x03
        if qos:
            # QoS 1/2 carry a packet id we skip. We never request above 0, but a
            # broker replaying a stored message could still send one.
            offset += 2
        body = payload[offset:] if offset <= len(payload) else b""
        return {"topic": topic, "payload": body.decode("utf-8", "replace")}

    # ------------------------------------------------------------------ wire --
    def _send(self, data):
        try:
            self.sock.sendall(data)
        except OSError as err:
            raise MqttError(f"send failed: {err.strerror or err}") from err

    def _recv(self, count):
        """Read exactly count bytes, or raise."""
        while len(self._buf) < count:
            try:
                # Over-reading is fine and cheaper: the surplus stays in _buf for
                # the next packet. The MAX_PACKET_BYTES cap bounds what we ask for.
                chunk = self.sock.recv(65536)
            except (TimeoutError, socket.timeout):
                raise
            except OSError as err:
                raise MqttError(f"read failed: {err.strerror or err}") from err
            if not chunk:
                raise MqttError("broker closed the connection")
            self._buf += chunk
        out, self._buf = self._buf[:count], self._buf[count:]
        return out

    def _read_packet(self):
        header = self._recv(1)[0]
        length, shift = 0, 0
        while True:
            byte = self._recv(1)[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 21:
                raise MqttError("malformed remaining-length field")
        if length > MAX_PACKET_BYTES:
            raise MqttError(f"packet of {length} bytes exceeds the {MAX_PACKET_BYTES} byte cap")
        return header >> 4, header & 0x0F, self._recv(length) if length else b""


# ------------------------------------------------------------- validation ----

def check_host(host):
    if not isinstance(host, str) or not HOST_RE.match(host):
        raise ValueError("invalid host")
    return host


def check_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return port


def check_topic(topic, allow_wildcards):
    if not isinstance(topic, str) or not topic:
        raise ValueError("invalid topic")
    raw = topic.encode("utf-8")
    if len(raw) > MAX_TOPIC_BYTES:
        raise ValueError(f"topic exceeds {MAX_TOPIC_BYTES} bytes")
    if "\x00" in topic or any(ord(c) < 0x20 or ord(c) == 0x7F for c in topic):
        raise ValueError("invalid topic")
    if not allow_wildcards and ("+" in topic or "#" in topic):
        # You cannot publish to a wildcard. Accepting one and doing nothing would
        # look like a successful publish that never arrives anywhere.
        raise ValueError("cannot publish to a wildcard topic")
    return topic


def check_payload(payload):
    if payload is None:
        return ""
    if not isinstance(payload, str):
        raise ValueError("payload must be a string")
    if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
    return payload
