#!/usr/bin/env bash
# The localStorage key migration, run against the REAL block in index.html.
#
# WHAT THIS PROTECTS. The 12 remembered-state keys were renamed ccc.* -> agentmux.*
# during the rebrand. These are persisted OPERATOR data - theme, board layout,
# collapse state, current view - so a plain find-and-replace wipes them on the next
# load, with no error, no console message, and nothing to roll back to. The operator
# just finds their board rearranged and their theme reset.
#
# WHY IT READS index.html RATHER THAN A COPY. A copy of the migration in this file
# would drift from the one that ships, and then this suite would be asserting about
# code nobody runs. It extracts the block and executes it against a fake storage.
#
# WHY THE BLOCK LIVES IN THE INLINE HEAD SCRIPT. app.js is the LAST script on the
# page (index.html:556, after netscan.js and runs.js), so a migration there would not
# provably run before those modules read their own keys. The inline script is first
# by construction.
#
# WHY EACH CHECK IS INDIVIDUALLY CAUGHT rather than left to throw. A missing
# migration block must FAIL every property cleanly, not crash the suite - a crashed
# suite is not proof it can discriminate, and check_test_failability.sh refuses it
# as such (see its summary/exit cross-check).
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  storage_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$storage_node_dir" ] || export PATH="$storage_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_frontend_storage: node is not on PATH, no migration checks ran'
  echo 'passed 0, failed 0'
  exit 0
fi
[ -f dashboard/index.html ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');

const KEYS = ['authOpen', 'boardFree', 'boardPlacements.v1', 'feed.v1', 'importedThemes',
              'netscan.v1', 'panePlacement', 'queueSeenAt', 'runs.v1', 'tab.v1',
              'theme', 'view'];

const html = fs.readFileSync('dashboard/index.html', 'utf8');
const start = html.indexOf('// ONE-TIME KEY MIGRATION');
const end = start >= 0 ? html.indexOf('})();', start) : -1;
const source = (start >= 0 && end > start) ? html.slice(start, end + 5) : null;
const firstSrc = html.indexOf('<script src=');

let passed = 0, failed = 0;
function check(name, fn) {
  try {
    if (source === null) throw Error('the migration block is missing from index.html');
    fn();
    console.log('  ok    ' + name);
    passed++;
  } catch (err) {
    // Two leading spaces: the shape testlib uses and check_test_failability.sh counts.
    console.log('  FAIL  ' + name + ' - ' + err.message);
    failed++;
  }
}

function makeStorage(initial) {
  const map = new Map(Object.entries(initial));
  return { map,
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: k => map.delete(k) };
}
const run = storage => vm.runInNewContext(source, { localStorage: storage });

check('the migration precedes every external script', () => {
  assert.ok(firstSrc > 0, 'no <script src= found in index.html');
  assert.ok(start < firstSrc,
    'the migration must precede every external script, or netscan.js and runs.js read first');
});

check('every remembered key is carried by the migration', () => {
  for (const key of KEYS) {
    assert.ok(source.includes(`'${key}'`), `the migration does not carry ${key}`);
  }
});

check('operator state is carried across and the old keys are cleared', () => {
  const s = makeStorage({
    'ccc.theme': 'cc-dark',
    'ccc.view': 'terminals',
    'ccc.boardPlacements.v1': '{"TM-1":[10,20]}',
    'ccc.tab.v1': 'journal',
  });
  run(s);
  assert.equal(s.getItem('agentmux.theme'), 'cc-dark');
  assert.equal(s.getItem('agentmux.view'), 'terminals');
  assert.equal(s.getItem('agentmux.boardPlacements.v1'), '{"TM-1":[10,20]}');
  assert.equal(s.getItem('agentmux.tab.v1'), 'journal');
  assert.equal(s.getItem('ccc.theme'), null);
});

check('the stored theme value cc-dark is preserved verbatim', () => {
  // The theme VALUE is not a key. Renaming cc-dark resets every operator's theme
  // even after a correct key migration.
  const s = makeStorage({ 'ccc.theme': 'cc-dark' });
  run(s);
  assert.equal(s.getItem('agentmux.theme'), 'cc-dark');
});

check('running the migration twice is a no-op', () => {
  const s = makeStorage({ 'ccc.theme': 'cc-dark', 'ccc.view': 'terminals' });
  run(s);
  const before = JSON.stringify([...s.map.entries()].sort());
  run(s);
  assert.equal(JSON.stringify([...s.map.entries()].sort()), before);
});

check('a value already under the new name is never clobbered by a stale one', () => {
  const s = makeStorage({ 'ccc.theme': 'stale', 'agentmux.theme': 'current' });
  run(s);
  assert.equal(s.getItem('agentmux.theme'), 'current');
  assert.equal(s.getItem('ccc.theme'), null);
});

check('a fresh browser stores nothing', () => {
  const s = makeStorage({});
  run(s);
  assert.equal(s.map.size, 0);
});

check('storage that throws does not break boot', () => {
  // Private mode throws on access. Losing a remembered layout is a far smaller
  // problem than a page that will not boot.
  run({ getItem() { throw new Error('SecurityError'); },
        setItem() { throw new Error('SecurityError'); },
        removeItem() { throw new Error('SecurityError'); } });
});

console.log(`passed ${passed}, failed ${failed}`);
process.exit(failed ? 1 : 0);
JS
