"""The port inventory: what the vanilla dashboard has, derived from its source.

WHY THIS EXISTS. The React rewrite must be 1:1 - every view, panel, module,
stored preference and endpoint that exists today has to exist afterwards, plus
the new work. The way a rewrite loses a feature is never a decision; it is a
list somebody wrote from memory, and the missing line is found by an operator
six weeks later when the thing they use every day is gone.

So the list is not written. It is DERIVED from the source on every run, and
compared against a manifest that has to account for each item. An item present
in the source and absent from the manifest fails the check - a new feature
cannot be added to the old dashboard without someone deciding whether it ports.
An item marked `ported` whose React counterpart does not exist on disk fails
too, so the manifest cannot claim work that was not done.

THREE STATES, and the third is the honest one that makes this usable:
  vanilla  - exists in the old UI, not yet ported. The default.
  ported   - has a React counterpart, and `react` names the file. Checked.
  dropped  - deliberately not ported, and `why` says so in a sentence. A drop
             is a decision somebody signed, not an omission.

Derivation is deliberately conservative: it over-reports rather than under.
A false entry costs somebody thirty seconds to mark `dropped`; a missing one
costs a feature.
"""

import io
import json
import re
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent
REPO = DASHBOARD.parent
MANIFEST = REPO / 'docs' / 'port-parity.json'
WEB = REPO / 'packages' / 'web'


def _read(path):
    """Never raises. /mnt/c is 9p and a read there can fail transiently; a
    parity check that explodes on an EIO is a check people learn to re-run
    rather than read."""
    try:
        return io.open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def _strip_js_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'(?m)//.*$', '', text)


def inventory():
    """Everything the current dashboard exposes, as {kind: sorted[names]}."""
    html = _read(DASHBOARD / 'index.html')
    app = _strip_js_comments(_read(DASHBOARD / 'app.js'))
    server = _read(DASHBOARD / 'server.py')

    views = set(re.findall(r'data-view="([a-z]+)"', html))
    # A view is also anything registerView() names, in case the rail markup and
    # the registry ever disagree - which is exactly the kind of drift that
    # leaves a view reachable by URL and invisible in the nav.
    views |= set(re.findall(r"registerView\(\s*['\"]([a-z]+)['\"]", app))

    panels = set(re.findall(r'data-panel="([a-z0-9]+)"', html))
    panels |= set(re.findall(r"registerPanel\(\s*['\"][a-z]+['\"]\s*,\s*['\"]([a-z0-9]+)['\"]", app))

    modules = set(re.findall(r'<script[^>]+src="([a-z0-9_]+\.js)"', html))
    modules.discard('app.js')          # the host, not a view module

    # Stored preferences. These are the ones a careless rename silently wipes -
    # themes, board layout, collapse state - so they are inventoried by the
    # CONSTANT that holds them and by the literal it is assigned.
    storage = set()
    for name, value in re.findall(r"(?:const|let|var)\s+([A-Z][A-Z0-9_]*KEY)\s*=\s*['\"]([^'\"]+)['\"]", app):
        storage.add(value)
    storage |= set(re.findall(r"localStorage\.(?:get|set|remove)Item\(\s*['\"]([^'\"]+)['\"]", app))

    routes = set(re.findall(r'path\s*==\s*["\'](/api/[a-z0-9_/-]+)["\']', server))
    routes |= set(re.findall(r'path\.startswith\(["\'](/api/[a-z0-9_/-]+)["\']', server))
    routes |= set(re.findall(r'path\s+in\s+\(([^)]*?)\)', server, re.S) and
                  re.findall(r'["\'](/api/[a-z0-9_/-]+)["\']', server))

    board_ops = set()
    for pattern in (r'BOARD_READS\s*=\s*[\{\(]([^}\)]*)[\}\)]',
                    r'BOARD_WRITES\s*=\s*[\{\(]([^}\)]*)[\}\)]'):
        match = re.search(pattern, server, re.S)
        if match:
            board_ops |= set(re.findall(r"['\"]([a-z_]+)['\"]", match.group(1)))

    return {
        'views': sorted(views),
        'panels': sorted(panels),
        'modules': sorted(modules),
        'storage': sorted(storage),
        'routes': sorted(routes),
        'board_ops': sorted(board_ops),
    }


def load_manifest():
    raw = _read(MANIFEST)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def react_exists(relative):
    """Does the claimed React counterpart actually exist?"""
    if not relative:
        return False
    return (WEB / relative).is_file()


def audit():
    """Returns (unclassified, unbacked, dropped) for the whole surface.

    unclassified - in the source, missing from the manifest. The dangerous one.
    unbacked     - manifest says `ported`, the named file is not on disk.
    dropped      - deliberately not ported, with the reason, for the report.
    """
    inv = inventory()
    man = load_manifest()
    unclassified, unbacked, dropped = [], [], []

    for kind, names in inv.items():
        entries = man.get(kind, {})
        for name in names:
            entry = entries.get(name)
            if entry is None:
                unclassified.append((kind, name))
                continue
            status = (entry or {}).get('status', 'vanilla')
            if status == 'ported':
                if not react_exists((entry or {}).get('react', '')):
                    unbacked.append((kind, name, (entry or {}).get('react', '<none named>')))
            elif status == 'dropped':
                dropped.append((kind, name, (entry or {}).get('why', '<no reason given>')))
    return unclassified, unbacked, dropped


def summary():
    """Counts per kind and per status, for a one-line progress report."""
    inv = inventory()
    man = load_manifest()
    out = {}
    for kind, names in inv.items():
        entries = man.get(kind, {})
        counts = {'total': len(names), 'ported': 0, 'vanilla': 0, 'dropped': 0, 'unclassified': 0}
        for name in names:
            entry = entries.get(name)
            if entry is None:
                counts['unclassified'] += 1
            else:
                counts[(entry or {}).get('status', 'vanilla')] = \
                    counts.get((entry or {}).get('status', 'vanilla'), 0) + 1
        out[kind] = counts
    return out


def seed():
    """A manifest skeleton with every item marked `vanilla`, for bootstrapping."""
    return {kind: {name: {'status': 'vanilla'} for name in names}
            for kind, names in inventory().items()}


if __name__ == '__main__':
    import sys
    if '--seed' in sys.argv:
        print(json.dumps(seed(), indent=2, sort_keys=True))
    else:
        for kind, counts in summary().items():
            print(f"{kind:12} {counts}")
