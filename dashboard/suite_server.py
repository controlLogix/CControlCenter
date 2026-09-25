#!/usr/bin/env python3
"""Find the running dashboard - any checkout's - without contacting its database.

Also owns the TAKEOVER MARKER, because this module already answers "which home is the
server on" and is already called at both moments that matter.

WHY THE MARKER EXISTS. run_tests.sh repoints the operator's dashboard at a disposable
home for the length of a gate run and restores it from an EXIT trap. The restore is
careful - it verifies itself with --expect rather than assuming - but a trap cannot
survive its process group being killed, and `server_home()` below reads /proc, so the
operator's real home exists ONLY as a shell variable in that one process. Kill the pane
holding a gate run and the address dies with it: the dashboard keeps serving a temp
directory that is then deleted, and the board renders every column empty with no error
anywhere.

So the address is written down before the takeover and removed once the restore is
proved. A later `agentmux` invocation finds the note and finishes the job.
"""
import argparse
import json
import os
import stat
import tempfile
import time
from pathlib import Path

MARKER_NAME = '.dashboard-takeover.json'


def is_dashboard(script):
    """Is this an agentmux dashboard, from ANY checkout?

    Deliberately not scoped to this one, and that is the whole of TM-020.
    restart.sh:18-20 kills every process matching 'dashboard/serv' regardless of
    which checkout started it, so a discovery that recognised only this
    checkout's server identified nothing while displacing something - and the
    restore then had nothing to put back. Discovery has to cover what the kill
    covers, or the restore is a guess.

    Checked by shape rather than by path: a server.py inside a dashboard/
    directory that also holds restart.sh. Never raises - these paths can be on
    the 9p mount, where a stat under load raises EIO out of a call that reads as
    total, and a process we cannot classify is simply not counted.
    """
    try:
        return (script.name == 'server.py'
                and script.parent.name == 'dashboard'
                and script.parent.joinpath('restart.sh').is_file())
    except OSError:
        return False


def server_location():
    """(home, cwd) of this checkout's running dashboard, or (None, None).

    The cwd matters as much as the home and used to be discarded here. A restore
    that repoints the home but restarts the server from somewhere else leaves the
    operator looking at a different checkout - the page works, so nothing reports
    an error, and the only symptom is that edits do not appear. See TM-020.
    """
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            if len(args) < 2 or not Path(os.fsdecode(args[0])).name.startswith('python'):
                continue
            candidate = Path(os.fsdecode(args[1]))
            if candidate.name != 'server.py':
                continue
            cwd = proc.joinpath('cwd').resolve()
            if not is_dashboard((cwd / candidate).resolve()):
                continue
            env = dict(item.split(b'=', 1) for item in proc.joinpath('environ').read_bytes().split(b'\0') if b'=' in item)
            home = os.fsdecode(env.get(b'AGENTMUX_HOME') or env.get(b'HOME', os.fsencode(str(Path.home()))))
            if not env.get(b'AGENTMUX_HOME'):
                home = str(Path(home) / '.agentmux')
            found.append((str((cwd / home).resolve()), str(cwd)))
        except (FileNotFoundError, ProcessLookupError):
            continue
    # Resource probes can briefly fork before exec, retaining the server cmdline.
    # Duplicate processes with the same home are unambiguous; different homes are not.
    homes = {home for home, _ in found}
    if len(homes) > 1:
        raise RuntimeError(f'multiple dashboard homes; cannot safely restore: {sorted(homes)}')
    if not homes:
        return None, None
    home = next(iter(homes))
    # Two servers on one home but different checkouts is the same ambiguity one
    # step along: restoring to either would be a guess.
    cwds = {cwd for _, cwd in found}
    if len(cwds) > 1:
        raise RuntimeError(f'one dashboard home across several checkouts; '
                           f'cannot safely restore: {sorted(cwds)}')
    return home, next(iter(cwds))


def server_home():
    """Back-compatible: the home alone."""
    return server_location()[0]


# ── the takeover marker ──────────────────────────────────────────────────────

def marker_path(operator_home):
    return Path(operator_home).resolve() / MARKER_NAME


def write_marker(operator_home, test_home, gate_pid, repo):
    """Record where the dashboard belongs, before anything repoints it.

    Same shape as the orchestrator warrant in taskmgmt/coordination.py: a versioned
    JSON dict, staged with mkstemp in the destination directory, chmod 0600, then
    os.replace. The replace is what makes a half-written marker impossible - a reader
    either sees the previous state or the complete new one, never a torn file.
    """
    path = marker_path(operator_home)
    record = {'version': 1,
              'operator_home': str(Path(operator_home).resolve()),
              'test_home': str(Path(test_home).resolve()),
              'gate_pid': int(gate_pid),
              # The repair has to run dashboard/restart.sh, and that script refuses
              # unless dashboard/server.py exists relative to the working directory.
              # Without this the note says where to put the dashboard back but not
              # which checkout can do it.
              #
              # THE OPERATOR'S CHECKOUT, not the gate's. They are usually
              # different - the gate runs from an ext4 clone because 9p drops
              # EIO under load - and restoring into the gate's clone leaves the
              # operator editing files nothing is serving. TM-020.
              'repo': str(Path(repo).resolve()),
              'started_at': int(time.time())}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{MARKER_NAME}.')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(record, indent=2) + '\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def read_marker(operator_home):
    """The marker as a dict, or None. Never raises.

    Returns None on EVERY anomaly, the same discipline orchestrator_warrant() uses: a
    reader that throws turns a corrupt note into a broken CLI, and this one runs on
    every single agentmux invocation.
    """
    path = marker_path(operator_home)
    try:
        info = path.lstat()
        # Not a symlink and not someone else's file. A marker names a directory we are
        # about to restart a server against, so a planted one is worth refusing.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return None
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get('version') != 1:
        return None
    for key in ('operator_home', 'test_home', 'repo'):
        if not isinstance(record.get(key), str) or not record[key]:
            return None
    try:
        record['gate_pid'] = int(record.get('gate_pid'))
    except (TypeError, ValueError):
        return None
    return record


def gate_alive(pid):
    """Is the gate that wrote the marker still running?

    The same liveness test courier.py and dispatch.py already use. PermissionError means
    the pid exists and belongs to someone else, which still counts as alive - refusing to
    repair is the safe answer there.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def clear_marker(operator_home):
    try:
        marker_path(operator_home).unlink()
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fallback')
    parser.add_argument('--server-cwd', action='store_true',
                        help="print the running dashboard's working directory, "
                             'or nothing when none is running')
    parser.add_argument('--expect')
    parser.add_argument('--mark', action='store_true',
                        help='record the takeover before repointing the dashboard')
    parser.add_argument('--clear', action='store_true',
                        help='remove the marker once the restore is proved')
    parser.add_argument('--stale', action='store_true',
                        help='print "<operator_home>\\t<repo>" if a marker exists whose '
                             'gate is gone; exit 1 otherwise')
    parser.add_argument('--operator', help='the operator home the marker lives in')
    parser.add_argument('--test-home')
    parser.add_argument('--gate-pid', type=int)
    parser.add_argument('--repo')
    args = parser.parse_args()
    try:
        if args.mark:
            for name in ('operator', 'test_home', 'gate_pid', 'repo'):
                if getattr(args, name) in (None, ''):
                    raise RuntimeError(f'--mark needs --{name.replace("_", "-")}')
            write_marker(args.operator, args.test_home, args.gate_pid, args.repo)
            return
        if args.clear:
            if not args.operator:
                raise RuntimeError('--clear needs --operator')
            clear_marker(args.operator)
            return
        if args.stale:
            if not args.operator:
                raise RuntimeError('--stale needs --operator')
            record = read_marker(args.operator)
            # No marker, or a gate still running, are both "nothing to do" - and they
            # must be indistinguishable to the caller, which simply does nothing.
            if record is None or gate_alive(record['gate_pid']):
                parser.exit(1)
            print(record['operator_home'] + '\t' + record['repo'] + '\t' + record['test_home'])
            return
        home, cwd = server_location()
        if args.server_cwd:
            # Silence plus exit 0 when nothing is running: the caller falls back
            # to its own checkout, which is the right answer on a machine with
            # no dashboard up. An error here would make the gate refuse to start.
            if cwd:
                print(cwd)
            return
        if args.expect:
            if home != str(Path(args.expect).resolve()):
                raise RuntimeError('running dashboard is not using the requested home')
        elif home or args.fallback:
            print(home or str(Path(args.fallback).resolve()))
        else:
            raise RuntimeError('no dashboard process found')
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'dashboard isolation: {error}\n')


if __name__ == '__main__':
    main()
