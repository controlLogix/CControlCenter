#!/usr/bin/env bash
# Frontend regressions that cost the operator real time.
#   bash <(tr -d '\r' < dashboard/test_frontend.sh)
#
# WHAT THESE ARE, HONESTLY: shape assertions over app.js, not behavioural tests. The
# real verification was done in a browser and is recorded below so a future reader
# knows what these are protecting and can redo it. A grep cannot catch a reintroduction
# written differently - but it does catch the exact line coming back, which is the
# common way a fix is lost (a revert, a merge, a copy-paste from an older branch).
#
# THE BUG THEY GUARD. syncAgents() ran `els.grid.appendChild(rec.cell)` for every pane
# on every tick. appendChild on a node ALREADY in the document does not copy it - it
# DETACHES and re-inserts it, and a detached element loses the scroll offset of
# everything inside it. tick() runs at POLL_MS = 3000.
#
# Measured in Chrome via Playwright, 3 agents, 15 seconds:
#
#            build          grid childList mutations     xterm viewport scroll
#     pre-fix (HEAD)        15 removed / 15 re-inserted      11 -> 0
#     fixed                  0 removed /  0 re-inserted      11 -> 11
#
# 3 panes x 5 ticks = 15. That is the "I scroll down and after a bit it resets to the
# top" report, and it is also why `follow` looked unreliable: a pane pinned to the
# bottom was re-attached at zero a moment later.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
# shellcheck source=/dev/null
. dashboard/testlib.sh

APP=dashboard/app.js
[ -f "$APP" ] || { echo "missing $APP" >&2; exit 2; }

echo '--- the grid is not rebuilt on every poll ---'
# The pre-fix line, verbatim. Its absence is the regression guard.
if grep -qE 'if \(rec\) els\.grid\.appendChild\(rec\.cell\);' "$APP"; then
  bad 'syncAgents re-appends every cell unconditionally - scroll dies every 3s'
else
  ok 'no unconditional per-tick re-append'
fi
if grep -q 'orderMatches' "$APP"; then
  ok 'the reorder is guarded by an order comparison'
else
  bad 'nothing compares the desired order against the DOM before reordering'
fi

echo '--- follow pins the element that actually scrolls ---'
# There are two scroll contexts per pane and they are mutually exclusive: xterm's own
# viewport when the pane fits, and the HOST element once updateOverflowState sets
# `.scrolls` because the pane is too big to fit at the legibility floor. The old code
# only ever called term.scrollToBottom(), which is a no-op in the second case - i.e.
# follow did nothing in exactly the case big enough to need it.
if grep -q 'function followPane' "$APP"; then
  ok 'followPane exists'
else
  bad 'no followPane: follow only ever addressed one of the two scroll contexts'
fi
if grep -qE 'host\.scrollTop = host\.scrollHeight' "$APP"; then
  ok 'and it pins the host, not just the xterm viewport'
else
  bad 'followPane never touches the host scroll offset'
fi
if grep -qE "els\.follow\.addEventListener\('change'" "$APP"; then
  ok 'ticking the checkbox acts immediately, not at the next frame of output'
else
  bad 'follow only reacts to output, so it looks dead on an idle agent'
fi

echo '--- a view remembers where it was left ---'
# Setting `hidden` takes an element out of layout and the browser drops its scrollTop.
# The views that never poll (journal, board, tickets, iiot) have no other way to lose
# their position, so this is the whole of their half of the report.
if grep -q 'viewScroll' "$APP"; then
  ok 'showView records and restores per-view scroll'
else
  bad 'switching views and returning lands at the top'
fi
if grep -qE 'requestAnimationFrame\(\(\) => \{[[:space:]]*$' "$APP" && grep -q 'entering.scrollTop' "$APP"; then
  ok 'and restores after layout, not while the element is still display:none'
else
  bad 'the restore does not wait for layout; assigning scrollTop now clamps to 0'
fi

echo '--- app.js still parses ---'
if command -v node >/dev/null 2>&1; then
  if node --check "$APP" 2>/dev/null; then ok 'node --check passes'; else bad 'app.js is not valid JavaScript'; fi
else
  echo '  (node not on PATH; run under bash -ic for nvm to parse-check app.js)'
fi

finish
