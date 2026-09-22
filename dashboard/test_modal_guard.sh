#!/usr/bin/env bash
# Verify the `send` modal guard against real captured pane text.
#   bash <(tr -d '\r' < dashboard/test_modal_guard.sh)
#
# No tmux, no CLI, no network: agentmux.sh's modal_text takes the text directly, so
# every sample below is a literal capture rather than a live agent.
#
# WHY THIS SUITE EXISTS. `send` types text and then presses Enter. If the pane is
# showing a selection dialog, that Enter actuates whatever is highlighted instead of
# talking to the agent. It has gone wrong twice, both times destructively:
#
#   2026-09-20  a codex "Update available / Press enter to continue" prompt took the
#               Enter, chose "Update now", and npm install killed the pane mid-session
#   2026-09-22  a claude "No, exit / Yes, I accept" consent dialog took the Enter,
#               chose the DEFAULT of "No, exit", and the agent exited
#
# The second one is why the false-negative half matters more than the false-positive
# half: a missed modal destroys an agent, while an over-eager guard merely asks the
# operator to use `key`. Both are checked, because a guard that fires on an ordinary
# prompt would make `send` useless and get switched off.
set -u
[ -f agentmux.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

GUARD="$(mktemp)"
trap 'rm -f "$GUARD"' EXIT
tr -d '\r' < agentmux.sh > "$GUARD"
# Pull in just the function; the script's dispatch runs on source otherwise.
eval "$(sed -n '/^modal_text() {/,/^}/p' "$GUARD")"

pass=0; fail=0

modal() {   # modal <label> <text...>  - MUST be detected
  if modal_text "$2"; then
    printf '  ok    %-56s detected\n' "$1"; pass=$((pass + 1))
  else
    printf '  FAIL  %-56s MISSED - send would actuate this\n' "$1"; fail=$((fail + 1))
  fi
}

normal() {  # normal <label> <text...> - must NOT be detected
  if modal_text "$2"; then
    printf '  FAIL  %-56s false positive - send would refuse\n' "$1"; fail=$((fail + 1))
  else
    printf '  ok    %-56s not a modal\n' "$1"; pass=$((pass + 1))
  fi
}

echo '--- the two that actually cost an agent ---'
modal 'codex update prompt (2026-09-20)' '  Update available
  1. Update now (runs npm install)
  Press enter to continue'
modal 'claude bypass consent (2026-09-22)' '  By proceeding, you accept all responsibility.
  ❯ No, exit
    Yes, I accept
  Enter to confirm · Esc to cancel'

echo '--- claude startup dialogs ---'
modal 'folder trust'            '  Do you trust the files in this folder?
  ❯ No, exit
    Yes, I trust this folder'
modal 'workspace safety check'  '  Quick safety check: Is this a project you created or one you trust?
  ❯ No, exit
    Yes, I accept'
modal 'opus effort recommendation' ' We recommend Opus 5 at medium effort
   ❯ Switch Opus 5 to medium effort
     Keep high'
modal 'bare confirm footer'     '  Enter to confirm · Esc to cancel'

echo '--- codex / grok dialogs ---'
modal 'codex directory trust'   '  Do you trust the contents of this directory?
  › 1. Yes, continue
    2. No, quit'
modal 'numbered selection'      '  ❯ 1. Claude account with subscription
    2. Anthropic Console account'
modal 'y/n inline'              '  Overwrite the file? [y/n]'
modal 'parenthesised y/n'       '  Continue (y/N)'
modal 'press any key'           '  Press any key to continue'
modal 'select an option'        '  Select an option to continue'
modal 'login menu'              '  ❯ Sign in with your account'

echo '--- ordinary panes: the guard must stay quiet ---'
normal 'claude idle prompt'     '❯
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents'
normal 'claude placeholder'     '❯ Try "how does <filepath> work?"
  ⏵⏵ auto mode on (shift+tab to cycle)'
normal 'codex idle prompt'      '› Ask Codex to do anything

  gpt-6-astra default · /mnt/c/Dev/agentmux'
normal 'grok idle prompt'       '  │ ❯                                   │
  Grok 4.7 (high) · always-approve'
normal 'bash prompt'            'nick@MEP31337:/tmp$'
normal 'a finished answer'      '❯ What is 6 times 7? Reply with only the number.
● 42
✻ Cogitated for 2s · done 2:40 PM'
normal 'prose mentioning exit'  '● The function will exit when the last agent is killed.'
normal 'shell output'           'total 20
drwxr-xr-x 2 nick nick 4096 Sep 22 09:38 .'
normal 'a diff'                 '+  if not logged in:
-      continue'

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
