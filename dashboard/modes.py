"""Mode profiles: the shape of the console for one kind of work.

A mode names which views are on the rail, which agents, skills and MCP servers
are in scope, the theme, and how the blade behaves. Adding a mode is adding a
file to modes/; no code changes.

AN INVALID FILE IS NEVER FATAL. A console that will not start because of a YAML
typo is worse than one that starts degraded and says which file is wrong and
where. Every problem becomes a diagnostic carrying the file, the field and - when
the parser gives us one - the line and column. The last good compile of a mode
stays live while its file is broken, so an editor save mid-keystroke does not
blank the rail.

YAML IS OPTIONAL, DELIBERATELY. dashboard/SPEC_agentmux.md's rule is that the
dashboard installs from a clone with no network and no pip. PyYAML is a system
package here, not vendored, so a plant box may not have it. Missing PyYAML
disables modes and says so - exactly the posture modbus_rtu.py:86-88 takes for
pyserial. Vendoring it is the fix; see the task.

NO WATCHER. modes/ lives on /mnt/c, which is a 9p mount, and inotify does not
fire there for Windows-side writes. The loader restats on read instead. Polling
is unglamorous and it is the thing that actually works across this boundary.
"""
import os
from pathlib import Path

try:
    import yaml
    YAML_ERROR = None
except Exception as err:                    # noqa: BLE001 - report, never die
    yaml = None
    YAML_ERROR = f"{type(err).__name__}: {err}"

ROOT = Path(__file__).resolve().parent.parent
MODES_DIR = Path(os.environ.get("AGENTMUX_MODES_DIR") or (ROOT / "modes"))

# The views the shell actually has. A mode naming anything else is a diagnostic
# rather than a blank rail item.
VIEWS = ("terminals", "status", "board", "runs", "organization", "iiot",
         "github", "settings")
PANELS = ("conversation", "confirmations", "runs")
STATES = ("hidden", "overlay", "pinned")

MIN_WIDTH, MAX_WIDTH = 320, 900

# Last good compile per id, so a broken edit does not blank a live rail.
_last_good = {}


def _diag(file, field, message, line=None, col=None):
    d = {"file": file, "field": field, "message": message}
    if line is not None:
        d["line"] = line
    if col is not None:
        d["col"] = col
    return d


def _mark(err):
    """Line and column out of a PyYAML error, when it carries one."""
    mark = getattr(err, "problem_mark", None)
    if mark is None:
        return None, None
    return mark.line + 1, mark.column + 1


def compile_mode(path, raw):
    """Validate one parsed mode. Returns (mode or None, [diagnostics])."""
    name = path.name
    problems = []

    if not isinstance(raw, dict):
        return None, [_diag(name, None, "a mode file must be a mapping")]

    stem = path.stem
    ident = raw.get("id")
    if not isinstance(ident, str) or not ident:
        problems.append(_diag(name, "id", "id is required"))
        ident = stem
    elif ident != stem:
        # The switcher addresses a mode by id and the operator edits it by
        # filename; if those disagree, one of them is a lie.
        problems.append(_diag(name, "id",
                              f'id "{ident}" does not match the filename "{stem}"'))

    views = raw.get("views")
    if not isinstance(views, list) or not views:
        problems.append(_diag(name, "views", "views must be a non-empty list"))
        views = list(VIEWS)
    else:
        unknown = [v for v in views if v not in VIEWS]
        if unknown:
            problems.append(_diag(name, "views",
                                  f"unknown view(s): {', '.join(map(str, unknown))}"))
            views = [v for v in views if v in VIEWS] or list(VIEWS)

    default_view = raw.get("default_view")
    if default_view is not None and default_view not in views:
        problems.append(_diag(name, "default_view",
                              f'default_view "{default_view}" is not in views'))
        default_view = None
    if default_view is None:
        default_view = views[0]

    blade = raw.get("blade") if isinstance(raw.get("blade"), dict) else {}
    state = blade.get("default_state", "hidden")
    if state not in STATES:
        problems.append(_diag(name, "blade.default_state",
                              f'must be one of: {", ".join(STATES)}'))
        state = "hidden"
    width = blade.get("width", 420)
    if not isinstance(width, int) or not MIN_WIDTH <= width <= MAX_WIDTH:
        problems.append(_diag(name, "blade.width",
                              f"must be an integer between {MIN_WIDTH} and {MAX_WIDTH}"))
        width = 420
    panels = blade.get("panels") or list(PANELS)
    if not isinstance(panels, list) or any(p not in PANELS for p in panels):
        problems.append(_diag(name, "blade.panels",
                              f'panels must be drawn from: {", ".join(PANELS)}'))
        panels = list(PANELS)

    session = raw.get("session") if isinstance(raw.get("session"), dict) else {}

    def names(field):
        value = raw.get(field) or []
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            problems.append(_diag(name, field, f"{field} must be a list of names"))
            return []
        return value

    mode = {
        "id": ident,
        "title": raw.get("title") or ident,
        "description": raw.get("description") or "",
        "icon": raw.get("icon") or "",
        "order": raw.get("order") if isinstance(raw.get("order"), int) else 100,
        "theme": raw.get("theme") or None,
        "views": views,
        "default_view": default_view,
        "mcp": names("mcp"),
        "agents": names("agents"),
        "skills": names("skills"),
        "blade": {"default_state": state, "width": width, "panels": panels},
        "session": {
            "durable": bool(session.get("durable")),
            "idle_ttl_minutes": session.get("idle_ttl_minutes", 30),
            "background_agents": bool(session.get("background_agents")),
            "source_capture": bool(session.get("source_capture")),
            "artifact_dir": session.get("artifact_dir") or None,
        },
        "file": name,
    }
    return mode, problems


def load_modes():
    """Every mode, plus every diagnostic. Never raises."""
    diagnostics = []

    if yaml is None:
        return [], [_diag(None, None,
                          "modes need PyYAML, which is not installed here. "
                          "Install it, or vendor it under dashboard/vendor/ as paho "
                          f"is. ({YAML_ERROR})")]

    try:
        paths = sorted(p for p in MODES_DIR.glob("*.yaml") if p.is_file())
    except OSError as err:
        return [], [_diag(None, None, f"modes directory unreadable: {err}")]

    modes = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as err:
            diagnostics.append(_diag(path.name, None, f"unreadable: {err}"))
            continue
        try:
            raw = yaml.safe_load(text)
        except Exception as err:            # noqa: BLE001 - any parse failure
            line, col = _mark(err)
            diagnostics.append(_diag(path.name, None,
                                     str(getattr(err, "problem", err)), line, col))
            # A file that will not parse keeps its last good compile, so an
            # editor save mid-keystroke does not blank the rail.
            keep = _last_good.get(path.stem)
            if keep:
                modes.append(dict(keep, stale=True))
            continue

        mode, problems = compile_mode(path, raw)
        diagnostics.extend(problems)
        if mode is not None:
            _last_good[path.stem] = mode
            modes.append(mode)

    modes.sort(key=lambda m: (m["order"], m["id"]))
    return modes, diagnostics


def snapshot():
    modes, diagnostics = load_modes()
    return {
        "modes": modes,
        "diagnostics": diagnostics,
        "dir": str(MODES_DIR),
        # Said out loud: a watcher would not fire here, so the UI knows the
        # freshness it is getting.
        "watch": "poll",
    }
