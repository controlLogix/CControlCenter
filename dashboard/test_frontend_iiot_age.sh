#!/usr/bin/env bash
# TM-025: the age on a tag row must not be computed across two clocks.
#
#   bash <(tr -d '\r' < dashboard/test_frontend_iiot_age.sh)
#
# WHAT THIS PROTECTS. iiot.js:11-14 says a number on screen with no age next to
# it is the most dangerous thing this panel can display. An age that is WRONG is
# worse, because it still looks authoritative - and until 2026-09-25 every age
# here was computed as "Date.now() / 1000 - tag.last_good", which subtracts the
# BROWSER's clock from the SERVER's. Those agree only by luck. WSL2 drifts
# against its Windows host after sleep, and Phase 6 puts a phone on the tailnet.
#
# The verdict now comes from the server - modbus_poll.py sends "stale" and
# "age_ms" - and the only thing the browser adds is monotonic elapsed time since
# the snapshot arrived. So a browser clock that is ten minutes out changes
# nothing on screen, which is what these checks assert: by running the REAL
# render path out of iiot.js under a faked clock, not by grepping for it.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  age_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$age_node_dir" ] || export PATH="$age_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_frontend_iiot_age: node is not on PATH, no clock-skew checks ran'
  echo 'passed 0, failed 0'
  exit 0
fi
[ -f dashboard/iiot.js ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const iiot = fs.readFileSync('dashboard/iiot.js', 'utf8');

let passed = 0, failed = 0;
async function check(name, fn) {
  try { await fn(); console.log('  ok    ' + name); passed++; }
  catch (err) { console.log('  FAIL  ' + name + ' - ' + err.message); failed++; }
}

// A DOM stub just deep enough to run the real render.
function harness() {
  const makeNode = (tag) => ({
    tag, children: [], dataset: {}, className: '', textContent: '', value: '', rows: 0,
    placeholder: '', style: {setProperty() {}}, classList: {add() {}, remove() {}},
    appendChild(c) { this.children.push(c); return c; },
    append(...c) { this.children.push(...c); },
    replaceChildren(...c) { this.children = c; },
    addEventListener() {}, setAttribute() {}, removeAttribute() {},
  });
  const root = makeNode('div');

  // Both clocks are ours to move. `wall` is the browser's epoch - the one that
  // can be wrong. `mono` is performance.now() - the one that cannot go backwards.
  const clock = {wall: 1750000000000, mono: 5000};
  let snapshot = null, offline = false;
  const ctx = {
    document: {
      // Only the Modbus panel. The PROFINET IIFE below it gets null and returns.
      getElementById: (id) => (id === 'modbusHint' ? root : null),
      createElement: makeNode,
    },
    window: {
      addEventListener(name, fn) { if (name === 'agentmux:ready') this._ready = fn; },
    },
    performance: {now: () => clock.mono},
    Date: new Proxy(Date, {get: (t, k) => (k === 'now' ? () => clock.wall : t[k])}),
    setTimeout: () => {},
    fetch: async () => {
      if (offline) throw new Error('fetch failed');
      return {ok: true, status: 200, json: async () => snapshot};
    },
  };
  ctx.window.window = ctx.window;
  ctx.window.AGENTMUX = {registerCard: (id, fn) => { ctx._refresh = fn; }};
  vm.runInNewContext(iiot, ctx);
  ctx.window._ready();
  assert.ok(ctx._refresh, 'iiot.js registered no refresh callback');

  return {
    clock,
    serve(s) { snapshot = s; },
    goOffline() { offline = true; },
    async refresh() { await ctx._refresh(); },
    // What the operator actually sees.
    read() {
      const rows = root.children.find(c => c.className === 'tag-rows');
      const state = root.children.find(c => c.className === 'field-state');
      return {
        status: state.textContent,
        rows: rows.children.map(r => ({
          name: r.children[0].textContent,
          value: r.children[1].textContent,
          chip: r.children[2].textContent,
          age: r.children[3].textContent,
          stale: r.dataset.stale,
        })),
      };
    },
  };
}

// A snapshot exactly as modbus_poll.py builds one. `last_good` is in the
// SERVER's epoch and is deliberately nowhere near the browser's above.
const SERVER_EPOCH = 1600000000;
const snap = (over) => Object.assign({
  connected: true, error: null,
  config: {host: '10.0.0.5', port: 502, interval: 2, tags: []},
  tags: [
    {name: 'Pressure', unit: 1, address: 0, value: 12.3, engineering_unit: 'bar',
     last_good: SERVER_EPOCH, stale: false, age_ms: 400},
    {name: 'Temp', unit: 1, address: 2, value: 64.1, engineering_unit: 'C',
     last_good: SERVER_EPOCH - 90, stale: true, age_ms: 90000},
  ],
}, over || {});

(async () => {

await check('a ten-minute browser clock skew changes no verdict and no age', async () => {
  const honestRun = harness();
  honestRun.serve(snap());
  await honestRun.refresh();
  const honest = honestRun.read();

  // Same server snapshot, same monotonic clock - only the browser's wall clock
  // is ten minutes out, the way WSL2 drifts against its host after a sleep.
  const skewed = harness();
  skewed.clock.wall += 10 * 60 * 1000;
  skewed.serve(snap());
  await skewed.refresh();

  assert.deepEqual(skewed.read(), honest,
    'a browser clock ten minutes out changed what the panel says');
  // A live feed carrying one old value: the old tag greys, the fresh one does
  // not, and the banner says which. The browser's clock decided none of it.
  assert.equal(honest.rows[0].chip, 'live');
  assert.equal(honest.rows[1].chip, 'STALE');
  assert.match(honest.status, /^CONNECTED/);
});

await check('one stale tag greys one chip, not the whole table', async () => {
  // The bug this replaces: `connected` ANDed in `tags.every(t => !t.stale)`, so
  // a single old value reported the feed as DISCONNECTED and greyed every chip.
  // Forty chips greying at once is one connectivity fact rendered forty times,
  // and it teaches the operator that the chips do not mean anything.
  const h = harness();
  h.serve(snap());
  await h.refresh();
  const view = h.read();
  assert.deepEqual(view.rows.map(r => r.chip), ['live', 'STALE'],
    'a stale tag changed the verdict on a fresh one');
  assert.deepEqual(view.rows.map(r => r.stale), ['false', 'true']);
  // And the banner carries the feed-level fact, once, where it belongs.
  assert.equal(view.status, 'CONNECTED — 1 of 2 tags stale');
});

await check('a fresh feed still reads live under the same ten-minute skew', async () => {
  // The inverse, and the one the old code got wrong the other way: every tag
  // fresh by the SERVER's reckoning must stay live no matter what hour the
  // browser thinks it is. `Date.now() / 1000 - last_good` made this fail.
  const fresh = () => snap({tags: [
    {name: 'Pressure', unit: 1, address: 0, value: 12.3, engineering_unit: 'bar',
     last_good: SERVER_EPOCH, stale: false, age_ms: 400}]});

  const honestRun = harness();
  honestRun.serve(fresh());
  await honestRun.refresh();
  const honest = honestRun.read();
  assert.equal(honest.rows[0].chip, 'live');
  assert.match(honest.status, /^CONNECTED/);

  const skewed = harness();
  skewed.clock.wall += 10 * 60 * 1000;
  skewed.serve(fresh());
  await skewed.refresh();
  assert.deepEqual(skewed.read(), honest,
    'a browser ten minutes fast reported a fresh feed differently');
});

await check('the age is the age the server measured, not a re-read of its epoch', async () => {
  const h = harness();
  // last_good is an hour before the server epoch; age_ms says five seconds.
  // Anything deriving the age from last_good would print an hour.
  h.serve(snap({tags: [{name: 'P', unit: 1, address: 0, value: 1, engineering_unit: '',
                        last_good: SERVER_EPOCH - 3600, stale: false, age_ms: 5000}]}));
  await h.refresh();
  assert.equal(h.read().rows[0].age, '5s ago',
    'the row did not render the age the server measured');
});

await check('a tag never read says so, rather than rendering as an age', async () => {
  const h = harness();
  h.serve(snap({connected: false, tags: [
    {name: 'Unread', unit: 1, address: 9, value: null, engineering_unit: '',
     last_good: null, stale: true, age_ms: null}]}));
  await h.refresh();
  const row = h.read().rows[0];
  // A blank or a zero here reads as "just now", the opposite of the truth.
  assert.equal(row.age, 'never read', 'a never-read tag did not say so');
  assert.equal(row.value, '—', 'a never-read tag rendered a value');
  assert.equal(row.stale, 'true');
});

await check('when the poll stops answering the age keeps growing, on the monotonic clock', async () => {
  // This is the case the monotonic term exists for. A SUCCESSFUL poll re-bases
  // it every second, so it only shows when the server stops answering - which
  // is exactly when a frozen age would be most dangerous: the last value stays
  // on screen looking as recent as it did a minute ago.
  const h = harness();
  h.serve(snap({tags: [{name: 'P', unit: 1, address: 0, value: 1, engineering_unit: '',
                        last_good: SERVER_EPOCH, stale: false, age_ms: 1000}]}));
  await h.refresh();
  assert.equal(h.read().rows[0].age, '1s ago');

  // The feed dies, and an NTP correction lands mid-session: the wall clock goes
  // BACKWARDS thirty seconds while thirty real seconds pass. An age built on
  // Date.now() would go backwards too, or freeze.
  h.goOffline();
  h.clock.mono += 30000;
  h.clock.wall -= 30000;
  await h.refresh();
  const view = h.read();
  assert.equal(view.rows[0].age, '31s ago', 'the age did not follow the monotonic clock');
  // A dead feed DOES say something about every tag: those verdicts were the
  // server's, computed at a moment that has passed, and they get less true
  // every second. A chip reading "live" off a reading nobody has confirmed
  // since the link dropped is the lie iiot.js:11-14 is about.
  assert.equal(view.rows[0].chip, 'STALE', 'a dead feed still read as live');
  assert.match(view.status, /^NO UPDATE/,
    'the banner did not say which link was the problem');
});

await check('a page that has stopped hearing says so, rather than blaming the device', async () => {
  // Three different faults used to print the same word. "The dashboard cannot
  // reach the PLC" and "this browser tab has not heard from the dashboard" send
  // somebody to opposite ends of the building.
  const h = harness();
  h.serve(snap({tags: [{name: 'P', unit: 1, address: 0, value: 1, engineering_unit: '',
                        last_good: SERVER_EPOCH, stale: false, age_ms: 100}]}));
  await h.refresh();
  assert.match(h.read().status, /^CONNECTED/);

  // The snapshot ages past one poll interval without a new one arriving. Both
  // clocks move together, because this comparison is browser-to-browser.
  h.clock.wall += 30000;
  h.clock.mono += 30000;
  h.goOffline();
  await h.refresh();
  const view = h.read();
  assert.match(view.status, /^NO UPDATE/,
    'a page that stopped hearing reported it as a device fault');
  assert.match(view.status, /cannot reach the dashboard/,
    'the banner does not say WHICH link is down');
  assert.match(view.status, /30s/, 'the banner does not say how long it has been');
  // And the device is not blamed for it: nothing here claims the PLC is at fault.
  assert.ok(!/^DISCONNECTED/.test(view.status));
});

await check('nothing in the panel subtracts a browser clock from a server one', async () => {
  // The comments in there now WARN against this, so strip them: a test that
  // cannot tell an implementation from a comment about it asserts nothing.
  const code = iiot.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  const crossed = code.match(/Date\.now\(\)\s*\/\s*1000/g) || [];
  assert.equal(crossed.length, 0,
    crossed.length + ' place(s) still convert the browser clock to the server epoch');
  assert.match(code, /age_ms/, 'the panel no longer reads the age the server sends');
  assert.match(code, /performance\.now\(\)/,
    'elapsed time is not measured on the monotonic clock');
});

console.log('passed ' + passed + ', failed ' + failed);
process.exit(failed ? 1 : 0);
})();
JS
