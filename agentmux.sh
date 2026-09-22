#!/usr/bin/env bash
# agentmux - drive other coding-agent CLIs (codex, claude, ...) in tmux panes.
#
# Runs inside WSL. Each agent is one tmux session on a dedicated tmux server
# socket ("agentmux"), so it never collides with an interactive tmux.
#
# Canonical source: <checkout>/agentmux.sh

set -uo pipefail

SOCKET="agentmux"
ROOT="${AGENTMUX_HOME:-$HOME/.agentmux}"
LOGDIR="$ROOT/logs"
RUNDIR="$ROOT/run"
mkdir -p "$LOGDIR" "$RUNDIR"

POLL_MS="${AGENTMUX_POLL_MS:-1500}"     # how often to sample the pane
QUIET_MS="${AGENTMUX_QUIET_MS:-5000}"   # pane unchanged this long => idle
TIMEOUT_S="${AGENTMUX_TIMEOUT_S:-300}"  # hard ceiling for wait/ask
COLS="${AGENTMUX_COLS:-200}"
ROWS="${AGENTMUX_ROWS:-50}"

ESC=$(printf '\033')

tm() { tmux -L "$SOCKET" "$@"; }
die() { printf 'agentmux: %s\n' "$*" >&2; exit 1; }
have() { tm has-session -t "=$1" 2>/dev/null; }
need() { have "$1" || die "no such agent: '$1' (try: agentmux list)"; }

# Strip ANSI CSI / OSC / charset escapes and CRs so captured text is diffable.
strip_ansi() {
  sed -e "s/${ESC}\[[0-9;:?]*[ -\/]*[@-~]//g" \
      -e "s/${ESC}\][^\a]*\a//g" \
      -e "s/${ESC}[()][A-Za-z0-9]//g" \
      -e "s/${ESC}[=>]//g" \
      -e 's/\r//g'
}

# Drop leading and trailing blank lines, leave the middle alone.
trim_edges() { sed -e '/./,$!d' | tac | sed -e '/./,$!d' | tac; }

# C:\foo or C:/foo -> /mnt/c/foo ; anything else passes through unchanged.
to_wsl_path() {
  case "$1" in
    [A-Za-z]:[\\/]*) wslpath -u "$1" 2>/dev/null || printf '%s' "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

# Newest nvm-managed node bin dir, so panes get the Linux toolchain ahead of
# the Windows shims that WSL interop appends to PATH.
node_bin() {
  ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1
}

# The claude config dir this machine ACTUALLY uses.
#
# Do not assume ~/.claude. A setup may export CLAUDE_CONFIG_DIR from .bashrc or
# .profile - neither of which is sourced by `wsl.exe -- bash -s`, so the harness's
# own environment is not evidence of what an interactive session resolves to.
# Ask a login shell instead, and only fall back to ~/.claude.
effective_claude_dir() {
  local d="${CLAUDE_CONFIG_DIR:-}"
  [ -z "$d" ] && d="$(bash -lc 'printf "%s" "${CLAUDE_CONFIG_DIR:-}"' 2>/dev/null)"
  [ -n "$d" ] && [ -d "$d" ] && { printf '%s' "$d"; return 0; }
  printf '%s' "$HOME/.claude"
}

# Config dir for spawned claude agents.
#
# Claude Code's permissive mode lives in settings.json, but the operator's own
# settings.json may be shared with a Windows install (see link-windows-state.sh).
# Setting bypassPermissions there would silently put the operator's OWN
# interactive sessions into bypass mode, so spawned agents get their own
# CLAUDE_CONFIG_DIR: a per-entry mirror that keeps skills, plugins and CLAUDE.md
# shared but owns its settings.json.
#
# Dropped from the agent's settings.json copy:
#   hooks      - the operator's SessionEnd hooks kill MCP servers and check git;
#                a spawned agent must not fire those on exit.
#   statusLine - references host-specific paths.
#
# NOT symlinked into the mirror - mutable operator state. These entries may point
# at the Windows profile, and a spawned agent runs unrestricted, so linking them
# would let it overwrite or prune the operator's own history and backups.
claude_config_dir() {
  local d="$ROOT/claude-config" src entry base tmp
  src="$(effective_claude_dir)"
  mkdir -p "$d"
  if [ -d "$src" ]; then
    for entry in "$src"/* "$src"/.[!.]*; do
      [ -e "$entry" ] || continue
      base="${entry##*/}"
      case "$base" in
        settings.json|settings.local.json) continue ;;   # ours, never shared
        sessions|history.jsonl|backups|projects|todos|statsig|shell-snapshots|ide)
          continue ;;                                     # mutable operator state
      esac
      [ -e "$d/$base" ] || ln -s "$entry" "$d/$base" 2>/dev/null
    done
  fi

  # Regenerated every spawn so it tracks edits to the operator's settings.
  # Written to a temp file and renamed, so a concurrent spawn can never read a
  # half-written settings.json, and a failed python run leaves the previous good
  # file in place rather than a truncated one.
  if command -v python3 >/dev/null 2>&1 && [ -f "$src/settings.json" ]; then
    tmp="$d/.settings.json.$$"
    if python3 - "$src/settings.json" "$tmp" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
try:
    with open(src, encoding='utf-8') as fh:
        cfg = json.load(fh)
except Exception:
    cfg = {}
cfg.pop('hooks', None)
cfg.pop('statusLine', None)
cfg.setdefault('permissions', {})['defaultMode'] = 'bypassPermissions'
with open(dst, 'w', encoding='utf-8') as fh:
    json.dump(cfg, fh, indent=2)
PY
    then
      mv -f "$tmp" "$d/settings.json"
    else
      rm -f "$tmp"
    fi
  fi

  # Last resort, and still atomic.
  if [ ! -f "$d/settings.json" ]; then
    tmp="$d/.settings.json.$$"
    printf '%s\n' '{ "permissions": { "defaultMode": "bypassPermissions" } }' > "$tmp" \
      && mv -f "$tmp" "$d/settings.json"
  fi

  # Caller claims UNRESTRICTED on the strength of this file; prove it first.
  if ! grep -q '"defaultMode": *"bypassPermissions"' "$d/settings.json" 2>/dev/null; then
    printf 'agentmux: failed to establish bypassPermissions in %s\n' "$d/settings.json" >&2
    return 1
  fi
  printf '%s' "$d"
}

# Path to the scripted Atlassian CLI, or empty if task management is not set up.
#
# MCP cannot be reached from a shell script, so Jira lifecycle calls go through
# taskmgmt/task.py. Both the CLI and a 0600 config must exist; otherwise every
# hook below silently no-ops, so agentmux keeps working with no Atlassian setup.
task_cli() {
  local cli="${AGENTMUX_TASK_CLI:-${AGENTMUX_REPO:-}/taskmgmt/task.py}"
  [ -n "${AGENTMUX_REPO:-}${AGENTMUX_TASK_CLI:-}" ] || return 1
  [ -f "$cli" ] || return 1
  [ -f "$HOME/.agentmux/atlassian.json" ] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  printf '%s' "$cli"
}

# Fire a task.py subcommand without ever letting it break the caller. A Jira
# outage must not stop an agent spawning or a pane being killed.
task_try() {
  local cli; cli="$(task_cli)" || return 0
  timeout 45 python3 "$cli" "$@" 2>&1 | sed 's/^/  jira: /' || true
}

# tmux pane target for an agent. "=name" matches a session but is NOT a valid
# pane target, so resolve to the stable pane id (%N) recorded at spawn time.
pane_of() {
  local p
  p="$(cat "$RUNDIR/$1.pane" 2>/dev/null)"
  if [ -z "$p" ] || ! tm has-session -t "=$1" 2>/dev/null; then
    p="$(tm list-panes -t "$1" -F '#{pane_id}' 2>/dev/null | head -1)"
    [ -n "$p" ] && printf '%s\n' "$p" > "$RUNDIR/$1.pane"
  fi
  printf '%s' "$p"
}

pane_hash() {
  tm capture-pane -p -t "$(pane_of "$1")" 2>/dev/null | strip_ansi | sed 's/[[:space:]]*$//' | cksum
}

usage() {
  cat <<'USAGE'
agentmux - drive other agent CLIs in tmux panes

  spawn <name> [--cli codex|claude|grok|shell|<cmd>] [--cwd DIR] [--model M]
               [--task ABC-123] [--auth METHOD]
                               start an agent in a detached tmux session.
                               --task binds a Jira issue: recorded in run/, shown
                               by `list` and the dashboard, and exported to the
                               pane as $AGENTMUX_TASK
                               --auth picks an auth method from dashboard/auth.json
                               (account OAuth, an API key, Vertex, or
                               any OpenAI-compatible endpoint). Omit it to use the
                               CLI's configured default.
                               List them: python3 taskmgmt/setup_auth.py --list
                               grok = xAI's CLI, authenticated by ACCOUNT LOGIN
                               (`grok login`), no API key required
  send   <name> [--force] <text...>
                               type text + Enter into the agent. Refuses if the pane
                               is showing a prompt (an update notice, a trust dialog),
                               because Enter would actuate that instead - use `key`
                               to answer a modal, or --force to override
  key    <name> <keys...>      tmux key names only, no text, no implicit Enter
                               (Enter, Escape, Down, C-c) - use for modals
  read   <name> [--lines N]    current pane contents, ANSI stripped
  tail   <name> [--lines N]    scrollback log for the agent
  wait   <name> [--timeout S] [--quiet S]
                               block until the pane stops changing
  ask    <name> <text...>      send, wait for idle, then print the pane
  post   <to> [--kind K] [--ref R] [--from NAME] <text...>
                               queue a message FOR ANOTHER AGENT in this agent's
                               outbox, ~/.agentmux/queue/<sender>.jsonl. The sender
                               is $AGENTMUX_AGENT inside a pane, else 'orchestrator'.
                               K is one of plan request reply status finding error.
                               Queueing is not delivery - the courier does that
  courier start|stop|status|once|watch
                               deliver queued messages to their recipients with
                               `send`. `start` detaches and writes a pidfile;
                               `once` makes a single pass, which is what a test or a
                               cron line wants. A recipient that is down, or showing
                               a prompt, is retried rather than forced
  list                         show agents, state and cwd
  kill   <name> | --all        stop agent(s)
  reap   [--dry-run]           remove run/ sidecars for agents with no live tmux
                               session. A reboot takes the tmux server without
                               going through `kill`, so orphans accumulate; the
                               dashboard shows each as `stale` but never removes it.
                               Logs are left alone
  attach <name>                print the command to watch the agent live
  exec   <text...> [--cwd DIR] [--model M]
                               headless one-shot "codex exec", no tmux

Spawned codex/claude agents run with the provider's master permission bypass by
default (unrestricted). Set AGENTMUX_NO_BYPASS=1 to spawn sandboxed instead.

Env: AGENTMUX_QUIET_MS, AGENTMUX_TIMEOUT_S, AGENTMUX_POLL_MS, AGENTMUX_COLS/ROWS
     AGENTMUX_NO_BYPASS
USAGE
}

# Auth method resolution.
#
# WHY A HELPER RATHER THAN A CASE BLOCK: the set of auth methods is data
# (dashboard/auth.json), so the harness must not hardcode which ones exist. It asks
# the manifest what a method needs, and gets back shell-ready exports plus any extra
# CLI flags.
#
# Secrets are NOT returned. A method's secret env var names are declared in the
# manifest and their VALUES live in $ROOT/env (0600), which is sourced into the pane
# separately - so a key never passes through this variable, this script's output, or
# the tmux command line.
#
# Prints:  <flags>\t<exports>
# Returns: 1 if the method is unknown or not fully configured.
auth_resolve() {
  local method="$1" cli="$2" repo="${AGENTMUX_REPO:-}"
  [ -n "$repo" ] || { printf 'agentmux: AGENTMUX_REPO is unset; cannot read the auth manifest\n' >&2; return 1; }
  python3 - "$repo" "$method" "$cli" <<'PY'
import json, os, pathlib, re, sys, shlex

repo, method_id, cli = sys.argv[1], sys.argv[2], sys.argv[3]
manifest = pathlib.Path(repo) / "dashboard" / "auth.json"
root = pathlib.Path(os.path.expanduser("~/.agentmux"))

try:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    methods = {m["id"]: m for m in data["methods"]}
    providers = {p["id"]: p for p in data["providers"]}
except (OSError, ValueError, KeyError) as err:
    sys.exit(f"agentmux: cannot read {manifest}: {err}")

method = methods.get(method_id)
if method is None:
    sys.exit(f"agentmux: unknown --auth method '{method_id}'. "
             f"Run: python3 taskmgmt/setup_auth.py --list")
if method["cli"] != cli:
    sys.exit(f"agentmux: --auth {method_id} is for --cli {method['cli']}, not {cli}")
provider = providers.get(method.get("provider"))
if provider is None:
    sys.exit(f"agentmux: {method_id} names an unknown provider "
             f"{method.get('provider')!r} in {manifest}")

settings = {}
path = root / "auth.json"
if path.exists():
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        sys.exit(f"agentmux: {path} is not valid JSON: {err}")
# Two scopes: shared provider attributes (a region, a key) and per-method ones (a
# model id, a gateway URL). Keeping them apart is what stops two CLIs on the same
# provider from overwriting each other's model.
shared = (settings.get("providers") or {}).get(provider["id"], {})
mine = (settings.get("methods") or {}).get(method_id, {})

# A provider's SECRETS are declared here as NAMES and their values live in
# $ROOT/env. Only presence is checked and no value is read into this process.
#
# WHY THIS IS HERE: the gate used to validate settings[] only. An api-key method
# declares no settings, so codex-api-key and claude-api-key resolved as "configured"
# with no key stored at all, and the CLI died inside the pane with nothing pointing
# at the cause. setup_auth --list and /api/auth both checked secrets correctly; only
# the spawn path did not.
env_names = set()
env_path = root / "env"
if env_path.exists():
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            found = re.match(r"\s*export\s+([A-Z][A-Z0-9_]*)=", line)
            if found:
                env_names.add(found.group(1))
    except OSError as err:
        sys.exit(f"agentmux: cannot read {env_path}: {err}")

missing = [f"{provider['id']}.{s['key']}" for s in provider.get("settings", [])
           if s["key"] not in shared]
missing += [f"{method_id}.{s['key']}" for s in method.get("settings", [])
            if s["key"] not in mine]
secrets = [name for name in provider.get("secrets", []) if name not in env_names]
if missing or secrets:
    # A secret is entered against the PROVIDER, a setting against the method, so point
    # at whichever command can actually fix what is missing.
    fix = (f"--provider {provider['id']}" if secrets else method_id)
    sys.exit(f"agentmux: --auth {method_id} is not configured (missing "
             f"{', '.join(missing + secrets)}). "
             f"Run: python3 taskmgmt/setup_auth.py {fix}")

exports = []
for name, literal in (method.get("env") or {}).items():
    exports.append(f"export {name}={shlex.quote(str(literal))};")
for name, key in (method.get("env_from_provider") or {}).items():
    exports.append(f"export {name}={shlex.quote(str(shared[key]))};")
for name, key in (method.get("env_from_method") or {}).items():
    exports.append(f"export {name}={shlex.quote(str(mine[key]))};")

flags = []
if "codex_profile" in method:
    profile = pathlib.Path(os.environ.get("CODEX_HOME") or (pathlib.Path.home() / ".codex"))
    if not (profile / f"{method_id}.config.toml").is_file():
        sys.exit(f"agentmux: codex profile for {method_id} is missing. "
                 f"Run: python3 taskmgmt/setup_auth.py {method_id}")
    # Replaces the yolo profile: codex layers exactly one -p/--profile.
    flags.append(f"--profile {method_id}")
    # Pass the model EXPLICITLY as well, even though the profile also names one.
    # The profile is a file only setup_auth.py writes, but the model is switchable from
    # the dashboard's Settings, which writes ~/.agentmux/auth.json. A flag overrides the
    # profile, so a model chosen in the UI takes effect on the next spawn without the
    # TOML having to be regenerated - and there is only one authority for it.
    chosen_model = mine.get("model")
    if chosen_model:
        flags.append(f"-m {shlex.quote(str(chosen_model))}")

print(" ".join(flags) + "\t" + " ".join(exports))
PY
}

# The configured default method for a CLI, or empty if none is set.
auth_default_for() {
  local cli="$1"
  python3 - "$cli" <<'PY' 2>/dev/null
import json, os, pathlib, sys
path = pathlib.Path(os.path.expanduser("~/.agentmux/auth.json"))
if path.exists():
    try:
        print(json.loads(path.read_text(encoding="utf-8")).get("active", {}).get(sys.argv[1], ""))
    except ValueError:
        pass
PY
}

cmd_spawn() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "spawn needs a name"
  local cli="codex" cwd="$PWD" model="" task="" summary="" created="" auth=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --cli)      cli="${2:-}";   shift 2 ;;
      --cwd)      cwd="${2:-}";   shift 2 ;;
      --model|-m) model="${2:-}"; shift 2 ;;
      --task)     task="${2:-}";  shift 2 ;;
      --auth)     auth="${2:-}";  shift 2 ;;
      *) die "spawn: unknown option '$1'" ;;
    esac
  done
  have "$name" && die "agent '$name' already exists (kill it first)"

  # A name reaches three places that make an unchecked one dangerous rather than
  # merely untidy: the pane environment (as $AGENTMUX_AGENT, inside single quotes,
  # so a quote character escapes into the launch command), a sidecar path under
  # run/, and a queue filename the courier and the dashboard both read back. The
  # accepted set is a subset of ccstore.py's NAME_PATTERN - '.' is excluded because
  # tmux gives it meaning in a target specifier.
  printf '%s' "$name" | grep -Eq '^[A-Za-z0-9_-]{1,64}$' \
    || die "agent name must be 1-64 chars of letters, digits, '_' or '-' (got '$name')"

  # Jira binding. Two accepted forms:
  #   --task ABC-123        bind an existing issue
  #   --task new:"Summary"  create the issue first, then bind the returned key
  #
  # Validated, never passed through: this value reaches the pane environment and a
  # sidecar the dashboard renders, so an unchecked string is both a shell- and a
  # display-injection vector.
  if [ -n "$task" ]; then
    case "$task" in
      new:*)
        summary="${task#new:}"
        [ -n "$summary" ] || die '--task new: needs a summary, e.g. --task new:"Fix the thing"'
        task_cli >/dev/null || die "--task new: needs taskmgmt/task.py plus ~/.agentmux/atlassian.json"
        created="$(timeout 60 python3 "$(task_cli)" create --summary "$summary"                     --label agentmux --label "agent-$name" 2>/dev/null | tail -1)"
        printf '%s' "$created" | grep -Eq '^[A-Z][A-Z0-9_]+-[0-9]+$'           || die "could not create a Jira issue (got '${created:-<empty>}')"
        task="$created"
        printf "created Jira issue %s for agent '%s'
" "$task" "$name"
        ;;
      *)
        printf '%s' "$task" | grep -Eq '^[A-Z][A-Z0-9_]+-[0-9]+$'           || die "--task must be ABC-123 or new:\"Summary\" (got '$task')"
        ;;
    esac
  fi

  cwd="$(to_wsl_path "$cwd")"
  [ -d "$cwd" ] || die "not a directory: $cwd"

  # Spawned agents get unrestricted access by DEFAULT. The permissive posture is
  # carried in each provider's own config rather than as a CLI flag:
  #   codex  - the "yolo" profile in $CODEX_HOME/yolo.config.toml
  #   claude - permissions.defaultMode in a dedicated CLAUDE_CONFIG_DIR
  # Set AGENTMUX_NO_BYPASS=1 to spawn a sandboxed pane instead.
  # `shell` and the passthrough case are never rewritten - a bare command string
  # is the caller's own.
  local bypass=1
  [ "${AGENTMUX_NO_BYPASS:-0}" = "1" ] && bypass=0

  local nb launch env_prefix
  nb="$(node_bin)"
  # ~/.grok/bin holds xAI's grok CLI. Its installer adds that to .bashrc, which a
  # tmux pane never sources (non-login, non-interactive), so add it explicitly.
  env_prefix="export PATH='${nb}:'\$HOME'/.grok/bin:'\$PATH;"
  # An issue key is not a secret, so exporting it directly is fine. Contrast
  # $ROOT/env below, which is SOURCED precisely so credentials never reach the
  # tmux command line or `ps`. The key is validated in the arg loop above.
  [ -n "$task" ] && env_prefix="$env_prefix export AGENTMUX_TASK='${task}';"
  # The agent's own name. Without it an agent has no way to know what it is called,
  # so it cannot fill in the sender field and `agentmux post` has nothing to
  # attribute. Validated against the pattern above, so the quoting holds.
  env_prefix="$env_prefix export AGENTMUX_AGENT='${name}';"

  # Private env for spawned panes - API keys for custom providers (e.g.
  # XAI_API_KEY for the codex "grok" profile) go in $ROOT/env, mode 0600, on the
  # Linux filesystem. It is SOURCED at pane start rather than interpolated into
  # the tmux command, so the value never appears in `ps` output, in
  # `#{pane_start_command}`, or in this script's own logs. Panes are non-login
  # shells, so ~/.bashrc and ~/.profile are not read - this is the hook for them.
  if [ -f "$ROOT/env" ]; then
    case "$(stat -c '%a' "$ROOT/env" 2>/dev/null)" in
      600|400) ;;
      *) printf "agentmux: %s/env is not mode 0600 - refusing to load it.\n         chmod 600 '%s/env'\n" "$ROOT" "$ROOT" >&2; return 1 ;;
    esac
    env_prefix="$env_prefix set -a; . '$ROOT/env'; set +a;"
  fi
  # Auth method. An explicit --auth wins; otherwise use whatever setup_auth.py
  # recorded as this CLI's active method. No method configured means the CLI's own
  # built-in default (an existing OAuth login), which is the pre-existing behaviour.
  local auth_flags="" auth_exports="" auth_line=""
  [ -n "$auth" ] || auth="$(auth_default_for "$cli")"
  if [ -n "$auth" ]; then
    auth_line="$(auth_resolve "$auth" "$cli")" || return 1
    auth_flags="${auth_line%%$(printf '\t')*}"
    auth_exports="${auth_line#*$(printf '\t')}"
    [ -n "$auth_exports" ] && env_prefix="$env_prefix $auth_exports"
  fi

  case "$cli" in
    codex)
      launch="codex${model:+ -m $model}"
      [ "$bypass" = 1 ] && launch="codex --profile yolo${model:+ -m $model}"
      # A custom-provider method brings its own profile, and codex accepts exactly
      # one --profile. The method's profile replaces yolo, so carry the permission
      # posture across with explicit flags instead of silently losing it.
      #
      # auth_flags may already carry the method's configured model as -m. An explicit
      # `spawn --model` must still win, and codex takes the LAST -m, so appending the
      # caller's value after the method's gives the right precedence:
      #   spawn --model X  >  the model set in Settings  >  the profile's model
      if [ -n "$auth_flags" ]; then
        launch="codex ${auth_flags}${model:+ -m $model}"
        [ "$bypass" = 1 ] && launch="$launch --dangerously-bypass-approvals-and-sandbox"
      fi
      ;;
    claude)
      launch="claude${model:+ --model $model}"
      if [ "$bypass" = 1 ]; then
        local ccd
        # Refuse to spawn rather than report UNRESTRICTED for an agent whose
        # bypass config could not be written.
        ccd="$(claude_config_dir)" || die "could not prepare the claude config dir"
        env_prefix="$env_prefix export CLAUDE_CONFIG_DIR='${ccd}';"
      fi
      ;;
    grok)
      # xAI's own CLI. Authenticates with a BROWSER/DEVICE login to the Grok
      # account (~/.grok/auth.json via `grok login`); XAI_API_KEY is only the
      # non-browser fallback. So this needs no key at all - unlike the codex
      # xai provider, which needs one AND is broken anyway (xAI rejects codex's
      # built-in `namespace` tool type).
      launch="grok${model:+ -m $model}"
      [ "$bypass" = 1 ] && launch="grok --permission-mode bypassPermissions${model:+ -m $model}"
      ;;
    shell)  launch="${SHELL:-/bin/bash}" ;;
    *)      launch="$cli" ;;
  esac

  tm new-session -d -s "$name" -c "$cwd" -x "$COLS" -y "$ROWS" \
     "${env_prefix} exec ${launch}" \
     || die "failed to start tmux session"

  local pane
  pane="$(tm list-panes -t "$name" -F '#{pane_id}' 2>/dev/null | head -1)"
  [ -n "$pane" ] || die "spawned '$name' but could not resolve its pane"
  printf '%s\n' "$pane" > "$RUNDIR/$name.pane"

  tm set-option -t "=$name" history-limit 50000 >/dev/null 2>&1
  tm set-option -t "=$name" mouse on >/dev/null 2>&1   # scroll works when you attach
  : > "$LOGDIR/$name.log"
  tm pipe-pane -o -t "$pane" "cat >> '$LOGDIR/$name.log'"

  printf '%s\n' "$cli" > "$RUNDIR/$name.cli"
  printf '%s\n' "$cwd" > "$RUNDIR/$name.cwd"
  printf '%s\n' "$launch" > "$RUNDIR/$name.launch"
  date -Is > "$RUNDIR/$name.started"
  # Read back by `list` and by the dashboard through its hardened read_field().
  [ -n "$task" ] && printf '%s\n' "$task" > "$RUNDIR/$name.task"
  # Which auth method this agent actually started with. An id from auth.json, never
  # a credential - the dashboard reads this file, so it must be safe to display.
  [ -n "$auth" ] && printf '%s\n' "$auth" > "$RUNDIR/$name.auth"
  # Recorded explicitly: for claude the bypass lives in the pane's environment,
  # not the launch line, so the launch line alone cannot tell you the posture.
  case "$cli" in
    codex|claude|grok) [ "$bypass" = 1 ] && echo UNRESTRICTED || echo sandboxed ;;
    *)            echo n/a ;;
  esac > "$RUNDIR/$name.perms"

  # Liveness gate. tmux new-session exits 0 even when the child dies instantly,
  # so without this a bad flag or a missing binary reports a successful spawn
  # and only surfaces later as "no such agent". Measured on a broken codex.
  sleep 2
  # Two ways the child can be gone: the session vanished with it, or - under
  # `remain-on-exit on` - the session survives holding a dead pane. Checking only
  # the session passes the second case and reports a successful spawn for a
  # process that already exited.
  local dead=""
  have "$name" || dead="session gone"
  [ -z "$dead" ] && [ "$(tm display-message -p -t "$pane" '#{pane_dead}' 2>/dev/null)" = "1" ] \
    && dead="pane dead (remain-on-exit)"
  if [ -n "$dead" ]; then
    printf "spawn FAILED: '%s' exited immediately (%s).\n" "$name" "$dead" >&2
    printf "launch line was: %s\n" "$launch" >&2
    if [ -s "$LOGDIR/$name.log" ]; then
      printf -- '--- last output ---\n' >&2
      strip_ansi < "$LOGDIR/$name.log" | tail -15 >&2
    fi
    rm -f "$RUNDIR/$name".* 2>/dev/null
    return 1
  fi

  printf "spawned '%s' [%s] in %s\n" "$name" "$cli" "$cwd"
  [ -n "$auth" ] && printf "  auth: %s\n" "$auth"

  # Bring the message courier up with the first agent.
  #
  # Nothing survives a reboot here - the tmux server, the Bedrock gateway and the
  # courier all have to be started again, and a courier that is not running fails
  # SILENTLY: `post` succeeds, the message sits in the queue, and the recipient
  # simply never hears anything. Tying it to spawn means messaging works whenever
  # there is anything to message, without a boot-time service.
  #
  # AGENTMUX_NO_COURIER=1 opts out. Failure here is never fatal to a spawn.
  if [ "${AGENTMUX_NO_COURIER:-0}" != "1" ] && [ -n "${AGENTMUX_REPO:-}" ] \
     && [ -f "$AGENTMUX_REPO/taskmgmt/courier.py" ]; then
    if ! python3 "$AGENTMUX_REPO/taskmgmt/courier.py" --status 2>/dev/null \
         | grep -q '^courier:   running'; then
      cmd_courier start >/dev/null 2>&1 \
        && printf "  courier: started (queued messages will be delivered)\n"
    fi
  fi
  # Report the profile actually in force. An --auth method brings its own, replacing
  # yolo, so naming yolo unconditionally described a configuration that was not running.
  [ "$bypass" = 1 ] && case "$cli" in
    codex)  if [ -n "$auth_flags" ]; then
              printf "  permissions: UNRESTRICTED (--dangerously-bypass-approvals-and-sandbox)\n"
            else
              printf "  permissions: UNRESTRICTED (codex profile 'yolo')\n"
            fi ;;
    claude) printf "  permissions: UNRESTRICTED (CLAUDE_CONFIG_DIR bypassPermissions)\n" ;;
    grok)   printf "  permissions: UNRESTRICTED (--permission-mode bypassPermissions)\n" ;;
  esac
  printf "watch it:  wsl -d Ubuntu -- tmux -L %s attach -t %s\n" "$SOCKET" "$name"
}

# Does the pane currently show a blocking prompt that is NOT the agent's normal input?
#
# WHY THIS EXISTS. `send` appends Enter, so sending text while a modal is up actuates the
# modal's default rather than talking to the agent. That is not theoretical: a codex
# "Update available! 1. Update now / Press enter to continue" prompt appeared on a fresh
# spawn, a routine `send` landed on it, and Enter selected "Update now" — which ran
# npm install and took the agent down mid-session.
#
# Matching the LAST few lines only, because these prompts live at the bottom of the pane
# and the same words appear harmlessly in scrollback.
# The patterns below are in three groups, and the second and third exist because the
# first was not enough. Measured 2026-09-22 on a fresh `claude` pane: it shows THREE
# modals in a row - folder trust, bypass-permissions consent, then an Opus effort
# recommendation - and none of them matched. `send` typed into the second one, Enter
# selected its default of "No, exit", and the agent died. That is bug 30 all over
# again on a different CLI, so the guard now covers the shapes rather than one CLI's
# wording:
#
#   1. explicit question forms  - the original set
#   2. confirm/cancel footers   - "Enter to confirm", "Esc to cancel"
#   3. a SELECTED option line   - a caret or arrow followed by an answer word, or by
#                                 a numbered choice
#
# Group 3 needs care: `❯` and `›` are also the IDLE input prompts of claude and codex.
# It only fires when the marker is followed by an answer-shaped word or "N.", which an
# empty prompt never is.
#
# Matching the LAST few lines only, because these prompts live at the bottom of the pane
# and the same words appear harmlessly in scrollback.
# Split in two so the PATTERN can be tested without a tmux server or a real CLI:
# modal_text takes the text, modal_prompt supplies it from a pane.
# dashboard/test_modal_guard.sh exercises modal_text against captured samples.
modal_text() {
  printf '%s' "$1" | grep -Eqi \
    'press enter to continue|update now \(runs|\[y/n\]|\(y/n\)|do you (want|trust)|allow this|press any key|select an option|continue\? *$|enter to confirm|esc to cancel|no, (exit|quit)|yes, i (accept|trust)|trust this folder|[❯›▶>][[:space:]]+([0-9]+\.|yes\b|no\b|switch\b|keep\b|continue\b|sign in\b|log ?in\b)'
}

modal_prompt() {
  local pane="$1" tail_text
  tail_text="$(tm capture-pane -p -t "$pane" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -8)"
  modal_text "$tail_text"
}

cmd_send() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "send needs a name"
  need "$name"
  local force=0
  if [ "${1:-}" = "--force" ]; then force=1; shift; fi
  local text="$*" pane
  [ -n "$text" ] || die "send needs text"
  pane="$(pane_of "$name")"
  [ -n "$pane" ] || die "cannot resolve pane for '$name'"

  # Refuse rather than actuate someone else's default. `key` exists precisely for
  # answering a modal deliberately, and it sends no implicit Enter.
  if [ "$force" != 1 ] && modal_prompt "$pane"; then
    printf "agentmux: '%s' is showing a prompt, not its normal input. Refusing to send:\n" "$name" >&2
    printf '%s\n' "  Enter would actuate that prompt's default instead of talking to the agent." >&2
    printf '%s\n' "  Look:   agentmux read $name --lines 12" >&2
    printf '%s\n' "  Answer: agentmux key $name Escape     (or Down/Enter as appropriate)" >&2
    printf '%s\n' "  Override if you are sure: agentmux send $name --force <text>" >&2
    return 1
  fi
  # The newline test must use $'\n'. "$(printf '\n')" collapses to the empty
  # string (command substitution strips trailing newlines), so it matches every
  # prompt and would wrap single-line sends in paste markers as well.
  if [ "${text#*$'\n'}" != "$text" ]; then
    # multi-line: bracketed paste, else each newline submits the prompt early
    tm send-keys -t "$pane" -l -- "${ESC}[200~${text}${ESC}[201~"
  else
    tm send-keys -t "$pane" -l -- "$text"
  fi
  sleep 0.4
  tm send-keys -t "$pane" Enter
}

# Forward tmux key names with NO text and NO implicit Enter. This is the only
# safe way to answer a modal: cmd_send always appends Enter, which actuates
# whatever the child CLI has focused. Permission-bypass flags remove approval
# prompts but not first-run or account-level modals, so this stays necessary.
#   agentmux key rev Escape
#   agentmux key rev Down Down Enter
cmd_key() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "key needs a name"
  need "$name"
  [ $# -gt 0 ] || die "key needs at least one tmux key name (Enter, Escape, Down, C-c, ...)"

  # Validate before sending. tmux send-keys treats an unrecognised key NAME as
  # literal text and still exits 0, so a typo silently types itself into the
  # agent and submits: `key rev Dowm Enter` would enter the word "Dowm". That is
  # the same silent-success failure this verb exists to avoid, so reject
  # anything not recognisably a key name rather than pass it through.
  local k
  for k in "$@"; do
    case "$k" in
      Enter|Escape|Tab|BTab|Space|BSpace|Backspace|Up|Down|Left|Right) ;;
      Home|End|PageUp|PageDown|PPage|NPage|Insert|IC|Delete|DC) ;;
      F1|F2|F3|F4|F5|F6|F7|F8|F9|F10|F11|F12) ;;
      [CMS]-[!-~]|[CMS]-[CMS]-[!-~]) ;;                   # C-c, M-x, C-M-a
      [CMS]-Enter|[CMS]-Tab|[CMS]-Up|[CMS]-Down|[CMS]-Left|[CMS]-Right) ;;
      *) die "not a recognised tmux key name: '$k'
       (valid: Enter Escape Tab BTab Space BSpace Up Down Left Right Home End
        PageUp PageDown Insert Delete F1-F12, or a modifier form like C-c, M-x)
       To type literal TEXT, use 'send' instead - but note send appends Enter." ;;
    esac
  done

  local pane
  pane="$(pane_of "$name")"
  [ -n "$pane" ] || die "cannot resolve pane for '$name'"
  # `--` so a key name can never be parsed as a send-keys option.
  tm send-keys -t "$pane" -- "$@" || die "send-keys failed for keys: $*"
  printf "sent keys to '%s': %s\n" "$name" "$*"
}

cmd_read() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "read needs a name"
  need "$name"
  local lines=""
  while [ $# -gt 0 ]; do
    case "$1" in --lines|-n) lines="${2:-}"; shift 2 ;; *) shift ;; esac
  done
  local out
  out="$(tm capture-pane -p -J -t "$(pane_of "$name")" | strip_ansi | sed 's/[[:space:]]*$//' | trim_edges)"
  if [ -n "$lines" ]; then
    printf '%s\n' "$out" | tail -n "$lines"
  else
    printf '%s\n' "$out"
  fi
}

cmd_tail() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "tail needs a name"
  local lines=200
  while [ $# -gt 0 ]; do
    case "$1" in --lines|-n) lines="${2:-200}"; shift 2 ;; *) shift ;; esac
  done
  [ -f "$LOGDIR/$name.log" ] || die "no log for '$name'"
  strip_ansi < "$LOGDIR/$name.log" | tail -n "$lines"
}

cmd_wait() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "wait needs a name"
  need "$name"
  local timeout="$TIMEOUT_S" quiet_ms="$QUIET_MS"
  while [ $# -gt 0 ]; do
    case "$1" in
      --timeout|-t) timeout="${2:-$TIMEOUT_S}"; shift 2 ;;
      --quiet|-q)   quiet_ms=$(( ${2:-5} * 1000 )); shift 2 ;;
      *) shift ;;
    esac
  done
  local last="" stable=0 elapsed=0 cur
  local deadline_ms=$(( timeout * 1000 ))
  local sleep_s
  sleep_s="$(awk -v m="$POLL_MS" 'BEGIN{printf "%.3f", m/1000}')"
  while :; do
    have "$name" || { printf "agent '%s' exited\n" "$name" >&2; return 3; }
    cur="$(pane_hash "$name")"
    if [ "$cur" = "$last" ]; then
      stable=$(( stable + POLL_MS ))
    else
      stable=0; last="$cur"
    fi
    if [ "$stable" -ge "$quiet_ms" ]; then
      printf 'idle after %ss\n' "$(( elapsed / 1000 ))" >&2
      return 0
    fi
    if [ "$elapsed" -ge "$deadline_ms" ]; then
      printf 'timeout after %ss (agent still busy)\n' "$timeout" >&2
      return 2
    fi
    sleep "$sleep_s"
    elapsed=$(( elapsed + POLL_MS ))
  done
}

cmd_ask() {
  local name="${1:-}"; shift || true
  [ -n "$name" ] || die "ask needs a name"
  need "$name"
  local timeout="$TIMEOUT_S" quiet_s=$(( QUIET_MS / 1000 ))
  local -a words=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --timeout|-t) timeout="${2:-$TIMEOUT_S}"; shift 2 ;;
      --quiet|-q)   quiet_s="${2:-5}"; shift 2 ;;
      *) words+=("$1"); shift ;;
    esac
  done
  local text="${words[*]}"
  [ -n "$text" ] || die "ask needs text"
  cmd_send "$name" "$text"
  sleep 1
  cmd_wait "$name" --timeout "$timeout" --quiet "$quiet_s"
  local rc=$?
  printf -- '----- %s -----\n' "$name"
  cmd_read "$name"
  return "$rc"
}

# Append a message to THIS agent's outbox, ~/.agentmux/queue/<sender>.jsonl.
#
# The queue existed long before anything wrote to it from an agent: the dashboard
# rendered it and dashboard/seed_queue.py was the only producer. This is the verb an
# agent actually calls, and `agentmux courier` is what delivers the result.
#
# The sender is $AGENTMUX_AGENT, exported into every spawned pane. Outside a pane
# there is no such variable, so it falls back to 'orchestrator' - which is exactly
# what the Claude Code session driving all this is.
#
# Written through python3 rather than printf because a body is arbitrary agent text:
# newlines, quotes and backslashes all have to survive into one JSON line intact,
# and hand-rolling that escaping in shell is how a queue file gets corrupted.
cmd_post() {
  local recipient="${1:-}"; shift || true
  [ -n "$recipient" ] || die "post needs a recipient: agentmux post <name> [--kind K] <text...>"
  local kind="status" ref="" sender="${AGENTMUX_AGENT:-orchestrator}"
  local -a words=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --kind) kind="${2:-}"; shift 2 ;;
      --ref)  ref="${2:-}";  shift 2 ;;
      --from) sender="${2:-}"; shift 2 ;;
      *) words+=("$1"); shift ;;
    esac
  done
  local text="${words[*]}"
  [ -n "$text" ] || die "post needs a message body"
  case "$kind" in
    plan|request|reply|status|finding|error) ;;
    *) die "kind must be one of: plan request reply status finding error (got '$kind')" ;;
  esac

  python3 - "$ROOT" "$sender" "$recipient" "$kind" "$ref" "$text" <<'PY' || return 1
import json, os, pathlib, re, sys, time

root, sender, recipient, kind, ref, body = sys.argv[1:7]
name = re.compile(r"[A-Za-z0-9_.-]{1,64}")
for label, value in (("sender", sender), ("recipient", recipient)):
    if not name.fullmatch(value):
        sys.exit(f"agentmux: {label} '{value}' is not a valid agent name")

queue = pathlib.Path(root) / "queue"
queue.mkdir(parents=True, exist_ok=True)
path = queue / f"{sender}.jsonl"
# Refuse a link rather than write through one: the outbox is read back by the
# dashboard and the courier, so a symlinked or hardlinked queue file is a way to
# get agent-authored text appended to something else entirely.
if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
    sys.exit(f"agentmux: {path} is a link - refusing to write to it")

record = {
    "at": time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z"),
    "sender": sender, "recipient": recipient, "kind": kind,
    "body": body[:65536], "ref": ref[:256] or None,
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
os.chmod(path, 0o600)
print(f"posted {kind} to {recipient}")
PY
}

# The delivery half. Runs taskmgmt/courier.py, which tails every outbox and hands
# each addressed message to its recipient with `agentmux send`.
#
# `start` detaches deliberately. The Bedrock gateway is a foreground process that
# nothing supervises and that does not survive a reboot, which has cost a session's
# first ten minutes more than once; a background courier with a pidfile at least
# survives the shell that launched it.
cmd_courier() {
  local repo="${AGENTMUX_REPO:-}"
  [ -n "$repo" ] || die "AGENTMUX_REPO is unset; cannot find taskmgmt/courier.py"
  local script="$repo/taskmgmt/courier.py"
  [ -f "$script" ] || die "not found: $script"
  local action="${1:-status}"; shift || true
  case "$action" in
    start)
      mkdir -p "$ROOT/courier"
      if python3 "$script" --status 2>/dev/null | grep -q '^courier:   running'; then
        printf 'courier is already running\n'; return 0
      fi
      # Created and locked down BEFORE nohup writes to it: the courier's output
      # carries message bodies, and a shell redirect would otherwise make the file
      # 0644 while every other piece of courier state is 0600.
      : >> "$ROOT/courier/courier.out"
      chmod 600 "$ROOT/courier/courier.out"
      nohup python3 "$script" --watch "$@" >> "$ROOT/courier/courier.out" 2>&1 &
      disown 2>/dev/null || true
      sleep 1
      python3 "$script" --status | head -1
      ;;
    stop)   python3 "$script" --stop ;;
    status) python3 "$script" --status ;;
    once)   python3 "$script" --once "$@" ;;
    watch)  python3 "$script" --watch "$@" ;;
    *) die "courier: unknown action '$action' (start|stop|status|once|watch)" ;;
  esac
}

# The permission mode the PANE is actually in, or empty if it cannot be told.
#
# WHY THIS EXISTS: run/<name>.perms records what spawn CONFIGURED, which is not the
# same thing as what the agent ended up in. Measured 2026-09-22: a claude agent
# spawned with bypassPermissions answered its startup dialogs and settled in `auto
# mode`, while `list` went on reporting UNRESTRICTED. Reporting an agent as less
# restricted than it is would be the dangerous direction; reporting it as more
# restricted is merely wrong, and either way a listing that cannot be trusted is worse
# than one that admits it does not know.
#
# Every CLI prints its mode in the pane footer, so read it from there.
observed_perms() {
  local name="$1" footer
  footer="$(tm capture-pane -p -t "$name" 2>/dev/null | strip_ansi | grep -v '^[[:space:]]*$' | tail -6)"
  case "$footer" in
    *"bypass permissions on"*)  printf 'bypass' ;;
    *"auto mode on"*)           printf 'auto' ;;
    *"plan mode on"*)           printf 'plan' ;;
    *"accept edits on"*)        printf 'acceptEdits' ;;
    *"always-approve"*)         printf 'always-approve' ;;
    *"YOLO"*|*"yolo"*)          printf 'yolo' ;;
    *) printf '' ;;
  esac
}

# Mention orphaned sidecars without acting on them. `list` is a read, so it says
# what is there and names the verb; `reap` is what removes anything.
report_stale() {
  local n; n="$(stale_count)"
  [ "$n" = 0 ] && return 0
  printf '\n%s stale sidecar set(s) for agents with no live session - `agentmux reap` removes them\n' "$n"
}

cmd_list() {
  if ! tm list-sessions >/dev/null 2>&1; then
    echo "no agents running"; report_stale; return 0
  fi
  printf '%-14s %-12s %-9s %-14s %-10s %-18s %s\n' NAME CLI STATE PERMS TASK AUTH CWD
  # Process substitution rather than a pipe: a piped `while read` runs in a subshell,
  # so $mismatch would be discarded the moment the loop ended and the note below would
  # never print.
  local mismatch=""
  while read -r n; do
    cli="$(cat "$RUNDIR/$n.cli" 2>/dev/null || echo '?')"
    cwd="$(cat "$RUNDIR/$n.cwd" 2>/dev/null || echo '?')"
    perms="$(cat "$RUNDIR/$n.perms" 2>/dev/null || echo '?')"
    task="$(cat "$RUNDIR/$n.task" 2>/dev/null || echo '-')"
    # Prefer what the pane says over what spawn intended. A '*' marks a value that
    # was configured but could not be confirmed from the pane, so the column never
    # silently presents an assumption as an observation.
    actual="$(observed_perms "$n")"
    if [ -n "$actual" ]; then
      case "$perms:$actual" in
        UNRESTRICTED:bypass|UNRESTRICTED:yolo|UNRESTRICTED:always-approve) ;;
        *) mismatch="$mismatch $n=$actual" ;;
      esac
      perms="$actual"
    else
      perms="$perms*"
    fi
    # An auth method id, never a credential. '-' means the CLI's own built-in
    # default, i.e. an existing OAuth login that agentmux does not manage.
    auth="$(cat "$RUNDIR/$n.auth" 2>/dev/null || echo '-')"
    # A passthrough --cli string can be arbitrarily long; truncate so a long one
    # cannot wreck the alignment of every other row.
    [ "${#cli}" -gt 12 ] && cli="${cli:0:11}+"
    if [ "$(tm list-clients -t "=$n" 2>/dev/null | wc -l)" -gt 0 ]; then
      st="attached"
    else
      st="detached"
    fi
    printf '%-14s %-12s %-9s %-14s %-10s %-18s %s\n' "$n" "$cli" "$st" "$perms" "$task" "$auth" "$cwd"
  done < <(tm list-sessions -F '#{session_name}' 2>/dev/null)

  # Say it plainly when the pane disagrees with what spawn configured, rather than
  # leaving the operator to notice a column they have read a hundred times.
  if [ -n "$mismatch" ]; then
    printf '\nPERMS differs from what spawn configured:%s\n' "$mismatch"
    printf '  the pane is the authority here; a startup dialog can change the mode.\n'
  fi
  printf '%s' "" # keep the function's output tidy when nothing follows
  report_stale
}

# Stop the courier once the last agent is gone.
#
# The mirror of the autostart in `spawn`. Without it the courier outlives every
# agent and polls an empty queue every few seconds until the next reboot - which is
# how it behaved when first written, and it is exactly the kind of orphan this
# session spent its time removing from run/. Started with the first agent, stopped
# with the last.
stop_courier_if_idle() {
  [ "${AGENTMUX_NO_COURIER:-0}" = "1" ] && return 0
  [ -n "${AGENTMUX_REPO:-}" ] && [ -f "$AGENTMUX_REPO/taskmgmt/courier.py" ] || return 0
  # Any session still up means somebody may still be messaging.
  tm list-sessions >/dev/null 2>&1 && return 0
  python3 "$AGENTMUX_REPO/taskmgmt/courier.py" --status 2>/dev/null \
    | grep -q '^courier:   running' || return 0
  python3 "$AGENTMUX_REPO/taskmgmt/courier.py" --stop >/dev/null 2>&1 \
    && printf 'courier stopped (no agents left)\n'
}

cmd_kill() {
  local target="${1:-}"
  [ -n "$target" ] || die "kill needs a name or --all"
  if [ "$target" = "--all" ]; then
    if tm kill-server 2>/dev/null; then echo "killed all agents"; else echo "no agents running"; fi
    stop_courier_if_idle
    return 0
  fi
  need "$target"

  # Close out Jira BEFORE the session dies: the transition comment and the
  # Confluence report are both built from this agent's pane log, and the log is
  # only meaningful while the sidecars still exist. Both calls are best-effort -
  # task_try swallows failures so a Jira outage cannot stop a kill.
  local bound; bound="$(cat "$RUNDIR/$target.task" 2>/dev/null || true)"
  if [ -n "$bound" ] && task_cli >/dev/null; then
    task_try done "$bound" --from-log "$target"
    task_try report "$target" --title "agentmux run - $target - $bound"
    # Mark it handled so the dashboard reaper does not post a second time.
    printf '%s\n' "killed-by-cli" > "$RUNDIR/$target.reported" 2>/dev/null || true
  fi

  tm kill-session -t "=$target" && printf "killed '%s'\n" "$target"
  rm -f "$RUNDIR/$target".* 2>/dev/null
  stop_courier_if_idle
}

# All names that have sidecars under run/, live or not.
sidecar_names() {
  ls "$RUNDIR" 2>/dev/null \
    | sed -n 's/\.\(cli\|cwd\|perms\|task\|auth\|pane\|launch\|started\|reported\)$//p' \
    | sort -u
}

# How many of those have no live tmux session. Used by `list` to nudge.
stale_count() {
  local name n=0
  while read -r name; do
    [ -n "$name" ] || continue
    have "$name" || n=$((n + 1))
  done <<EOF
$(sidecar_names)
EOF
  printf '%s' "$n"
}

# Remove run/ sidecars whose tmux session no longer exists.
#
# WHY THIS EXISTS: `kill` removes an agent's sidecars, but a reboot takes the whole
# tmux server without going through `kill`, and nothing else ever cleans up.
# Measured 2026-09-22: 45 files for seven agents from a session days earlier. The
# dashboard is honest about them - it labels each `stale`, dims the pane and opens no
# stream - but they never go away, and /api/agents keeps counting them, which is what
# made four smoke.sh stream checks fail against an empty /api/stream-all.
#
# Deletion is deliberately an explicit verb rather than a side effect of listing or
# of a GET. A read that quietly removes state is how you lose the one sidecar that
# would have explained an incident.
cmd_reap() {
  local dry=0
  case "${1:-}" in
    --dry-run|-n) dry=1 ;;
    "") ;;
    *) die "reap takes --dry-run or nothing (got '$1')" ;;
  esac

  # If tmux itself is missing, a failed has-session is indistinguishable from a dead
  # session, and guessing in that direction deletes state. Refuse instead.
  command -v tmux >/dev/null 2>&1 \
    || die "tmux not found - cannot tell a dead session from a broken query; refusing to reap"

  local name bound found=0 reaped=0
  while read -r name; do
    [ -n "$name" ] || continue
    if have "$name"; then continue; fi
    found=$((found + 1))
    local files; files="$(ls "$RUNDIR/$name".* 2>/dev/null | wc -l)"
    if [ "$dry" = 1 ]; then
      printf 'would reap %-14s (%s file(s))\n' "$name" "$files"
      continue
    fi

    # Same close-out as `kill`, for the same reason: an orphan is a dead agent, and
    # its Jira issue should not stay open because the tmux server went away rather
    # than the operator typing `kill`. Best-effort - task_try swallows failures.
    bound="$(cat "$RUNDIR/$name.task" 2>/dev/null || true)"
    if [ -n "$bound" ] && [ ! -f "$RUNDIR/$name.reported" ] && task_cli >/dev/null; then
      task_try done "$bound" --from-log "$name"
      task_try report "$name" --title "agentmux run - $name - $bound"
    fi

    rm -f "$RUNDIR/$name".* 2>/dev/null
    reaped=$((reaped + 1))
    printf 'reaped %-14s (%s file(s))\n' "$name" "$files"
  done <<EOF
$(sidecar_names)
EOF

  if [ "$found" = 0 ]; then
    echo "no stale sidecars"
  elif [ "$dry" = 1 ]; then
    printf '%s stale agent(s); run `agentmux reap` to remove them\n' "$found"
  else
    printf '%s stale agent(s) reaped. Logs under %s are untouched.\n' "$reaped" "$LOGDIR"
  fi
}

cmd_attach() {
  local name="${1:-}"
  [ -n "$name" ] || die "attach needs a name"
  need "$name"
  printf 'wsl -d Ubuntu -- tmux -L %s attach -t %s\n' "$SOCKET" "$name"
  echo "(detach with Ctrl-b d)"
}

cmd_exec() {
  local cwd="$PWD" model=""
  local -a words=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --cwd)      cwd="${2:-}";   shift 2 ;;
      --model|-m) model="${2:-}"; shift 2 ;;
      *) words+=("$1"); shift ;;
    esac
  done
  local text="${words[*]}"
  [ -n "$text" ] || die "exec needs a prompt"
  cwd="$(to_wsl_path "$cwd")"
  [ -d "$cwd" ] || die "not a directory: $cwd"
  export PATH="$(node_bin):$PATH"
  # Same unrestricted default as cmd_spawn, via the same config-carried profile.
  local bypass=""
  [ "${AGENTMUX_NO_BYPASS:-0}" != "1" ] && bypass="--profile yolo"
  # stdin is redirected from /dev/null: codex exec inherits stdin otherwise, so
  # when called from inside a heredoc it swallows the rest of the caller's
  # script as prompt text and never runs it (audit D32).
  if [ -n "$model" ]; then
    ( cd "$cwd" && codex exec ${bypass:+$bypass} -m "$model" "$text" < /dev/null )
  else
    ( cd "$cwd" && codex exec ${bypass:+$bypass} "$text" < /dev/null )
  fi
}

case "${1:-}" in
  spawn)  shift; cmd_spawn  "$@" ;;
  send)   shift; cmd_send   "$@" ;;
  key)    shift; cmd_key    "$@" ;;
  read)   shift; cmd_read   "$@" ;;
  tail)   shift; cmd_tail   "$@" ;;
  wait)   shift; cmd_wait   "$@" ;;
  ask)    shift; cmd_ask    "$@" ;;
  post)   shift; cmd_post   "$@" ;;
  courier) shift; cmd_courier "$@" ;;
  list)   shift; cmd_list   "$@" ;;
  kill)   shift; cmd_kill   "$@" ;;
  reap)   shift; cmd_reap   "$@" ;;
  attach) shift; cmd_attach "$@" ;;
  exec)   shift; cmd_exec   "$@" ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command '$1' (try: agentmux help)" ;;
esac
