"""Roster proposals and approval; writes share the board transaction and audit log."""
from pathlib import Path
import sys

import ccboard

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
import agentdefs


def _target(db, value):
    key = ccboard.key_field(value, "id", required=True)
    if key is None or not ccboard.KEY_RE.fullmatch(key):
        raise ccboard.Invalid("missing id")
    return key, ccboard.entity(db, key)


def _rows(db, key):
    return [dict(row) for row in db.execute(
        "SELECT * FROM board_roster WHERE entity_key=? ORDER BY position,id", (key,))]


def _payload(db, key):
    rows = _rows(db, key)
    return {"id": key, "members": rows, "count": len(rows)}


def _write_target(db, body):
    actor = ccboard.text(body.get("actor"), "actor", 64, required=True,
                         pattern=ccboard.NAME_RE)
    key, task = _target(db, body.get("id"))
    if task.get("status") in ("done", "deleted"):
        raise ccboard.Refused("cannot change the roster of a closed card", [
            {"field": "status", "hint": "reopen the card before changing its roster"}])
    return key, task, actor


def roster(db, params):
    values = params.get("id", [])
    if not isinstance(values, list) or len(values) != 1:
        raise ccboard.Invalid("one id is required")
    key, _ = _target(db, values[0])
    return _payload(db, key)


def recruit(db, body):
    key, task, actor = _write_target(db, body)
    specs, _ = agentdefs.load_all()
    selected = agentdefs.choose_roster(task, specs, ccboard.config(db))
    existing = _rows(db, key)
    hired = {row["agent_name"] for row in existing if row["status"] == "hired"}
    desired = [(spec.name, spec.role, position) for position, spec in enumerate(selected)
               if spec.name not in hired]
    current = [(row["agent_name"], row["role"], row["position"]) for row in existing
               if row["status"] != "hired"]
    # A retry preserves proposal IDs, timestamps and history. A fresh recruitment
    # after approval deliberately replaces every non-hired row with a proposal.
    if current == desired and all(row["status"] in ("proposed", "hired") for row in existing):
        return _payload(db, key)
    db.execute("DELETE FROM board_roster WHERE entity_key=? AND status!='hired'", (key,))
    stamp = ccboard.now()
    for name, role, position in desired:
        db.execute("INSERT INTO board_roster "
                   "(entity_key,agent_name,role,position,proposed_by,at,updated_at) "
                   "VALUES (?,?,?,?,?,?,?)", (key, name, role, position, actor, stamp, stamp))
    ccboard._record(db, key, "recruit", actor, detail={"members": [r[0] for r in desired]})
    return _payload(db, key)


def approve(db, body):
    key, _, actor = _write_target(db, body)
    members = body.get("members")
    if not isinstance(members, list) or len(members) > 32:
        raise ccboard.Invalid("members must be a list of at most 32 agent names")
    for name in members:
        ccboard.text(name, "member", 64, required=True, pattern=agentdefs.NAME_RE)
    if len(set(members)) != len(members):
        raise ccboard.Invalid("members must be unique")
    rows = _rows(db, key)
    available = {row["agent_name"] for row in rows
                 if row["status"] in ("proposed", "approved", "hired")}
    if set(members) - available:
        raise ccboard.Invalid("every approved member must have been proposed")
    if not rows:
        raise ccboard.Refused("recruit a roster before approval", [
            {"field": "roster", "hint": "POST /api/board/recruit with id and actor"}])
    # Approval is one decision for this proposal. Repeating it must not rewrite
    # the original approver or timestamp; a different decision needs recruitment.
    hired = {row["agent_name"] for row in rows if row["status"] == "hired"}
    decided = {row["agent_name"] for row in rows if row["status"] == "approved"}
    if any(row["status"] in ("approved", "rejected", "finished") for row in rows):
        if set(members) - hired == decided:
            return _payload(db, key)
        raise ccboard.Refused("roster already approved; recruit before changing approval", [
            {"field": "roster", "hint": "POST /api/board/recruit with id and actor"}])
    stamp = ccboard.now()
    approved, rejected = [], []
    for row in rows:
        if row["status"] != "proposed":
            continue
        name = row["agent_name"]
        status = "approved" if name in members else "rejected"
        db.execute("UPDATE board_roster SET status=?,approved_by=?,approved_at=?,updated_at=? "
                   "WHERE id=?", (status, actor if status == "approved" else None,
                                  stamp if status == "approved" else None, stamp, row["id"]))
        (approved if status == "approved" else rejected).append(name)
    if approved:
        ccboard._record(db, key, "approve", actor, detail={"members": approved})
    if rejected:
        ccboard._record(db, key, "reject", actor, detail={"members": rejected})
    return _payload(db, key)


def hire(db, body):
    raise ccboard.Invalid("hire is not implemented yet")
