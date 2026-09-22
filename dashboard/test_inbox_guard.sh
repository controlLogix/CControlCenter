#!/usr/bin/env bash
# Verify `agentmux inbox` cannot be pointed outside the inbox directory.
#   bash <(tr -d '\r' < dashboard/test_inbox_guard.sh)
#
# WHY. cmd_inbox interpolated its argument straight into "$ROOT/inbox/$name.jsonl".
# `inbox ../queue/claude --clear` therefore resolved to ~/.agentmux/queue/claude.jsonl -
# a real agent outbox, outside inbox/ - and --clear unlinked it, destroying messages
# that had not been delivered yet. cmd_post rejected such a name; cmd_inbox accepted
# it. Found by grok reviewing agentmux.sh on 2026-09-22.
#
# Runs against a THROWAWAY AGENTMUX_HOME, so a regression here cannot destroy real
# queue files while proving that it would.
set -u
[ -f agentmux.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

HOME_DIR="$(mktemp -d)"
AM="$(mktemp)"
trap 'rm -rf "$HOME_DIR" "$AM"' EXIT
tr -d '\r' < agentmux.sh > "$AM"
export AGENTMUX_HOME="$HOME_DIR"

mkdir -p "$HOME_DIR/inbox" "$HOME_DIR/queue"
printf '{"at":"t","sender":"dev","recipient":"orchestrator","kind":"reply","body":"real mail","ref":null}\n' \
  > "$HOME_DIR/inbox/orchestrator.jsonl"
printf '{"at":"t","sender":"dev","recipient":"rev","kind":"request","body":"UNDELIVERED","ref":null}\n' \
  > "$HOME_DIR/queue/dev.jsonl"

pass=0; fail=0
ok()   { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

echo '--- a traversing name is refused ---'
for name in '../queue/dev' '../../etc/passwd' 'a/b' '/etc/passwd' '..' '.'; do
  if bash "$AM" inbox "$name" --clear >/dev/null 2>&1; then
    bad "accepted '$name'"
  else
    ok "refused '$name'"
  fi
done

echo '--- and the outbox it would have destroyed is intact ---'
if [ -f "$HOME_DIR/queue/dev.jsonl" ] && grep -q UNDELIVERED "$HOME_DIR/queue/dev.jsonl"; then
  ok 'queue/dev.jsonl still holds its undelivered message'
else
  bad 'queue/dev.jsonl was destroyed'
fi

echo '--- an empty name is the default, not an error ---'
# "${1:-orchestrator}" substitutes the default for an empty argument too, so this is
# the same as `agentmux inbox`. Asserted rather than assumed, because it decides
# whether the traversal guard above needs to handle the empty case at all.
if bash "$AM" inbox '' >/dev/null 2>&1; then
  ok "an empty name falls back to 'orchestrator'"
else
  bad 'an empty name errored'
fi

echo '--- a legitimate name still works ---'
# Re-created here so this section does not depend on what ran above.
printf '{"at":"t","sender":"dev","recipient":"orchestrator","kind":"reply","body":"real mail","ref":null}\n' \
  > "$HOME_DIR/inbox/orchestrator.jsonl"
if bash "$AM" inbox orchestrator 2>/dev/null | grep -q 'real mail'; then
  ok 'reads the orchestrator inbox'
else
  bad 'could not read a valid inbox'
fi
if bash "$AM" inbox orchestrator --clear >/dev/null 2>&1 \
   && [ ! -f "$HOME_DIR/inbox/orchestrator.jsonl" ]; then
  ok '--clear empties a valid inbox'
else
  bad '--clear did not work on a valid inbox'
fi
if bash "$AM" inbox nosuchagent 2>/dev/null | grep -qi 'empty'; then
  ok 'a missing inbox reports empty rather than failing'
else
  bad 'missing inbox did not report empty'
fi
if bash "$AM" inbox 'with.dots-and_underscores' 2>/dev/null | grep -qi 'empty'; then
  ok 'dots, dashes and underscores are accepted'
else
  bad 'rejected a legitimate name'
fi

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
