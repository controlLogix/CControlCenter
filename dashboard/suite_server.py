#!/usr/bin/env python3
"""Find this checkout's running dashboard home without contacting its database."""
import argparse
import os
from pathlib import Path


def listener_pids(port):
    """Pids holding a LISTEN socket on 127.0.0.1/0.0.0.0:<port>, from /proc/net/tcp.

    Needed since the gate runs its own dashboard on a private port while the
    operator's stays up on 8787 (TM-223): with two servers alive, "the dashboard" is
    ambiguous, and the only honest answer is the one bound to the port asked about."""
    inodes = set()
    for table in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if len(f) > 9 and f[3] == '0A' and int(f[1].rsplit(':', 1)[1], 16) == port:
                inodes.add(f[9])
    pids = set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            for fd in proc.joinpath('fd').iterdir():
                link = os.readlink(fd)
                if link.startswith('socket:[') and link[8:-1] in inodes:
                    pids.add(int(proc.name))
                    break
        except (FileNotFoundError, ProcessLookupError, PermissionError, NotADirectoryError):
            continue
    return pids


def server_home(port=None):
    """The home of this checkout's dashboard. With `port`, only the process actually
    listening on it counts - the others are someone else's server."""
    script = Path(__file__).resolve().with_name('server.py')
    only = listener_pids(port) if port else None
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        if only is not None and int(proc.name) not in only:
            continue
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            if len(args) < 2 or not Path(os.fsdecode(args[0])).name.startswith('python'):
                continue
            candidate = Path(os.fsdecode(args[1]))
            if candidate.name != 'server.py':
                continue
            cwd = proc.joinpath('cwd').resolve()
            if (cwd / candidate).resolve() != script:
                continue
            env = dict(item.split(b'=', 1) for item in proc.joinpath('environ').read_bytes().split(b'\0') if b'=' in item)
            home = os.fsdecode(env.get(b'AGENTMUX_HOME') or env.get(b'HOME', os.fsencode(str(Path.home()))))
            if not env.get(b'AGENTMUX_HOME'):
                home = str(Path(home) / '.agentmux')
            found.append(str((cwd / home).resolve()))
        except (FileNotFoundError, ProcessLookupError):
            continue
    # Resource probes can briefly fork before exec, retaining the server cmdline.
    # Duplicate processes with the same home are unambiguous; different homes are not.
    homes = set(found)
    if len(homes) > 1:
        raise RuntimeError(f'multiple dashboard homes; cannot safely restore: {sorted(homes)}')
    return next(iter(homes)) if homes else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fallback')
    parser.add_argument('--expect')
    parser.add_argument('--port', type=int, default=None,
                        help='only the dashboard listening on this port')
    parser.add_argument('--pid', action='store_true', help='print the listener pid(s) on --port and exit')
    args = parser.parse_args()
    if args.pid:
        print(' '.join(str(p) for p in sorted(listener_pids(args.port or 8787))))
        return
    try:
        home = server_home(args.port)
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
