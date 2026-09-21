#!/usr/bin/env bash
# Print a column ruler into each shell agent, so clipping and legibility can be
# MEASURED rather than eyeballed. Run from the repo root inside WSL:
#   bash <(tr -d '\r' < dashboard/seed_ruler.sh)
#
# The ruler makes three things checkable at a glance and from a test:
#   - column 1 is visible at all (left edge not cut off)
#   - the 10-column tick marks are distinguishable (text is legible, not mush)
#   - the END marker at column ~100 is either on screen or reachable by scrolling
set -u
[ -f agentmux.sh ] || { echo 'run from the agentmux repo root' >&2; exit 2; }
AM="$HOME/.local/bin/agentmux"

# Built here rather than inline in the send, so no quoting has to survive two shells.
script='/tmp/agentmux-ruler.sh'
cat > "$script" <<'RULER'
clear
printf '%s\n' "----+----1----+----2----+----3----+----4----+----5----+----6----+----7----+----8----+----9----+---100"
printf '%s\n' "COL1 the quick brown fox jumps over the lazy dog 0123456789 ABCDEFGHIJKLMNOP END-OF-LINE-AT-100"
printf '%s\n' "wide: $(printf 'x%.0s' $(seq 1 150)) <-- column 157, past a 100-col pane"
for i in $(seq 1 8); do printf 'line %02d  filler text to give the pane some height and something to read\n' "$i"; done
RULER
chmod 600 "$script"

for agent in "$@"; do
  "$AM" send "$agent" "bash $script" >/dev/null 2>&1 || { echo "  $agent: send failed"; continue; }
  sleep 0.3
  "$AM" key "$agent" Enter >/dev/null 2>&1
  echo "  $agent: ruler sent"
done
sleep 2
for agent in "$@"; do
  echo "--- $agent ---"
  "$AM" read "$agent" 2>&1 | grep -c 'END-OF-LINE-AT-100' | sed 's/^/  END marker lines: /'
done
