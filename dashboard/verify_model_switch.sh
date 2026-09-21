#!/usr/bin/env bash
# Prove the model chosen in Settings is the model a newly spawned agent actually uses.
#   bash <(tr -d '\r' < dashboard/verify_model_switch.sh) [agent-name]
#
# End to end on purpose: reads the stored setting, spawns, then checks the recorded launch
# line AND what codex itself prints. A stored value that never reaches the process is the
# failure mode this guards.
set -u
NAME="${1:-modeltest}"
AM="$HOME/.local/bin/agentmux"
[ -f agentmux.sh ] || { echo 'run from the agentmux repo root' >&2; exit 2; }

want="$(python3 -c '
import json, pathlib
path = pathlib.Path.home() / ".agentmux" / "auth.json"
print(json.loads(path.read_text(encoding="utf-8"))["methods"]["codex-custom"]["model"])
')"
echo "  model in ~/.agentmux/auth.json : $want"

"$AM" kill "$NAME" >/dev/null 2>&1
"$AM" spawn "$NAME" --cli codex --auth codex-custom --cwd "$PWD" 2>&1 | head -2 | sed 's/^/  /'
sleep 8

launch="$(cat "$HOME/.agentmux/run/$NAME.launch" 2>/dev/null || echo '(none)')"
echo "  recorded launch line          : $launch"

case "$launch" in
  *"-m $want"*) echo "  launch carries the chosen model: YES" ;;
  *)            echo "  launch carries the chosen model: NO  <-- the UI setting did not reach the process" ;;
esac

reported="$("$AM" read "$NAME" 2>&1 | grep -oFm1 "$want")"
echo "  codex reports model           : ${reported:-<not visible yet>}"
[ "$reported" = "$want" ] && echo "  MATCH" || echo "  MISMATCH (or the banner has scrolled)"
