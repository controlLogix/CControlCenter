"""Agent definition reads and atomic, checksum-guarded write operations.

Read operations receive parse_qs parameters; writes receive the JSON body.
Each operation owns its validation and returns a JSON-serializable payload.
"""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

import ccboard

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
import agentdefs

# The check and mutation must be serialized together in the threaded server.
_WRITE_LOCK = threading.Lock()


def agents(db, params):
    """Return the discovered roster, or one full definition for editing."""
    name = None
    if "name" in params:
        values = params["name"]
        if (len(values) != 1 or not isinstance(values[0], str)
                or not agentdefs.NAME_RE.fullmatch(values[0])):
            raise ccboard.Invalid("name must match ^[a-z][a-z0-9-]{0,63}$")
        name = values[0]

    specs, problems = agentdefs.load_all()

    def payload(spec):
        row = asdict(spec)
        for field in ("tools", "tools_deny", "capabilities"):
            row[field] = list(row[field])
        row["editable"] = spec.scope != "claude"
        return row

    if name is not None:
        if name not in specs:
            raise ccboard.NotFound("agent not found: " + name)
        return payload(specs[name])

    rows = []
    for key in sorted(specs):
        row = payload(specs[key])
        del row["persona"]
        rows.append(row)
    return {"agents": rows, "scopes": list(agentdefs.SCOPES),
            "problems": problems, "count": len(rows)}


def _directories():
    home = Path.home()
    root = Path(os.environ.get("AGENTMUX_HOME", str(home / ".agentmux"))).absolute()
    return ((Path.cwd() / ".agentmux/agents", "repo"),
            (root / "agents", "global"),
            (Path.cwd() / ".claude/agents", "claude"),
            (home / ".claude/agents", "claude"))


def _target(body):
    if not isinstance(body, dict):
        raise ccboard.Invalid("definition must be an object")
    name, scope = body.get("name"), body.get("scope")
    if not isinstance(name, str) or not agentdefs.NAME_RE.fullmatch(name):
        raise ccboard.Invalid("name must match ^[a-z][a-z0-9-]{0,63}$")
    if scope not in ("repo", "global"):
        raise ccboard.Invalid("scope must be repo or global; claude definitions are read-only")
    directory = next(d for d, s in _directories() if s == scope)
    path = directory / (name + ".md")
    # Reject redirected agent directories and leaf symlinks, including dangling ones.
    if directory.is_symlink() or path.is_symlink():
        raise ccboard.Invalid("definition path must not be a symlink")
    if "path" in body:
        supplied = body["path"]
        if (not isinstance(supplied, str) or "\x00" in supplied
                or Path(supplied).absolute() != path or Path(supplied).resolve() != path.resolve()):
            raise ccboard.Invalid("path must name the definition in its agent directory")
    if path.exists() and not path.is_file():
        raise ccboard.Invalid("definition must be a regular file")
    return path, scope


def _conflict(message, path):
    raise ccboard.Refused(message, [{"field": "name", "hint": str(path)}])


def _check_collisions(path):
    for directory, _ in _directories():
        other = directory / path.name
        if other.absolute() == path.absolute():
            continue
        if other.exists() or other.is_symlink():
            # Discovery also deduplicates aliased directories.
            if directory.resolve() == path.parent.resolve():
                continue
            _conflict("agent name already taken: " + path.stem, other)


def _check_checksum(path, body):
    checksum = body.get("checksum")
    if path.exists():
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != actual:
            _conflict("definition changed or name already taken; reload before saving", path)
    elif checksum not in (None, ""):
        _conflict("definition no longer exists; reload before saving", path)


def _encode(body, path, scope):
    fields = {}
    try:
        for key in agentdefs.KEYS:
            value = body.get("tools_deny" if key == "tools-deny" else key)
            if value is None:
                continue
            if key in ("tools", "tools-deny", "capabilities"):
                if not isinstance(value, list) or any(
                        not isinstance(item, str) or not item.strip() or "," in item
                        for item in value):
                    raise ValueError(f"{key} must be a list of nonempty strings without commas")
                value = ", ".join(value)
            elif key == "max_instances":
                if type(value) is not int:
                    raise ValueError("max_instances must be an integer from 1 to 8")
                value = str(value)
            fields[key] = agentdefs._string(value, key)
        persona = agentdefs._string(body.get("persona", ""), "persona", multiline=True)
        raw = ("---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                                for key, value in sorted(fields.items()))
               + "---\n" + persona).encode("utf-8")
        if len(raw) > agentdefs.MAX_BYTES:
            raise ValueError("definition exceeds 64 KiB")
        defaults = agentdefs._defaults(_directories()[1][0].parent, lambda *args: None)
        parsed, parsed_persona = agentdefs._frontmatter(raw)
        spec = agentdefs._spec(path, scope, raw, parsed, parsed_persona, *defaults)
    except (ValueError, TypeError) as exc:
        raise ccboard.Invalid(str(exc)) from exc
    return raw, spec


def agentdef(db, body):
    with _WRITE_LOCK:
        path, scope = _target(body)
        _check_collisions(path)
        _check_checksum(path, body)
        raw, spec = _encode(body, path, scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp creates a unique 0600 file regardless of the process umask;
        # changing umask here would affect unrelated HTTP threads.
        fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp",
                                         dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        row = asdict(spec)
        for field in ("tools", "tools_deny", "capabilities"):
            row[field] = list(row[field])
        return dict(row, editable=True)


def agentdrop(db, body):
    with _WRITE_LOCK:
        path, _ = _target(body)
        if not path.exists():
            raise ccboard.NotFound("agent not found: " + body["name"])
        # UNCONDITIONAL, exactly as agentdef does it. Making the checksum optional
        # here meant a caller could delete a definition simply by omitting the key -
        # so a stale tab could destroy a file that a SAVE from that same stale state
        # would have been refused. And unlike ccboard.delete, which is a soft delete
        # precisely so nothing is lost, this is a real unlink with no way back.
        _check_checksum(path, body)
        path.unlink()
        return {"ok": True, "scope": body["scope"], "name": body["name"]}
