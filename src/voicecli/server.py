"""Local HTTP API on 127.0.0.1, the seam a future ByteDesk plugin will talk to.

GET  /health          {"ok": true, "state": ..., "device": ...}
GET  /devices         input devices
GET  /events          Server-Sent Events stream of every engine event
POST /listening       body {"on": true|false}
POST /device          body {"device": "<index or name substring>"}
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class Api:
    def __init__(self, port: int, status: Callable[[], dict], devices: Callable[[], list],
                 set_listening: Callable[[bool], None], set_device: Callable[[str], None]):
        self.port = port
        self.status = status
        self.devices = devices
        self.set_listening = set_listening
        self.set_device = set_device
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    def publish(self, event: dict) -> None:
        if event.get("type") == "level":
            return  # too chatty for subscribers
        with self._lock:
            for q in self._subs:
                q.put(event)

    def start(self) -> None:
        api = self

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
                    self._json(200, {"ok": True, **api.status()})
                elif self.path == "/devices":
                    self._json(200, api.devices())
                elif self.path == "/events":
                    self._events()
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                try:
                    body = self._body()
                    if self.path == "/listening":
                        api.set_listening(bool(body.get("on", True)))
                    elif self.path == "/device":
                        api.set_device(str(body["device"]))
                    else:
                        return self._json(404, {"error": "not found"})
                    self._json(200, {"ok": True, **api.status()})
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
                    self.wfile.write(f"data: {json.dumps({'type': 'hello', **api.status()})}\n\n".encode())
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
