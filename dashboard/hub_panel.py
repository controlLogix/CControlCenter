"""Read-only hub client for the dashboard's Hub view (TM-216).

The dashboard is a CLIENT of agentmux-hub, exactly like `agentmux hub ...`: it
connects to the hub's unix socket, sends one JSON line {"verb", "args"}, and reads
one JSON line back. It never opens hub.db.

WHY NOT JUST READ hub.db WITH sqlite3. docs/PROTOCOL.md section 3 says the hub/
directory is owned by agentmux-hub and "Nothing else opens these files", and
section 8 explains why that is load-bearing rather than tidiness: hub.db runs in
WAL mode with ONE writer connection owned by the hub process. A second process
holding a read transaction pins the WAL (checkpoints cannot truncate it while that
reader's snapshot is live), a reader that crashes mid-transaction leaves -shm state
for the hub to recover, and a reader on the wrong side of the 9P/drvfs boundary
corrupts the WAL index outright. It would also bypass the hub's identity and
visibility rules, and every schema change in hub/store.py would silently break
the dashboard. The socket verbs are the stable interface; this module uses only
the read-only ones.

The dashboard runs outside any tmux pane, so the hub identifies it as "operator".
It deliberately does NOT call `inbox`: reading the operator inbox marks mail as
received, and a dashboard glancing at it must not count as the operator reading it.
"""
import json
import os
import re
import socket

TIMEOUT_S = 2.0
# One response line. A status or a work list is kilobytes; this only has to stop a
# runaway answer from being buffered forever.
MAX_RESPONSE = 16 * 1024 * 1024
# The only verbs this module will ever send. Every one of them is read-only on
# the hub side; there is no path from an HTTP request to a writing verb.
READ_VERBS = frozenset({"status", "agents", "work_list", "work_show", "events"})

WORK_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
SLUG = re.compile(r"[A-Za-z0-9_.-]{1,64}")
WORK_STATES = frozenset({"ready", "claimed", "waiting_children", "blocked", "done",
                         "failed", "cancelled"})
ENTITY = re.compile(r"[a-z_]{1,16}")
EVENT_PAGE = 2000


class HubDown(Exception):
    """The socket is absent, refused, or not a socket at all: no hub is running."""


class HubTimeout(Exception):
    """A hub is listening but did not answer in time."""


def default_home():
    return os.environ.get("AGENTMUX_HOME") or os.path.expanduser("~/.agentmux")


def socket_path(home=None):
    return os.path.join(str(home or default_home()), "hub", "hub.sock")


def call(verb, args=None, home=None, timeout=TIMEOUT_S):
    """Send one read verb and return the hub's decoded response dict unchanged."""
    if verb not in READ_VERBS:
        raise ValueError(f"not a read verb: {verb}")
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise HubDown("hub not running")
    path = socket_path(home)
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(path)
        except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError, PermissionError):
            raise HubDown("hub not running") from None
        except socket.timeout:
            raise HubTimeout(f"hub did not answer within {timeout:g} s") from None
        except OSError:
            raise HubDown("hub not running") from None
        try:
            s.sendall((json.dumps({"verb": verb, "args": args or {}}) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_RESPONSE:
                    raise ValueError("hub response too large")
        except socket.timeout:
            raise HubTimeout(f"hub did not answer within {timeout:g} s") from None
        except (ConnectionResetError, BrokenPipeError):
            raise HubDown("hub not running") from None
    finally:
        s.close()
    if not buf.strip():
        raise HubDown("hub not running")
    return json.loads(buf)


def _int(raw, default, lo, hi):
    if raw is None or not re.fullmatch(r"-?[0-9]{1,12}", raw):
        return default
    return min(max(int(raw), lo), hi)


def events_tail(n, entity=None, home=None):
    """The last n events. The hub pages forward from a sequence number, so walk it
    in pages and keep the tail; the answer carries `next`, the seq to poll from."""
    since, keep, last = 0, [], 0
    for _ in range(500):
        r = call("events", {"since": since, "limit": EVENT_PAGE, **({"entity": entity} if entity else {})},
                 home=home)
        if not r.get("ok"):
            return r
        rows = r.get("result") or []
        keep = (keep + rows)[-n:] if n else []
        if rows:
            since = last = rows[-1]["seq"]
        if len(rows) < EVENT_PAGE:
            break
    return {"ok": True, "caller": r.get("caller"), "result": keep, "next": last}


def endpoint(sub, query, home=None):
    """(http_status, body) for GET /api/hub/<sub>. `query` is a parse_qs dict."""
    q = {k: v[0] for k, v in (query or {}).items() if v}
    try:
        if sub == "status":
            r = call("status", home=home)
        elif sub == "agents":
            r = call("agents", {"live": q.get("live") == "1"}, home=home)
        elif sub == "work":
            args = {}
            if q.get("state"):
                if q["state"] not in WORK_STATES:
                    return 400, {"error": "unknown work state"}
                args["state"] = q["state"]
            if q.get("repo"):
                if not SLUG.fullmatch(q["repo"]):
                    return 400, {"error": "invalid repo"}
                args["repo"] = q["repo"]
            r = call("work_list", args, home=home)
        elif sub.startswith("work/"):
            work_id = sub[len("work/"):]
            if not WORK_ID.fullmatch(work_id):
                return 400, {"error": "invalid work id"}
            r = call("work_show", {"work_id": work_id}, home=home)
            if r.get("ok") and r.get("result") is None:
                return 404, {"error": f"no work item {work_id}"}
        elif sub == "events":
            entity = q.get("entity")
            if entity and not ENTITY.fullmatch(entity):
                return 400, {"error": "invalid entity"}
            if "tail" in q:
                r = events_tail(_int(q["tail"], 200, 0, 2000), entity, home=home)
            else:
                args = {"since": _int(q.get("since"), 0, 0, 2 ** 62),
                        "limit": _int(q.get("limit"), 200, 1, 2000)}
                if entity:
                    args["entity"] = entity
                r = call("events", args, home=home)
                if r.get("ok"):
                    rows = r.get("result") or []
                    r["next"] = rows[-1]["seq"] if rows else args["since"]
        else:
            return 404, {"error": "not found"}
    except HubDown:
        return 503, {"error": "hub not running"}
    except HubTimeout as err:
        return 504, {"error": str(err)}
    except (ValueError, OSError) as err:
        return 502, {"error": f"hub answered badly: {str(err)[:200]}"}
    if not r.get("ok"):
        # The hub refused the request; pass its reason through.
        return 502, r
    return 200, r
