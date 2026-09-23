import http.client
import json
import queue
import socket

import pytest

from voicecli import server
from voicecli.server import Api, load_token

TOKEN = "t" * 43


class FakeApp:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"state": "ptt_idle", "target": {"title": "secret window"}}

    def devices(self):
        return [{"name": "mic"}]

    def windows(self):
        return [{"hwnd": 1, "title": "Claude Code"}]

    def set_mode(self, mode):
        if mode not in ("ptt", "open"):
            raise ValueError("bad mode")
        self.calls.append(("mode", mode))

    def set_listening(self, on):
        self.calls.append(("listening", on))

    def set_target(self, hwnd):
        self.calls.append(("target", hwnd))

    def set_device(self, spec):
        self.calls.append(("device", spec))

    def show(self):
        self.calls.append(("show",))

    def quit(self):
        self.calls.append(("quit",))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def api():
    app = FakeApp()
    a = Api(free_port(), app, token=TOKEN)
    a.start()
    yield a
    a.stop()


def call(api, method, path, body=None, token=TOKEN, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
    h = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    conn.request(method, path, body=data, headers=h)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, json.loads(payload) if payload else None


def test_health_without_token_reveals_nothing(api):
    status, body = call(api, "GET", "/health", token=None)
    assert status == 200 and body["ok"] and "target" not in body and "state" not in body
    status, body = call(api, "GET", "/health")
    assert body["target"]["title"] == "secret window"


@pytest.mark.parametrize("path", ["/devices", "/windows", "/events"])
def test_reads_need_the_token(api, path):
    assert call(api, "GET", path, token=None)[0] == 401
    assert call(api, "GET", path, token="wrong" * 10)[0] == 401


def test_writes_need_the_token(api):
    assert call(api, "POST", "/quit", body={}, token=None)[0] == 401
    assert api.app.calls == []


def test_dns_rebinding_host_is_refused(api):
    status, _ = call(api, "GET", "/devices", headers={"Host": f"evil.example:{api.port}"})
    assert status == 403


def test_browser_origin_is_refused_even_with_token(api):
    status, _ = call(api, "POST", "/mode", body={"mode": "open"}, headers={"Origin": "https://evil.example"})
    assert status == 403
    assert api.app.calls == []


def test_simple_form_post_is_refused(api):
    # What a cross-site <form> or fetch(no-cors) can send: text/plain, no custom headers.
    status, _ = call(api, "POST", "/quit", body=b"{}", headers={"Content-Type": "text/plain"})
    assert status == 415
    assert api.app.calls == []


def test_body_limits(api):
    assert call(api, "POST", "/mode", body=b"x" * (server.MAX_BODY + 1))[0] == 413
    assert call(api, "POST", "/mode", body=b"[1, 2]")[0] == 400
    assert call(api, "POST", "/mode", body=b"{nope")[0] == 400


def test_valid_request_reaches_the_app(api):
    status, body = call(api, "POST", "/mode", body={"mode": "open"})
    assert status == 200 and body["ok"]
    assert api.app.calls == [("mode", "open")]
    assert call(api, "POST", "/mode", body={"mode": "shout"})[0] == 400
    assert call(api, "POST", "/target", body={"title": "claude"})[0] == 200
    assert api.app.calls[-1] == ("target", 1)


def test_event_queues_are_bounded_and_keep_the_newest():
    a = Api(0, FakeApp(), token=TOKEN)
    q = queue.Queue(maxsize=3)
    a._subs.append(q)
    for i in range(5):
        a.publish({"type": "final", "n": i})
    assert [q.get_nowait()["n"] for _ in range(3)] == [2, 3, 4]


def test_subscriber_limit(api, monkeypatch):
    monkeypatch.setattr(server, "MAX_SUBSCRIBERS", 1)
    first = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
    first.request("GET", "/events", headers={"Authorization": f"Bearer {TOKEN}"})
    resp = first.getresponse()
    assert resp.status == 200 and resp.fp.readline().startswith(b"data: ")
    assert call(api, "GET", "/events")[0] == 503
    first.close()


def test_token_file_is_created_once(tmp_path):
    path = tmp_path / "api-token"
    token = load_token(path)
    assert len(token) >= 32 and load_token(path) == token
