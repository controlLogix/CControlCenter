"""Agent definition reads and seams for subsequent EP-015 write operations.

Read operations receive parse_qs parameters; writes receive the JSON body.
Each operation owns its validation and returns a JSON-serializable payload.
"""

from dataclasses import asdict
from pathlib import Path
import sys

import ccboard

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
import agentdefs


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


def agentdef(db, body):
    raise ccboard.Invalid("agentdef is not implemented yet")


def agentdrop(db, body):
    raise ccboard.Invalid("agentdrop is not implemented yet")
