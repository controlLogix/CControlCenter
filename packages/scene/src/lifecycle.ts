/* The frame loop, and the three reasons it is usually not running.
 *
 * These machines sit on a production line for weeks. A WebGL scene spinning at
 * 60fps in a background tab for a fortnight is rude on a desktop and actively
 * expensive on a laptop, and nobody is looking at it. `design/field.js` already
 * pauses its shader on `document.hidden` for exactly this reason; the 3D view
 * has more to lose, because a topology scene costs far more per frame than a
 * fullscreen gradient.
 *
 * So there are three guards, and they compose:
 *
 *   1. RENDER ON DEMAND. A device topology is STILL. There is no orbit, no
 *      drift, no shimmer, nothing that is different in the next frame unless a
 *      person moved the camera or the data changed. So the default number of
 *      frames per second is zero. `invalidate()` buys exactly one frame; the
 *      render callback can return true to ask for another, which is how a
 *      camera move animates and the only way anything runs continuously.
 *   2. document.hidden STOPS THE LOOP. Not throttles: cancels the pending RAF
 *      and refuses to schedule another until the tab comes back. Browsers
 *      already throttle background RAF, but throttled is not stopped, and a
 *      throttled scene still holds the GPU context hot.
 *   3. A FRAME BUDGET. Below it, the frame is deferred rather than drawn, the
 *      same skip field.js does. On a plant-floor integrated GPU this is the
 *      difference between a view that is usable while dragging and one that is
 *      not.
 *
 * AND EVERY LISTENER IS WRITTEN DOWN. `on()` is the only way this package adds
 * one, so `dispose()` cannot miss one — the same argument as the ledger next
 * door. `lifecycle.test.mjs` drives all of it with fakes: no DOM, no GPU.
 */

export interface LifecycleHost {
  requestFrame?: (cb: (t: number) => void) => number;
  cancelFrame?: (handle: number) => void;
  now?: () => number;
  doc?: any;
  win?: any;
  /** Frames per second ceiling. Never a floor — see the header. */
  maxFps?: number;
}

export interface ListenerTarget {
  addEventListener: (type: string, handler: any, options?: any) => void;
  removeEventListener: (type: string, handler: any, options?: any) => void;
}

/** Return true from the render callback to ask for one more frame. */
export type RenderFn = (now: number) => boolean | void;

export interface Lifecycle {
  on(target: ListenerTarget | null | undefined, type: string, handler: any, options?: any): void;
  start(render: RenderFn): void;
  invalidate(): void;
  isPaused(): boolean;
  isScheduled(): boolean;
  isDisposed(): boolean;
  listenerCount(): number;
  stats(): { frames: number; deferred: number; pauses: number };
  dispose(): void;
}

const DEFAULT_MAX_FPS = 45;

export function createLifecycle(host: LifecycleHost = {}): Lifecycle {
  const doc = host.doc ?? (typeof document === 'undefined' ? null : document);
  const win = host.win ?? (typeof window === 'undefined' ? null : window);

  const requestFrame: (cb: (t: number) => void) => number =
    host.requestFrame
    ?? (win && typeof win.requestAnimationFrame === 'function'
      ? win.requestAnimationFrame.bind(win)
      : (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16) as unknown as number);

  const cancelFrame: (handle: number) => void =
    host.cancelFrame
    ?? (win && typeof win.cancelAnimationFrame === 'function'
      ? win.cancelAnimationFrame.bind(win)
      : (handle: number) => clearTimeout(handle as unknown as ReturnType<typeof setTimeout>));

  const now: () => number =
    host.now
    ?? (win?.performance && typeof win.performance.now === 'function'
      ? () => win.performance.now()
      : () => Date.now());

  const budget = 1000 / Math.max(1, host.maxFps ?? DEFAULT_MAX_FPS);

  const listeners: { target: ListenerTarget; type: string; handler: any; options?: any }[] = [];
  let render: RenderFn | null = null;
  let handle = 0;
  let last = -Infinity;
  let paused = false;
  let dead = false;
  let frames = 0;
  let deferred = 0;
  let pauses = 0;

  function schedule(): void {
    if (dead || paused || handle) return;
    handle = requestFrame(frame);
  }

  function frame(t: number): void {
    handle = 0;
    if (dead) return;
    // Belt and braces: the tab may have gone away between the schedule and the
    // callback, and a frame drawn into a hidden tab is a frame nobody sees.
    if (paused || isHidden()) return;

    const stamp = Number.isFinite(t) ? t : now();
    if (stamp - last < budget) {
      // Deferred, not dropped. The work still happens, one tick later, which
      // is what keeps a drag smooth instead of stuttering.
      deferred += 1;
      schedule();
      return;
    }
    last = stamp;
    frames += 1;
    let again = false;
    try {
      again = render ? render(stamp) === true : false;
    } catch {
      /* A render that threw must not take the loop with it; the caller's
       * degrade-to-nothing contract is handled a level up, in topology.ts. */
      again = false;
    }
    if (again) schedule();
  }

  function isHidden(): boolean {
    try {
      return Boolean(doc && doc.hidden);
    } catch {
      return false;
    }
  }

  function onVisibility(): void {
    if (dead) return;
    if (isHidden()) {
      if (paused) return;
      paused = true;
      pauses += 1;
      if (handle) {
        cancelFrame(handle);
        handle = 0;
      }
      return;
    }
    if (!paused) return;
    paused = false;
    // The clock restarts, so the first frame back is never charged for the
    // hours the tab spent in the background.
    last = -Infinity;
    schedule();
  }

  const api: Lifecycle = {
    on(target, type, handler, options) {
      if (dead || !target || typeof target.addEventListener !== 'function') return;
      target.addEventListener(type, handler, options);
      listeners.push({ target, type, handler, options });
    },

    start(fn: RenderFn) {
      if (dead) return;
      render = fn;
      paused = isHidden();
      if (paused) pauses += 1;
      schedule();
    },

    invalidate() {
      if (dead) return;
      // A tab that is hidden does not get a frame banked for later; when it
      // comes back, onVisibility schedules one and the scene redraws whole.
      if (isHidden()) {
        if (!paused) {
          paused = true;
          pauses += 1;
        }
        return;
      }
      schedule();
    },

    isPaused: () => paused,
    isScheduled: () => handle !== 0,
    isDisposed: () => dead,
    listenerCount: () => listeners.length,
    stats: () => ({ frames, deferred, pauses }),

    dispose() {
      if (dead) return;
      dead = true;
      render = null;
      if (handle) {
        cancelFrame(handle);
        handle = 0;
      }
      // Reverse order and each one guarded: a target that has already been
      // torn down by the host must not strand the listeners behind it.
      for (let i = listeners.length - 1; i >= 0; i -= 1) {
        const entry = listeners[i];
        try {
          entry.target.removeEventListener(entry.type, entry.handler, entry.options);
        } catch {
          /* nothing useful to do; keep removing the rest */
        }
      }
      listeners.length = 0;
    },
  };

  // Registered through the same tracked path as everything else, so it is
  // removed by dispose() with no special case.
  api.on(doc as ListenerTarget, 'visibilitychange', onVisibility);

  return api;
}
