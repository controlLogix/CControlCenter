"""Phase 1 Control Center persistence and bounded, read-only queue ingestion."""

from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading


DB_PATH = Path.home() / ".agentmux" / "cc.db"
QUEUE_DIR = Path.home() / ".agentmux" / "queue"
NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# "claim" and "release" are coordination, not conversation: an agent announcing that
# it has taken or given up a resource. They are a distinct kind so the dashboard can
# filter them and an agent can tell a work boundary from a remark. The vocabulary is
# duplicated in courier.py, agentmux.sh and app.js - all four must agree or a message
# accepted by one is invisible in another.
MESSAGE_KINDS = frozenset(("plan", "request", "reply", "status", "finding", "error",
                           "claim", "release"))
EPIC_STATUSES = frozenset(("open", "in_progress", "blocked", "done", "archived"))
TASK_STATUSES = frozenset(("todo", "in_progress", "blocked", "done", "cancelled"))
QUEUE_FILE_BYTES = 262144
QUEUE_TOTAL_BYTES = 4194304
QUEUE_MAX_FILES = 128
_schema_lock = threading.Lock()

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS epics (
        id INTEGER PRIMARY KEY, key TEXT UNIQUE, title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open', jira_key TEXT,
        created_at TEXT, updated_at TEXT, notes TEXT)""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY, epic_id INTEGER REFERENCES epics(id) ON DELETE CASCADE,
        title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo', agent TEXT,
        jira_key TEXT, created_at TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL,
        agent TEXT, subject TEXT, body TEXT)""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, sender TEXT NOT NULL,
        recipient TEXT, kind TEXT NOT NULL, body TEXT, ref TEXT)""",
    """CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        address TEXT, port INTEGER, protocol TEXT, meta TEXT, created_at TEXT)""",
)


class Invalid(ValueError):
    pass


class NotFound(Exception):
    pass


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def parse_timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise Invalid("invalid timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        raise Invalid("timestamp must be ISO-8601 with an offset") from None


def timestamp_sort_key(value):
    try:
        return parse_timestamp(value).isoformat(timespec="microseconds")
    except Invalid:
        return None


@contextmanager
def connection():
    """A fresh connection, committed/rolled back and closed on every request."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.is_symlink():
        raise OSError("unsafe database path")
    if DB_PATH.exists():
        info = DB_PATH.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("unsafe database file")
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with _schema_lock:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("unsupported database version")
            with db:
                for statement in SCHEMA:
                    db.execute(statement)
                if version == 0:
                    db.execute("PRAGMA user_version=1")
        with db:
            yield db
    finally:
        db.close()


def text_field(body, key, maximum=256, required=False, pattern=None):
    value = body.get(key)
    if value is None and not required:
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or (required and not value.strip()) or "\x00" in value
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
            or (pattern is not None and not pattern.fullmatch(value))):
        raise Invalid("invalid " + key)
    return value


def positive_id(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise Invalid("invalid id")
    return value


def validate_write(resource, body):
    fields = {
        "epics": {"title", "key", "jira_key", "notes"},
        "tasks": {"epic_id", "title", "agent", "jira_key"},
        "journal": {"kind", "subject", "body", "agent"},
        "devices": {"name", "kind", "address", "port", "protocol", "meta"},
        "status": {"kind", "id", "status"},
        "delete": {"kind", "id"},
    }
    if not isinstance(body, dict) or body.keys() - fields[resource]:
        raise Invalid("unknown fields or invalid JSON object")
    token = re.compile(r"[A-Za-z0-9_.-]{1,64}")
    if resource == "epics":
        return dict(title=text_field(body, "title", required=True),
                    key=text_field(body, "key", 64, pattern=token),
                    jira_key=text_field(body, "jira_key", 64, pattern=token),
                    notes=text_field(body, "notes", 8192))
    if resource == "tasks":
        return dict(epic_id=positive_id(body.get("epic_id")),
                    title=text_field(body, "title", required=True),
                    agent=text_field(body, "agent", 64, pattern=NAME_PATTERN),
                    jira_key=text_field(body, "jira_key", 64, pattern=token))
    if resource == "journal":
        return dict(kind=text_field(body, "kind", 64, True, token),
                    subject=text_field(body, "subject", required=True),
                    body=text_field(body, "body", 8192),
                    agent=text_field(body, "agent", 64, pattern=NAME_PATTERN))
    if resource == "devices":
        port = body.get("port")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise Invalid("invalid port")
        meta = body.get("meta")
        if meta is not None:
            if not isinstance(meta, dict):
                raise Invalid("meta must be an object")
            try:
                meta = json.dumps(meta, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                raise Invalid("invalid meta") from None
            if len(meta) > 8192:
                raise Invalid("meta too large")
        return dict(name=text_field(body, "name", required=True),
                    kind=text_field(body, "kind", 64, True, token),
                    address=text_field(body, "address", 255), port=port,
                    protocol=text_field(body, "protocol", 64, pattern=token), meta=meta)
    if resource == "delete":
        kind = body.get("kind")
        if not isinstance(kind, str) or kind not in ("epic", "task", "device"):
            raise Invalid("invalid kind")
        return dict(kind=kind, id=positive_id(body.get("id")))
    kind = body.get("kind")
    status_value = body.get("status")
    if not isinstance(kind, str) or kind not in ("epic", "task"):
        raise Invalid("invalid kind")
    allowed = EPIC_STATUSES if kind == "epic" else TASK_STATUSES
    if not isinstance(status_value, str) or status_value not in allowed:
        raise Invalid("invalid status")
    return dict(kind=kind, id=positive_id(body.get("id")), status=status_value)


def device_row(row):
    result = dict(row)
    result["meta"] = json.loads(result["meta"]) if result["meta"] else None
    return result


def write(db, resource, values):
    now = timestamp()
    if resource == "epics":
        cursor = db.execute(
            "INSERT INTO epics (key,title,jira_key,notes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (values["key"], values["title"], values["jira_key"], values["notes"], now, now))
        return dict(db.execute("SELECT * FROM epics WHERE id=?", (cursor.lastrowid,)).fetchone())
    if resource == "tasks":
        if db.execute("SELECT id FROM epics WHERE id=?", (values["epic_id"],)).fetchone() is None:
            raise NotFound("epic not found")
        cursor = db.execute(
            "INSERT INTO tasks (epic_id,title,agent,jira_key,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (values["epic_id"], values["title"], values["agent"], values["jira_key"], now, now))
        return dict(db.execute("SELECT * FROM tasks WHERE id=?", (cursor.lastrowid,)).fetchone())
    if resource == "journal":
        cursor = db.execute("INSERT INTO journal (at,kind,agent,subject,body) VALUES (?,?,?,?,?)",
                            (now, values["kind"], values["agent"], values["subject"], values["body"]))
        return dict(db.execute("SELECT * FROM journal WHERE id=?", (cursor.lastrowid,)).fetchone())
    if resource == "devices":
        cursor = db.execute(
            "INSERT INTO devices (name,kind,address,port,protocol,meta,created_at) VALUES (?,?,?,?,?,?,?)",
            (values["name"], values["kind"], values["address"], values["port"],
             values["protocol"], values["meta"], now))
        return device_row(db.execute("SELECT * FROM devices WHERE id=?", (cursor.lastrowid,)).fetchone())
    if resource == "delete":
        # Table name comes from a fixed map, never from the request - the only place
        # an identifier is chosen dynamically, so it is chosen from code.
        #
        # journal is deliberately absent: it is append-only, which is the whole
        # point of an operational log. Deleting an epic cascades to its tasks via
        # the schema's ON DELETE CASCADE.
        table = {"epic": "epics", "task": "tasks", "device": "devices"}[values["kind"]]
        removed = 0
        if values["kind"] == "epic":
            removed = db.execute("SELECT COUNT(*) FROM tasks WHERE epic_id=?",
                                 (values["id"],)).fetchone()[0]
        cursor = db.execute(f"DELETE FROM {table} WHERE id=?", (values["id"],))
        if cursor.rowcount == 0:
            raise NotFound("id not found")
        return {"ok": True, "kind": values["kind"], "id": values["id"],
                "cascaded_tasks": removed}
    if values["kind"] == "epic":
        cursor = db.execute("UPDATE epics SET status=?,updated_at=? WHERE id=?",
                            (values["status"], now, values["id"]))
        row = db.execute("SELECT * FROM epics WHERE id=?", (values["id"],)).fetchone()
    else:
        cursor = db.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?",
                            (values["status"], now, values["id"]))
        row = db.execute("SELECT * FROM tasks WHERE id=?", (values["id"],)).fetchone()
    if cursor.rowcount == 0:
        raise NotFound("id not found")
    return dict(row)


def queue_messages():
    """Read bounded tails through a pinned directory; never follow file links."""
    if QUEUE_DIR.is_symlink():
        raise OSError("unsafe queue directory")
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(QUEUE_DIR, flags | os.O_DIRECTORY)
    result = []
    budget = QUEUE_TOTAL_BYTES
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= QUEUE_MAX_FILES or budget <= 0:
                    break
                filename = entry.name
                if not filename.endswith(".jsonl") or not NAME_PATTERN.fullmatch(filename[:-6]):
                    continue
                try:
                    before = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        continue
                    fd = os.open(filename, flags | os.O_NONBLOCK, dir_fd=directory)
                    with os.fdopen(fd, "rb", buffering=0) as stream:
                        info = os.fstat(stream.fileno())
                        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                                or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
                            continue
                        size = min(info.st_size, QUEUE_FILE_BYTES, budget)
                        start = info.st_size - size
                        stream.seek(start)
                        raw = stream.read(size)
                        budget -= len(raw)
                        if os.fstat(stream.fileno()).st_nlink != 1:
                            continue
                    if start:
                        raw = raw.partition(b"\n")[2]
                    # Ignore a partial final record until its terminating newline arrives.
                    for line in raw.split(b"\n")[:-1]:
                        try:
                            value = json.loads(line)
                            if not isinstance(value, dict):
                                continue
                            at = text_field(value, "at", 64, True)
                            parse_timestamp(at)
                            kind = text_field(value, "kind", 64, True)
                            if kind not in MESSAGE_KINDS:
                                continue
                            result.append(dict(
                                at=at, sender=text_field(value, "sender", 64, True, NAME_PATTERN),
                                recipient=text_field(value, "recipient", 64, pattern=NAME_PATTERN),
                                kind=kind, body=text_field(value, "body", 65536),
                                ref=text_field(value, "ref", 256)))
                        except (ValueError, UnicodeError, RecursionError):
                            continue
                except OSError:
                    continue
    finally:
        os.close(directory)
    return result


def read(db, resource, limit=100, since=None):
    if resource == "epics":
        epics = [dict(row, tasks=[]) for row in db.execute("SELECT * FROM epics ORDER BY id")]
        by_id = {row["id"]: row for row in epics}
        for row in db.execute("SELECT * FROM tasks ORDER BY id"):
            if row["epic_id"] in by_id:
                by_id[row["epic_id"]]["tasks"].append(dict(row))
        return epics
    if resource == "devices":
        return [device_row(row) for row in db.execute("SELECT * FROM devices ORDER BY id")]
    if resource == "journal":
        return [dict(row) for row in db.execute(
            "SELECT * FROM journal ORDER BY at DESC,id DESC LIMIT ?", (limit,))]
    # Normalize offsets without SQLite julianday's fractional-second rounding.
    db.create_function("cc_timestamp", 1, timestamp_sort_key, deterministic=True)
    rows = [dict(row) for row in db.execute(
        "SELECT * FROM messages ORDER BY cc_timestamp(at) DESC,id DESC LIMIT ?", (limit,))]
    rows.extend(queue_messages())
    ordered = []
    for row in rows:
        try:
            at = parse_timestamp(row["at"])
        except Invalid:
            continue
        if since is None or at > since:
            ordered.append((at, row))
    ordered.sort(key=lambda item: item[0])
    return [row for _, row in ordered[-limit:]]
