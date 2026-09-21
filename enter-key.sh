#!/usr/bin/env bash
# enter-key.sh - prompt for the xAI key in a terminal, safely.
#
# Runs inside a tmux pane you attach to. The key is read with `read -s`, so:
#   - it is never echoed, therefore never enters the pane's output stream
#     (which means tmux pipe-pane / capture-pane cannot record it)
#   - it is never a command argument, so it is not in ~/.bash_history or `ps`
#   - it is written to ~/.agentmux/env at mode 0600 on the Linux filesystem
#     (not /mnt/c, where POSIX modes are meaningless)

set -uo pipefail
ENVFILE="$HOME/.agentmux/env"
mkdir -p "$(dirname "$ENVFILE")"

printf '\n'
printf '  xAI / Grok API key entry\n'
printf '  ------------------------\n'
printf '  Paste the key and press Enter. Nothing will appear as you type.\n'
printf '  Ctrl-C to abort.\n\n'

while :; do
  umask 077
  read -rsp '  key: ' k
  printf '\n'
  if [ -z "$k" ]; then
    printf '  empty - try again.\n\n'
    continue
  fi
  if [ "${#k}" -lt 20 ]; then
    printf '  that is only %d characters, which looks too short for an xAI key.\n' "${#k}"
    read -rp '  use it anyway? [y/N] ' yn
    case "$yn" in [Yy]*) ;; *) printf '\n'; continue ;; esac
  fi
  printf 'XAI_API_KEY=%s\n' "$k" > "$ENVFILE"
  chmod 600 "$ENVFILE"
  unset k
  printf '\n  written: %s\n' "$(ls -l "$ENVFILE")"
  printf '  length and prefix only, never the value:\n'
  # shellcheck disable=SC1090
  ( set -a; . "$ENVFILE"; set +a; printf '    %d chars, starts %s...\n' "${#XAI_API_KEY}" "${XAI_API_KEY:0:4}" )
  printf '\n  Done. Detach with Ctrl-b d, then tell Claude it is set.\n\n'
  break
done
