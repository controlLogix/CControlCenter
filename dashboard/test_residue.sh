#!/usr/bin/env bash
# Probe the REAL gate and runner in disposable repositories. The restart, tmux,
# and suite subjects are stubs: even a broken historical runner cannot stop a live
# dashboard or write a real database. Only production scripts under test are copied.
set -u
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
python3 - "$PWD" "$work" > "$work/results" <<'PY'
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time

repo, work = map(Path, sys.argv[1:])

def check(label, condition, detail=''):
    print(('ok' if condition else 'bad') + '\tresidue: ' + label + ('' if condition else ' ' + detail), flush=True)

def put(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o700)

def copy(name, fixture):
    put(fixture / name, (repo / name).read_text())

try:
    for index, name in enumerate(('auth.json', 'cc.db', 'cc.db-wal', 'cc.db-shm', 'cc.db-journal', 'env',
                                  'atlassian.json', 'journal.jsonl', 'run/agent.cli',
                                  'claims/file.json', 'runs/run/events.jsonl', 'queue/agent.jsonl', 'inbox/agent.jsonl',
                                  'claude-config/settings.json', 'new-file.json', 'deleted.json')):
        fixture = work / f'gate-{index}'
        live = fixture / 'live'
        target = live / name
        put(fixture / 'agentmux.sh', '# fixture\n')
        copy('dashboard/check_test_residue.sh', fixture)
        if (repo / 'dashboard/residue_state.py').exists():
            copy('dashboard/residue_state.py', fixture)
        put(live / 'auth.json', '{}\n')
        if name != 'new-file.json':
            put(target, 'original\n')
        stub = fixture / 'dashboard/run_tests.sh'
        put(stub, 'exit 0\n')
        env = dict(os.environ, AGENTMUX_HOME=str(live), TMPDIR=str(fixture))
        command = ['bash', 'dashboard/check_test_residue.sh', '--root', str(live)]
        clean = subprocess.run(command, cwd=fixture, env=env, text=True, capture_output=True)
        mutation = 'p.unlink()' if name == 'deleted.json' else "p.parent.mkdir(parents=True, exist_ok=True); p.write_text('changed\\n')"
        put(fixture / 'mutate.py', f'from pathlib import Path\np = Path({str(target)!r})\n{mutation}\n')
        put(stub, 'python3 ' + shlex.quote(str(fixture / 'mutate.py')) + '\n')
        dirty = subprocess.run(command, cwd=fixture, env=env, text=True, capture_output=True)
        check('gate detects ' + name, clean.returncode == 0 and dirty.returncode != 0
              and 'RESIDUE:' in dirty.stdout and str(target) in dirty.stdout,
              f'(clean={clean.returncode}, dirty={dirty.returncode})')

    put(stub, 'exit 7\n')
    failed = subprocess.run(command, cwd=fixture, env=env, text=True, capture_output=True)
    check('a failed suite cannot pass a clean residue gate', failed.returncode != 0
          and 'SUITE FAILED: exit 7' in failed.stdout, f'(rc={failed.returncode})')

    # KILL is the case the marker exists for: SIGKILL to the process group, so the EXIT
    # trap that normally restores the dashboard never runs at all. That is not
    # hypothetical - the idle watchdog kills panes, and it took these panes three times
    # in one night.
    for mode in ('normal', 'suite-failure', 'INT', 'TERM', 'KILL', 'start-failure', 'restore-failure', 'different-caller-home', 'wrong-server-home'):
        fixture = work / ('runner-' + mode)
        fixture.mkdir()
        live = fixture / 'operator'
        live.mkdir()
        put(live / 'cc.db', 'operator database\n')
        copy('dashboard/run_tests.sh', fixture)
        # Model discovery/verification without inspecting or restarting any server.
        # Models discovery, verification AND the takeover marker. The marker has to be
        # real here: the whole point of the KILL case is that the note outlives a runner
        # that never got to run its trap, so a stub that only pretends to write it would
        # prove nothing.
        put(fixture / 'dashboard/suite_server.py',
            "import json, os, sys, time, pathlib\n"
            "a = sys.argv\n"
            "def opt(name):\n"
            "    return a[a.index(name) + 1] if name in a else None\n"
            "marker = pathlib.Path(os.environ['ORIGINAL_SERVER_HOME']) / '.dashboard-takeover.json'\n"
            "if '--mark' in a:\n"
            "    marker.parent.mkdir(parents=True, exist_ok=True)\n"
            "    marker.write_text(json.dumps({'version': 1, 'operator_home': opt('--operator'),\n"
            "        'test_home': opt('--test-home'), 'gate_pid': int(opt('--gate-pid')),\n"
            "        'repo': opt('--repo'), 'started_at': int(time.time())}, indent=2) + '\\n')\n"
            "elif '--clear' in a:\n"
            "    marker.unlink(missing_ok=True)\n"
            "elif '--expect' not in a: print(os.environ['ORIGINAL_SERVER_HOME'])\n"
            "elif os.environ['CASE_MODE'] == 'wrong-server-home' and a[-1] != os.environ['ORIGINAL_SERVER_HOME']: sys.exit(1)\n")
        put(fixture / 'agentmux.sh', '# fixture\n')
        put(fixture / 'dashboard/server.py', '# existence only; never started\n')
        # All external effects terminate at these fixture-owned stubs.
        put(fixture / 'bin/flock', '#!/bin/sh\nexit 0\n', True)
        put(fixture / 'bin/tmux', '#!/bin/sh\ncase "$*" in *list-sessions*) echo fixture-agent;; esac\n', True)
        put(fixture / 'dashboard/restart.sh', '''python3 - "$@" <<'RESTART'
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE'])
log = root / 'restarts'
rows = log.read_text().splitlines() if log.exists() else []
ready = root / 'ready'
writer_running = False
if ready.exists():
    state = pathlib.Path('/proc') / ready.read_text() / 'stat'
    try:
        writer_running = state.read_text().split(') ', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        pass
with log.open('a') as handle:
    handle.write(json.dumps({'home': os.environ.get('AGENTMUX_HOME'), 'args': sys.argv[1:], 'writer_running': writer_running}) + '\\n')
mode = os.environ['CASE_MODE']
if (mode == 'start-failure' and not rows) or (mode == 'restore-failure' and rows):
    sys.exit(1)
RESTART
''')
        subject = '''import os, pathlib, time
root = pathlib.Path(os.environ['FIXTURE'])
mode = os.environ['CASE_MODE']
if os.environ.get('FIRST_SUITE') == '1':
    (root / 'ready').write_text(str(os.getpid()))
    if mode in ('INT', 'TERM'):
        time.sleep(5)
    if mode == 'suite-failure':
        print('  FAIL  deliberate suite failure')
        print('passed 0, failed 1')
        raise SystemExit(1)
print('passed 1, failed 0')
'''
        put(fixture / 'subject.py', subject)
        for source in (repo / 'dashboard').glob('test_*.sh'):
            first = 'FIRST_SUITE=1 ' if source.name == 'test_testlib.sh' else ''
            put(fixture / 'dashboard' / source.name, first + 'python3 subject.py\n')
        for source in (repo / 'dashboard').glob('test_*.py'):
            put(fixture / 'dashboard' / source.name, subject)
        # Every non-test_* suite run_tests.sh invokes. A new one added there and
        # not here leaves the fixture without the file, and the runner fails on a
        # missing script rather than on the thing this case is testing.
        for name in ('smoke.sh', 'check_test_failability.sh', 'check_line_endings.sh',
                     'check_vendor.sh', 'check_field_writes.sh'):
            put(fixture / 'dashboard' / name, 'python3 subject.py\n')
        env = dict(os.environ, AGENTMUX_HOME=str(fixture / 'caller-home') if mode == 'different-caller-home' else str(live), ORIGINAL_SERVER_HOME=str(live), FIXTURE=str(fixture), CASE_MODE=mode,
                   TMPDIR=str(fixture), PATH=str(fixture / 'bin') + os.pathsep + os.environ['PATH'])
        proc = subprocess.Popen(['bash', 'dashboard/run_tests.sh'], cwd=fixture, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        if mode in ('INT', 'TERM', 'KILL'):
            deadline = time.monotonic() + 8
            while not (fixture / 'ready').exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if (fixture / 'ready').exists():
                if mode == 'KILL':
                    # The whole process group, so nothing gets a chance to clean up.
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    os.kill(proc.pid, getattr(signal, 'SIG' + mode))
        try:
            output, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate()
        rows = [json.loads(line) for line in (fixture / 'restarts').read_text().splitlines()]
        rc = {'normal': 0, 'different-caller-home': 0, 'INT': 130, 'TERM': 143}.get(mode, 1)
        isolated = bool(rows) and rows[0]['home'] != str(live)
        marker = live / '.dashboard-takeover.json'
        if mode == 'KILL':
            # No restore is possible here and none is expected. What must survive is the
            # ADDRESS: without it the operator's home is unrecoverable, because
            # OPERATOR_ROOT was only ever a variable in the shell that just died.
            record = json.loads(marker.read_text()) if marker.exists() else {}
            check('a killed runner leaves the dashboard address behind',
                  proc.returncode == -signal.SIGKILL and isolated and marker.exists()
                  and record.get('operator_home') == str(live)
                  and record.get('test_home') == rows[0]['home'],
                  f'(rc={proc.returncode}, marker={marker.exists()}, '
                  f'home={record.get("operator_home")})')
            continue
        # The note is cleared only once the restore is PROVED, so restore-failure keeps
        # it on purpose - that is the case where the next agentmux invocation has to
        # finish the job, and discarding the address there would lose it for good.
        # Everywhere else it must be gone, which is what proves the clear path runs at
        # all rather than the marker simply never landing.
        if mode == 'restore-failure':
            check('a failed restore keeps the address for the next invocation',
                  marker.exists(), f'(marker={marker.exists()})')
        else:
            check('no takeover marker is left behind on ' + mode, not marker.exists(),
                  f'(marker={marker.exists()})')
        restored = len(rows) == 2 and rows[-1]['home'] == str(live) and not rows[-1]['writer_running']
        safe = all(not row['args'] for row in rows) and (live / 'cc.db').read_bytes() == b'operator database\n'
        cleanup = isolated and (Path(rows[0]['home']).exists() if mode == 'restore-failure' else not Path(rows[0]['home']).exists())
        check('runner isolates and restores on ' + mode,
              proc.returncode == rc and isolated and restored and safe and cleanup,
              f'(rc={proc.returncode}, restarts={len(rows)}, isolated={isolated}, cleanup={cleanup})')
    # Exercise the actual restart launch in a safe process fixture. Only the log
    # destination and external discovery/readiness commands are redirected; no port
    # is bound and pgrep can never return an operator PID.
    fixture = work / 'detached-restart'
    fixture.mkdir()
    copy('dashboard/restart.sh', fixture)
    launcher = fixture / 'dashboard/restart.sh'
    launcher.write_text(launcher.read_text().replace('/tmp/agentmux-server.log', str(fixture / 'server.log')))
    put(fixture / 'dashboard/server.py', '# never imported\n')
    put(fixture / 'bin/pgrep', '#!/bin/sh\nexit 1\n', True)
    put(fixture / 'bin/sleep', '#!/bin/sh\nexit 0\n', True)
    put(fixture / 'bin/python3', '#!' + sys.executable + "\nimport os, pathlib, time\npathlib.Path(os.environ['SERVER_PID_FILE']).write_text(str(os.getpid()))\ntime.sleep(30)\n", True)
    put(fixture / 'bin/curl', '#!' + sys.executable + "\nimport os, pathlib, time\np=pathlib.Path(os.environ['SERVER_PID_FILE'])\nfor _ in range(100):\n if p.exists(): break\n time.sleep(.01)\nraise SystemExit(0 if p.exists() else 1)\n", True)
    marker = fixture / 'server-pid'
    env = dict(os.environ, SERVER_PID_FILE=str(marker), AGENTMUX_HOME=str(fixture / 'home'),
               PATH=str(fixture / 'bin') + os.pathsep + os.environ['PATH'])
    proc = subprocess.Popen(['bash', 'dashboard/restart.sh'], cwd=fixture, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    proc.communicate(timeout=8)
    pid = int(marker.read_text())
    try:
        detached = os.getsid(pid) != proc.pid
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(.05)
        state = Path('/proc') / str(pid) / 'stat'
        alive = state.exists() and state.read_text().split(') ', 1)[1].split()[0] != 'Z'
        check('restored server outlives the launcher process group', proc.returncode == 0 and detached and alive)
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
except Exception as error:
    check('fixture completed', False, repr(error))
    raise
PY
fixture_rc=$?
while IFS=$'\t' read -r result label; do
  case "$result" in ok) ok "$label" ;; *) bad "$label" ;; esac
done < "$work/results"
[ "$fixture_rc" = 0 ] || bad "residue fixture crashed (exit=$fixture_rc)"
finish
