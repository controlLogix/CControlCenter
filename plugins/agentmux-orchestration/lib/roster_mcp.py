"""Newline JSON-RPC roster reader. Discovery never contacts the dashboard."""
import json
from gateway import Refused, loads, read

MAX_FRAME = 64 * 1024
TOOLS = [
    {"name": "agent_roster", "description": "Read agent definitions; optionally select a name.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}},
    {"name": "team_roster", "description": "Read the proposed and approved team members for a task.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False}},
]


class ProtocolError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def dispatch(method, params):
    if not isinstance(params, dict):
        raise ProtocolError(-32602, "params must be an object")
    if method == "initialize":
        version = params.get("protocolVersion", "2024-11-05")
        if not isinstance(version, str):
            raise ProtocolError(-32602, "protocolVersion must be a string")
        return {"protocolVersion": version if version in ("2024-11-05", "2025-03-26", "2025-06-18") else "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentmux-roster", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method != "tools/call":
        raise ProtocolError(-32601, "method not found")
    name = params.get("name")
    if name not in ("agent_roster", "team_roster"):
        raise ProtocolError(-32602, "unknown roster tool")
    args = params.get("arguments", {})
    if not isinstance(args, dict):
        raise ProtocolError(-32602, "arguments must be an object")
    key = "name" if name == "agent_roster" else "id"
    if set(args) - {key}:
        raise ProtocolError(-32602, "unexpected tool argument")
    if key in args and (not isinstance(args[key], str) or not args[key] or len(args[key]) > 256 or "\0" in args[key]):
        raise ProtocolError(-32602, key + " must be a nonempty string of at most 256 characters")
    try:
        if name == "team_roster" and "id" not in args:
            raise Refused("team_roster requires a task id")
        data = read("/api/board/agents" if name == "agent_roster" else "/api/board/roster", args)
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=True, allow_nan=False)}]}
    except Refused as exc:
        return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}


def reply(message):
    if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)):
        raise ProtocolError(-32600, "invalid JSON-RPC request")
    identity = message.get("id")
    if "id" in message and (isinstance(identity, bool) or not isinstance(identity, (str, int, type(None)))):
        raise ProtocolError(-32600, "invalid JSON-RPC id")
    if "id" not in message:
        return None  # Notifications never trigger reads or protocol output.
    try:
        return {"jsonrpc": "2.0", "id": identity,
                "result": dispatch(message["method"], message.get("params", {}))}
    except ProtocolError as exc:
        return {"jsonrpc": "2.0", "id": identity, "error": {"code": exc.code, "message": exc.message}}


def serve(source, output):
    while True:
        raw = source.readline(MAX_FRAME + 1)
        if not raw:
            return
        try:
            if len(raw) > MAX_FRAME:
                while raw and not raw.endswith(b"\n"):
                    raw = source.readline(MAX_FRAME + 1)
                raise ProtocolError(-32700, "JSON-RPC frame exceeds the size limit")
            try:
                message = loads(raw.decode("utf-8"))
            except (ValueError, RecursionError):
                raise ProtocolError(-32700, "invalid JSON") from None
            result = reply(message)
        except ProtocolError as exc:
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": exc.code, "message": exc.message}}
        if result is not None:
            output.write(json.dumps(result, ensure_ascii=True, allow_nan=False) + "\n")
            output.flush()
