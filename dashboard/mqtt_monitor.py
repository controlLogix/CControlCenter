"""A live MQTT topic monitor and browser, on the Eclipse Paho client.

WHAT THIS IS. One long-lived broker session per server, owned by Paho's own network
thread, feeding two views of the same traffic:

  - a TOPIC TREE: every topic seen, folded on '/', each leaf carrying its latest
    payload, when it arrived, how many times it has arrived, its QoS and whether
    it was retained. This is the "browse what is on this broker" half.
  - a MESSAGE LOG: a bounded ring of the most recent messages in arrival order,
    for watching a topic change rather than reading its current value.

WHY PAHO AND NOT dashboard/mqtt.py. The hand-written client in mqtt.py is fine for
the bounded publish/subscribe endpoints - connect, do one thing, disconnect - and
it still serves them. It was never adequate for a monitor, and a real broker proved
it: a zigbee2mqtt bridge publishes a 217 KB retained message, which exceeded that
client's 64 KB packet cap. The session raised, reconnected, received the same
retained message again on re-subscribe, and raised again. An unbreakable loop
against an ordinary broker, and the panel showed five topics forever.

Raising the cap would have moved the number, not fixed the class. A monitor has to
survive arbitrary packet sizes, speak TLS, carry credentials, handle QoS 1 and 2
flows it did not ask for, and back off sensibly across reconnects. Paho does all of
that and is the reference implementation. It is vendored - see vendor/README.md.

CREDENTIALS DO NOT COME FROM THE BROWSER, which is the rule everywhere else in this
dashboard and is not relaxed here. The page posts a host, a port and topic filters.
A username, a password or a TLS client key is read from an operator-owned file,
0600, keyed by host:port - never accepted over HTTP, never returned by any endpoint,
never logged. See AuthStore below.

BOUNDED IN EVERY DIRECTION. A broker publishing a million distinct topics must not
grow this process without limit, so the tree is capped at MAX_TOPICS and the log at
MAX_MESSAGES, each stored payload is truncated at MAX_VALUE_BYTES, and the overflow
is REPORTED rather than hidden - a browser showing 2000 of 40000 topics must say so
or it is lying about what is on the broker. Note the difference from the old cap:
this one bounds what is DISPLAYED and never refuses what arrives, so an oversized
message costs you detail, not the session.

RECONNECTS ARE AUTOMATIC BUT VISIBLE. A dropped broker is normal on a plant network,
so Paho reconnects with its own backoff; this never presents stale values as live.
Every topic carries its own age and the snapshot carries the connection state, so
the UI can grey out what has stopped arriving.
"""

import json
import os
import re
import ssl
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

# Vendored, so the dashboard still starts from a clone with no pip and no network.
_VENDOR = str(Path(__file__).resolve().parent / "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

try:
    import paho.mqtt as paho_pkg
    import paho.mqtt.client as paho
    from paho.mqtt.enums import CallbackAPIVersion
    PAHO_VERSION = getattr(paho_pkg, "__version__", "?")
    PAHO_ERROR = None
except Exception as err:                      # pragma: no cover - vendor missing
    paho = None
    CallbackAPIVersion = None
    PAHO_VERSION = "unavailable"
    PAHO_ERROR = f"{type(err).__name__}: {err}"

MAX_TOPICS = 2000
MAX_MESSAGES = 1000
MAX_VALUE_BYTES = 2048
MAX_FILTERS = 16
KEEPALIVE = 30
RECONNECT_MIN = 2
RECONNECT_MAX = 60

TOPIC_SEGMENT_MAX = 64
TOPIC_BYTES_MAX = 512


class Invalid(ValueError):
    """Operator input the monitor refuses. Maps to HTTP 400."""


class Unavailable(RuntimeError):
    """The client library is not usable. Maps to HTTP 503."""


def _truncate(raw):
    """Decode and cap a payload for DISPLAY. Never rejects, always reports."""
    if len(raw) <= MAX_VALUE_BYTES:
        return raw.decode("utf-8", "replace"), False
    return raw[:MAX_VALUE_BYTES].decode("utf-8", "replace"), True


# A hostname label or an IP literal. Deliberately strict: this string becomes the
# target of an outbound connection, so nothing shell-like, no scheme, no path, no
# userinfo, no port smuggled in.
HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,253}[A-Za-z0-9])?\Z")


def check_topic_filter(value):
    if not isinstance(value, str) or not value:
        raise Invalid("a topic filter may not be empty")
    if len(value.encode("utf-8")) > TOPIC_BYTES_MAX:
        raise Invalid(f"topic filter exceeds {TOPIC_BYTES_MAX} bytes")
    if "\x00" in value or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise Invalid("topic filter contains control characters")
    # MQTT 3.1.1 4.7.1: '#' is only legal as the final level, '+' occupies a whole
    # level. A broker refuses a malformed filter with a SUBACK failure, which is a
    # round trip and a confusing error; say so here instead.
    levels = value.split("/")
    for index, level in enumerate(levels):
        if "#" in level:
            if level != "#" or index != len(levels) - 1:
                raise Invalid("'#' must be the last level of a filter, on its own")
        if "+" in level and level != "+":
            raise Invalid("'+' must occupy a whole level of a filter, on its own")
    return value


def validate(config):
    """Check a monitor configuration without connecting to anything."""
    if not isinstance(config, dict):
        raise Invalid("configuration must be a JSON object")
    unknown = config.keys() - {"host", "port", "filters", "client_id", "tls"}
    if unknown:
        raise Invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    host = config.get("host")
    if not isinstance(host, str) or not HOST_RE.match(host):
        raise Invalid("invalid host")
    port = config.get("port", 1883)
    if type(port) is not int or not 1 <= port <= 65535:
        raise Invalid("invalid port")
    filters = config.get("filters") or ["#"]
    if not isinstance(filters, list) or not 1 <= len(filters) <= MAX_FILTERS:
        raise Invalid(f"filters must be a list of 1 to {MAX_FILTERS} topic filters")
    checked = [check_topic_filter(item) for item in filters]
    if len(set(checked)) != len(checked):
        raise Invalid("duplicate topic filter")
    client_id = config.get("client_id") or "ccc-monitor"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,23}", str(client_id)):
        # 23 characters is the MQTT 3.1.1 floor a broker must accept. Longer ids
        # are legal but optional, and a broker that refuses one fails the CONNECT
        # with a code that reads like an auth problem.
        raise Invalid("client_id must be 1-23 characters of A-Z a-z 0-9 . _ : -")
    tls = config.get("tls")
    if tls is not None and not isinstance(tls, bool):
        raise Invalid("tls must be true or false")
    return {"host": host, "port": port, "filters": checked,
            "client_id": str(client_id), "tls": bool(tls)}


class AuthStore:
    """Broker credentials, read from disk and never from a request.

    The file is the operator's, written in a terminal, 0600, and shaped:

        {"192.168.1.10:8883": {"username": "ccc", "password": "...",
                               "tls": true, "ca_cert": "/etc/ssl/plant-ca.pem",
                               "insecure": false}}

    A world- or group-readable file is REFUSED rather than read, exactly as
    taskmgmt/atlassian.py does: a secret that anyone on the box can read is not a
    secret, and silently using it anyway teaches the operator it is fine.

    Nothing in this class is ever returned to the browser. `describe()` says only
    whether an entry exists and whether it carries a password - never a value, a
    length or a prefix, because a prefix is still a leak.
    """

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        try:
            info = self.path.stat()
        except OSError:
            return {}, None
        if os.name != "nt" and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return {}, (f"{self.path} is mode {oct(info.st_mode & 0o777)[2:]}; "
                        f"must be 600. Run: chmod 600 {self.path}")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, f"{self.path} is not readable JSON; broker credentials ignored."
        return (data if isinstance(data, dict) else {}), None

    def for_broker(self, host, port):
        data, problem = self._load()
        entry = data.get(f"{host}:{port}") or data.get(host) or {}
        return (entry if isinstance(entry, dict) else {}), problem

    def describe(self, host, port):
        entry, problem = self.for_broker(host, port)
        return {"configured": bool(entry),
                "username": bool(entry.get("username")),
                "password": bool(entry.get("password")),
                "tls": bool(entry.get("tls")),
                "ca_cert": bool(entry.get("ca_cert")),
                "problem": problem,
                "path": str(self.path)}


class Monitor:
    """One broker session, restartable, with a persisted configuration."""

    def __init__(self, path, journal=None, autostart=True, auth_path=None):
        self.path = Path(path)
        self.journal = journal
        self.auth = AuthStore(auth_path or self.path.with_name("mqtt-auth.json"))
        self.lock = threading.Lock()
        self.config = None
        self.client = None
        self.topics = {}            # topic -> record
        self.messages = []          # newest last, bounded ring
        self.dropped_topics = 0
        self.dropped_messages = 0
        self.state = "stopped"      # stopped | connecting | connected | error
        self.error = None
        self.connected_at = None
        self.received = 0
        self.granted = {}
        self.sequence = 0
        self.auth_note = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if saved and autostart:
            try:
                self.start(saved, persist=False)
            except (Invalid, Unavailable, OSError):
                # A configuration that no longer validates, or a missing client
                # library, must not keep the server from starting. It stays on disk
                # for the operator to fix and the panel says what is wrong.
                self.state = "error"
                self.error = ("Saved monitor configuration could not be started."
                              if PAHO_ERROR is None else
                              f"MQTT client unavailable ({PAHO_ERROR}).")

    # -- lifecycle ----------------------------------------------------------
    def start(self, config, persist=True):
        if paho is None:
            raise Unavailable(
                f"The MQTT client library is not importable ({PAHO_ERROR}). "
                f"Restore dashboard/vendor/paho - see vendor/README.md.")
        checked = validate(config)
        self.stop(keep_data=True)
        if persist:
            self._save(checked)

        entry, problem = self.auth.for_broker(checked["host"], checked["port"])
        client = paho.Client(CallbackAPIVersion.VERSION2,
                             client_id=checked["client_id"],
                             clean_session=True,
                             protocol=paho.MQTTv311)
        if entry.get("username"):
            client.username_pw_set(str(entry["username"]),
                                   str(entry["password"]) if entry.get("password") else None)
        if checked["tls"] or entry.get("tls"):
            context = ssl.create_default_context(cafile=entry.get("ca_cert") or None)
            if entry.get("insecure"):
                # Opt-in, per broker, in the operator's own file. Never a default,
                # and never something the page can ask for.
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            client.tls_set_context(context)
        client.reconnect_delay_set(min_delay=RECONNECT_MIN, max_delay=RECONNECT_MAX)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.on_subscribe = self._on_subscribe

        with self.lock:
            self.config = checked
            self.client = client
            self.state = "connecting"
            self.error = None
            self.granted = {}
            self.auth_note = problem
        try:
            # connect_async + loop_start: the socket is opened on Paho's thread, so
            # an unreachable broker cannot block the HTTP request that asked for it.
            client.connect_async(checked["host"], checked["port"], keepalive=KEEPALIVE)
            client.loop_start()
        except (OSError, ValueError) as err:
            with self.lock:
                self.state = "error"
                self.error = f"could not start the session: {err}"
        return self.snapshot()

    def stop(self, keep_data=True):
        with self.lock:
            client, self.client = self.client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        with self.lock:
            self.state = "stopped"
            self.error = None
            self.connected_at = None
            if not keep_data:
                self._clear_locked()
        return self.snapshot()

    def clear(self):
        with self.lock:
            self._clear_locked()
        return self.snapshot()

    def _clear_locked(self):
        self.topics = {}
        self.messages = []
        self.dropped_topics = 0
        self.dropped_messages = 0
        self.received = 0

    def _save(self, config):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(config, out, indent=2)
            os.replace(temp, self.path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def close(self):
        self.stop(keep_data=False)

    # -- Paho callbacks -----------------------------------------------------
    #
    # These run on Paho's network thread, so every one of them takes the lock and
    # does no I/O of its own.

    def _on_connect(self, client, _userdata, _flags, reason, _properties=None):
        if getattr(reason, "is_failure", False):
            with self.lock:
                self.state = "error"
                self.error = f"broker refused the connection: {reason}"
            return
        config = self.config
        with self.lock:
            self.state = "connected"
            self.error = None
            self.connected_at = time.time()
            self.granted = {}
        if config:
            # Re-subscribed on every connect, not just the first: a reconnect
            # starts a clean session, and a monitor that silently stops receiving
            # after a blip is worse than one that never started.
            client.subscribe([(item, 0) for item in config["filters"]])

    def _on_subscribe(self, _client, _userdata, _mid, reason_codes, _properties=None):
        config = self.config
        if not config:
            return
        with self.lock:
            for topic, code in zip(config["filters"], reason_codes):
                # Paho 2.x hands back ReasonCode objects, which carry the wire
                # value on `.value` and do NOT implement __int__ - so int(code)
                # raises, out of a callback, on the broker's thread, where it
                # killed the subscription silently and left the tree empty.
                value = getattr(code, "value", code)
                failed = getattr(code, "is_failure", None)
                if failed is None:
                    failed = int(value) >= 0x80
                self.granted[topic] = "refused" if failed else f"qos {int(value)}"
            if self.granted and all(v == "refused" for v in self.granted.values()):
                self.state = "error"
                self.error = "the broker refused every topic filter"

    def _on_disconnect(self, _client, _userdata, *args):
        # Paho hands this callback different shapes across API versions; the only
        # thing this needs is "we are no longer connected".
        with self.lock:
            if self.state == "connected":
                self.state = "connecting"
            self.connected_at = None

    def _on_message(self, _client, _userdata, message):
        value, truncated = _truncate(message.payload or b"")
        at = time.time()
        topic = message.topic[:TOPIC_BYTES_MAX]
        with self.lock:
            self.received += 1
            self.sequence += 1
            record = self.topics.get(topic)
            if record is None:
                if len(self.topics) >= MAX_TOPICS:
                    # Refuse the NEW topic rather than evicting an old one: a
                    # browser whose tree reshuffles under the operator is worse
                    # than one that says it is full.
                    self.dropped_topics += 1
                    return
                record = self.topics[topic] = {
                    "topic": topic, "count": 0, "first_at": at}
            record.update(value=value, at=at, qos=int(message.qos),
                          retain=bool(message.retain), bytes=len(message.payload or b""),
                          truncated=truncated)
            record["count"] += 1
            self.messages.append({
                "seq": self.sequence, "topic": topic, "value": value, "at": at,
                "qos": int(message.qos), "retain": bool(message.retain),
                "bytes": len(message.payload or b""), "truncated": truncated})
            if len(self.messages) > MAX_MESSAGES:
                overflow = len(self.messages) - MAX_MESSAGES
                del self.messages[:overflow]
                self.dropped_messages += overflow

    # -- publishing ---------------------------------------------------------
    def publish(self, topic, payload, qos=0, retain=False):
        """Publish on the session that is already open. Never opens one."""
        with self.lock:
            client, config = self.client, self.config
            connected = self.state == "connected"
        if client is None or config is None:
            raise Invalid("point the monitor at a broker first")
        if not connected:
            raise Invalid("the monitor is not connected to the broker")
        check_topic_filter(topic)
        if "+" in topic or "#" in topic:
            # You cannot publish to a wildcard. Accepting one and doing nothing
            # would look like a successful publish that never arrives anywhere.
            raise Invalid("cannot publish to a wildcard topic")
        if not isinstance(payload, str):
            raise Invalid("payload must be a string")
        raw = payload.encode("utf-8")
        if len(raw) > 256 * 1024:
            raise Invalid("payload exceeds 256 KiB")
        if qos not in (0, 1, 2):
            raise Invalid("qos must be 0, 1 or 2")
        info = client.publish(topic, raw, qos=int(qos), retain=bool(retain))
        if info.rc != 0:
            raise Invalid(f"the client refused the publish (rc {info.rc})")
        if qos:
            # QoS 1 and 2 are acknowledged, so "delivered" is a claim we can
            # actually make - but only after waiting for the ack.
            info.wait_for_publish(timeout=5)
            if not info.is_published():
                raise Invalid("the broker did not acknowledge the publish in 5s")
        return {"ok": True, "qos": int(qos), "retain": bool(retain),
                "detail": (f"Acknowledged by the broker at QoS {qos}." if qos else
                           f"Written to the socket at QoS 0 (unacknowledged).")}

    # -- reading ------------------------------------------------------------
    def snapshot(self, limit=200, since=0, topic_filter=""):
        """One consistent view: connection state, the topic tree and recent traffic."""
        needle = str(topic_filter or "").lower()[:256]
        with self.lock:
            topics = [dict(record) for record in self.topics.values()
                      if not needle or needle in record["topic"].lower()]
            messages = [dict(row) for row in self.messages
                        if row["seq"] > since and (not needle or needle in row["topic"].lower())]
            config = dict(self.config) if self.config else None
            state = {
                "state": self.state,
                "error": self.error,
                "config": config,
                "connected_at": self.connected_at,
                "received": self.received,
                "granted": dict(self.granted),
                "dropped_topics": self.dropped_topics,
                "dropped_messages": self.dropped_messages,
                "topic_count": len(self.topics),
                "sequence": self.sequence,
                "auth_note": self.auth_note,
            }
        topics.sort(key=lambda record: record["topic"])
        messages = messages[-max(1, min(int(limit or 200), MAX_MESSAGES)):]
        messages.reverse()                       # newest first, as every log view here does
        state.update(topics=topics, messages=messages, tree=build_tree(topics),
                     max_topics=MAX_TOPICS, max_messages=MAX_MESSAGES,
                     client=f"paho-mqtt {PAHO_VERSION}",
                     auth=(self.auth.describe(config["host"], config["port"])
                           if config else self.auth.describe("", 0)))
        return state


def build_tree(topics):
    """Fold a flat topic list on '/' into a tree the browser can render lazily."""
    root = {"segment": "", "path": "", "children": {}, "leaf": None, "count": 0}
    for record in topics:
        node = root
        segments = record["topic"].split("/")[:TOPIC_SEGMENT_MAX]
        for depth, segment in enumerate(segments):
            path = "/".join(segments[:depth + 1])
            child = node["children"].get(segment)
            if child is None:
                child = node["children"][segment] = {
                    "segment": segment, "path": path, "children": {}, "leaf": None,
                    "count": 0}
            node = child
            node["count"] += 1
        node["leaf"] = record

    def freeze(node):
        return {"segment": node["segment"], "path": node["path"],
                "count": node["count"], "leaf": node["leaf"],
                "children": [freeze(child) for _, child in sorted(node["children"].items())]}

    return [freeze(child) for _, child in sorted(root["children"].items())]
