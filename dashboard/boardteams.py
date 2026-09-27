"""Roster proposals and approval; writes share the board transaction and audit log."""
from pathlib import Path
import json
import os
import sys
import tempfile
import threading

import ccboard

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
import agentdefs
import dispatch

HIRE_SLOTS = threading.BoundedSemaphore(2)


class HireForbidden(Exception):
    pass


class HireUnavailable(Exception):
    pass


def _target(db, value):
    key = ccboard.key_field(value, "id", required=True)
    if key is None or not ccboard.KEY_RE.fullmatch(key):
        raise ccboard.Invalid("missing id")
    return key, ccboard.entity(db, key)


def _rows(db, key):
    return [dict(row) for row in db.execute(
        "SELECT * FROM board_roster WHERE entity_key=? ORDER BY position,id", (key,))]


def _proposal_gaps(db, key):
    row = db.execute("SELECT detail FROM board_history WHERE entity_key=? "
                     "AND event='recruit' ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    return json.loads(row[0] or "{}").get("gaps", []) if row else []


def _payload(db, key):
    rows = _rows(db, key)
    return {"id": key, "members": rows, "count": len(rows), "gaps": _proposal_gaps(db, key)}


def _write_target(db, body):
    actor = ccboard.text(body.get("actor"), "actor", 64, required=True,
                         pattern=ccboard.NAME_RE)
    key, task = _target(db, body.get("id"))
    if task.get("status") in ("done", "deleted"):
        raise ccboard.Refused("cannot change the roster of a closed card", [
            {"field": "status", "hint": "reopen the card before changing its roster"}])
    return key, task, actor


def _retire_target(db, body):
    """Like _write_target, except A CLOSED CARD IS ALLOWED - and that is the point.

    Every other roster write refuses once the card is done or deleted, which is right
    for recruiting and approving onto finished work and exactly backwards for taking a
    team OFF it. Because the guard covered all of them equally, the roster of a
    completed card could never be changed again: the two agents on TM-083 had been
    welded to a card that went done on 2026-09-24, and the only way to remove them was
    to edit cc.db by hand. A card being finished is precisely when its roster should be
    clearable.
    """
    actor = ccboard.text(body.get("actor"), "actor", 64, required=True,
                         pattern=ccboard.NAME_RE)
    key, task = _target(db, body.get("id"))
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
    dependencies = {}
    for row in db.execute("SELECT entity_key,blocked_by FROM board_deps"):
        dependencies.setdefault(row["entity_key"], []).append(row["blocked_by"])
    selected = agentdefs.choose_roster(task, specs, ccboard.config(db),
                                       dependencies=dependencies)
    gaps = getattr(selected, "gaps", [])
    existing = _rows(db, key)
    hired = {row["agent_name"] for row in existing if row["status"] == "hired"}
    desired = [(spec.name, spec.role, position) for position, spec in enumerate(selected)
               if spec.name not in hired]
    current = [(row["agent_name"], row["role"], row["position"]) for row in existing
               if row["status"] != "hired"]
    # A retry preserves proposal IDs, timestamps and history. A fresh recruitment
    # after approval deliberately replaces every non-hired row with a proposal.
    if current == desired and gaps == _proposal_gaps(db, key) and all(row["status"] in ("proposed", "hired") for row in existing):
        return _payload(db, key)
    db.execute("DELETE FROM board_roster WHERE entity_key=? AND status!='hired'", (key,))
    stamp = ccboard.now()
    for name, role, position in desired:
        db.execute("INSERT INTO board_roster "
                   "(entity_key,agent_name,role,position,proposed_by,at,updated_at) "
                   "VALUES (?,?,?,?,?,?,?)", (key, name, role, position, actor, stamp, stamp))
    ccboard._record(db, key, "recruit", actor, detail={"members": [r[0] for r in desired], "gaps": gaps})
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


def retire(db, body):
    """Take members off a roster: proposed/approved/hired -> finished.

    THE ONE TRANSITION THE MODEL NAMED AND NEVER IMPLEMENTED. `finished` is already
    recognised by approve()'s already-decided guard and by the Teams panel's `decided`
    check, and nothing anywhere ever set it - so a member could be proposed, approved,
    rejected and hired, and never leave. Combined with the closed-card guard above
    (see _retire_target) a finished card kept its team on the board for good.

    A HIRED MEMBER WITH A PANE STILL UP IS NOT RETIRED, it is abandoned. Taking it off
    the roster while it is still running is how an agent ends up editing a card nobody
    believes it owns - so that is refused, and the fix is to kill the pane first. If
    tmux cannot be reached we cannot show the pane is gone, and "cannot prove it is
    stopped" is treated as "do not proceed", the same way collect_one does.
    """
    key, _task, actor = _retire_target(db, body)
    members = body.get("members")
    if not isinstance(members, list) or not 1 <= len(members) <= 32:
        raise ccboard.Invalid("members must be a list of 1 to 32 agent names")
    for name in members:
        ccboard.text(name, "member", 64, required=True, pattern=agentdefs.NAME_RE)
    if len(set(members)) != len(members):
        raise ccboard.Invalid("members must be unique")

    rows = _rows(db, key)
    on_roster = {row["agent_name"]: row for row in rows
                 if row["status"] in ("proposed", "approved", "hired")}
    unknown = sorted(set(members) - set(on_roster))
    if unknown:
        raise ccboard.Refused("not on this roster: " + ", ".join(unknown), [
            {"field": "members", "hint": f"GET /api/board/roster?id={key} lists who is"}])

    panes = {row["member_name"] for row in on_roster.values()
             if row["status"] == "hired" and row["member_name"]}
    if panes:
        running = dispatch.live_agents()        # TmuxUnavailable propagates on purpose
        busy = sorted(name for name in members
                      if on_roster[name]["member_name"] in running)
        if busy:
            raise ccboard.Refused(
                "still running: " + ", ".join(busy), [
                    {"field": "members",
                     "hint": "agentmux kill " + on_roster[busy[0]]["member_name"]}])

    stamp = ccboard.now()
    for name in members:
        db.execute("UPDATE board_roster SET status='finished',updated_at=? WHERE id=?",
                   (stamp, on_roster[name]["id"]))
    ccboard._record(db, key, "retire", actor, detail={"members": sorted(members)})
    return _payload(db, key)


def hire(db, body, *, bind_host=None):
    # Port 8787 is unauthenticated. The Origin allowlist only stops a browser
    # on another origin; a non-browser can omit Origin. Any local process with
    # socket access can hire. These five bounds are defence in depth, not
    # authentication: trusted definitions, approval, config, slots and posture.
    cfg = ccboard.config(db)
    if bind_host != "127.0.0.1":
        raise HireForbidden("dashboard hiring requires a 127.0.0.1 listener")
    if not cfg.get("dashboardMayHire") or not cfg.get("dispatchEnabled"):
        raise HireForbidden("dashboardMayHire and dispatchEnabled must both be enabled")
    key, task = _target(db, body.get("id"))
    name = ccboard.text(body.get("name"), "name", 64, required=True,
                        pattern=agentdefs.NAME_RE)
    row = db.execute("SELECT * FROM board_roster WHERE entity_key=? AND agent_name=? "
                     "AND status='approved'", (key, name)).fetchone()
    if row is None or task.get("status") in ("done", "deleted"):
        raise ccboard.Refused("hire requires an approved roster row on an open card", [
            {"field": "roster", "hint": "recruit and approve this name for this card"}])
    if not HIRE_SLOTS.acquire(blocking=False):
        raise HireUnavailable("dashboard hire slots exhausted")
    try:
        # Only id and name are read from the wire. cli/cwd/argv/model/flags and
        # even actor are ignored; resolve the current definition from disk.
        spec = agentdefs.resolve(name, dispatch.REPO)
        if spec is None:
            raise ccboard.Refused("agent definition is unavailable", [
                {"field": "name", "hint": "restore a valid agent definition"}])
        posture = spec.posture
        if os.environ.get("AGENTMUX_NO_BYPASS") == "1" and posture == "unrestricted":
            posture = "workspace-write"
        member = dispatch.member_name(key, spec.role, row["position"] + 1)
        args = ["spawn", member, "--cli", spec.cli, "--cwd", str(dispatch.REPO),
                "--agentdef", spec.name, "--posture", posture,
                "--team", key, "--role", spec.role]
        for flag, value in (("--model", spec.model), ("--auth", spec.auth),
                            ("--tools", ",".join(spec.tools)),
                            ("--deny-tools", ",".join(spec.tools_deny))):
            if value:
                args += [flag, value]
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".persona") as persona:
            persona.write(spec.persona)
            persona.flush()
            rc, _, _ = dispatch.agentmux(*args, "--persona-file", persona.name)
        if rc:
            raise HireUnavailable("agent spawn failed")
        db.execute("UPDATE board_roster SET status='hired',member_name=?,updated_at=? WHERE id=?",
                   (member, ccboard.now(), row["id"]))
        ccboard._record(db, key, "hire", "dashboard", detail={"name": name, "member": member})
        return _payload(db, key)
    finally:
        HIRE_SLOTS.release()
