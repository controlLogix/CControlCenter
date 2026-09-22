"""Local HTTP API on 127.0.0.1, the seam a future ByteDesk plugin will talk to.

GET  /health          state, mode, device, target window, options
GET  /devices         input devices
GET  /windows         windows that text can be sent to
GET  /events          Server-Sent Events stream of every engine event
POST /listening       {"on": true|false}             open mic: pause/resume
POST /mode            {"mode": "ptt"|"open"}
POST /device          {"device": "<index or name substring>"}
POST /target          {"hwnd": 1234} | {"title": "substring"} | {} to follow focus
POST /show            bring the overlay forward (used by a second launch)
POST /quit            exit voicecli
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import App


class Api:
    def __init__(self, port: int, app: "App"):
        self.port = port
        self.app = app
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    def publish(self, event: dict) -> None:
        if event.get("type") == "level":
            return  # too chatty for subscribers
        with self._lock:
            for q in self._subs:
                q.put(event)

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

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep stdout clean for JSONL
                pass

            def _json(self, code: int, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                if self.path == "/health":
                    self._json(200, {"ok": True, **app.status()})
                elif self.path == "/devices":
                    self._json(200, app.devices())
                elif self.path == "/windows":
                    self._json(200, app.windows())
                elif self.path == "/events":
                    self._events()
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                try:
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
                        return self._json(404, {"error": "not found"})
                    self._json(200, {"ok": True, **app.status()})
                except (KeyError, ValueError) as e:
                    self._json(400, {"error": str(e)})
                except Exception as e:  # e.g. the device would not open
                    self._json(500, {"error": str(e)})

            def _events(self):
                q: queue.Queue = queue.Queue()
                with api._lock:
                    api._subs.append(q)
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

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="api", daemon=True).start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
