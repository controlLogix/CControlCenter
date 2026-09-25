"""Filesystem calls that cross the 9p mount, which fail transiently under load.

WHAT THIS IS FOR. `/mnt/c` is a 9p filesystem, and on this machine a stat or a
read of a path under it raises `OSError: [Errno 5] Input/output error` while the
gate is running. Not often, and not reproducibly - which is the problem.

The trap is that Python's convenience wrappers read as total and are not.
`Path.exists()` and `Path.is_file()` swallow ENOENT, ENOTDIR, EBADF and ELOOP
and **re-raise everything else**, so they look like a question that always has
an answer and in fact raise EIO. That is how TM-013 killed whole network scans
out of a function whose own docstring said "Never fatal", and how TM-027 turned
one gate run into "4 suite(s) failed" on a tree where nothing was wrong.

THE DISTINCTION THIS MODULE KEEPS. "The thing is not there" and "we could not
find out whether the thing is there" are different answers, and collapsing them
in either direction is a bug:

  - treat EIO as "absent" and a suite silently tests nothing;
  - treat EIO as an error and the gate goes red on a tree with no defect, which
    teaches people to re-run it until it goes green.

So `reachable()` answers only the first question, and `unreachable_reason()`
gives a suite what it needs to SKIP with a stated cause. A skip that names the
path is information; an EIO traceback out of setUpClass is noise.
"""

import errno
import os
from pathlib import Path

# The errnos Path.exists()/is_file() already treat as "no, it is not there".
# Anything outside this set is a question we could not answer.
ABSENT = {errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP}
if hasattr(errno, 'EINVAL'):
    ABSENT.add(errno.EINVAL)   # what Windows raises for a malformed name


def crosses_9p(path):
    """Is this path on the Windows mount, where EIO is a thing that happens?

    Only used to word diagnostics. The guards below are unconditional: a
    transient IO error is worth distinguishing from absence wherever it happens,
    and a guard that only applied to paths matching a prefix would miss the
    symlink from ~/.claude into /mnt/c that TM-027 actually tripped over.
    """
    try:
        text = os.fspath(Path(path).resolve())
    except OSError:
        text = str(path)
    return text.replace('\\', '/').lower().startswith('/mnt/')


def unreachable_reason(path, kind='dir'):
    """None if `path` is a usable <kind>, else a sentence saying why not.

    Never raises. The caller decides what an unreachable subject means for it -
    usually SkipTest, because a test whose subject could not be read has not
    passed and has not failed.
    """
    probe = Path(path)
    try:
        ok = probe.is_dir() if kind == 'dir' else probe.is_file()
    except OSError as exc:
        if exc.errno in ABSENT:
            return f'{path} is absent'
        where = ' (9p mount)' if crosses_9p(path) else ''
        return f'{path} could not be read{where}: {exc.strerror or exc}'
    return None if ok else f'{path} is absent'


def reachable(path, kind='dir'):
    """True only when `path` is a usable <kind>. Never raises."""
    return unreachable_reason(path, kind) is None


def skip_if_unreadable(case, path, kind='dir'):
    """Skip `case` with a stated reason when `path` cannot be read.

    `case` is a TestCase or its class - anything with skipTest, or None to raise
    SkipTest directly, which is what setUpClass needs.
    """
    reason = unreachable_reason(path, kind)
    if reason is None:
        return
    import unittest
    raise unittest.SkipTest(reason)


def guard(operation, path, *args, **kwargs):
    """Run `operation`, converting an IO failure into a SkipTest that says why.

    For the calls that walk a tree rather than ask about one file - copytree is
    the one that bit us, and it raises shutil.Error carrying a list of 22
    separate EIOs, which is unreadable in a traceback and means exactly one
    thing: the source was not readable.
    """
    import shutil
    import unittest
    try:
        return operation(*args, **kwargs)
    except unittest.SkipTest:
        raise
    except (OSError, shutil.Error) as exc:
        where = ' (9p mount)' if crosses_9p(path) else ''
        detail = str(exc)
        if len(detail) > 200:
            detail = detail[:200] + f'... [{detail.count("Errno")} errors]'
        raise unittest.SkipTest(f'{path} could not be read{where}: {detail}') from exc
