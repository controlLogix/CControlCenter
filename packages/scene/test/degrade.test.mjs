/* Degrading to nothing, silently — the behaviour a plant floor actually gets.
 *
 * Node has no WebGL and no document, which for once is the environment we want:
 * it is exactly what an Intel driver that will not give up a context looks like
 * from inside createTopology. The contract is that this is not an error. The
 * scene unwinds whatever it had built, the handle says `ok: false`, the reason
 * arrives as one word for the caller to branch on, and the operator sees the 2D
 * device tree that has always worked — no dialog, no toast, no console noise.
 *
 * Skipped rather than failed when three.js is not installed, so the rules in
 * origin.ts, conflict.ts and layout.ts can still be verified from a clone with
 * no node_modules.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

let createTopology = null;
let importError = null;
try {
  ({ createTopology } = await import('../src/topology.ts'));
} catch (err) {
  importError = err;
}

const skip = createTopology
  ? false
  : `three.js is not installed (${importError?.message ?? 'import failed'})`;

/** Just enough DOM for createTopology to get as far as the renderer. */
function fakeContainer() {
  const documentElement = {
    dataset: {},
    getAttribute: () => null,
  };
  const defaultView = {
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    devicePixelRatio: 1,
  };
  const ownerDocument = { documentElement, defaultView, createElement: () => null };
  return {
    clientWidth: 800,
    clientHeight: 600,
    ownerDocument,
    appended: [],
    appendChild(child) { this.appended.push(child); return child; },
    removeChild() {},
  };
}

test('no container at all is a quiet no', { skip }, () => {
  const reasons = [];
  for (const nothing of [null, undefined, {}, 7, 'div']) {
    const view = createTopology(nothing, { onUnavailable: (r) => reasons.push(r) });
    assert.equal(view.ok, false);
    assert.equal(view.element, null);
    assert.equal(view.layout(), null);
  }
  assert.deepEqual(reasons, Array(5).fill('no-container'));
});

test('no WebGL means fall back, not fail', { skip }, () => {
  const reasons = [];
  const view = createTopology(fakeContainer(), {
    onUnavailable: (reason) => reasons.push(reason),
  });
  assert.equal(view.ok, false, 'ok:false is how the caller knows to render the 2D tree');
  assert.equal(reasons.length, 1, 'said once');
  assert.ok(
    ['no-webgl', 'init-failed'].includes(reasons[0]),
    `expected a fallback reason, got ${reasons[0]}`,
  );
});

test('the inert handle is inert, not a trap', { skip }, () => {
  const view = createTopology(fakeContainer(), {});
  // A host that mounts, polls, focuses and unmounts must be able to do all of
  // it against a scene that never existed, without a single guard of its own.
  assert.doesNotThrow(() => {
    view.setData({ groups: [], total: 0, conflicts: 0 });
    view.setData(null);
    view.focus('10.0.0.1');
    view.focus(null, { instant: true });
    view.select('10.0.0.1');
    view.select(null);
    view.setLabel('10.0.0.1', '41.2 degC');
    view.resize();
    view.dispose();
    view.dispose();
  });
});

test('a callback that throws does not stop the caller falling back', { skip }, () => {
  assert.doesNotThrow(() => {
    const view = createTopology(null, {
      onUnavailable: () => { throw new Error('the host panicked'); },
    });
    assert.equal(view.ok, false);
  });
});

test('nothing is written to the console on the way down', { skip }, () => {
  const noise = [];
  const saved = {};
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    saved[level] = console[level];
    console[level] = (...args) => noise.push([level, ...args]);
  }
  try {
    const view = createTopology(fakeContainer(), {});
    view.setData({ groups: [], total: 0, conflicts: 0 });
    view.dispose();
  } finally {
    for (const level of Object.keys(saved)) console[level] = saved[level];
  }
  assert.deepEqual(
    noise,
    [],
    'this is a nicer way to look at data the operator can already read. A decorative '
    + 'layer that announces its own absence has the priority backwards.',
  );
});
