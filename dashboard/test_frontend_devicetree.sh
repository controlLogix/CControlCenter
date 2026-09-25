#!/usr/bin/env bash
# The device tree panel: a guess and a statement must not render alike.
#
#   bash <(tr -d '\r' < dashboard/test_frontend_devicetree.sh)
#
# WHAT THIS PROTECTS. The Ethernet scanner answers "what is listening?" - a TCP
# connect and an OUI lookup, which is an INFERENCE. CIP ListIdentity answers
# "what are you?" - the device's own vendor, revision and serial, which is a
# STATEMENT. Rendering both with the same confidence is the same class of lie as
# an un-aged value on the tag table, and it is the failure this panel exists to
# prevent rather than a detail of how it looks.
#
# So these drive the REAL render out of devicetree.js against recorded data and
# assert on what comes out, not on the source.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  dt_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$dt_node_dir" ] || export PATH="$dt_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_frontend_devicetree: node is not on PATH, no panel checks ran'
  echo 'passed 0, failed 0'
  exit 0
fi
# The REPO ROOT check exits 2, because being in the wrong directory is not a
# test result. The SUBJECT being absent is - it must fail cleanly, with counts,
# or the failability gate cannot tell "this would have caught the regression"
# from "this file could not run at all". Both produce no assertions.
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
if [ ! -f dashboard/devicetree.js ]; then
  echo '  FAIL  dashboard/devicetree.js is missing, so none of this is guaranteed'
  echo 'passed 0, failed 1'
  exit 1
fi

node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const src = fs.readFileSync('dashboard/devicetree.js', 'utf8');

let passed = 0, failed = 0;
async function check(name, fn) {
  try { await fn(); console.log('  ok    ' + name); passed++; }
  catch (err) { console.log('  FAIL  ' + name + ' - ' + err.message); failed++; }
}

function harness(payload) {
  const made = [];
  const makeNode = (tag) => {
    const n = {
      tag, children: [], dataset: {}, className: '', textContent: '', title: '',
      disabled: false, hidden: false,
      appendChild(c) { this.children.push(c); return c; },
      append(...c) { this.children.push(...c); },
      replaceChildren(...c) { this.children = c; },
      addEventListener(name, fn) { (this.on ||= {})[name] = fn; },
      setAttribute() {},
      get lastChild() { return this.children[this.children.length - 1]; },
    };
    made.push(n);
    return n;
  };
  const root = makeNode('div');
  const ctx = {
    document: {
      getElementById: (id) => (id === 'devicePanel' ? root : null),
      createElement: makeNode,
    },
    window: { addEventListener(n, fn) { if (n === 'agentmux:ready') this._ready = fn; } },
    fetch: async (url) => ({
      ok: true, status: 200,
      json: async () => (url.includes('discover') ? {count: 1, at: 1} : payload),
    }),
    setTimeout: () => {},
  };
  ctx.window.window = ctx.window;
  ctx.window.AGENTMUX = { registerCard: (id, fn) => { ctx._refresh = fn; } };
  vm.runInNewContext(src, ctx);
  ctx.window._ready();
  return { root, made, refresh: () => ctx._refresh() };
}

// Every node whose textContent contains a string.
const textOf = (made) => made.map(n => String(n.textContent || '')).join('\n');
const find = (made, pred) => made.filter(pred);

const IDENTIFIED = {
  address: '10.0.0.5', sources: ['segment-scan', 'cip-listidentity'],
  hostname: 'plc-line1', mac: '00:00:bc:11:22:33',
  vendor: 'Rockwell Automation/Allen-Bradley',
  vendor_source: 'cip-listidentity (the device said so)',
  ports: [{port: 44818, service: 'ethernet-ip'}],
  identity: {product_name: '1756-L83E/B', revision: '32.11', serial: 'a1b2c3d4',
             device_type: 'Programmable Logic Controller'},
  endpoints: [], promoted: null, conflicts: [], suggested: ['ethernet-ip'],
};
const GUESSED = {
  address: '10.0.0.9', sources: ['segment-scan'], hostname: null, mac: '00:80:41:aa:bb:cc',
  vendor: 'Vemotec GmbH', vendor_source: 'segment-scan (OUI)',
  ports: [{port: 502, service: 'modbus'}],
  identity: null, endpoints: [], promoted: null, conflicts: [], suggested: ['modbus-tcp'],
};
const payload = (over) => Object.assign({
  groups: [{network: '10.0.0.0/24', devices: [IDENTIFIED, GUESSED], count: 2, self_reported: 1}],
  total: 2, conflicts: 0, scan: null, scan_state: 'done',
  discovery: {at: 1, error: null, available: true, count: 1},
}, over || {});

(async () => {

await check('a self-reported device and an inferred one are marked differently', async () => {
  const h = harness(payload());
  await h.refresh();
  const rows = find(h.made, n => n.className === 'device-row');
  assert.equal(rows.length, 2);
  // THE assertion this panel exists for.
  assert.equal(rows[0].dataset.selfReported, 'true',
    'a device that answered ListIdentity is not marked as self-reported');
  assert.equal(rows[1].dataset.selfReported, 'false',
    'a device known only from a port sweep is marked as though it identified itself');
});

await check('a vendor never appears without where it came from', async () => {
  const h = harness(payload());
  await h.refresh();
  const sources = find(h.made, n => n.className === 'kv-src').map(n => n.textContent);
  assert.equal(sources.length, 2, 'a vendor was rendered with no provenance beside it');
  assert.ok(sources.some(s => s.includes('the device said so')));
  assert.ok(sources.some(s => s.includes('OUI')));
});

await check('a device with no name says so rather than rendering blank', async () => {
  const h = harness(payload());
  await h.refresh();
  const names = find(h.made, n => n.className === 'device-name').map(n => n.textContent);
  assert.deepEqual(names, ['1756-L83E/B', 'unidentified']);
});

await check('the source chips explain the difference, not just name it', async () => {
  const h = harness(payload());
  await h.refresh();
  const chips = find(h.made, n => n.className === 'src-chip');
  const cip = chips.find(c => c.textContent === 'cip-listidentity');
  const scan = chips.find(c => c.textContent === 'segment-scan');
  assert.ok(/told you/i.test(cip.title), 'the CIP chip does not say the device spoke');
  assert.ok(/inference/i.test(scan.title), 'the scan chip does not say it is an inference');
});

await check('disagreement is shown, not resolved', async () => {
  const conflicted = Object.assign({}, IDENTIFIED, {conflicts: [{
    field: 'vendor',
    values: [{value: 'Rockwell Automation', source: 'segment-scan (OUI)'},
             {value: 'Rockwell Automation/Allen-Bradley', source: 'cip-listidentity'}],
  }]});
  const h = harness(payload({
    groups: [{network: '10.0.0.0/24', devices: [conflicted], count: 1, self_reported: 1}],
    total: 1, conflicts: 1}));
  await h.refresh();
  const warn = find(h.made, n => n.className === 'device-conflict');
  assert.equal(warn.length, 1, 'a disagreement was not rendered');
  const shown = find(h.made, n => n.className === 'conflict-value').map(n => n.textContent);
  // BOTH values, each with its source. Not one winner.
  assert.equal(shown.length, 2);
  assert.ok(shown.some(s => s.includes('Rockwell Automation —')));
  assert.ok(shown.some(s => s.includes('Allen-Bradley —')));
});

await check('nothing scanned yet and nothing found are different answers', async () => {
  // These used to look identical everywhere in this dashboard, and an empty
  // list with no explanation reads as the second when it is usually the first.
  const fresh = harness(payload({groups: [], total: 0, scan_state: 'idle',
                                 discovery: {at: null, error: null, available: null, count: 0}}));
  await fresh.refresh();
  const a = textOf(fresh.made);
  assert.ok(/Nothing has looked yet/.test(a), 'an unscanned segment claims nothing is there');

  const ran = harness(payload({groups: [], total: 0, scan_state: 'done',
                               discovery: {at: 1, error: null, available: true, count: 0}}));
  await ran.refresh();
  assert.ok(/Nothing answered/.test(textOf(ran.made)));
});

await check('CIP discovery being unavailable is stated, not silently empty', async () => {
  const h = harness(payload({discovery: {at: null, available: false,
                                         error: "ImportError: no module named 'pycomm3'", count: 0}}));
  await h.refresh();
  const state = find(h.made, n => n.className === 'field-state')[0];
  assert.ok(/unavailable/.test(state.textContent), 'a missing pycomm3 looks like a quiet zero');
  assert.ok(/pycomm3/.test(state.textContent), 'the reason is not carried');
});

await check('the group says how many identified themselves, not just how many answered', async () => {
  const h = harness(payload());
  await h.refresh();
  const count = find(h.made, n => n.className === 'group-count')[0];
  assert.match(count.textContent, /2 found/);
  assert.match(count.textContent, /1 identified themselves/);
});

console.log(`passed ${passed}, failed ${failed}`);
process.exit(failed ? 1 : 0);
})();
JS
