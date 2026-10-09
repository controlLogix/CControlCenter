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

TYPES = {"message", "handoff", "result", "work", "knowledge", "code", "revoke"}
PLANE_OF = {"message": "msg", "handoff": "msg", "result": "msg", "work": "work",
            "knowledge": "know", "code": "code", "revoke": "ctl"}
TOKEN = re.compile(r"^[a-z0-9_]{1,32}$")
RID = re.compile(r"^r[0-9a-f]{12}$")


class BadEnvelope(ValueError):
    pass


def make(type_, frm, node, rid=None, to="*", data=None):
    if type_ not in TYPES:
        raise BadEnvelope(f"unknown envelope type {type_!r}")
    return {"v": 2, "id": ulid(), "type": type_, "from": frm, "node": node, "rid": rid, "to": to,
            "at": now(), "data": data or {}}


def subject(plane, frm, *tail):
    for t in (frm, *tail):
        if not TOKEN.match(t or ""):
            raise BadEnvelope(f"subject token {t!r} is not [a-z0-9_]")
    return ".".join(("am", plane, frm, *tail))


def parse_subject(subj: str):
    parts = subj.split(".")
    if len(parts) < 3 or parts[0] != "am":
        raise BadEnvelope(f"not a federation subject: {subj}")
    return parts[1], parts[2], parts[3:]


def validate(env) -> dict:
    if not isinstance(env, dict) or env.get("v") != 2:
        raise BadEnvelope("not a v2 envelope")
    if env.get("type") not in TYPES:
        raise BadEnvelope(f"unknown type {env.get('type')!r}")
    if not TOKEN.match(str(env.get("from", ""))):
        raise BadEnvelope("bad sender")
    if env.get("rid") is not None and not RID.match(str(env["rid"])):
        raise BadEnvelope("bad rid")
    if not isinstance(env.get("data", {}), dict):
        raise BadEnvelope("data must be an object")
    if not str(env.get("id", "")):
        raise BadEnvelope("missing id")
    return env
