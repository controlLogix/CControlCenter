#!/usr/bin/env bash
# link-windows-state.sh - share codex/claude state between WSL and Windows.
#
# Run inside WSL. Portable: discovers the Windows profile at run time and
# assumes nothing about the username, distro, drive letter or node version.
#
#   ./link-windows-state.sh --check     report current state, change nothing
#   ./link-windows-state.sh --apply     create the links
#   ./link-windows-state.sh --revert    undo, restoring from the backup
#
# WHY THIS IS NOT JUST "ln -s ~/.claude"
#
# A whole-directory symlink of ~/.claude is the obvious move and it breaks
# Windows. Two files under plugins/ record absolute, OS-specific paths, and
# Claude Code REWRITES them on every run:
#
#   known_marketplaces.json  installLocation -> rewritten to the Linux path
#   installed_plugins.json   installPath     -> recorded as the Windows path
#
# Share those and the first WSL run silently drops every plugin skill from all
# NEW Windows sessions ("failed to load: cache-miss"), and re-asserts the Linux
# path on every later invocation, including `claude -p`. There is no state of a
# shared plugins/ in which both sides work.
#
# So ~/.claude is built as a REAL directory of per-entry symlinks, with the
# path-bearing entries kept WSL-local. Plugin payloads stay shared; the two
# path-bearing JSONs are per-OS. Nothing in the plugins themselves is modified.
#
# ~/.codex is a whole-directory symlink, because codex's auth.json contains no
# paths and sharing it means one login for both sides.

set -uo pipefail

MODE="${1:---check}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/.agentmux-state-backup"

# Entries kept WSL-local: they hold Windows-only absolute paths, OS-specific
# handles, or state that is meaningless across the boundary.
CLAUDE_LOCAL=(
  ide              # cross-session registry: mixes win32 named pipes with Linux peers
  shell-snapshots  # Windows bash snapshots, not valid shells here
  plugins          # handled specially below - most of it IS shared
  statsig
)
# Inside plugins/, only these stay local. Everything else is shared.
PLUGINS_LOCAL=(
  known_marketplaces.json
  installed_plugins.json
)

info() { printf '  %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- discovery ---

# Windows user profile as a WSL path. Tries interop, then wslu, then a scan.
find_win_home() {
  local wp="" p
  wp="$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r\n')"
  if [ -z "$wp" ] && command -v wslvar >/dev/null 2>&1; then
    wp="$(wslvar USERPROFILE 2>/dev/null | tr -d '\r\n')"
  fi
  if [ -n "$wp" ]; then
    p="$(wslpath -u "$wp" 2>/dev/null)"
    [ -n "$p" ] && [ -d "$p" ] && { printf '%s' "$p"; return 0; }
  fi
  # Last resort: a Users dir on any mounted drive holding a matching name.
  for p in /mnt/*/Users/*; do
    [ -d "$p" ] || continue
    case "${p##*/}" in
      All\ Users|Default|Default\ User|Public) continue ;;
    esac
    printf '%s' "$p"; return 0
  done
  return 1
}

in_list() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [ "$x" = "$needle" ] && return 0; done
  return 1
}

# Is $1 already a symlink resolving to $2?
links_to() {
  [ -L "$1" ] || return 1
  [ "$(readlink -f "$1" 2>/dev/null)" = "$(readlink -f "$2" 2>/dev/null)" ]
}

# -------------------------------------------------------- path translation ---

# Rewrite drive-letter paths to their /mnt/... equivalents inside the WSL-local
# plugin config copies, so plugins resolve on THIS side too. Only the local
# copies are touched - the plugins themselves and the Windows config are not.
# Idempotent: once translated, nothing matches the drive-letter pattern again.
translate_local_paths() {
  local f target
  command -v python3 >/dev/null 2>&1 || {
    warn "python3 not found - skipping path translation (plugins will not load in WSL)"
    return 0
  }
  for f in "${PLUGINS_LOCAL[@]}"; do
    target="$WSL_CLAUDE/plugins/$f"
    [ -f "$target" ] && [ ! -L "$target" ] || continue
    python3 - "$target" <<'PY'
import json, re, subprocess, sys

path = sys.argv[1]
DRIVE = re.compile(r'^[A-Za-z]:[\\/]')
cache = {}

def to_wsl(win):
    if win not in cache:
        try:
            cache[win] = subprocess.run(
                ['wslpath', '-u', win], capture_output=True, text=True, timeout=10
            ).stdout.strip() or win
        except Exception:
            cache[win] = win
    return cache[win]

def walk(node):
    if isinstance(node, dict):
        return {k: walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(v) for v in node]
    if isinstance(node, str) and DRIVE.match(node):
        return to_wsl(node)
    return node

with open(path, encoding='utf-8') as fh:
    before = json.load(fh)
after = walk(before)
if after != before:
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(after, fh, indent=2)
    print(f"  translated paths in {path.rsplit('/', 1)[-1]}")
else:
    print(f"  paths already WSL-native in {path.rsplit('/', 1)[-1]}")
PY
  done
}

# ------------------------------------------------------------------- report ---

describe() {
  local p="$1"
  if [ -L "$p" ]; then printf 'symlink -> %s' "$(readlink "$p")"
  elif [ -d "$p" ]; then printf 'real dir (%s entries)' "$(ls -A "$p" 2>/dev/null | wc -l)"
  elif [ -e "$p" ]; then printf 'real file'
  else printf 'absent'
  fi
}

do_check() {
  echo "Windows profile : $WIN_HOME"
  echo
  echo "codex"
  info "WSL  ~/.codex          : $(describe "$HOME/.codex")"
  info "Win  .codex            : $(describe "$WIN_CODEX")"
  info "auth.json (shareable)  : $(describe "$WIN_CODEX/auth.json")"
  echo
  echo "claude"
  info "WSL  $WSL_CLAUDE : $(describe "$WSL_CLAUDE")"
  info "Win  .claude           : $(describe "$WIN_CLAUDE")"
  info "Win  .credentials.json : $(describe "$WIN_CLAUDE/.credentials.json")"
  if [ -d "$WSL_CLAUDE" ] && [ ! -L "$WSL_CLAUDE" ]; then
    local linked total
    linked="$(find "$WSL_CLAUDE" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    total="$(ls -A "$WSL_CLAUDE" 2>/dev/null | wc -l)"
    info "entries linked to Win  : $linked of $total"
  fi
  echo
  echo "plugin-path guard (the thing that breaks Windows if shared)"
  local f
  for f in "${PLUGINS_LOCAL[@]}"; do
    info "$f : $(describe "$WSL_CLAUDE/plugins/$f")   [must be 'real file' or 'absent', never a symlink]"
  done
  echo
  [ -d "$BACKUP_DIR" ] && { echo "backups"; ls -1 "$BACKUP_DIR" | sed 's/^/  /'; }
  return 0
}

# -------------------------------------------------------------------- apply ---

backup_if_real() {
  local p="$1" name="$2"
  [ -e "$p" ] || return 0
  [ -L "$p" ] && return 0          # already a link, nothing of ours to lose
  mkdir -p "$BACKUP_DIR"
  local tgz="$BACKUP_DIR/${name}-${STAMP}.tar.gz"
  tar czf "$tgz" -C "$(dirname "$p")" "$(basename "$p")" 2>/dev/null \
    && info "backed up $name -> $tgz"
}

# Whole-directory symlink, merging any pre-existing WSL content to Windows.
link_whole() {
  local wsl="$1" win="$2" name="$3"
  if links_to "$wsl" "$win"; then info "$name already linked"; return 0; fi
  mkdir -p "$win"
  if [ -e "$wsl" ] && [ ! -L "$wsl" ]; then
    backup_if_real "$wsl" "$name"
    # Merge WSL-side content into Windows, never clobbering what is there.
    cp -rn "$wsl/." "$win/" 2>/dev/null
    rm -rf "$wsl"
  fi
  [ -L "$wsl" ] && rm -f "$wsl"
  ln -s "$win" "$wsl" && info "$name -> $win"
}

# Real directory of per-entry symlinks, honouring a local-only exclusion list.
link_per_entry() {
  local wsl="$1" win="$2"; shift 2
  local -a local_names=("$@")
  mkdir -p "$wsl"
  local entry base target
  for entry in "$win"/* "$win"/.[!.]*; do
    [ -e "$entry" ] || continue
    base="${entry##*/}"
    target="$wsl/$base"
    if in_list "$base" "${local_names[@]}"; then
      # Must NOT be a link. If a previous run linked it, break the link and
      # give this side its own copy so WSL writes cannot reach Windows.
      if [ -L "$target" ]; then
        rm -f "$target"
        cp -r "$entry" "$target" 2>/dev/null
        info "un-linked (now WSL-local): $base"
      elif [ ! -e "$target" ] && [ -f "$entry" ]; then
        cp "$entry" "$target" 2>/dev/null
        info "WSL-local copy: $base"
      fi
      continue
    fi
    links_to "$target" "$entry" && continue
    [ -L "$target" ] && rm -f "$target"
    if [ -e "$target" ]; then
      mv "$target" "$target.pre-link-$STAMP" && info "moved aside: $base"
    fi
    ln -s "$entry" "$target" && info "linked: $base"
  done
}

do_apply() {
  echo "Windows profile : $WIN_HOME"
  echo

  echo "codex - whole-directory share (auth.json has no paths)"
  link_whole "$HOME/.codex" "$WIN_CODEX" ".codex"
  echo

  echo "claude - per-entry share with the plugin-path entries kept local"
  [ -d "$WIN_CLAUDE" ] || die "no Windows .claude at $WIN_CLAUDE - run Claude Code on Windows once first"
  if [ -L "$WSL_CLAUDE" ]; then
    rm -f "$WSL_CLAUDE"
    info "removed pre-existing whole-dir symlink (the unsafe shape)"
  else
    backup_if_real "$WSL_CLAUDE" ".claude"
  fi
  link_per_entry "$WSL_CLAUDE" "$WIN_CLAUDE" "${CLAUDE_LOCAL[@]}"
  echo

  echo "  plugins - share the payloads, keep the two path-bearing files local"
  if [ -d "$WIN_CLAUDE/plugins" ]; then
    link_per_entry "$WSL_CLAUDE/plugins" "$WIN_CLAUDE/plugins" "${PLUGINS_LOCAL[@]}"
  else
    info "no Windows plugins dir - nothing to share"
  fi
  echo
  echo "  translating paths in the WSL-local copies so plugins load here too"
  translate_local_paths
  echo

  # Guard: assert the invariant this whole script exists to protect.
  local f bad=0
  for f in "${PLUGINS_LOCAL[@]}"; do
    if [ -L "$WSL_CLAUDE/plugins/$f" ]; then
      warn "$f is a SYMLINK - Windows plugins will break. Re-run --apply."
      bad=1
    fi
  done
  [ "$bad" = 0 ] && echo "guard OK: no path-bearing plugin file is shared."
  echo
  cat <<'NOTE'
Logins are still per-side:
  codex  - shared. One `codex login` (either side) now serves both.
  claude - NOT shareable. Windows keeps its login in the Windows credential
           store (DPAPI), which Linux cannot read; there is no credentials
           file to link. Run `claude` in WSL and `/login` once.

Verify Windows plugins survived, from a NEW Windows session:
  claude plugin list
NOTE
}

# ------------------------------------------------------------------- revert ---

do_revert() {
  local tgz pair dir label
  # "<directory>|<backup label>". The label is stable even when the directory is
  # not, because CLAUDE_CONFIG_DIR can move it.
  for pair in "$WSL_CLAUDE|.claude" "$HOME/.codex|.codex"; do
    dir="${pair%%|*}"; label="${pair##*|}"
    [ -L "$dir" ] && { rm -f "$dir"; info "removed symlink $label ($dir)"; }
    if [ -d "$dir" ] && [ ! -L "$dir" ]; then
      find "$dir" -maxdepth 2 -type l -delete 2>/dev/null
      info "removed per-entry symlinks under $label"
    fi
    tgz="$(ls -1t "$BACKUP_DIR/${label}-"*.tar.gz 2>/dev/null | head -1)"
    if [ -n "$tgz" ]; then
      rm -rf "$dir"
      # backup_if_real archived with -C dirname(dir) basename(dir), so the
      # archive's top-level entry is the real basename. It must be unpacked into
      # that directory's PARENT, not blindly into $HOME.
      tar xzf "$tgz" -C "$(dirname "$dir")" \
        && info "restored $label from $(basename "$tgz")"
    else
      info "no backup for $label - left as-is (empty dirs may remain)"
    fi
  done
  echo "Windows-side state was never modified by --apply, so nothing to undo there."
}

# Resolve the config dir Claude Code actually reads.
#
# CLAUDE_CONFIG_DIR may move it anywhere - on this machine it is ~/.claude-wsl.
# Linking ~/.claude when the CLI reads somewhere else silently does nothing, and
# --check would report success for sharing that is not happening. A login shell is
# asked because this script is normally run via process substitution, which
# sources neither .bashrc nor .profile.
wsl_claude_dir() {
  local d="${CLAUDE_CONFIG_DIR:-}"
  [ -z "$d" ] && d="$(bash -lc 'printf "%s" "${CLAUDE_CONFIG_DIR:-}"' 2>/dev/null)"
  [ -n "$d" ] && { printf '%s' "$d"; return 0; }
  printf '%s' "$HOME/.claude"
}

# --------------------------------------------------------------------- main ---

command -v wslpath >/dev/null 2>&1 || die "not running inside WSL"
WIN_HOME="$(find_win_home)" || die "could not locate the Windows user profile"
WSL_CLAUDE="$(wsl_claude_dir)"
[ "$WSL_CLAUDE" = "$HOME/.claude" ] \
  || info "CLAUDE_CONFIG_DIR moves the WSL config dir to $WSL_CLAUDE"
WIN_CLAUDE="$WIN_HOME/.claude"
WIN_CODEX="$WIN_HOME/.codex"

case "$MODE" in
  --check)  do_check ;;
  --apply)  do_apply ;;
  --revert) do_revert ;;
  *) die "usage: $0 --check | --apply | --revert" ;;
esac
