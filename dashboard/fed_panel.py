"""The dashboard's Federation view (EP-032, docs/FEDERATION.md section 11).

Like hub_panel.py, a CLIENT of agentmux-hub over its unix socket - never a reader of
hub.db. Unlike the Hub view it can act, because the operator's federation decisions
belong where the operator is looking: approve or deny a quarantined item, pull or
release the kill switch, move a shared card. Those are the only writes, each one an
allowlisted hub verb with validated arguments; the hub still decides (the dashboard
runs outside every pane, so the hub sees it as the operator - the same as a terminal).
"""
import json
import os
import re
import socket

TIMEOUT_S = 5.0
MAX_RESPONSE = 16 * 1024 * 1024

QID = re.compile(r"Q-[0-9A-Z]{10}")
CARD = re.compile(r"[A-Z][A-Z0-9]{0,9}-[0-9]{1,7}")
STATUSES = ("todo", "doing", "review", "done", "blocked")


def _flag(v):
    if not isinstance(v, bool):
        raise ValueError("expected true or false")
    return v


def _match(rx):
    def check(v):
        if not isinstance(v, str) or not rx.fullmatch(v):
            raise ValueError("invalid id")
        return v
    return check


def _status(v):
    if v not in STATUSES:
        raise ValueError("invalid status")
    return v


# verb -> {arg: validator}. Nothing else crosses from HTTP to the hub.
WRITE_VERBS = {
    "fed_approve": {"id": _match(QID), "privileged": _flag},
    "fed_deny": {"id": _match(QID)},
    "fed_kill": {"revoke": _flag},
    "fed_resume": {},
    "fed_board_move": {"key": _match(CARD), "status": _status},
}
REQUIRED = {"fed_approve": {"id"}, "fed_deny": {"id"}, "fed_board_move": {"key", "status"}}


class HubDown(Exception):
    pass


def socket_path(home=None):
    home = home or os.environ.get("AGENTMUX_HOME") or os.path.expanduser("~/.agentmux")
    return os.path.join(str(home), "hub", "hub.sock")


def call(verb, args, home=None, timeout=TIMEOUT_S):
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise HubDown("hub not running")
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(socket_path(home))
        except OSError:
            raise HubDown("hub not running") from None
        s.sendall((json.dumps({"verb": verb, "args": args}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_RESPONSE:
                raise ValueError("response too large")
    except socket.timeout:
        raise TimeoutError(f"hub did not answer within {timeout:g} s") from None
    finally:
        s.close()
    return json.loads(buf or b"{}")


def panel(home=None):
    try:
        r = call("fed_panel", {}, home)
    except HubDown as e:
        return 503, {"error": str(e)}
    except TimeoutError as e:
        return 504, {"error": str(e)}
    if not r.get("ok"):
        return 502, {"error": r.get("error") or "hub refused"}
    return 200, {"result": r["result"]}


def action(body, home=None):
    verb = body.get("verb")
    spec = WRITE_VERBS.get(verb)
    if spec is None:
        return 400, {"error": "not an allowed federation action"}
    raw = body.get("args") or {}
    if not isinstance(raw, dict) or set(raw) - set(spec):
        return 400, {"error": "unexpected arguments"}
    try:
        args = {k: spec[k](v) for k, v in raw.items()}
    except ValueError as e:
        return 400, {"error": str(e)}
    missing = REQUIRED.get(verb, set()) - set(args)
    if missing:
        return 400, {"error": f"missing {', '.join(sorted(missing))}"}
    try:
        r = call(verb, args, home, timeout=30)
    except HubDown as e:
        return 503, {"error": str(e)}
    except TimeoutError as e:
        return 504, {"error": str(e)}
    if not r.get("ok"):
        return 409, {"error": r.get("error") or "hub refused"}
    return 200, {"result": r["result"]}
