#!/usr/bin/env python3
"""Byte/mode manifests for persistent state reachable by the dashboard suites.

No contents or credentials are printed. Pane logs and courier runtime files are
excluded: live agents append to them continuously independently of the suite.
Claude runtime histories/backups/cache stamps are likewise excluded; its settings
and configuration links remain covered. Queue/inbox, run metadata, claims, run ledgers, configuration and SQLite sidecars
are included. Concurrent operator edits therefore correctly produce a dirty result;
this detects differences, it does not claim to attribute who made them.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

STATE_DIRS = ('run', 'claims', 'runs', 'queue', 'inbox')
# These are Claude's own rotating runtime state, also explicitly excluded by the
# claude_config_dir mirror in agentmux.sh. The suite only writes its configuration.
CLAUDE_RUNTIME = {'sessions', 'history.jsonl', 'backups', 'projects', 'todos',
                  'statsig', 'shell-snapshots', 'ide'}


def record(path, result):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        value = {'link': os.readlink(path)}
    elif stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1048576), b''):
                digest.update(chunk)
        value = {'sha256': digest.hexdigest(), 'mode': stat.S_IMODE(info.st_mode)}
    elif stat.S_ISDIR(info.st_mode):
        for child in sorted(path.iterdir()):
            record(child, result)
        return
    else:
        raise ValueError(f'cannot verify non-regular state: {path}')
    result[str(path)] = value


def snapshot(roots, codex):
    result = {}
    for root in roots:
        root = Path(root).absolute()
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            # Every top-level file (including cc.db-{wal,shm,journal}, auth, env,
            # atlassian and journal fallback), plus persistent state directories.
            if path.name == 'claude-config' and path.is_dir() and not path.is_symlink():
                for child in sorted(path.iterdir()):
                    if child.name not in CLAUDE_RUNTIME and not child.name.endswith('.stamp.json'):
                        record(child, result)
            elif not path.is_dir() or path.is_symlink() or path.name in STATE_DIRS:
                record(path, result)
    for home in codex:
        home = Path(home).absolute()
        for path in set(home.glob('*.config.toml')) | {
                home / name for name in ('config.toml', 'auth.json', 'settings.json')}:
            if path.exists() or path.is_symlink():
                record(path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='verb', required=True)
    take = sub.add_parser('snapshot')
    take.add_argument('output')
    take.add_argument('--root', action='append', required=True)
    take.add_argument('--codex', action='append', default=[])
    compare = sub.add_parser('compare')
    compare.add_argument('before')
    compare.add_argument('after')
    args = parser.parse_args()
    try:
        if args.verb == 'snapshot':
            Path(args.output).write_text(json.dumps(snapshot(args.root, args.codex), sort_keys=True))
            return 0
        before = json.loads(Path(args.before).read_text())
        after = json.loads(Path(args.after).read_text())
        changed = False
        for path in sorted(before.keys() | after.keys()):
            if before.get(path) != after.get(path):
                action = 'created' if path not in before else 'deleted' if path not in after else 'modified'
                print(f'RESIDUE: {action}: {path}')
                changed = True
        if not changed:
            print(f'CLEAN: {len(before)} covered files are byte/mode-identical; no additions or deletions')
        return int(changed)
    except (OSError, ValueError) as error:
        print(f'NOT VERIFIED: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
