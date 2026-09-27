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
eval "$(sed -n '/^modal_answer() {/,/^}/p' "$GUARD")"
eval "$(sed -n '/^modal_decision() {/,/^}/p' "$GUARD")"

# shellcheck source=/dev/null
. dashboard/testlib.sh          # ok/bad/check/check_rc/rc_is/count_msgs, one copy

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

echo '--- unblock: what may be answered, and what may NOT ---'
# `send` refusing is only half an answer: nothing ANSWERS, so a pane parked on a
# first-run dialog waits for a human. `unblock` closes that - but only for prompts it
# can positively identify, and only with the option that declines or keeps the current
# state. The defaults here are hostile, which is the whole reason there is no generic
# "press Enter": codex preselects "Update now (runs npm install -g)" and claude
# preselects "No, exit", which kills the agent.

answers() {   # answers <label> <expected-keys> <text>
  local got
  if got="$(modal_answer "$3")"; then
    if [ "${got%%|*}" = "$2" ]; then
      printf '  ok    %-56s answers %s\n' "$1" "$2"; pass=$((pass + 1))
    else
      printf '  FAIL  %-56s pressed %s, wanted %s\n' "$1" "${got%%|*}" "$2"; fail=$((fail + 1))
    fi
  else
    printf '  FAIL  %-56s no answer offered\n' "$1"; fail=$((fail + 1))
  fi
}

leaves() {    # leaves <label> <text>  - must be left for a person
  if modal_answer "$2" >/dev/null; then
    printf '  FAIL  %-56s ANSWERED - this is a decision\n' "$1"; fail=$((fail + 1))
  else
    printf '  ok    %-56s left for a person\n' "$1"; pass=$((pass + 1))
  fi
}

names() {     # names <label> <needle> <text> - the refusal says WHAT the decision is
  local why
  if why="$(modal_decision "$3")" && printf '%s' "$why" | grep -qiF -- "$2"; then
    printf '  ok    %-56s named: %s\n' "$1" "$why"; pass=$((pass + 1))
  else
    printf '  FAIL  %-56s not named (%s)\n' "$1" "${why:-no classification}"; fail=$((fail + 1))
  fi
}

answers 'the codex update nag is a nuisance, not a decision' 2 '  Update available
  1. Update now (runs npm install)
  Press enter to continue'

# EVERY ONE OF THESE MUST BE LEFT ALONE. A harness that clicks through a trust
# dialog, a consent dialog or an account chooser has removed the point of the guard.
leaves 'folder trust'            '  Do you trust the files in this folder?
  ❯ No, exit
    Yes, I trust this folder'
leaves 'claude bypass consent'   '  By proceeding, you accept all responsibility.
  ❯ No, exit
    Yes, I accept'
leaves 'codex directory trust'   '  Do you trust the contents of this directory?
  › 1. Yes, continue
    2. No, quit'
leaves 'account chooser'         '  ❯ 1. Claude account with subscription
    2. Anthropic Console account'
leaves 'a destructive y/n'       '  Overwrite the file? [y/n]'
leaves 'an unrecognised prompt'  '  Frobnicate the widget? [a/b/c]'

names 'trust is named as a trust decision' 'trust' '  Do you trust the files in this folder?
  ❯ No, exit'
names 'consent is named, and so is its lethal default' 'No, exit' \
  '  By proceeding, you accept all responsibility.
  ❯ No, exit
    Yes, I accept'
names 'an account chooser is named' 'account' '  ❯ 1. Claude account with subscription
    2. Anthropic Console account'

finish
[ "$fail" -eq 0 ] || exit 1
