/* dispose() completeness, proved rather than asserted in a comment.
 *
 * A leaking WebGL scene does not throw. It makes the machine a little slower
 * every time the operator switches views, and on a panel PC that sits on a line
 * for weeks the symptom arrives as "the dashboard has gone funny" three days
 * later, with nothing in any log. The only defence that survives maintenance is
 * one where allocation and teardown cannot drift apart — which is why every
 * geometry, material, texture, observer and teardown step in this package goes
 * through the ledger, and why this file drives a full build/rebuild/dispose
 * cycle with fakes and asserts the ledger ends empty.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createLedger, trackMaterial } from '../src/resources.ts';

/** A stand-in for a three.js geometry/material/texture: it records disposal. */
function fake(name) {
  const record = { name, disposeCalls: 0, dispose: null };
  record.dispose = () => { record.disposeCalls += 1; };
  return record;
}

test('every tracked object is disposed exactly once and the ledger empties', () => {
  const ledger = createLedger('t');
  const objects = ['geometry', 'material', 'texture', 'ring', 'line'].map(fake);
  for (const object of objects) {
    assert.equal(ledger.track(object, object.name), object, 'track returns its argument');
  }
  assert.equal(ledger.size(), objects.length);

  const report = ledger.disposeAll();
  assert.equal(report.disposed, objects.length);
  assert.equal(report.failed.length, 0);
  for (const object of objects) {
    assert.equal(object.disposeCalls, 1, `${object.name} was disposed ${object.disposeCalls} times`);
  }
  assert.equal(ledger.size(), 0);
  assert.deepEqual(ledger.outstanding(), []);
  assert.equal(ledger.disposed(), true);
});

test('disposal runs in reverse creation order', () => {
  const ledger = createLedger('t');
  const order = [];
  for (const name of ['first', 'second', 'third']) {
    ledger.track({ dispose: () => order.push(name) }, name);
  }
  ledger.disposeAll();
  assert.deepEqual(order, ['third', 'second', 'first'], 'a thing disposes before what it was built on');
});

test('a second disposeAll is a no-op, not a double free', () => {
  const ledger = createLedger('t');
  const object = fake('geometry');
  ledger.track(object);
  ledger.disposeAll();
  const again = ledger.disposeAll();
  assert.equal(object.disposeCalls, 1);
  assert.deepEqual(again, { disposed: 0, released: 0, failed: [], children: 0 });
});

test('one driver throwing does not strand the other forty behind it', () => {
  const ledger = createLedger('t');
  const before = fake('before');
  const after = fake('after');
  ledger.track(before, 'before');
  ledger.track({ dispose: () => { throw new Error('driver reset'); } }, 'exploding');
  ledger.track(after, 'after');

  const report = ledger.disposeAll();
  assert.equal(before.disposeCalls, 1);
  assert.equal(after.disposeCalls, 1);
  assert.equal(report.disposed, 2);
  assert.equal(report.failed.length, 1);
  assert.equal(report.failed[0].label, 'exploding');
  assert.equal(ledger.size(), 0, 'a failure must not leave the ledger holding a reference');
});

test('objects with no dispose are released, not counted as disposed', () => {
  const ledger = createLedger('t');
  ledger.track({ isLight: true }, 'ambient-light');
  ledger.track(null, 'nothing');
  const report = ledger.disposeAll();
  assert.equal(report.released, 2);
  assert.equal(report.disposed, 0);
});

test('deferred teardown steps run, in reverse, and are counted', () => {
  const ledger = createLedger('t');
  const order = [];
  ledger.defer(() => order.push('observer'), 'resize-observer');
  ledger.defer(() => order.push('renderer'), 'renderer');
  ledger.defer(() => { throw new Error('gone'); }, 'broken');
  const report = ledger.disposeAll();
  assert.deepEqual(order, ['renderer', 'observer']);
  assert.equal(report.disposed, 2);
  assert.equal(report.failed[0].label, 'broken');
});

test('a child scope is disposed by its parent, so dispose cannot miss one', () => {
  const root = createLedger('root');
  const child = root.child('build');
  const grandchild = child.child('labels');
  const objects = [fake('root-geo'), fake('build-geo'), fake('label-tex')];
  root.track(objects[0]);
  child.track(objects[1]);
  grandchild.track(objects[2]);

  assert.equal(root.size(), 3);
  assert.equal(root.outstanding().length, 3);

  const report = root.disposeAll();
  assert.equal(report.children, 2);
  for (const object of objects) assert.equal(object.disposeCalls, 1);
  assert.equal(root.size(), 0);
  assert.equal(child.disposed(), true);
  assert.equal(grandchild.disposed(), true);
});

test('tracking after disposal disposes on the spot instead of leaking quietly', () => {
  const ledger = createLedger('t');
  ledger.disposeAll();
  const late = fake('late');
  assert.equal(ledger.track(late, 'late'), late, 'the caller\'s expression still evaluates');
  assert.equal(late.disposeCalls, 1, 'an object tracked into a dead scope is freed immediately');
  assert.equal(ledger.size(), 0);

  const order = [];
  ledger.defer(() => order.push('ran'));
  assert.deepEqual(order, ['ran']);
});

test('trackMaterial finds the textures hanging off a material', () => {
  const ledger = createLedger('t');
  const map = fake('canvas-texture');
  const normal = fake('normal-map');
  const material = fake('sprite-material');
  material.map = map;
  material.normalMap = normal;
  material.color = { r: 1 };          // not a texture; must not be tracked
  material.userData = { note: 'hi' };

  trackMaterial(ledger, material, 'label');
  assert.equal(ledger.size(), 3, 'the material and both of its maps');

  ledger.disposeAll();
  assert.equal(map.disposeCalls, 1, 'a texture nothing else references would have leaked');
  assert.equal(normal.disposeCalls, 1);
  assert.equal(material.disposeCalls, 1);
});

test('a rebuild frees the previous tree and leaves the shared objects alone', () => {
  /* The setData() shape: a root scope for the renderer and the shared
   * geometry, a build scope replaced wholesale on every new device tree. This
   * is the cycle that actually leaks in production, because the 2D panel
   * re-polls every four seconds and the 3D one follows it. */
  const root = createLedger('topology');
  const shared = [fake('node-geometry'), fake('node-edges'), fake('node-material')];
  for (const object of shared) root.track(object, object.name);

  let build = createLedger('build');
  root.defer(() => build.disposeAll(), 'build-scope');

  const generations = [];
  for (let generation = 0; generation < 5; generation += 1) {
    build.disposeAll();
    build = createLedger('build');
    const made = [];
    for (let i = 0; i < 12; i += 1) made.push(build.track(fake(`gen${generation}-${i}`)));
    generations.push(made);

    // Everything from every previous generation is already gone...
    for (const older of generations.slice(0, -1)) {
      for (const object of older) {
        assert.equal(object.disposeCalls, 1, `${object.name} survived a rebuild`);
      }
    }
    // ...and nothing shared was touched by a rebuild.
    for (const object of shared) assert.equal(object.disposeCalls, 0);
  }

  root.disposeAll();
  for (const object of [...shared, ...generations.flat()]) {
    assert.equal(object.disposeCalls, 1, `${object.name} was not disposed exactly once`);
  }
  assert.equal(root.size(), 0);
  assert.equal(build.size(), 0);
  assert.deepEqual(root.outstanding(), [], 'nothing survives dispose()');
});
