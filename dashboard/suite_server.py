#!/usr/bin/env python3
"""Find this checkout's running dashboard home without contacting its database."""
import argparse
import atexit
import os
from pathlib import Path
import struct
import subprocess
import sys

# Linux answers every question here from /proc. macOS has no /proc, and will not show
# another process's environment to a non-root caller even when it is the same user, so
# the one fact /proc gave us that nothing else can - which AGENTMUX_HOME a dashboard
# runs on - is declared by the dashboard itself in a per-user registry, one file per
# pid. A declaration is only believed for a pid whose argv and cwd prove it is this
# checkout's server.py, so a stale file left by a killed server, or a recycled pid,
# is ignored rather than trusted.
HAS_PROC = Path('/proc/self').is_dir()
REGISTRY = Path(f'/tmp/agentmux-dashboards-{os.getuid()}')


def declare_home(home):
    """Called by server.py once it has bound its port. A no-op where /proc exists."""
    if HAS_PROC:
        return
    try:
        REGISTRY.mkdir(mode=0o700, exist_ok=True)
        if REGISTRY.stat().st_uid != os.getuid() or REGISTRY.is_symlink():
            return                      # someone else's directory: declare nothing
        entry = REGISTRY / str(os.getpid())
        entry.write_text(str(Path(home).resolve()))
        atexit.register(lambda: entry.unlink(missing_ok=True))
    except OSError:
        pass


def _darwin_argv(pid):
    """argv of a same-user process via sysctl KERN_PROCARGS2 (exact, unlike ps)."""
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, pid)          # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0):
        raise ProcessLookupError(pid)
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0):
        raise ProcessLookupError(pid)
    raw = buf.raw[:size.value]
    argc = struct.unpack('i', raw[:4])[0]
    rest = raw[4:]
    rest = rest[rest.index(b'\0'):].lstrip(b'\0')    # skip the exec path and padding
    return rest.split(b'\0')[:argc]


def _darwin_cwd(pid):
    out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=10).stdout
    for line in out.splitlines():
        if line.startswith('n'):
            return Path(line[1:])
    raise ProcessLookupError(pid)


def _is_our_server(args, cwd, script):
    if len(args) < 2 or not Path(os.fsdecode(args[0])).name.lower().startswith('python'):
        return False
    candidate = Path(os.fsdecode(args[1]))
    return candidate.name == 'server.py' and (cwd / candidate).resolve() == script


def _darwin_listener_pids(port):
    out = subprocess.run(['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=10).stdout
    return {int(p) for p in out.split() if p.isdecimal()}


def _darwin_server_homes(only, script):
    found = []
    try:
        entries = [e for e in REGISTRY.iterdir() if e.name.isdecimal()]
    except OSError:
        entries = []
    for entry in entries:
        pid = int(entry.name)
        if only is not None and pid not in only:
            continue
        try:
            if _is_our_server(_darwin_argv(pid), _darwin_cwd(pid), script):
                found.append(str(Path(entry.read_text().strip()).resolve()))
        except (OSError, ValueError, ProcessLookupError, subprocess.SubprocessError):
            continue
    return found


def listener_pids(port):
    """Pids holding a LISTEN socket on 127.0.0.1/0.0.0.0:<port>, from /proc/net/tcp.

    Needed since the gate runs its own dashboard on a private port while the
    operator's stays up on 8787 (TM-223): with two servers alive, "the dashboard" is
    ambiguous, and the only honest answer is the one bound to the port asked about."""
    if not HAS_PROC:
        return _darwin_listener_pids(port)
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
    found = [] if HAS_PROC else _darwin_server_homes(only, script)
    for proc in Path('/proc').iterdir() if HAS_PROC else ():
        if not proc.name.isdecimal():
            continue
        if only is not None and int(proc.name) not in only:
            continue
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            cwd = proc.joinpath('cwd').resolve()
            if not _is_our_server(args, cwd, script):
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
