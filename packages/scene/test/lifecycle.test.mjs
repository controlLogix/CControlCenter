/* The loop that is usually not running, and the listeners that all come off.
 *
 * Two promises are tested here because both are invisible when broken:
 *
 *   A hidden tab draws nothing. Browsers throttle background rAF but do not
 *   stop it, and a throttled WebGL scene still holds a hot GPU context. These
 *   machines sit on a line for weeks; design/field.js pauses its shader for
 *   exactly this reason and a topology costs far more per frame than a
 *   gradient.
 *
 *   dispose() removes every listener. One survivor keeps the whole closure —
 *   scene, renderer, device tree — alive after a view switch, and nothing in
 *   the product will ever say so.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { createLifecycle } from '../src/lifecycle.ts';

/** A frame clock under test control: nothing runs until pump() is called. */
function harness({ hidden = false, maxFps = 45 } = {}) {
  const queue = [];
  let clock = 0;
  const listeners = [];

  const target = {
    added: 0,
    addEventListener(type, handler, options) {
      this.added += 1;
      listeners.push({ target: this, type, handler, options, live: true });
    },
    removeEventListener(type, handler, options) {
      const entry = listeners.find(
        (l) => l.target === this && l.type === type && l.handler === handler && l.live,
      );
      if (entry) entry.live = false;
    },
  };

  const doc = {
    hidden,
    addEventListener(type, handler, options) {
      listeners.push({ target: doc, type, handler, options, live: true });
    },
    removeEventListener(type, handler, options) {
      const entry = listeners.find(
        (l) => l.target === doc && l.type === type && l.handler === handler && l.live,
      );
      if (entry) entry.live = false;
    },
    fire(type) {
      for (const l of listeners) if (l.target === doc && l.type === type && l.live) l.handler({});
    },
  };

  const life = createLifecycle({
    doc,
    win: {},
    maxFps,
    now: () => clock,
    requestFrame: (cb) => {
      queue.push(cb);
      return queue.length;   // a non-zero handle, as rAF returns
    },
    cancelFrame: (handle) => { queue[handle - 1] = null; },
  });

  return {
    life,
    doc,
    target,
    listeners,
    advance(ms) { clock += ms; },
    get clock() { return clock; },
    /** Run whatever is queued, once. */
    pump() {
      const pending = queue.splice(0, queue.length);
      let ran = 0;
      for (const cb of pending) {
        if (typeof cb === 'function') { cb(clock); ran += 1; }
      }
      return ran;
    },
    pending() { return queue.filter(Boolean).length; },
    liveListeners() { return listeners.filter((l) => l.live).length; },
  };
}

test('nothing renders until something asks for a frame', () => {
  const h = harness();
  let renders = 0;
  h.life.start(() => { renders += 1; });
  assert.equal(h.pending(), 1, 'start banks the first paint');
  h.pump();
  assert.equal(renders, 1);

  // And then it stops. A still topology has no reason to burn a frame.
  h.advance(1000);
  assert.equal(h.pending(), 0);
  assert.equal(h.pump(), 0);
  assert.equal(renders, 1, 'the loop must not free-run');
});

test('invalidate buys exactly one frame, however many times it is called', () => {
  const h = harness();
  let renders = 0;
  h.life.start(() => { renders += 1; });
  h.pump();

  h.advance(100);
  for (let i = 0; i < 10; i += 1) h.life.invalidate();
  assert.equal(h.pending(), 1, 'ten invalidations are still one frame');
  h.pump();
  assert.equal(renders, 2);
});

test('a render that returns true keeps the loop going, and only while it does', () => {
  const h = harness();
  let renders = 0;
  let moving = true;
  h.life.start(() => { renders += 1; return moving; });

  for (let i = 0; i < 4; i += 1) { h.advance(100); h.pump(); }
  assert.equal(renders, 4, 'a camera move animates');

  moving = false;
  h.advance(100);
  h.pump();
  assert.equal(renders, 5);
  h.advance(100);
  assert.equal(h.pending(), 0, 'the move finished, so the loop stopped');
});

test('below the frame budget the work is deferred, not dropped', () => {
  const h = harness({ maxFps: 50 });   // a 20ms budget
  let renders = 0;
  h.life.start(() => { renders += 1; });
  h.pump();
  assert.equal(renders, 1);

  h.advance(5);
  h.life.invalidate();
  h.pump();
  assert.equal(renders, 1, 'too soon: this frame was not drawn');
  assert.equal(h.life.stats().deferred, 1);
  assert.equal(h.pending(), 1, 'but it was rescheduled rather than thrown away');

  h.advance(20);
  h.pump();
  assert.equal(renders, 2, 'the deferred work still happened');
});

test('a hidden tab stops the loop and cancels the frame already queued', () => {
  const h = harness();
  let renders = 0;
  h.life.start(() => { renders += 1; });
  h.pump();
  assert.equal(renders, 1);

  h.advance(100);
  h.life.invalidate();
  assert.equal(h.pending(), 1);

  h.doc.hidden = true;
  h.doc.fire('visibilitychange');
  assert.equal(h.life.isPaused(), true);
  assert.equal(h.pending(), 0, 'the queued frame was cancelled, not left to fire');

  // And nothing can talk it into one while it is hidden.
  for (let i = 0; i < 5; i += 1) { h.advance(100); h.life.invalidate(); }
  assert.equal(h.pending(), 0);
  assert.equal(h.pump(), 0);
  assert.equal(renders, 1, 'a background tab drew a frame');
});

test('coming back draws once, and is not charged for the time it was away', () => {
  const h = harness();
  let seen = [];
  h.life.start((now) => { seen.push(now); });
  h.pump();

  h.doc.hidden = true;
  h.doc.fire('visibilitychange');
  h.advance(3 * 3600 * 1000);          // three hours in the background
  h.doc.hidden = false;
  h.doc.fire('visibilitychange');

  assert.equal(h.life.isPaused(), false);
  assert.equal(h.pending(), 1);
  h.pump();
  assert.equal(seen.length, 2, 'exactly one catch-up frame, not one per hour');
  assert.equal(h.life.stats().pauses, 1);
});

test('a scene started in a hidden tab does not start running', () => {
  const h = harness({ hidden: true });
  let renders = 0;
  h.life.start(() => { renders += 1; });
  assert.equal(h.life.isPaused(), true);
  assert.equal(h.pending(), 0);
  assert.equal(renders, 0);
});

test('a frame that fires after the tab hid still draws nothing', () => {
  const h = harness();
  let renders = 0;
  h.life.start(() => { renders += 1; });
  h.pump();
  h.advance(100);
  h.life.invalidate();
  // The tab goes away without a visibilitychange reaching us first — the
  // race the second guard inside frame() exists for.
  h.doc.hidden = true;
  h.pump();
  assert.equal(renders, 1);
});

test('a render that throws does not take the loop with it', () => {
  const h = harness();
  let calls = 0;
  h.life.start(() => { calls += 1; throw new Error('driver'); });
  h.pump();
  assert.equal(calls, 1);
  h.advance(100);
  h.life.invalidate();
  h.pump();
  assert.equal(calls, 2, 'the loop survived to be told to stop by its owner');
});

test('dispose removes every listener it added, including its own', () => {
  const h = harness();
  const handlers = [() => {}, () => {}, () => {}];
  h.life.on(h.target, 'pointermove', handlers[0]);
  h.life.on(h.target, 'wheel', handlers[1], { passive: false });
  h.life.on(h.target, 'keydown', handlers[2]);

  assert.equal(h.life.listenerCount(), 4, 'three plus the visibilitychange it registers itself');
  assert.equal(h.liveListeners(), 4);

  h.life.dispose();
  assert.equal(h.liveListeners(), 0, 'one survivor keeps the whole scene alive');
  assert.equal(h.life.listenerCount(), 0);
  assert.equal(h.life.isDisposed(), true);
});

test('dispose cancels the pending frame and refuses to schedule another', () => {
  const h = harness();
  let renders = 0;
  h.life.start(() => { renders += 1; });
  assert.equal(h.pending(), 1);

  h.life.dispose();
  assert.equal(h.pending(), 0);

  h.life.invalidate();
  h.life.start(() => { renders += 1; });
  h.life.on(h.target, 'pointermove', () => {});
  assert.equal(h.pending(), 0);
  assert.equal(h.pump(), 0);
  assert.equal(renders, 0);
  assert.equal(h.life.listenerCount(), 0, 'a listener added after dispose would never come off');
});

test('a listener is removed with the options it was added with', () => {
  const h = harness();
  const handler = () => {};
  const options = { passive: false };
  h.life.on(h.target, 'wheel', handler, options);
  const entry = h.listeners.find((l) => l.type === 'wheel');
  assert.equal(entry.options, options);
  h.life.dispose();
  assert.equal(entry.live, false);
});

test('a removeEventListener that throws does not strand the listeners behind it', () => {
  const h = harness();
  const hostile = {
    addEventListener() {},
    removeEventListener() { throw new Error('detached'); },
  };
  h.life.on(hostile, 'pointermove', () => {});
  h.life.on(h.target, 'keydown', () => {});
  h.life.dispose();
  assert.equal(h.liveListeners(), 0);
});

test('dispose twice is harmless', () => {
  const h = harness();
  h.life.start(() => {});
  h.life.dispose();
  h.life.dispose();
  assert.equal(h.life.isDisposed(), true);
});
