#!/usr/bin/env bash
# Offline evidence-retention tests (TM-211) and shared-credential repair (TM-212).
# Isolated AGENTMUX_HOME, fake tmux on PATH, no model calls, never reads a real login.
set -euo pipefail
python3 - <<'PY'
import json, os, pathlib, re, subprocess, tempfile, time
repo = pathlib.Path.cwd()
counter = 0
def check(label):
    global counter
    counter += 1; print('ok', counter, label, flush=True)
with tempfile.TemporaryDirectory(prefix='agentmux-evidence-') as td:
    root = pathlib.Path(td)
    harness = root / 'agentmux.sh'
    harness.write_text((repo / 'agentmux.sh').read_text().replace('\r', ''))
    bindir = root / 'bin'; bindir.mkdir()
    state = root / 'state'; state.mkdir()
    home = root / 'home'
    logs = home / 'logs'; archive = logs / 'archive'
    cfg = home / 'claude-config'; carch = cfg / '.archive'
    src = root / 'claude-source'; src.mkdir()
    (src / 'settings.json').write_text('{}')
    (src / 'CLAUDE.md').write_text('shared instructions')
    # The shared store is itself a link, as it is when a setup links it elsewhere:
    # adoption must write through to the real target and leave the link standing.
    (src / 'real').mkdir()
    shared_target = src / 'real' / 'creds.json'
    shared_target.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'shared-original', 'accessToken': 'a'}}))
    shared_target.chmod(0o600)
    shared = src / '.credentials.json'
    os.symlink(str(shared_target), shared)
    old = time.time() - 3600
    os.utime(shared_target, (old, old))
    tmux = bindir / 'tmux'
    tmux.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[3:]
root = pathlib.Path(os.environ['FAKE_STATE'])
cmd = args[0]
def target():
    return args[args.index('-t')+1].lstrip('=')
if cmd == 'has-session':
    sys.exit(0 if (root / target()).exists() else 1)
elif cmd == 'new-session':
    (root / args[args.index('-s')+1]).write_text(args[-1])
elif cmd == 'kill-session':
    p = root / target()
    if not p.exists(): sys.exit(1)
    p.unlink()
elif cmd == 'list-sessions':
    sys.exit(0 if any(root.iterdir()) else 1)
elif cmd == 'list-panes':
    print('%1')
elif cmd == 'display-message':
    print('0')
''')
    tmux.chmod(0o755)
    for name, body in [('sleep', 'exit 0'), ('claude', 'echo "--restricted --strict-mcp-config"')]:
        p = bindir / name; p.write_text('#!/bin/sh\n' + body + '\n'); p.chmod(0o755)
    env = dict(os.environ, AGENTMUX_HOME=str(home), AGENTMUX_NO_COURIER='1', AGENTMUX_IDLE_MINUTES='0',
               CLAUDE_CONFIG_DIR=str(src), FAKE_STATE=str(state), PATH=str(bindir)+':'+os.environ['PATH'])
    for k in ('AGENTMUX_NO_BYPASS', 'AGENTMUX_AGENT', 'AGENTMUX_LOG_ARCHIVE_KEEP', 'AGENTMUX_LOG_ARCHIVE_MB',
              'AGENTMUX_CLAUDE_ARCHIVE_KEEP', 'AGENTMUX_CLAUDE_ARCHIVE_MB'):
        env.pop(k, None)
    def am(*args, extra=None, ok=True):
        r = subprocess.run(['bash', str(harness), *args], env=dict(env, **(extra or {})),
                           text=True, capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
        assert (r.returncode == 0) == ok, (args, r.returncode, r.stdout, r.stderr)
        return r
    def spawn(name, cli='shell', extra=None):
        return am('spawn', name, '--cli', cli, '--cwd', str(root), extra=extra)
    def archives(name, d=archive):
        return sorted(p.name for p in d.iterdir() if p.name.startswith(name + '.')) if d.exists() else []
    stamp = re.compile(r'^\d{8}T\d{6}Z(-\d+)?$')
    def credentialish(tree):
        return [p for p in tree.rglob('*') if re.search('credential|token', p.name, re.I)]

    # 1. Respawn archives the previous log instead of truncating it.
    spawn('w1')
    (logs / 'w1.log').write_text('run one delivered X\n')
    am('kill', 'w1')
    assert (logs / 'w1.log').read_text() == 'run one delivered X\n', 'kill must not touch the log'
    spawn('w1')
    names = archives('w1')
    assert len(names) == 1, names
    assert names[0].endswith('.log') and stamp.match(names[0][len('w1.'):-len('.log')]), names
    assert (archive / names[0]).read_text() == 'run one delivered X\n'
    assert (logs / 'w1.log').read_text() == '', 'the new run starts a fresh log'
    am('kill', 'w1')
    spawn('w1')
    assert len(archives('w1')) == 1, 'an empty log is not archived'
    check('respawn archives the previous non-empty log; kill leaves it in place')

    # 2. Retention: newest N per agent, then a total size cap oldest-first.
    for i in range(5):
        (logs / 'w1.log').write_text(f'generation {i}\n')
        am('kill', 'w1')
        spawn('w1', extra={'AGENTMUX_LOG_ARCHIVE_KEEP': '3'})
    kept = archives('w1')
    assert len(kept) == 3, kept
    assert sorted((archive / n).read_text() for n in kept) == ['generation 2\n', 'generation 3\n', 'generation 4\n'], kept
    (archive / 'README.operator').write_text('not ours')
    big = b'x' * (400 * 1024)
    for s in ('20200101T000000Z', '20200102T000000Z', '20200103T000000Z'):
        (archive / f'old.{s}.log').write_bytes(big)
    (logs / 'w1.log').write_text('generation 5\n')
    am('kill', 'w1')
    spawn('w1', extra={'AGENTMUX_LOG_ARCHIVE_KEEP': '3', 'AGENTMUX_LOG_ARCHIVE_MB': '1'})
    total = sum(p.stat().st_size for p in archive.iterdir() if p.name != 'README.operator')
    assert total <= 1024 * 1024, total
    assert not (archive / 'old.20200101T000000Z.log').exists(), 'oldest goes first'
    assert (archive / 'old.20200103T000000Z.log').exists(), 'only as much as the cap requires'
    assert (archive / 'README.operator').exists(), 'files of another shape are never pruned'
    assert any((archive / n).read_text() == 'generation 5\n' for n in archives('w1'))
    check('log retention keeps newest N per agent and trims oldest-first to the size cap')

    # 3. GC archives a dead agent's claude mirror, never its credentials.
    spawn('c1', cli='claude')
    m1 = cfg / 'c1'
    link = m1 / '.credentials.json'
    assert link.is_symlink() and os.readlink(link) == str(shared), 'spawn links the shared store'
    (m1 / 'projects').mkdir(exist_ok=True)
    (m1 / 'projects' / 'session.jsonl').write_text('transcript of what c1 did\n')
    (m1 / 'oauth_token.txt').write_text('secret')
    (m1 / 'projects' / 'nested.credentials.bak').write_text('secret')
    am('kill', 'c1')
    assert m1.exists(), 'kill does not delete the mirror'
    spawn('c2', cli='claude')
    assert not m1.exists(), 'dead mirror moved out of the live area'
    a1 = archives('c1', carch)
    assert len(a1) == 1 and stamp.match(a1[0][len('c1.'):]), a1
    kept_tree = carch / a1[0]
    assert (kept_tree / 'projects' / 'session.jsonl').read_text() == 'transcript of what c1 did\n'
    assert (kept_tree / 'settings.json').exists()
    assert credentialish(kept_tree) == [], credentialish(kept_tree)
    assert json.loads(shared_target.read_text())['claudeAiOauth']['refreshToken'] == 'shared-original', \
        'removing the archived link must not touch the shared store'
    assert (carch.stat().st_mode & 0o777) == 0o700
    for i in range(3):
        am('kill', 'c2')
        spawn('c2', cli='claude', extra={'AGENTMUX_CLAUDE_ARCHIVE_KEEP': '2'})
    assert len(archives('c2', carch)) == 2, archives('c2', carch)
    check('GC archives dead claude mirrors with transcripts, strips every credential, keeps newest N')

    # 4. A diverged credential (refresh replaced the link with a real file).
    live = cfg / 'c2' / '.credentials.json'
    live.unlink()
    live.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'rotated-by-c2', 'accessToken': 'b'}}))
    now = time.time()
    os.utime(live, (now, now))
    spawn('c3', cli='claude')
    stale = cfg / 'c3' / '.credentials.json'
    stale.unlink()
    stale.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'stale-c3', 'accessToken': 'c'}}))
    os.utime(stale, (old - 60, old - 60))
    spawn('c4', cli='claude')
    junk = cfg / 'c4' / '.credentials.json'
    junk.unlink()
    junk.write_text('{not json')
    am('kill', 'c4')
    assert shared.is_symlink() and os.readlink(shared) == str(shared_target), 'shared link preserved'
    assert json.loads(shared_target.read_text())['claudeAiOauth']['refreshToken'] == 'rotated-by-c2', \
        'the newest valid diverged refresh is adopted into the shared store'
    assert (shared_target.stat().st_mode & 0o777) == 0o600
    for agent in ('c2', 'c3', 'c4'):
        p = cfg / agent / '.credentials.json'
        assert p.is_symlink() and os.readlink(p) == str(shared), (agent, 'repaired to the shared link')
    check('diverged credential: newest valid copy adopted, stale and invalid copies relinked')

    # A dead agent can hold the only valid refresh: GC must adopt it BEFORE archiving.
    dead = cfg / 'c3' / '.credentials.json'
    dead.unlink()
    dead.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'only-in-dead-c3', 'accessToken': 'd'}}))
    later = time.time() + 5
    os.utime(dead, (later, later))
    (state / 'c3').unlink()          # died without `kill` - tmux server went away
    spawn('c5', cli='claude')
    assert json.loads(shared_target.read_text())['claudeAiOauth']['refreshToken'] == 'only-in-dead-c3'
    a3 = archives('c3', carch)
    assert len(a3) == 1 and credentialish(carch / a3[0]) == [], a3
    # An older valid copy never overwrites a newer shared store.
    older = cfg / 'c5' / '.credentials.json'
    older.unlink()
    older.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'older-than-shared', 'accessToken': 'e'}}))
    os.utime(older, (old - 600, old - 600))
    am('idle', extra={'AGENTMUX_IDLE_MINUTES': '60'})
    assert json.loads(shared_target.read_text())['claudeAiOauth']['refreshToken'] == 'only-in-dead-c3'
    assert older.is_symlink() and os.readlink(older) == str(shared), 'idle tick repairs the link'
    check('GC adopts a dead mirror\'s newer refresh before archiving; an older copy never wins')
    print(f'passed {counter}, failed 0')
PY
