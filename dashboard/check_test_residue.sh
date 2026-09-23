#!/usr/bin/env bash
# Byte-check persistent live state around the full isolated suite. See residue_state.py
# for the coverage boundary. A file avoids nested wsl.exe bash -c quoting surprises.
# --root PATH and -- COMMAND are for checking disposable fixtures of this gate.
set -uo pipefail
[ -f agentmux.sh ] || { echo 'run from the agentmux repo root' >&2; exit 2; }
roots=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) [ "$#" -ge 2 ] || exit 2; roots+=(--root "$2"); shift 2 ;;
    --) shift; break ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ "${#roots[@]}" -eq 0 ]; then
  server_root="$(python3 dashboard/suite_server.py --fallback "${AGENTMUX_HOME:-$HOME/.agentmux}")" || exit 2
  roots=(--root "$server_root" --root "${AGENTMUX_HOME:-$HOME/.agentmux}" --root "$HOME/.agentmux"
         --codex "${CODEX_HOME:-$HOME/.codex}" --codex "$HOME/.codex")
fi
work=$(mktemp -d) || exit 2
trap 'rm -rf "$work"' EXIT
printf 'Coverage: top-level state files (including auth, env, Atlassian, cc.db and SQLite sidecars), run/, claims/, runs/, queue/, inbox/, claude-config/, and configured Codex profiles.\n'
printf 'Excluded: continuously changing pane logs, courier runtime files, and Claude histories/backups/cache stamps. Concurrent operator edits count as residue.\n'
python3 dashboard/residue_state.py snapshot "$work/before.json" "${roots[@]}" || exit 2
if [ "$#" -gt 0 ]; then
  "$@" > "$work/suite.log" 2>&1; suite_rc=$?
else
  bash <(tr -d '\r' < dashboard/run_tests.sh) > "$work/suite.log" 2>&1; suite_rc=$?
fi
tail -8 "$work/suite.log" | sed 's/^/      /'
python3 dashboard/residue_state.py snapshot "$work/after.json" "${roots[@]}" || exit 2
python3 dashboard/residue_state.py compare "$work/before.json" "$work/after.json"; residue_rc=$?
if [ "$suite_rc" != 0 ]; then
  echo "SUITE FAILED: exit $suite_rc (a clean snapshot does not make a failed suite pass)"
fi
if [ "$suite_rc" = 0 ] && [ "$residue_rc" = 0 ]; then
  echo 'IDEMPOTENT: all covered live state is unchanged after a successful suite'
else
  exit 1
fi
