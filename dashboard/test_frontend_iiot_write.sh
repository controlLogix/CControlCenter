#!/usr/bin/env bash
# The gate in front of a write to physical equipment.
#
# WHAT THIS PROTECTS. iiot.js can write raw coils and registers to a live Modbus
# device. Until 2026-09-25 that was gated by window.confirm() - one OK click, on a
# dialog that blocks the page, cannot show what is being overwritten, and cannot
# be left open while you walk over and look at the panel. Nothing tested it at
# all, so the gate could have been deleted without a single suite noticing.
#
# The first three are shape assertions over the source, which is what the frontend
# suites here are (see test_frontend.sh's header). They catch the realistic
# regression: somebody re-adds a direct send, or swaps the card back for a dialog.
# The last is behavioural - it runs the real commit path out of blade.js.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  iiot_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$iiot_node_dir" ] || export PATH="$iiot_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_frontend_iiot_write: node is not on PATH, no write-gate checks ran'
  echo 'passed 0, failed 0'
  exit 0
fi
[ -f dashboard/iiot.js ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');

const iiot = fs.readFileSync('dashboard/iiot.js', 'utf8');
const blade = fs.readFileSync('dashboard/blade.js', 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); console.log('  ok    ' + name); passed++; }
  catch (err) { console.log('  FAIL  ' + name + ' - ' + err.message); failed++; }
}

check('the equipment write is raised as a confirmation card, not a dialog', () => {
  assert.match(iiot, /AGENTMUX_BLADE/,
    'iiot.js no longer raises a blade confirmation for its write');
  assert.match(iiot, /kind:\s*'industrial_write'/,
    'the card does not declare itself an industrial write');
});

check('the only browser dialog left announces that it is the weaker gate', () => {
  const dialogs = iiot.match(/window\.confirm\s*\(/g) || [];
  assert.equal(dialogs.length, 1,
    `expected exactly one window.confirm (the announced fallback), found ${dialogs.length}`);
  assert.match(iiot, /agent console is unavailable, so this is the weaker confirmation/,
    'the fallback dialog does not say it is weaker than the card it replaced');
});

check('the card carries what is being overwritten, and says when it could not read it', () => {
  assert.match(iiot, /rendering/, 'no before/after rendering is built');
  assert.match(iiot, /readBackAt/, 'the card does not record whether a value was read');
  // The honest case matters more than the happy one: an unmatched address must
  // produce a null before-value so the card can say so, rather than a blank that
  // reads as "zero".
  assert.match(iiot, /anyRead\s*\?\s*'as last polled'\s*:\s*null/,
    'readBackAt is not driven by whether anything was actually read');
});

check('the age shown is the server verdict, never browser-minus-server arithmetic', () => {
  // iiot.js:95 already computes staleness as Date.now()/1000 - last_good, which
  // subtracts a browser clock from a server clock. That bug must not be copied
  // into the confirmation, where the number decides whether someone overwrites a
  // live value.
  const confirmBlock = iiot.slice(iiot.indexOf('function confirmWrite'),
                                  iiot.indexOf('async function send'));
  // Strip comments first. The comment in there WARNS against Date.now(), and a
  // test that cannot tell an implementation from a comment about the
  // implementation is not asserting what it claims to.
  const code = confirmBlock.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  assert.ok(!/Date\.now\(\)/.test(code),
    'the confirmation computes an age from the browser clock');
  assert.match(confirmBlock, /tag\.stale/,
    "the confirmation does not use the server's own staleness verdict");
});

// ── behavioural: the real commit path out of blade.js ──────────────────────────
check('a write is not sent until the exact typed phrase is entered', () => {
  const nodes = [];
  const makeNode = () => {
    const n = {
      children: [], dataset: {}, style: { setProperty() {} }, classList: { add() {}, remove() {} },
      value: '', textContent: '', disabled: false, type: '', placeholder: '',
      appendChild(c) { this.children.push(c); return c; },
      replaceChildren(...c) { this.children = c; },
      addEventListener(name, fn) { (this.on ||= {})[name] = fn; },
      setAttribute() {}, removeAttribute() {}, reportValidity() {}, setCustomValidity() {},
      focus() {}, click() { this.on && this.on.click && this.on.click(); },
      getBoundingClientRect: () => ({ width: 0, right: 0 }),
    };
    nodes.push(n);
    return n;
  };
  const ctx = {
    window: {
      AGENTMUX: { el: (tag, cls, text) => { const n = makeNode(); n.tag = tag; n.textContent = text || ''; return n; } },
      // blade.js boots on agentmux:ready; without firing it, ui is empty and
      // confirm() dereferences undefined.
      addEventListener(name, fn) { if (name === 'agentmux:ready') this._ready = fn; },
      dispatchEvent() {},
    },
    document: { getElementById: () => makeNode(), createElement: () => makeNode() },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    setTimeout: () => {}, CustomEvent: function () {},
  };
  ctx.window.window = ctx.window;
  vm.runInNewContext(blade, ctx);
  ctx.window._ready();   // boot it, as the page would

  const api = ctx.window.AGENTMUX_BLADE;
  assert.ok(api && typeof api.confirm === 'function', 'blade exposes no confirm()');

  const outcomes = [];
  api.confirm({
    kind: 'industrial_write',
    action: { tool: 'modbus function 6',
              target: { system: 'modbus', device: 'plc:502', path: 'unit 1 @ 0' },
              after: '42' },
    rendering: [{ label: 'unit 1 address 0', before: '7', after: '42', changed: true }],
    readBackAt: 'as last polled',
    onDecide: (outcome) => outcomes.push(outcome),
  });

  // Nothing decided merely by raising it.
  assert.deepEqual(outcomes, [], 'raising a card already decided it');

  // The phrase is derived from the action, so it names the target AND the value.
  const phrases = nodes.filter(n => typeof n.textContent === 'string'
    && n.textContent.includes('plc:502:unit 1 @ 0=42'));
  assert.ok(phrases.length > 0,
    'the typed phrase is not derived from the target and the value');

  // A commit with the wrong phrase must not settle the card.
  const inputs = nodes.filter(n => n.tag === 'input');
  const commits = nodes.filter(n => n.textContent === 'commit');
  assert.ok(inputs.length && commits.length, 'no phrase input or commit button was rendered');
  inputs[0].value = 'yes';
  commits[0].click();
  assert.deepEqual(outcomes, [], 'a wrong phrase committed the write');

  // The exact phrase settles it.
  inputs[0].value = 'plc:502:unit 1 @ 0=42';
  commits[0].click();
  assert.deepEqual(outcomes, ['committed'], 'the exact phrase did not commit');
});

console.log(`passed ${passed}, failed ${failed}`);
process.exit(failed ? 1 : 0);
JS
