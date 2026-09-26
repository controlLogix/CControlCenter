#!/usr/bin/env python3
"""Every child this harness spawns must be handed its own stdin.

WHY THIS SUITE EXISTS, AND WHY IT IS REPO-WIDE RATHER THAN PER-MODULE.

subprocess gives a child the parent's stdin whenever the argument is omitted.
`capture_output=True` redirects fds 1 and 2 only - it says nothing about fd 0. When the
parent is a bash reading its script from a pipe (`bash -s`, or the wsl.py helper that
every WSL call in this repo goes through), the child reads that pipe to EOF and the
REST OF THE SCRIPT IS GONE. The parent then exits 0, because nothing failed - the work
simply never ran.

That was found in taskmgmt/notify.py, where the Windows toast spawned powershell.exe
without it: a run-lifecycle script died immediately after `run.py verdict --pass`, and
the notification reported success while the caller's script had been eaten. It was
fixed there, and a repo sweep afterwards found EIGHT more call sites carrying the same
omission - in the courier's delivery path, the dispatch wrapper every verb goes
through, the chatter feed's send (running on an HTTP thread, so inheriting the SERVER's
stdin), and the reaper.

Fixing those eight is not the point. The point is that the ninth will be written by
someone who has never heard of this, so the rule needs a test rather than a comment.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The spawning calls that inherit stdin when it is not named.
SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}
# Either of these gives the child something that is not the parent's stdin.
SATISFIES = {"stdin", "input"}

passed = 0
failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label}")
        passed += 1
    else:
        print(f"  FAIL  {label}")
        print(f"          expected {expected!r}")
        print(f"          actual   {actual!r}")
        failed += 1


def spawn_calls(path):
    """Every subprocess spawn in one file, as (line, has_stdin)."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # subprocess.run(...) / sp.Popen(...) - attribute access on something
        if isinstance(func, ast.Attribute) and func.attr in SPAWNERS:
            base = func.value
            # Only count it when it is plausibly the subprocess module, so that
            # db.run(...) or logger.call(...) are not dragged in.
            if not (isinstance(base, ast.Name) and "subprocess" in base.id.lower()):
                continue
        else:
            continue
        names = {kw.arg for kw in node.keywords if kw.arg}
        guarded = bool(names & SATISFIES)
        # A `**{...}` expansion carries kw.arg = None, so a call that chooses between
        # stdin and input at runtime looks bare to the check above. github_auth._run
        # does exactly that:
        #
        #     **({"input": text} if text is not None else {"stdin": DEVNULL})
        #
        # and reading it as unguarded cost a real regression: a second stdin= was
        # added beside the expansion and every call raised "got multiple values for
        # keyword argument 'stdin'". What can be checked statically is that the call
        # mentions one of them at all; anything cleverer belongs in that module's own
        # test, and github_auth has one.
        if not guarded and any(kw.arg is None for kw in node.keywords):
            segment = ast.get_source_segment(source, node) or ""
            guarded = any(f'"{n}"' in segment or f"'{n}'" in segment
                          for n in SATISFIES)
        found.append((node.lineno, guarded))
    return found


def sources():
    """Harness modules. Test files are excluded: a test may legitimately spawn a
    child with an inherited stdin in order to prove this very failure."""
    for directory in ("taskmgmt", "dashboard"):
        for path in sorted((ROOT / directory).glob("*.py")):
            if path.name.startswith("test_"):
                continue
            yield path


print("--- every spawned child is handed its own stdin ---")

total = 0
offenders = []
for path in sources():
    for line, guarded in spawn_calls(path):
        total += 1
        if not guarded:
            offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")

# A sweep that finds nothing to check has gone blind - a renamed import or a changed
# call shape would silently empty this suite while it still reported success.
check("the sweep actually found spawning calls", True, total >= 20)
print(f"        ({total} subprocess spawn call(s) inspected)")

check("no spawn inherits the caller's stdin", [], offenders)

# And the rule holds in the file that taught it to us.
notify = ROOT / "taskmgmt" / "notify.py"
notify_calls = spawn_calls(notify)
check("notify.py still spawns at all", True, len(notify_calls) >= 3)
check("every notify.py spawn is guarded", [],
      [f"notify.py:{line}" for line, guarded in notify_calls if not guarded])

print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
