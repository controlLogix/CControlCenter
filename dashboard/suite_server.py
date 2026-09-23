#!/usr/bin/env python3
"""Find this checkout's running dashboard home without contacting its database."""
import argparse
import os
from pathlib import Path


def server_home():
    script = Path(__file__).resolve().with_name('server.py')
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
    args = parser.parse_args()
    try:
        home = server_home()
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
