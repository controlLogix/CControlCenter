"""MCP server for Voice CLI: lets an agent see and steer the push-to-talk app on this PC.

Voice CLI (voice-cli/ in this repo) already exposes an authenticated HTTP API on
127.0.0.1 - its docstring calls it "the seam a future plugin will talk to". This is that
plugin's other half: a stdio MCP server, Python standard library only, that turns MCP
tool calls into those HTTP requests.

Where things come from, and how a test overrides them:

    token   %APPDATA%\\voicecli\\api-token          VOICECLI_TOKEN_FILE
    port    "port" in %APPDATA%\\voicecli\\config.json, else 47821
    url     http://127.0.0.1:<port>                VOICECLI_URL

The token is read on every call, never cached, so a reinstall that rotates it needs no
restart. It is sent only to the loopback URL and never appears in a tool result.

Deliberately NOT exposed: POST /quit. Closing the operator's microphone app is not an
agent's decision; the tray icon does that.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout, as the MCP stdio spec defines.
stdout carries protocol messages only; diagnostics go to stderr.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVER = {"name": "voice-cli", "version": "1.0.0"}
PROTOCOL = "2025-06-18"
DEFAULT_PORT = 47821
HTTP_TIMEOUT_S = 5
LISTEN_DEFAULT_S = 30
LISTEN_MAX_S = 300


class VoiceError(Exception):
    """A failure the agent should read as a sentence, not a traceback."""


# ── configuration ────────────────────────────────────────────────────────────


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "voicecli"


def base_url() -> str:
    if os.environ.get("VOICECLI_URL"):
        return os.environ["VOICECLI_URL"].rstrip("/")
    port = DEFAULT_PORT
    try:
        cfg = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
        if isinstance(cfg.get("port"), int) and 0 < cfg["port"] < 65536:
            port = cfg["port"]
    except (OSError, ValueError, AttributeError):
        pass
    return f"http://127.0.0.1:{port}"


def token() -> str:
    path = Path(os.environ.get("VOICECLI_TOKEN_FILE") or config_dir() / "api-token")
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError:
        raise VoiceError(
            f"No Voice CLI API token at {path}. Voice CLI creates it on first run: "
            "install and start Voice CLI (voice-cli/README.md), then try again."
        ) from None
    if len(value) < 32:
        raise VoiceError(f"The Voice CLI API token at {path} is malformed.")
    return value


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _open(method: str, path: str, body: dict | None = None, timeout: float = HTTP_TIMEOUT_S):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base_url() + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("error") or e.reason
        except ValueError:
            detail = e.reason
        if e.code == 401:
            detail = "the API token was refused - restart Voice CLI so it and this plugin agree"
        raise VoiceError(f"Voice CLI answered {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as e:
        raise VoiceError(
            f"Voice CLI is not reachable at {base_url()} ({getattr(e, 'reason', e)}). "
            "Is it running? It lives in the notification area; start it from the Start menu."
        ) from None


def call(method: str, path: str, body: dict | None = None):
    with _open(method, path, body) as resp:
        return json.loads(resp.read() or b"null")


def listen(timeout_s: float, partials: bool) -> dict:
    """Wait on /events for the next finished phrase.

    Voice CLI still does what it always does with that phrase - types it into the
    focused or locked window - so this is for hearing an answer, not for taking the
    microphone away from the operator.
    """
    deadline = time.monotonic() + timeout_s
    heard: list[str] = []
    # The server sends a keepalive every 15 s, so with a read timeout above that a timed-out
    # read means either the deadline has passed (short waits) or the stream has stalled.
    # A timed-out socket file cannot be read again, so either way this is the last read.
    with _open("GET", "/events", timeout=min(timeout_s, 20) + 1) as resp:
        while time.monotonic() < deadline:
            try:
                raw = resp.readline()
            except (socket.timeout, TimeoutError):
                if time.monotonic() < deadline:
                    raise VoiceError("Voice CLI's event stream stalled (no keepalive).") from None
                break
            if not raw:
                raise VoiceError("Voice CLI closed the event stream (did it quit?).")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:])
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "partial" and partials:
                heard.append(ev.get("text", ""))
            elif kind == "final":
                out = {"heard": True, "text": ev.get("text", ""),
                       "audio_s": ev.get("audio_s"), "latency_s": ev.get("latency_s")}
                if partials:
                    out["partials"] = heard
                return out
            elif kind == "error":
                raise VoiceError(f"Voice CLI reported an error: {ev.get('message') or ev}")
    return {"heard": False, "timeout_s": timeout_s,
            "hint": "Nothing was said in time. In push-to-talk mode the operator must hold the talk key."}


# ── tools ────────────────────────────────────────────────────────────────────


def _obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": props or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


TOOLS = [
    {"name": "voice_status",
     "description": "Voice CLI's current state: listening mode, microphone, the window text is sent to "
                    "(null means it follows focus), model and typing options.",
     "inputSchema": _obj(),
     "run": lambda a: call("GET", "/health")},
    {"name": "voice_devices",
     "description": "List the microphones Voice CLI can use.",
     "inputSchema": _obj(),
     "run": lambda a: call("GET", "/devices")},
    {"name": "voice_windows",
     "description": "List the windows Voice CLI can type into, with their hwnd, title and process.",
     "inputSchema": _obj(),
     "run": lambda a: call("GET", "/windows")},
    {"name": "voice_lock",
     "description": "Lock Voice CLI onto one window, so spoken text goes there even while the operator "
                    "works in another app. Give a title substring (e.g. 'Claude Code') or an hwnd "
                    "from voice_windows.",
     "inputSchema": _obj({"title": {"type": "string", "minLength": 1},
                          "hwnd": {"type": "integer", "minimum": 1}}),
     "run": lambda a: call("POST", "/target", _lock_body(a))},
    {"name": "voice_unlock",
     "description": "Release the window lock: Voice CLI types into whatever window has focus again.",
     "inputSchema": _obj(),
     "run": lambda a: call("POST", "/target", {})},
    {"name": "voice_mode",
     "description": "Switch between push-to-talk ('ptt': hold the talk key) and open mic ('open': "
                    "always listening, phrases end on silence).",
     "inputSchema": _obj({"mode": {"type": "string", "enum": ["ptt", "open"]}}, ["mode"]),
     "run": lambda a: call("POST", "/mode", {"mode": a["mode"]})},
    {"name": "voice_listening",
     "description": "Open mic only: pause (on=false) or resume (on=true) listening.",
     "inputSchema": _obj({"on": {"type": "boolean"}}, ["on"]),
     "run": lambda a: call("POST", "/listening", {"on": bool(a["on"])})},
    {"name": "voice_device",
     "description": "Switch microphone, by index or by part of its name (see voice_devices).",
     "inputSchema": _obj({"device": {"type": "string", "minLength": 1}}, ["device"]),
     "run": lambda a: call("POST", "/device", {"device": str(a["device"])})},
    {"name": "voice_show",
     "description": "Bring Voice CLI's overlay forward so the operator can see it.",
     "inputSchema": _obj(),
     "run": lambda a: call("POST", "/show", {})},
    {"name": "voice_listen",
     "description": "Wait for the operator's next spoken phrase and return its text. Voice CLI still "
                    "types it into its target window as usual. Returns heard=false on timeout; the "
                    "wait can overrun timeout_s by up to 15 s, the app's keepalive interval.",
     "inputSchema": _obj({"timeout_s": {"type": "number", "minimum": 1, "maximum": LISTEN_MAX_S,
                                        "default": LISTEN_DEFAULT_S},
                          "partials": {"type": "boolean", "default": False}}),
     "run": lambda a: listen(float(a.get("timeout_s", LISTEN_DEFAULT_S)), bool(a.get("partials", False)))},
]
BY_NAME = {t["name"]: t for t in TOOLS}


def _lock_body(args: dict) -> dict:
    if args.get("hwnd"):
        return {"hwnd": int(args["hwnd"])}
    if args.get("title"):
        return {"title": str(args["title"])}
    raise VoiceError("voice_lock needs a title or an hwnd. To follow focus again, use voice_unlock.")


def _check_args(tool: dict, args: dict) -> None:
    """Enough schema checking that a bad call is refused here rather than reaching the app."""
    schema = tool["inputSchema"]
    props = schema["properties"]
    unknown = set(args) - set(props)
    if unknown:
        raise VoiceError(f"{tool['name']}: unknown argument(s) {sorted(unknown)}")
    for key in schema.get("required", []):
        if key not in args:
            raise VoiceError(f"{tool['name']}: missing required argument {key!r}")
    for key, value in args.items():
        spec = props[key]
        kind = spec.get("type")
        ok = {"string": isinstance(value, str),
              "boolean": isinstance(value, bool),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "number": isinstance(value, (int, float)) and not isinstance(value, bool)}.get(kind, True)
        if not ok:
            raise VoiceError(f"{tool['name']}: {key} must be a {kind}")
        if "enum" in spec and value not in spec["enum"]:
            raise VoiceError(f"{tool['name']}: {key} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"]:
            raise VoiceError(f"{tool['name']}: {key} must be at least {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise VoiceError(f"{tool['name']}: {key} must be at most {spec['maximum']}")
        if spec.get("minLength") and isinstance(value, str) and len(value) < spec["minLength"]:
            raise VoiceError(f"{tool['name']}: {key} must not be empty")


def run_tool(name: str, args: dict) -> dict:
    tool = BY_NAME.get(name)
    if tool is None:
        return {"content": [{"type": "text", "text": f"Unknown tool {name!r}."}], "isError": True}
    try:
        _check_args(tool, args)
        result = tool["run"](args)
    except VoiceError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}], "isError": False}


# ── JSON-RPC over stdio ──────────────────────────────────────────────────────


def handle(msg: dict) -> dict | None:
    """One request in, one response out. Notifications (no id) get no response."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    params = msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]}
    elif method == "tools/call":
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(mid, -32602, "arguments must be an object")
        result = run_tool(str(params.get("name")), args)
    else:
        return _error(mid, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def main() -> None:
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            reply = _error(None, -32700, "parse error")
        else:
            try:
                reply = handle(msg) if isinstance(msg, dict) else _error(None, -32600, "invalid request")
            except Exception as e:  # never let one bad call kill the server
                print(f"voice-cli mcp: {type(e).__name__}: {e}", file=sys.stderr)
                reply = _error(msg.get("id") if isinstance(msg, dict) else None, -32603, "internal error")
        if reply is not None:
            out.write(json.dumps(reply).encode() + b"\n")
            out.flush()


if __name__ == "__main__":
    main()
