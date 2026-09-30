#!/usr/bin/env bash
# clear-modals.sh - answer the known startup modals in agentmux agent panes.
#
# WHY THIS EXISTS
# A freshly spawned agent stops on a modal before it will accept a prompt.
# agentmux refuses to `send` into that state on purpose, because Enter would
# actuate the modal's default instead of talking to the agent. Clearing them by
# hand does not scale past about two agents, and clearing them blindly is worse
# than not clearing them at all - see the update rule below.
#
# THE ONE RULE THAT MATTERS: NEVER BLIND-ENTER.
# On 2026-09-29 a blind Enter, intended for a codex directory-trust dialog,
# landed on an "Update available!" prompt whose default was "1. Update now".
# It ran `npm install -g @openai/codex`, printed "Please restart Codex", and
# exited. Five panes died from one keystroke. This script only ever sends a key
# after a known pattern has matched, and it DECLINES updates rather than
# accepting them.
#
# Usage:
#   clear-modals.sh <agent> [<agent> ...]
#   clear-modals.sh --all
#   clear-modals.sh --all --dry-run
set -uo pipefail

PASSES=${CLEAR_MODALS_PASSES:-6}
SETTLE=${CLEAR_MODALS_SETTLE:-3}
DRY=0
AGENTS=()

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --all)     AGENTS=(__ALL__) ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    -*)        echo "unknown option: $arg" >&2; exit 2 ;;
    *)         AGENTS+=("$arg") ;;
  esac
done

if [ "${#AGENTS[@]}" -eq 0 ]; then
  echo "usage: $(basename "$0") <agent> [<agent> ...] | --all [--dry-run]" >&2
  exit 2
fi

if [ "${AGENTS[0]}" = "__ALL__" ]; then
  # Agent rows only. `agentmux list` also prints a trailing summary such as
  # "5 stale sidecar set(s) ..." whose first field is a number, so require an
  # identifier-shaped name AND a CLI column beside it.
  mapfile -t AGENTS < <(agentmux list 2>/dev/null \
    | awk 'NR>1 && NF>=3 && $1 ~ /^[A-Za-z][A-Za-z0-9_-]*$/ {print $1}')
  [ "${#AGENTS[@]}" -eq 0 ] && { echo "no agents running"; exit 0; }
fi

# Read a pane with escape sequences stripped, so patterns match plain text.
pane_text() {
  agentmux read "$1" --lines 40 2>/dev/null \
    | sed -r 's/\x1B\[[0-9;?]*[a-zA-Z]//g; s/\x1B[][][^\x07]*\x07//g; s/\x1B[()][AB0]//g'
}

# send_keys <agent> <label> <key> [<key> ...]
send_keys() {
  local agent="$1" label="$2"; shift 2
  if [ "$DRY" -eq 1 ]; then
    printf '  would answer %-22s with: %s\n' "$label" "$*"
    return 0
  fi
  printf '  answering %-22s with: %s\n' "$label" "$*"
  local k
  for k in "$@"; do
    agentmux key "$agent" "$k" >/dev/null 2>&1
    sleep 0.4
  done
}

# Returns 0 when it acted, 1 when nothing matched.
clear_one() {
  local agent="$1" txt
  txt="$(pane_text "$agent")"
  [ -z "$txt" ] && return 1

  # --- UPDATES: DECLINE. Accepting replaces the binary under a live pane and
  # the process exits. Option 3 ("Skip until next version") is chosen over
  # option 2 so a long run is not re-prompted every few minutes. Update the
  # CLI deliberately, outside a pane, never from inside one.
  if grep -qiE 'update available|1\. *update now|update now \(runs' <<<"$txt"; then
    send_keys "$agent" "update prompt (DECLINE)" Down Down Enter
    return 0
  fi

  # --- CLAUDE: bypass-permissions warning. Default is "No, exit"; the accept
  # option is one below it. The unrestricted posture is deliberate and lives in
  # provider config, not in a CLI flag - do not "fix" this by sandboxing.
  if grep -qiE 'bypass permissions mode' <<<"$txt" && grep -qiE 'yes, i accept' <<<"$txt"; then
    send_keys "$agent" "claude bypass warning" Down Enter
    return 0
  fi

  # --- GROK: directory trust. Letter-keyed, not arrow-keyed.
  if grep -qiE 'do you trust the contents' <<<"$txt"; then
    send_keys "$agent" "grok directory trust" y
    return 0
  fi

  # --- CODEX: directory trust. Accept is preselected, so a bare Enter is
  # correct here - but only because the pattern above proved it is this dialog
  # and not an update prompt.
  if grep -qiE 'allow codex to work|trust (this|the) (directory|folder)|do you want to allow' <<<"$txt"; then
    send_keys "$agent" "codex directory trust" Enter
    return 0
  fi

  # --- Generic yes/no warning with an explicit affirmative. Deliberately last,
  # and deliberately narrow: it requires a visible affirmative option so it
  # cannot fire on an ordinary prompt.
  if grep -qiE '\[y/n\]|\(y/n\)' <<<"$txt" && grep -qiE 'continue\?|proceed\?|trust|accept' <<<"$txt"; then
    send_keys "$agent" "generic y/n warning" y
    return 0
  fi

  return 1
}

# A pane is ready when it shows an input affordance and no known modal.
is_ready() {
  local txt; txt="$(pane_text "$1")"
  grep -qiE 'update available|bypass permissions mode|do you trust|allow codex to work' <<<"$txt" && return 1
  # Match a bare prompt (claude/codex: "❯ ", "› ") and a boxed one (grok draws
  # its input inside a border, so the prompt glyph is not at line start).
  grep -qE '^[[:space:]]*[│|]?[[:space:]]*(>|❯|›)' <<<"$txt"
}

rc=0
for agent in "${AGENTS[@]}"; do
  echo "== $agent"
  acted_any=0
  for ((i=1; i<=PASSES; i++)); do
    if clear_one "$agent"; then
      acted_any=1
      sleep "$SETTLE"
      continue
    fi
    break
  done

  if [ "$DRY" -eq 1 ]; then
    is_ready "$agent" && echo "  ready" || echo "  would still need attention"
    continue
  fi

  if is_ready "$agent"; then
    echo "  ready"
  elif [ "$acted_any" -eq 1 ]; then
    echo "  answered a modal but the pane is not at a prompt yet - re-run, or check with: agentmux read $agent"
    rc=1
  else
    echo "  no known modal matched and the pane is not at a prompt - inspect it: agentmux read $agent"
    rc=1
  fi
done

exit "$rc"
