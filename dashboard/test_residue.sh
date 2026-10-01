#!/usr/bin/env bash
# Probe the REAL gate and runner in disposable repositories. The restart, tmux,
# and suite subjects are stubs: even a broken historical runner cannot stop a live
# dashboard or write a real database. Only production scripts under test are copied.
set -u
. dashboard/testlib.sh
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

    # THE GATE NEVER TOUCHES THE OPERATOR'S DASHBOARD (TM-223). It used to restart the
    # 8787 server onto a throwaway home and restore it afterwards, and these cases
    # pinned that dance. They now pin its replacement, under the same failures: the
    # operator's server is never restarted; the gate starts its OWN server (with
    # --port, on the test home) and kills it on every exit path; the test home is
    # removed; the operator's database is untouched; and a run whose 8787 listener
    # changed underneath it fails loudly instead of passing.
    for mode in ('normal', 'suite-failure', 'INT', 'TERM', 'start-failure', 'different-caller-home', 'operator-changed'):
        fixture = work / ('runner-' + mode)
        fixture.mkdir()
        live = fixture / 'operator'
        live.mkdir()
        put(live / 'cc.db', 'operator database\n')
        copy('dashboard/run_tests.sh', fixture)
        # Discovery stubs: the 8787 listener's pid and home, as run_tests.sh asks for
        # them at start and again at exit. 'operator-changed' answers differently the
        # second time - a live server that was swapped during the run.
        put(fixture / 'dashboard/suite_server.py', '''import os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE'])
calls = root / 'pid-calls'
if '--pid' in sys.argv:
    n = len(calls.read_text().splitlines()) if calls.exists() else 0
    with calls.open('a') as f:
        f.write('x\\n')
    print('4242' if (n == 0 or os.environ['CASE_MODE'] != 'operator-changed') else '9999')
elif '--expect' in sys.argv:
    sys.exit(0)
else:
    print(os.environ['ORIGINAL_SERVER_HOME'])
''')
        put(fixture / 'agentmux.sh', '# fixture\n')
        # The gate's private server. Records how it was started, then lives until killed
        # - unless this is the case where it cannot start at all.
        put(fixture / 'dashboard/server.py', '''import json, os, pathlib, sys, time
root = pathlib.Path(os.environ['FIXTURE'])
with (root / 'servers').open('a') as f:
    f.write(json.dumps({'home': os.environ.get('AGENTMUX_HOME'), 'args': sys.argv[1:], 'pid': os.getpid()}) + '\\n')
if os.environ['CASE_MODE'] == 'start-failure':
    print('OSError: [Errno 98] Address already in use', file=sys.stderr)
    sys.exit(1)
time.sleep(60)
''')
        # Any call to restart.sh is a failure of the contract: it is how the old gate
        # took the operator's server away.
        put(fixture / 'dashboard/restart.sh', 'echo called >> "$FIXTURE/restarts"\n')
        put(fixture / 'bin/flock', '#!/bin/sh\nexit 0\n', True)
        put(fixture / 'bin/tmux', '#!/bin/sh\ncase "$*" in *list-sessions*) echo fixture-agent;; esac\n', True)
        put(fixture / 'bin/curl', '#!/bin/sh\n[ "$CASE_MODE" = start-failure ] && exit 7\nexit 0\n', True)
        subject = '''import os, pathlib, time
root = pathlib.Path(os.environ['FIXTURE'])
mode = os.environ['CASE_MODE']
if os.environ.get('FIRST_SUITE') == '1':
    (root / 'ready').write_text(str(os.getpid()))
    (root / 'suite-env').write_text(os.environ.get('AGENTMUX_BASE_URL', '') + '\\n' + os.environ.get('AGENTMUX_DASHBOARD', ''))
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
        for name in ('smoke.sh', 'check_test_failability.sh'):
            put(fixture / 'dashboard' / name, 'python3 subject.py\n')
        env = dict(os.environ, AGENTMUX_HOME=str(fixture / 'caller-home') if mode == 'different-caller-home' else str(live),
                   ORIGINAL_SERVER_HOME=str(live), FIXTURE=str(fixture), CASE_MODE=mode,
                   TMPDIR=str(fixture), PATH=str(fixture / 'bin') + os.pathsep + os.environ['PATH'])
        env.pop('AGENTMUX_BASE_URL', None)
        env.pop('AGENTMUX_DASHBOARD', None)
        proc = subprocess.Popen(['bash', 'dashboard/run_tests.sh'], cwd=fixture, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        if mode in ('INT', 'TERM'):
            deadline = time.monotonic() + 8
            while not (fixture / 'ready').exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if (fixture / 'ready').exists():
                os.kill(proc.pid, getattr(signal, 'SIG' + mode))
        try:
            output, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate()
        servers = [json.loads(l) for l in (fixture / 'servers').read_text().splitlines()] if (fixture / 'servers').exists() else []
        rc = {'normal': 0, 'different-caller-home': 0, 'INT': 130, 'TERM': 143}.get(mode, 1)
        never_restarted = not (fixture / 'restarts').exists()
        one_private = len(servers) == 1 and '--port' in servers[0]['args'] and servers[0]['home'] not in (str(live), str(fixture / 'caller-home'))
        def gone(pid):
            state = Path('/proc') / str(pid) / 'stat'
            try:
                return state.read_text().split(') ', 1)[1].split()[0] == 'Z'
            except FileNotFoundError:
                return True
        time.sleep(0.2)
        killed = one_private and gone(servers[0]['pid'])
        cleaned = one_private and not Path(servers[0]['home']).exists()
        safe = (live / 'cc.db').read_bytes() == b'operator database\n' and not (fixture / 'caller-home').exists()
        pointed = True
        if mode == 'normal':
            urls = (fixture / 'suite-env').read_text().splitlines() if (fixture / 'suite-env').exists() else []
            pointed = len(urls) == 2 and urls[0] == urls[1] and urls[0].startswith('http://127.0.0.1:') and not urls[0].endswith(':8787')
        reported = ('changed during the run' in output) if mode == 'operator-changed' else ('untouched' in output or mode == 'start-failure')
        check('gate leaves the operator dashboard alone on ' + mode,
              proc.returncode == rc and never_restarted and one_private and killed and cleaned and safe and pointed and reported,
              f'(rc={proc.returncode}, restarted={not never_restarted}, servers={len(servers)}, killed={killed}, '
              f'cleaned={cleaned}, safe={safe}, pointed={pointed}, reported={reported})')
    # Exercise the actual restart launch in a safe process fixture. Only the log
    # destination and external discovery/readiness commands are redirected; no port
    # is bound and pgrep can never return an operator PID.
    fixture = work / 'detached-restart'
    fixture.mkdir()
    copy('dashboard/restart.sh', fixture)
    launcher = fixture / 'dashboard/restart.sh'
    launcher.write_text(launcher.read_text().replace('/tmp/ccc-server.log', str(fixture / 'server.log')))
    put(fixture / 'dashboard/server.py', '# never imported\n')
    put(fixture / 'bin/pgrep', '#!/bin/sh\nexit 1\n', True)
    put(fixture / 'bin/sleep', '#!/bin/sh\nexit 0\n', True)
    put(fixture / 'bin/python3', '#!' + sys.executable + "\nimport os, pathlib, sys, time\nif any('suite_server.py' in a for a in sys.argv):\n raise SystemExit(0)\npathlib.Path(os.environ['SERVER_PID_FILE']).write_text(str(os.getpid()))\ntime.sleep(30)\n", True)
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
    # A server that cannot bind, with something already answering on 8787: the bare
    # reachability check calls that success. Nothing real is touched - pgrep never
    # returns, curl is a stub, and the "server" only ever prints a bind error.
    fixture = work / 'foreign-port'
    fixture.mkdir()
    copy('dashboard/restart.sh', fixture)
    launcher = fixture / 'dashboard/restart.sh'
    launcher.write_text(launcher.read_text().replace('/tmp/ccc-server.log', str(fixture / 'server.log')))
    put(fixture / 'dashboard/server.py', '# never starts\n')
    put(fixture / 'bin/pgrep', '#!/bin/sh\nexit 1\n', True)
    put(fixture / 'bin/sleep', '#!/bin/sh\nexit 0\n', True)
    put(fixture / 'bin/curl', '#!/bin/sh\nexit 0\n', True)
    put(fixture / 'bin/python3',
        '#!/bin/sh\ncase "$*" in *suite_server.py*) exit 1;; esac\n'
        'echo "OSError: [Errno 98] Address already in use" >&2\nexit 1\n', True)
    env = dict(os.environ, AGENTMUX_HOME=str(fixture / 'home'),
               PATH=str(fixture / 'bin') + os.pathsep + os.environ['PATH'])
    proc = subprocess.run(['bash', 'dashboard/restart.sh'], cwd=fixture, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    check('a restart whose server never bound is not reported as up',
          proc.returncode != 0 and 'up: http' not in proc.stdout,
          f'(rc={proc.returncode}, out={proc.stdout.strip()!r})')
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
