#!/usr/bin/env bash
# pycomm3 has exactly one importer, and the sidecar has no raw-CIP route.
#
#   bash <(tr -d '\r' < dashboard/check_field_writes.sh)
#
# WHY A TRIPWIRE RATHER THAN A FENCE. pycomm3 can write anything to a Logix
# controller, including arbitrary CIP services through generic_message. The
# capability wrapper in field/rockwell.py is defence in depth and nothing more -
# Python has no private, and a caller inside the process can reach the driver.
#
# What actually holds is the PROCESS boundary: the sidecar exposes no route that
# takes a raw CIP service, class, instance or attribute, so an unaudited write
# has no way in from outside. That absence is invisible - it is a thing that is
# not there - which is exactly the kind of property that gets deleted by
# accident. This is what notices.
#
# Same pattern as check_key_exposure.sh: cheap, specific, and it fails loudly
# the first time somebody adds the convenient thing.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

# ── 1. one importer ──────────────────────────────────────────────────────────
# Source files only. The vendored copy imports itself, and the tests and this
# script name it on purpose.
importers=""
while IFS= read -r file; do
  case "$file" in
    field/vendor/*|dashboard/check_field_writes.sh|dashboard/test_rockwell.py) continue ;;
    field/rockwell.py) continue ;;
  esac
  case "$file" in *.py) ;; *) continue ;; esac
  if grep -qE '^[[:space:]]*(import[[:space:]]+pycomm3|from[[:space:]]+pycomm3[[:space:]]+import)' "$file" 2>/dev/null; then
    importers="$importers$file"$'\n'
  fi
done < <(git ls-files 2>/dev/null || find . -name '*.py' -not -path './.git/*')

if [ -z "$importers" ]; then
  ok 'field writes: field/rockwell.py is the only importer of pycomm3'
else
  bad 'field writes: pycomm3 is imported outside field/rockwell.py'
  printf '%s' "$importers" | sed 's/^/          /'
fi

# And that the one importer still exists, so the check cannot pass by the
# subject having been deleted.
if grep -qE '^[[:space:]]*import[[:space:]]+pycomm3' field/rockwell.py 2>/dev/null; then
  ok 'field writes: the audited wrapper is present and imports pycomm3'
else
  bad 'field writes: field/rockwell.py does not import pycomm3; this check is vacuous'
fi

# ── 2. no generic_message anywhere but the refusal ───────────────────────────
# generic_message is the CIP escape hatch: any service, any class, any instance.
#
# PARSED, NOT GREPPED. Every file that matters mentions the name in prose,
# because explaining why the escape hatch is closed is the whole point of those
# docstrings - and a check that cannot tell an implementation from a comment
# about the implementation is not asserting what it claims to. So this looks for
# an attribute being READ or CALLED. The one legitimate mention in code is
# rockwell.py's `driver.generic_message = _refuse(...)`, which is a STORE.
leaks=$(python3 -B - <<'PY'
import ast, subprocess, sys

try:
    files = subprocess.run(['git', 'ls-files'], capture_output=True, text=True,
                           check=True).stdout.split()
except Exception:
    from pathlib import Path
    files = [str(p) for p in Path('.').rglob('*.py')]

bad = []
for name in files:
    if not name.endswith('.py') or name.startswith('field/vendor/'):
        continue
    try:
        tree = ast.parse(open(name, encoding='utf-8').read())
    except (OSError, SyntaxError):
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'generic_message':
            if isinstance(node.ctx, ast.Store):
                continue            # the refusal itself
            bad.append(f'{name}:{node.lineno}: read or called')
        if isinstance(node, ast.Name) and node.id == 'generic_message' \
                and isinstance(node.ctx, ast.Load):
            bad.append(f'{name}:{node.lineno}: referenced')
print('\n'.join(bad))
PY
)
if [ -z "$leaks" ]; then
  ok 'field writes: generic_message is never read or called, only refused'
else
  bad 'field writes: generic_message is reachable in code'
  printf '%s\n' "$leaks" | sed 's/^/          /'
fi

# ── 3. the sidecar takes no raw CIP addressing ───────────────────────────────
# A route that accepted a service/class/instance/attribute would be a way to
# write anything, with no tag name in the journal to say what was written.
if [ -f field/app.py ]; then
  raw=$(python3 -B - <<'PY'
import ast, sys
# Strings in docstrings are the module EXPLAINING that it has no such route.
# A check that cannot tell an implementation from a comment about the
# implementation is not asserting what it claims to.
tree = ast.parse(open('field/app.py', encoding='utf-8').read())
docstrings = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        doc = ast.get_docstring(node, clean=False)
        if doc:
            docstrings.add(doc)
bad = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in docstrings:
            continue
        low = node.value.lower()
        for token in ('generic_message', 'class_code', 'service_code'):
            if token in low:
                bad.append(f'line {node.lineno}: {node.value[:60]!r}')
print('\n'.join(bad))
PY
)
  if [ -z "$raw" ]; then
    ok 'field writes: the sidecar names no raw CIP service, class or attribute'
  else
    bad 'field writes: the sidecar appears to accept raw CIP addressing'
    printf '%s\n' "$raw" | sed 's/^/          /'
  fi
else
  bad 'field writes: field/app.py is missing'
fi

# ── 4. every write still goes through the shared journal ─────────────────────
if grep -q 'journal.intent' field/rockwell.py 2>/dev/null &&
   grep -qE 'handle\.settle' field/rockwell.py 2>/dev/null; then
  ok 'field writes: the wrapper journals an intent and settles an outcome'
else
  bad 'field writes: the wrapper does not journal intent/outcome'
fi

finish
