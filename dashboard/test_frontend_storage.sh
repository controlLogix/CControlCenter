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
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  storage_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$storage_node_dir" ] || export PATH="$storage_node_dir:$PATH"
fi
[ -f dashboard/index.html ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');

const html = fs.readFileSync('dashboard/index.html', 'utf8');
const start = html.indexOf('// ONE-TIME KEY MIGRATION');
assert.ok(start > 0, 'the migration block is missing from index.html');
const end = html.indexOf('})();', start);
assert.ok(end > start, 'the migration block is not closed');
const source = html.slice(start, end + 5);

// It must come before the scripts that read these keys. app.js is loaded last, so
// the block belongs in the inline head script, ahead of every <script src>.
const firstSrc = html.indexOf('<script src=');
assert.ok(start < firstSrc,
  'the migration must precede every external script, or netscan.js and runs.js read first');

const KEYS = ['authOpen', 'boardFree', 'boardPlacements.v1', 'feed.v1', 'importedThemes',
              'netscan.v1', 'panePlacement', 'queueSeenAt', 'runs.v1', 'tab.v1',
              'theme', 'view'];

function makeStorage(initial) {
  const map = new Map(Object.entries(initial));
  return { map,
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: k => map.delete(k) };
}
const run = storage => vm.runInNewContext(source, { localStorage: storage });

let passed = 0;
function ok(name) { console.log('  ok    ' + name); passed++; }

// Every key the app actually uses must be in the migration list, or its state is
// silently dropped. This is the assertion that catches a 13th key added later.
for (const key of KEYS) {
  assert.ok(source.includes(`'${key}'`), `the migration does not carry ${key}`);
}
ok('every remembered key is carried by the migration');

let s = makeStorage({
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
ok('operator state is carried across and the old keys are cleared');

// The theme VALUE is not a key. Renaming cc-dark resets every operator's theme
// even after a correct key migration, so it must survive verbatim.
assert.equal(s.getItem('agentmux.theme'), 'cc-dark');
ok('the stored theme value cc-dark is preserved verbatim');

const before = JSON.stringify([...s.map.entries()].sort());
run(s);
assert.equal(JSON.stringify([...s.map.entries()].sort()), before);
ok('running the migration twice is a no-op');

s = makeStorage({ 'ccc.theme': 'stale', 'agentmux.theme': 'current' });
run(s);
assert.equal(s.getItem('agentmux.theme'), 'current');
assert.equal(s.getItem('ccc.theme'), null);
ok('a value already under the new name is never clobbered by a stale one');

s = makeStorage({});
run(s);
assert.equal(s.map.size, 0);
ok('a fresh browser stores nothing');

// Private mode throws on access. Losing a remembered layout is a far smaller
// problem than a page that will not boot.
run({ getItem() { throw new Error('SecurityError'); },
      setItem() { throw new Error('SecurityError'); },
      removeItem() { throw new Error('SecurityError'); } });
ok('storage that throws does not break boot');

console.log(`passed ${passed}, failed 0`);
JS
