/* agentmux motion runtime — reveals, grain, and the guards that keep them honest.
 *
 * Framework-agnostic on purpose: the old vanilla dashboard and the React app
 * both use this, so the two cannot drift into two different motion languages
 * during the migration. It touches no framework API and holds no state a
 * component needs to know about.
 *
 * Usage:
 *   import { startMotion } from './motion.js';
 *   startMotion();                  // once, at boot
 *   // and after rendering new nodes:
 *   observeReveals(container);
 *
 * THE THREE THINGS THIS FILE IS CAREFUL ABOUT, each of which has bitten a
 * product like this before:
 *
 * 1. A REVEAL THAT NEVER FIRES IS A BLANK PAGE. Everything is visible until
 *    this script claims the document, and anything still hidden after a budget
 *    is forced visible regardless of the observer. A decoration must not be
 *    able to hide the product.
 * 2. A STAGGER IS A DELAY. Capped, because a 60-row table revealing at 28ms a
 *    row takes 1.7s to finish, and for that time it is indistinguishable from
 *    a table that is still loading.
 * 3. A DEAD ELEMENT MUST NOT PULSE. Liveness animation is gated on a data
 *    attribute that only the freshness logic sets - see motion.css.
 */

const REVEAL_SELECTOR = '[data-reveal]';
const STAGGER_CAP = 10;          // steps, not elements
const SAFETY_MS = 1200;          // after this, everything is visible, no exceptions

let observer = null;
let started = false;

function prefersReduced() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
        || document.documentElement.dataset.motion === 'off';
  } catch (_) {
    return false;   // a matchMedia that throws must not disable the product
  }
}

/** Force every reveal visible and stop hiding future ones. Idempotent. */
export function revealEverything(root = document) {
  for (const el of root.querySelectorAll(REVEAL_SELECTOR)) {
    el.classList.add('is-in', 'is-settled');
  }
}

/**
 * Start watching `root` for reveal targets. Safe to call repeatedly - a node
 * already observed is skipped, and a node already revealed is never re-hidden.
 */
export function observeReveals(root = document) {
  const targets = root.querySelectorAll(REVEAL_SELECTOR);
  if (!targets.length) return;

  // Reduced motion, or no observer in this browser: show it and be done. Not a
  // degraded experience - it is the same product without the ornament.
  if (prefersReduced() || typeof IntersectionObserver === 'undefined') {
    revealEverything(root);
    return;
  }

  // Stagger index, capped. Assigned per call so a newly rendered batch starts
  // its own sequence rather than continuing a previous one's.
  let index = 0;
  for (const el of targets) {
    if (el.dataset.revealBound === '1') continue;
    el.dataset.revealBound = '1';
    if (el.parentElement && el.parentElement.hasAttribute('data-stagger')) {
      el.style.setProperty('--i', String(Math.min(index, STAGGER_CAP)));
      index += 1;
    }
    observer.observe(el);
  }
}

function onIntersect(entries) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const el = entry.target;
    el.classList.add('is-in');
    observer.unobserve(el);
    // Drop will-change once the transition is over, so the page does not keep
    // a compositor layer per revealed element for the rest of the session.
    const done = () => {
      el.classList.add('is-settled');
      el.removeEventListener('transitionend', done);
    };
    el.addEventListener('transitionend', done);
    // transitionend does not fire when the duration is 0, which is exactly the
    // reduced-motion case, so settle on a timer too.
    setTimeout(done, 900);
  }
}

/* ── grain ───────────────────────────────────────────────────────────────────
 * A tiled noise tile, generated once into a data URL rather than shipped as a
 * PNG. 128x128 of monochrome noise at 4% costs nothing and removes an asset
 * from the build - which matters for a product whose whole dependency policy
 * is "installs from a clone with no network".
 */
function grainDataURL(size = 128) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(size, size);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    // Monochrome: the grain must not tint anything. A coloured grain over a
    // status chip shifts the colour that the chip exists to communicate.
    const v = (Math.random() * 255) | 0;
    d[i] = d[i + 1] = d[i + 2] = v;
    d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  try { return canvas.toDataURL('image/png'); } catch (_) { return null; }
}

export function installGrain() {
  if (document.querySelector('.grain-layer')) return;
  const url = grainDataURL();
  if (!url) return;                       // no canvas, no grain, no problem
  const layer = document.createElement('div');
  layer.className = 'grain-layer';
  layer.setAttribute('aria-hidden', 'true');
  layer.style.backgroundImage = `url(${url})`;
  layer.style.backgroundRepeat = 'repeat';
  document.body.appendChild(layer);
}

/* ── boot ──────────────────────────────────────────────────────────────────*/
export function startMotion({ grain = true } = {}) {
  if (started) return;
  started = true;

  observer = new IntersectionObserver(onIntersect, {
    // Fire slightly before the element is on screen so the transition is
    // already running when it arrives, rather than starting as it does.
    rootMargin: '0px 0px -8% 0px',
    threshold: 0.01,
  });

  // Claim the document. Until this attribute exists, motion.css keeps every
  // reveal target fully visible - so a script that fails to load leaves a
  // working product rather than an empty one.
  document.documentElement.setAttribute('data-motion-ready', '');

  observeReveals(document);
  if (grain && !prefersReduced()) installGrain();

  // THE BACKSTOP. Whatever happened - a detached subtree, a container that is
  // display:none at first paint, an observer that simply did not fire - no
  // element stays invisible past the budget.
  setTimeout(() => revealEverything(document), SAFETY_MS);

  // A tab restored from bfcache can arrive with observers already spent.
  window.addEventListener('pageshow', (e) => {
    if (e.persisted) revealEverything(document);
  });
}

export const _internals = { STAGGER_CAP, SAFETY_MS, grainDataURL, prefersReduced };
