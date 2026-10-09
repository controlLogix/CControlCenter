"""Envelope v2 and subject grammar: the canonical data model on the wire (FEDERATION.md 5).

  {"v": 2, "id": ULID, "type": T, "from": PEER, "node": NODE, "rid": RID|null,
   "to": PEER|"*", "at": ISO8601, "data": {...}}

Subjects are am.<plane>.<from>.<tail...>. Token 3 is the sender, and the server only
lets a peer publish subjects that carry its own id there, so a receiver takes the
sender from the subject and checks the payload agrees - never the other way round.
"""
from __future__ import annotations

import re

from hub.store import now, ulid

WORK_TYPES = {"work", "work_claim", "work_grant", "result"}
TYPES = {"message", "handoff", "knowledge", "code", "revoke"} | WORK_TYPES
PLANE_OF = {"message": "msg", "handoff": "msg", "result": "msg", "work": "work",
            "work_claim": "msg", "work_grant": "msg", "knowledge": "know", "code": "code", "revoke": "ctl"}
TOKEN = re.compile(r"^[a-z0-9_]{1,32}$")
RID = re.compile(r"^r[0-9a-f]{12}$")


class BadEnvelope(ValueError):
    pass


def make(type_, frm, node, rid=None, to="*", data=None):
    if type_ not in TYPES:
        raise BadEnvelope(f"unknown envelope type {type_!r}")
    return {"v": 3 if type_ in WORK_TYPES else 2, "id": ulid(), "type": type_, "from": frm, "node": node, "rid": rid, "to": to,
            "at": now(), "data": data or {}}


def subject(plane, frm, *tail):
    if plane == "work":
        # Old exact-filter consumers must not swallow v3 offers they cannot grant.
        tail = (*tail, "v3")
    for t in (frm, *tail):
        if not TOKEN.match(t or ""):
            raise BadEnvelope(f"subject token {t!r} is not [a-z0-9_]")
    return ".".join(("am", plane, frm, *tail))


def parse_subject(subj: str):
    parts = subj.split(".")
    if len(parts) < 3 or parts[0] != "am":
        raise BadEnvelope(f"not a federation subject: {subj}")
    if parts[1] not in set(PLANE_OF.values()) or any(not TOKEN.fullmatch(p) for p in parts[2:]):
        raise BadEnvelope("invalid subject plane or token")
    return parts[1], parts[2], parts[3:]


def validate_route(subj: str, env: dict):
    """Bind the broker-authenticated sender and route to the dispatched operation."""
    plane, frm, tail = parse_subject(subj)
    validate(env)
    if env["from"] != frm:
        raise BadEnvelope("spoof: subject and envelope sender differ")
    if PLANE_OF[env["type"]] != plane:
        raise BadEnvelope("subject plane and envelope type differ")
    if plane == "msg":
        expected = [env.get("to")]
    elif plane == "work":
        expected = [env.get("rid"), env.get("data", {}).get("role")]
        if env["v"] == 3:
            expected.append("v3")
    elif plane in ("know", "code"):
        expected = [env.get("rid")]
    else:
        expected = []
    if tail != expected or (plane != "msg" and env.get("to") != "*"):
        raise BadEnvelope("subject destination, repository or role differs from envelope")
    return plane, frm, tail


def validate(env) -> dict:
    if not isinstance(env, dict) or env.get("v") not in (2, 3):
        raise BadEnvelope("not a supported envelope version")
    if not isinstance(env.get("type"), str) or env["type"] not in TYPES:
        raise BadEnvelope(f"unknown type {env.get('type')!r}")
    if env.get("v") == 3 and env.get("type") not in WORK_TYPES:
        raise BadEnvelope("v3 is reserved for the work protocol")
    if not isinstance(env.get("from"), str) or not TOKEN.fullmatch(env["from"]):
        raise BadEnvelope("bad sender")
    if not isinstance(env.get("node"), str) or not TOKEN.fullmatch(env["node"]):
        raise BadEnvelope("bad node")
    if env.get("to") != "*" and (not isinstance(env.get("to"), str) or not TOKEN.fullmatch(env["to"])):
        raise BadEnvelope("bad destination")
    if env.get("rid") is not None and not RID.match(str(env["rid"])):
        raise BadEnvelope("bad rid")
    if not isinstance(env.get("data", {}), dict):
        raise BadEnvelope("data must be an object")
    if not isinstance(env.get("id"), str) or not 1 <= len(env["id"]) <= 128:
        raise BadEnvelope("missing id")
    return env
