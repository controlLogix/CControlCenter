import { startMotion } from '@design/motion.js';
import { startField, type FieldHandle } from '@design/field.js';

/* Motion and the field are started ONCE, at app boot, and never by a component.
 *
 * WHY NOT IN A COMPONENT EFFECT. Both of these touch the document rather than a
 * subtree: startMotion() sets data-motion-ready on <html> and appends the grain
 * layer to <body>; startField() appends a fixed canvas to <body>. Under
 * StrictMode a component effect runs twice, and under a route change it runs
 * again - so a component-owned field is a second WebGL context per navigation,
 * which on the integrated GPU this product runs on is how you lose the first
 * one to the browser's context limit and get a black rectangle.
 *
 * WHY startMotion() BEFORE THE FIRST RENDER. motion.js creates the
 * IntersectionObserver inside startMotion(), and observeReveals() needs it to
 * exist. React effects run after render, so calling startMotion() first means
 * every view's useReveals() has a live observer to hand its nodes to. It is
 * also what sets data-motion-ready, and until that attribute exists motion.css
 * keeps every [data-reveal] element visible - so the window between "bundle
 * parsed" and "React mounted" shows content rather than nothing.
 *
 * WHY THE FIELD IS DEFERRED. field.js is explicit that it must never block
 * first paint. It does not defer itself, so the deferral is here: compile the
 * shader once the page has actually painted and the router has settled.
 */

let motionStarted = false;
let field: FieldHandle | null = null;

export function bootMotion(): void {
  if (motionStarted) return;
  motionStarted = true;
  startMotion();
}

export function bootField(): void {
  if (field) return;

  const begin = () => {
    // Re-check: a fast double-invocation must not open two contexts.
    if (field) return;
    field = startField();
  };

  // requestIdleCallback is not in Safari. A two-frame delay is the honest
  // fallback: it is after first paint, which is the only property that matters.
  const idle = (window as unknown as {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  }).requestIdleCallback;

  if (typeof idle === 'function') idle(begin, { timeout: 1500 });
  else requestAnimationFrame(() => requestAnimationFrame(begin));
}

/** Tear the field down. Used by HMR so a dev reload does not leak a GL context. */
export function stopField(): void {
  field?.stop();
  field = null;
}

/** Re-read colour tokens into the shader. Call after the theme attribute flips. */
export function resyncField(): void {
  field?.syncColours?.();
}
