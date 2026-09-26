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

echo '--- no async wrapper restores a stale scroll offset ---'
# keepScroll() snapshotted scroll before a view loader and restored it after. The
# loaders are async, so on a cold load the restore fired 3.3 SECONDS after the click,
# by which time the operator had scrolled deliberately - and it threw that away.
# Caught with a stack: restoreScroll <- keepScroll <- showView, from 149 to 0.
# It was also built on a misdiagnosis: the pre-fix build held its scroll under three
# observed re-renders, so it never fixed anything.
# Comment lines are stripped first: the explanation of why keepScroll was removed
# names it, and a guard that matches its own documentation is a guard that always
# fires. Strip `//` lines and look at the code that is left.
if sed 's|^[[:space:]]*//.*$||' "$APP" | grep -q 'keepScroll('; then
  bad 'keepScroll is back: an async restore will overwrite deliberate scrolling'
else
  ok 'no async scroll-restore wrapper around the view loaders'
fi
if grep -q 'requestAnimationFrame(() => requestAnimationFrame(() => {' "$APP"; then
  ok 'the view restore waits two frames for layout'
else
  bad 'the view restore runs before the grid has been measured'
fi

echo '--- the scroll container is not zoomed, and the board has no dead space ---'
# zoom on an overflow:auto element keeps scrollTop in the element's own zoomed
# coordinate space, so offsets come back fractional (measured 2029.4166259765625) and
# scrollHeight, clientHeight and the thumb are each rounded from a different
# intermediate. Zoom the CONTENT and leave the scrolling box at scale 1.
if grep -qE '^\.view\.pad \{ zoom: 1; \}' dashboard/style.css; then
  ok 'the scrolling box is explicitly unzoomed'
else
  bad 'zoom is still on .view.pad, the element that scrolls'
fi
if grep -qE '^\.view\.pad > \* \{ zoom: var\(--ui-scale\); \}' dashboard/style.css; then
  ok 'and the scale is applied to its content instead'
else
  bad 'nothing applies --ui-scale to the view content'
fi
# align-content alone leaves align-items at stretch, so every card grows to the height
# of the tallest in its row. Measured 150px of empty grid inside a 752px list - real
# scroll extent with nothing in it, so the thumb stops matching what you can read.
if awk '/^\.board \{/,/^\}/' dashboard/style.css | grep -q 'align-items: start'; then
  ok 'board cards are their natural height, so the scroll extent is real content'
else
  bad 'board cards stretch to row height and pad the grid with dead scroll extent'
fi

echo '--- app.js still parses ---'
# THIS BRANCH USED TO PASS WITHOUT CHECKING ANYTHING. When node was absent it printed
# a note and called neither ok nor bad, so the suite reported "failed 0" while the
# only JavaScript parse check in it never ran - a green gate on a check that did not
# happen, which is the failure mode this repo keeps deciding it will not ship.
#
# So: find node the way the other suites do, and if it still is not there say SKIP at
# column zero, which run_tests.sh greps for and surfaces. Absent stays visible instead
# of counting as a pass.
if ! command -v node >/dev/null 2>&1; then
  node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$node_dir" ] || export PATH="$node_dir:$PATH"
fi
if command -v node >/dev/null 2>&1; then
  if node --check "$APP" 2>/dev/null; then ok 'node --check passes'; else bad 'app.js is not valid JavaScript'; fi
else
  echo 'SKIP node not found (nvm not installed?); app.js was NOT parse-checked'
fi

finish
