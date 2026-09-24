"""Local HTTP API on 127.0.0.1, the seam the voice-cli plugin (plugins/voice-cli/) talks to.

Every request except a bare liveness probe needs `Authorization: Bearer <token>`, where
the token is the contents of %APPDATA%\\voicecli\\api-token (created on first run, readable
only by this Windows user). Requests must name 127.0.0.1 or localhost in Host (defeats DNS
rebinding) and must not carry an Origin header (browsers always send one, so no web page
can drive the API). POST bodies are JSON objects of at most 64 KiB.

GET  /health          liveness without a token; state, mode, device, target and options with one
GET  /devices         input devices
GET  /windows         windows that text can be sent to
GET  /events          Server-Sent Events stream of every engine event
POST /listening       {"on": true|false}             open mic: pause/resume
POST /mode            {"mode": "ptt"|"open"}
POST /device          {"device": "<index or name substring>"}
POST /target          {"hwnd": 1234} | {"title": "substring"} | {} to follow focus
POST /show            bring the overlay forward
POST /quit            exit voicecli
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from .config import config_dir

if TYPE_CHECKING:
    from .app import App

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024
DRAIN_LIMIT = 1024 * 1024  # unread body bytes discarded before an error reply
MAX_SUBSCRIBERS = 8
SUBSCRIBER_QUEUE = 500  # events buffered per SSE client before the oldest are dropped
READ_TIMEOUT_S = 10


def token_path() -> Path:
    return config_dir() / "api-token"


def load_token(path: Path | None = None) -> str:
    """The API token, created on first use. %APPDATA% is private to the Windows user."""
    path = path or token_path()
    try:
        token = path.read_text(encoding="ascii").strip()
        if len(token) >= 32:
            return token
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(token, encoding="ascii")
    os.replace(tmp, path)
    return token


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second process bind the same port and take our requests;
    # SO_EXCLUSIVEADDRUSE refuses that.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class HttpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class Api:
    def __init__(self, port: int, app: "App", token: str | None = None):
        self.port = port
        self.app = app
        self.token = token
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._httpd: _Server | None = None

    def publish(self, event: dict) -> None:
        if event.get("type") == "level":
            return  # too chatty for subscribers
        with self._lock:
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except queue.Full:  # a client that stopped reading must not grow memory
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except (queue.Empty, queue.Full):
                        pass

    def _set_target(self, body: dict) -> None:
        app = self.app
        if body.get("hwnd"):
            app.set_target(int(body["hwnd"]))
        elif body.get("title"):
            needle = str(body["title"]).lower()
            match = next((w for w in app.windows() if needle in w["title"].lower()), None)
            if match is None:
                raise ValueError(f"no window titled like {body['title']!r}")
            app.set_target(match["hwnd"])
        else:
            app.set_target(None)

    def start(self) -> None:
        api, app = self, self.app
        if api.token is None:
            api.token = load_token()
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

        class Handler(BaseHTTPRequestHandler):
            server_version = "voicecli"
            sys_version = ""
            timeout = READ_TIMEOUT_S  # a client that stalls mid-request gets dropped

            def log_message(self, *args):  # keep stdout clean for JSONL
                pass

            def _json(self, code: int, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _check(self, need_token: bool = True) -> bool:
                """Reject what a browser or a rebinding DNS name would send, and missing tokens."""
                if self.headers.get("Host", "").lower() not in hosts:
                    raise HttpError(403, "bad Host header")
                if self.headers.get("Origin") is not None:
                    raise HttpError(403, "browser requests are not allowed")
                auth = self.headers.get("Authorization", "")
                authed = auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip().encode(), api.token.encode())
                if need_token and not authed:
                    raise HttpError(401, "missing or wrong bearer token")
                return authed

            def _body(self) -> dict:
                ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    raise HttpError(415, "Content-Type must be application/json")
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    raise HttpError(400, "bad Content-Length")
                if n < 0:
                    raise HttpError(400, "bad Content-Length")
                if n > MAX_BODY:
                    raise HttpError(413, f"body over {MAX_BODY} bytes")
                self._drained = True
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    raise HttpError(400, "body is not JSON")
                if not isinstance(body, dict):
                    raise HttpError(400, "body must be a JSON object")
                return body

            def _drain(self) -> None:
                """Read an unread request body before replying. Closing a Windows socket with
                unread data resets the connection, and the client never sees our error."""
                if getattr(self, "_drained", False):
                    return
                self._drained = True
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return
                if 0 < n <= DRAIN_LIMIT:
                    self.rfile.read(n)

            def _fail(self, code: int, message: str) -> None:
                self._drain()
                self._json(code, {"error": message})

            def _guard(self, fn) -> None:
                try:
                    fn()
                except HttpError as e:
                    self._fail(e.code, str(e))
                except (KeyError, ValueError, TypeError) as e:
                    self._fail(400, str(e))
                except OSError as e:  # e.g. the device would not open
                    self._fail(500, str(e))
                except Exception:
                    log.exception("API %s %s failed", self.command, self.path)
                    self._fail(500, "internal error")

            def do_GET(self):
                self._guard(self._get)

            def do_POST(self):
                self._guard(self._post)

            def _get(self):
                if self.path == "/health":
                    authed = self._check(need_token=False)
                    base = {"ok": True, "app": "voicecli", "version": __version__}
                    return self._json(200, {**base, **app.status()} if authed else base)
                self._check()
                if self.path == "/devices":
                    self._json(200, app.devices())
                elif self.path == "/windows":
                    self._json(200, app.windows())
                elif self.path == "/events":
                    self._events()
                else:
                    self._json(404, {"error": "not found"})

            def _post(self):
                self._check()
                body = self._body()
                if self.path == "/listening":
                    app.set_listening(bool(body.get("on", True)))
                elif self.path == "/mode":
                    app.set_mode(str(body["mode"]))
                elif self.path == "/device":
                    app.set_device(str(body["device"]))
                elif self.path == "/target":
                    api._set_target(body)
                elif self.path == "/show":
                    app.show()
                elif self.path == "/quit":
                    self._json(200, {"ok": True})
                    return app.quit()
                else:
                    raise HttpError(404, "not found")
                self._json(200, {"ok": True, **app.status()})

            def _events(self):
                q: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE)
                with api._lock:
                    if len(api._subs) >= MAX_SUBSCRIBERS:
                        raise HttpError(503, "too many event subscribers")
                    api._subs.append(q)
                self.connection.settimeout(None)  # the stream is long-lived; keepalives detect dead clients
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    self.wfile.write(f"data: {json.dumps({'type': 'hello', **app.status()})}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            ev = q.get(timeout=15)
                            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    with api._lock:
                        api._subs.remove(q)

        self._httpd = _Server(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._httpd.serve_forever, name="api", daemon=True).start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
