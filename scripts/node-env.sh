#!/usr/bin/env bash
# Resolve a usable Node inside WSL, and refuse the Windows one.
#
#     . scripts/node-env.sh          # sets AGENTMUX_NODE and puts it on PATH
#     bash scripts/node-env.sh       # prints what it found, exits non-zero if unusable
#
# WHY THIS EXISTS. Measured on this host, 2026-09-25:
#
#     ~/.nvm/versions/node/v24.21.0   exists
#     command -v node                 -> nothing, in login AND non-interactive shells
#     command -v npm                  -> /mnt/c/Program Files/nodejs/npm
#
# nvm is installed and never sourced, so the only Node reachable from a
# non-interactive WSL shell is the WINDOWS one, leaking through /mnt/c interop.
# That is worse than having none: `npm install` under it builds native modules for
# the wrong platform, and the failures do not name their cause. `.bytedesk/task-
# management/bin/tm` - a `#!/usr/bin/env node` shim - simply exits 127.
#
# ADR-0023 puts the API in WSL, so this has to be settled before any of it is built.
#
# The discovery is the same shape dashboard/test_e2e.sh:24-30 already uses. One
# mechanism, not two.

agentmux_node_resolve() {
  # An explicit override wins, so a host with a different layout needs no edit here.
  if [ -n "${AGENTMUX_NODE:-}" ] && [ -x "${AGENTMUX_NODE}" ]; then
    printf '%s' "$AGENTMUX_NODE"
    return 0
  fi

  # Highest nvm version, by version sort rather than lexical: v9 must not beat v24.
  local candidate
  candidate=$(ls -d "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1 || true)
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    printf '%s' "$candidate"
    return 0
  fi

  # A node already on PATH is acceptable ONLY if it is not the Windows one.
  local onpath
  onpath=$(command -v node 2>/dev/null || true)
  case "$onpath" in
    /mnt/*|/c/*|"") : ;;
    *) printf '%s' "$onpath"; return 0 ;;
  esac
  return 1
}

# The guard. A Windows node reached through interop is the failure this whole file
# exists for, so name it rather than letting a build fail obscurely later.
agentmux_node_guard() {
  local node="$1"
  case "$node" in
    /mnt/*|/c/*)
      echo "agentmux: refusing $node - that is the WINDOWS node, reached through" >&2
      echo "  /mnt interop. Native modules built with it are for the wrong platform" >&2
      echo "  and fail in ways that do not name their cause." >&2
      echo "  Install Node in WSL:  nvm install 24   (or set AGENTMUX_NODE)" >&2
      return 1 ;;
  esac
  [ -x "$node" ] || { echo "agentmux: $node is not executable" >&2; return 1; }
  return 0
}

AGENTMUX_NODE=$(agentmux_node_resolve || true)
if [ -z "${AGENTMUX_NODE:-}" ]; then
  echo 'agentmux: no usable Node found in WSL.' >&2
  echo '  Install one:  nvm install 24' >&2
  echo '  Or point at one:  export AGENTMUX_NODE=/path/to/bin/node' >&2
  return 1 2>/dev/null || exit 1
fi
agentmux_node_guard "$AGENTMUX_NODE" || { return 1 2>/dev/null || exit 1; }

export AGENTMUX_NODE
export PATH="$(dirname "$AGENTMUX_NODE"):$PATH"

# The task-management shim resolves its plugin root from homedir(). In WSL that is
# /home/<user>, while the plugin is installed under the WINDOWS profile - so
# `bin/tm` finds Node and then fails anyway with "cannot resolve tm for ...".
# Point it at the /mnt/c install when one is there and the caller has not already.
if [ -z "${TM_PLUGIN_ROOT:-}" ]; then
  for _amx_win_home in /mnt/c/Users/*/.claude/plugins/cache/bytedesk/task-management; do
    [ -d "$_amx_win_home" ] || continue
    # The install is one versioned directory deep; take the newest.
    _amx_tm=$(ls -d "$_amx_win_home"/*/ 2>/dev/null | sort | tail -1)
    if [ -n "$_amx_tm" ] && [ -f "${_amx_tm%/}/lib/store.mjs" ]; then
      export TM_PLUGIN_ROOT="${_amx_tm%/}"
      break
    fi
  done
  unset _amx_win_home _amx_tm
fi

# Only report when run directly; sourcing should be silent.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "AGENTMUX_NODE=$AGENTMUX_NODE"
  echo "version:      $("$AGENTMUX_NODE" --version)"
  echo "npm:          $(command -v npm || echo 'not on PATH')"
  echo "TM_PLUGIN_ROOT=${TM_PLUGIN_ROOT:-<unset>}"
fi
