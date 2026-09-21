#!/usr/bin/env bash
# Syntax-check every script in the repo. From the repo root inside WSL:
#   bash <(tr -d '\r' < dashboard/syntax_check.sh)
#
# A file rather than an inline loop because `$var` inside `wsl.exe bash -c "..."` is expanded
# by the OUTER shell, so the loop variable arrives empty and the check silently passes.
set -u
fail=0

for script in agentmux.sh install.sh link-windows-state.sh dashboard/*.sh; do
  [ -f "$script" ] || continue
  if bash -n <(tr -d '\r' < "$script") 2>/dev/null; then
    printf '  ok    %s\n' "$script"
  else
    printf '  FAIL  %s\n' "$script"
    bash -n <(tr -d '\r' < "$script") 2>&1 | sed 's/^/        /'
    fail=$((fail + 1))
  fi
done

for script in dashboard/*.py taskmgmt/*.py; do
  [ -f "$script" ] || continue
  if python3 -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$script"; then
    printf '  ok    %s\n' "$script"
  else
    printf '  FAIL  %s\n' "$script"
    fail=$((fail + 1))
  fi
done

echo
[ "$fail" -eq 0 ] && echo 'every script parses' || echo "$fail file(s) failed to parse"
exit "$fail"
