"""The task-management domain: keys, the full task record, gates and queries.

WHY THIS FILE EXISTS
--------------------
The Control Center board stored a title, a status, an agent and an integer primary
key. That is a list, not a task management system. An integer primary key is not an
identifier anybody can say out loud, write in a commit message, or put in a branch
name - it is a row number, it is not stable across a restore from backup, and two
boards both have a task 7.

This mirrors the identifier and record model of the bytedesk-marketplace
`task-management` plugin (ByteDeskAI/bytedesk-marketplace), which solves exactly
that: every entity carries a minted, zero-padded, never-reused key - EP-001,
TM-014, ADR-0007, SP-002, CAP-0003 - and a record rich enough that the key is worth
having. Same prefixes, same padding, same status vocabulary, same gate semantics.

WHAT IS DELIBERATELY DIFFERENT
------------------------------
Upstream persists one markdown file per entity and derives an index. Here the store
is SQLite in `cc.db`, because that is what every existing Control Center endpoint,
the CLI and the test suites already read, and because `dashboard/SPEC_CC.md` binds
this project to the Python 3 standard library with no pip. So:

  * `nextId` reads a directory for max+1 under a file lock. Here a `board_counters`
    row is bumped inside the same transaction as the insert, which is stronger:
    the number cannot be handed out twice even under concurrent writers, and it is
    never reused after a delete because the counter only ever moves forward.
  * Upstream soft-deletes by writing `status: deleted` into the file. That is kept
    exactly - `delete` sets the status, the row stays, and the key stays burned.

The vocabularies below are the upstream ones verbatim. They are duplicated in
app.js and in coordination.py; all three must agree or a value one accepts is
rejected by another, which is the failure smoke.sh already guards for statuses.
"""

import datetime as dt
import json
import os
import re
import sqlite3


# ── vocabulary ───────────────────────────────────────────────────────────────
#
# lib/paths.mjs KINDS, verbatim: prefix and zero-padding width.
KINDS = {
    "epic": ("EP", 3),
    "task": ("TM", 3),
    "adr": ("ADR", 4),
    "sprint": ("SP", 3),
    "capability": ("CAP", 4),
}
KEY_RE = re.compile(r"^(EP|TM|ADR|SP|CAP)-([0-9]{3,9})$")

# dashboard/src/lib/types.ts Status. One vocabulary for every kind, as upstream.
STATUSES = ("backlog", "open", "in_progress", "blocked", "parked", "done", "deleted")
RESOLVED = frozenset(("done", "deleted"))
# lib/store.mjs PRIORITIES - most urgent first; the queue order reads this.
PRIORITIES = ("highest", "high", "medium", "low", "lowest")
# lib/issue.mjs TYPES. `subtask` is not a type - parentage is the `parent` field.
TYPES = ("task", "bug", "story", "spike", "chore")
ADR_STATUSES = ("proposed", "accepted", "superseded")
LINK_TYPES = ("relates", "duplicates", "blocks", "causes", "implements")
CAP_LEVELS = ("high", "medium", "low")

# lib/completeness.mjs
TRIAGE_LABELS = ("needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix")
DECISION_MAP = "decision:map"
DECISION_KIND = ("decision:interview", "decision:research", "decision:prototype", "decision:unblock")
# Labels that hand the next move to a person. decision:research is absent on
# purpose: it is the one decision an agent can answer on its own.
NOT_FOR_AGENTS = ("ready-for-human", "needs-info", "wontfix", "human-gate",
                  "decision:interview", "decision:prototype", "decision:unblock", DECISION_MAP)
LABEL_CATALOG = tuple(sorted(set(TRIAGE_LABELS) | set(DECISION_KIND) | {DECISION_MAP, "human-gate"}))

# The status an entity is born in, per kind. Upstream stamps `status: "open"` in
# create() for everything and lets the ADR verb override it.
BIRTH_STATUS = {"epic": "open", "task": "open", "adr": "proposed",
                "sprint": "open", "capability": "open"}

MAX_TITLE = 256
MAX_BODY = 65536
MAX_TEXT = 8192
MAX_REF = 512
MAX_LIST = 200
NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
LABEL_RE = re.compile(r"[A-Za-z0-9_.:-]{1,48}")
PATH_RE = re.compile(r"[^\x00-\x1f]{1,512}")

# lib/config defaults. Stored per board in board_config so a project can change
# them; the names are upstream's so a reader of either codebase recognises them.
DEFAULT_CONFIG = {
    "requireOnCreate": ["body", "acceptance"],
    "requireOnStart": ["body", "acceptance"],
    "requireOnDone": ["body", "acceptance", "evidence", "actor"],
    "requireAcceptance": True,
    "requireEpic": True,
    "wipLimit": 3,
    "autoCloseEpic": True,
    "autoReady": "label",
}
CONFIG_BOOLS = {"requireAcceptance", "requireEpic", "autoCloseEpic"}
CONFIG_LISTS = {"requireOnCreate", "requireOnStart", "requireOnDone"}


class Invalid(ValueError):
    """A request that is malformed. Carries a message safe to return to a client."""


class NotFound(Exception):
    pass


class Refused(Exception):
    """A gate said no. `missing` names the gaps and the verb that fills each one."""

    def __init__(self, message, missing=None):
        super().__init__(message)
        self.missing = missing or []


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")
