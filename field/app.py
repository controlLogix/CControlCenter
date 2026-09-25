"""The field sidecar: the protocol modules behind a thin HTTP shell.

ADR-0023 puts the Node API inside WSL, next to cc.db and the tmux server, and the
protocol code on WINDOWS - because serial Modbus RTU needs COM ports
(modbus_rtu.py:3) and `On WSL2, USB serial/RS-485 adapters need usbipd attachment;
a Windows COM mapping may not be usable` (modbus_rtu.py:97-98). This is that
Windows half.

TWO CONSUMERS, ONE LIBRARY. This imports the protocol modules from dashboard/
rather than owning a copy of them, and dashboard/server.py keeps importing them
exactly as it does today. Two copies drift inside a week, and the request differ
would then be comparing a module against its own stale twin. Nothing here changes
protocol logic; when the modules eventually move, this import path is the single
line that follows them.

WHAT THIS DELIBERATELY DOES NOT HAVE, and must not grow:

  * No route takes a raw CIP service, class, instance or attribute, and there is
    no generic_message passthrough. That absence IS the audit boundary - the
    capability wrapper planned for pycomm3 is defence in depth, but Python has no
    private and a determined caller walks around it. The process boundary is what
    actually holds, so the HTTP surface is the thing to keep honest.
  * The one write route does not say WHAT to write. It names a ticket, and the
    ticket carries the target and the value, fixed when it was minted
    (field/tickets.py). A replayed or reused request can therefore only redo a
    write that was already authorised, and only once. The ticket came first on
    purpose: a write route that predates its gate never gets one, because by
    then something is calling it the old way.

BIND. 127.0.0.1 only, asserted at startup rather than assumed. Reaching this from
WSL needs mirrored networking - see docs/wsl-networking.md, which records that
127.0.0.1 from WSL does NOT reach a Windows loopback listener today, and neither
does the gateway address, because the listener is loopback-bound.
"""
import argparse
import hmac
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dashboard"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tickets                                    # noqa: E402

# rockwell imports pycomm3, which is vendored. Optional like every protocol
# module below: a missing wheel disables the Rockwell panel, it does not stop
# the sidecar answering /health and saying why.
try:
    import rockwell
    ROCKWELL_ERROR = None if rockwell.available() else rockwell.IMPORT_ERROR
except Exception as _rock_err:                    # noqa: BLE001
    rockwell = None
    ROCKWELL_ERROR = f"{type(_rock_err).__name__}: {_rock_err}"

# Imported for their side-effect-free helpers only. Each is optional: a missing
# dependency must disable one panel, not fail the sidecar's boot - the posture
# modbus_rtu.py:86-88 and mqtt_monitor.py:61-71 already take.
PROTOCOLS = {}
PROTOCOL_ERRORS = {}
for _name in ("enip", "logix", "ads", "mqtt", "modbus_poll", "modbus_rtu",
              "profinet", "ecat_diag", "netscan", "mqtt_monitor"):
    try:
        PROTOCOLS[_name] = __import__(_name)
    except Exception as _err:                      # noqa: BLE001 - report, never die
        PROTOCOL_ERRORS[_name] = f"{type(_err).__name__}: {_err}"

VERSION = "0.1.0"
DEFAULT_PORT = 8788
KEY_ENV = "AGENTMUX_FIELD_KEY"


def key_path():
    """Where the shared secret lives. %LOCALAPPDATA% on Windows, else the home."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "agentmux" / "field.key"
    return Path.home() / ".agentmux" / "field.key"


def load_key(create=False):
    """Read the shared secret, optionally minting one on first start."""
    path = key_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    if not create:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    value = os.urandom(32).hex()
    # 0600 before anything is written, so the secret is never briefly world-readable.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "agentmux-field/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):             # quiet by default
        if self.server.verbose:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is meant for a browser, and a stray content sniff on a
        # protocol payload is not a risk worth carrying.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        """Constant-time shared-secret check, before the body is even read."""
        presented = self.headers.get("X-AgentMux-Field-Key") or ""
        expected = self.server.key
        if not expected or not hmac.compare_digest(presented, expected):
            # No body: an unauthenticated caller learns nothing about what is here.
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    MAX_BODY = 64 * 1024

    def read_json(self):
        """Read a bounded JSON object, or answer and return None.

        The same shape as the dashboard's read_cc_body guards: POST only, a
        declared and bounded length, a real content type, and a dict at the top
        level. A write route is the last place to be relaxed about any of them.
        """
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self.send_json(415, {"error": "expected application/json"})
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_json(400, {"error": "bad Content-Length"})
            return None
        if length <= 0:
            self.send_json(400, {"error": "empty body"})
            return None
        if length > self.MAX_BODY:
            self.send_json(413, {"error": "body too large"})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "body is not valid JSON"})
            return None
        if not isinstance(payload, dict):
            self.send_json(400, {"error": "body must be a JSON object"})
            return None
        return payload

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            if not self.authorized():
                return
            return self.send_json(200, self.health())
        self.send_json(404, {"error": "no such route"})

    WRITE_KINDS = ("write_tag", "write_member", "write_struct")

    def do_POST(self):
        if not self.authorized():
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/rockwell/ticket":
            return self.mint_ticket()
        if path == "/rockwell/write":
            return self.redeem_write()
        # 404 for an unknown path; the two that exist are the two that exist.
        self.send_json(404, {"error": "no such route"})

    def mint_ticket(self):
        """Authorise ONE write. Nothing is sent to any device here.

        The value is fixed at this moment so that what a person is shown and
        what eventually executes are the same object rather than two that look
        alike.
        """
        body = self.read_json()
        if body is None:
            return
        kind = body.get("kind")
        if kind not in self.WRITE_KINDS:
            return self.send_json(400, {"error": f"kind must be one of {list(self.WRITE_KINDS)}"})
        for field in ("path", "tag"):
            if not isinstance(body.get(field), str) or not body[field].strip():
                return self.send_json(400, {"error": f"{field} is required"})
        if "value" not in body:
            return self.send_json(400, {"error": "value is required"})
        try:
            ticket = self.server.tickets.mint({
                "kind": kind, "path": body["path"], "tag": body["tag"],
                "value": body["value"],
            })
        except (ValueError, tickets.TicketError) as err:
            return self.send_json(409, {"error": str(err)})
        return self.send_json(201, ticket.summary())

    def redeem_write(self):
        """Perform the write one ticket authorises.

        This request carries a ticket id, an actor and a confirmation. It does
        NOT carry a target or a value - those are on the ticket, and there is no
        way to supply them here. That is the property the whole mechanism is for.
        """
        body = self.read_json()
        if body is None:
            return
        # Any attempt to restate the write here is refused rather than ignored.
        # Ignoring it would let a caller believe it had specified something.
        supplied = sorted({"kind", "path", "tag", "value"} & set(body))
        if supplied:
            return self.send_json(400, {
                "error": f"the write is on the ticket, not in this request; remove {supplied}"})
        actor = body.get("actor")
        if not isinstance(actor, str) or not actor.strip():
            return self.send_json(400, {"error": "a named actor is required"})
        if body.get("confirm") is not True:
            return self.send_json(400, {"error": "confirm must be true"})
        if rockwell is None or not rockwell.available():
            return self.send_json(503, {"error": f"rockwell is unavailable: {ROCKWELL_ERROR}"})
        try:
            action = self.server.tickets.redeem(body.get("ticket_id"), actor=actor)
        except tickets.TicketError as err:
            return self.send_json(409, {"error": str(err)})
        except ValueError as err:
            return self.send_json(400, {"error": str(err)})

        try:
            with rockwell.AuditedLogixSession(action["path"]) as session:
                method = getattr(session, action["kind"])
                result = method(action["tag"], action["value"], confirm=True, actor=actor)
        except rockwell.WriteRefused as err:
            # The controller said no, or a guard did. Nothing changed, and the
            # journal already records which.
            return self.send_json(409, {"error": str(err), "outcome": "rejected"})
        except Exception as err:                       # noqa: BLE001
            # We do not know whether it applied. Say exactly that, and offer
            # nothing that looks like a retry.
            return self.send_json(502, {
                "error": f"{type(err).__name__}: {err}",
                "outcome": "unknown",
                "advice": "Investigate at the equipment. Do not retry this write."})
        return self.send_json(200, dict(result, outcome="success"))

    def health(self):
        return {
            "ok": True,
            "version": VERSION,
            "host": socket.gethostname(),
            "platform": sys.platform,
            "bind": self.server.server_address[0],
            "port": self.server.server_address[1],
            # Which protocol modules loaded, and why any did not. A missing wheel
            # disables one panel; it must be visible rather than merely absent.
            "protocols": sorted(PROTOCOLS),
            "protocol_errors": PROTOCOL_ERRORS,
            # Reported rather than merely absent, same reason as the protocols
            # above: a disabled panel must be explicable from /health alone.
            "rockwell": rockwell is not None and rockwell.available(),
            "rockwell_error": ROCKWELL_ERROR,
            "tickets_outstanding": len(self.server.tickets.outstanding()),
        }


def assert_loopback(sock_address):
    """Refuse to serve on anything but loopback. Asserted, not assumed."""
    host = sock_address[0]
    if host not in ("127.0.0.1", "::1"):
        raise SystemExit(
            f"agentmux-field: refusing to bind {host}. This process holds the only\n"
            "  code that can write to field equipment; it is reachable from the API\n"
            "  over loopback and must never be reachable from anywhere else.\n"
            "  See docs/wsl-networking.md for how the WSL API reaches it."
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="agentmux field sidecar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--print-key", action="store_true",
                        help="mint the shared secret if absent, print it, and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.print_key:
        print(load_key(create=True))
        return 0

    key = os.environ.get(KEY_ENV) or load_key(create=True)
    assert_loopback((args.host, args.port))

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.key = key
    server.verbose = args.verbose
    # In memory, on the server object: restarting the sidecar invalidates every
    # outstanding authorisation, which is the correct blast radius.
    server.tickets = tickets.TicketStore()
    assert_loopback(server.server_address)
    host, port = server.server_address[0], server.server_address[1]
    print(f"agentmux field sidecar: http://{host}:{port}", flush=True)
    if PROTOCOL_ERRORS:
        for name, err in sorted(PROTOCOL_ERRORS.items()):
            print(f"  unavailable: {name} - {err}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
