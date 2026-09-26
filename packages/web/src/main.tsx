/* Boot order matters here, and each line is deliberate.
 *
 * 1. tokens.css, then motion.css, then this app's base.css. Tokens first
 *    because everything after it reads var()s it defines; base.css last
 *    because it is the only file allowed to override, and it does not.
 * 2. startMotion() BEFORE the first render. It creates the IntersectionObserver
 *    that every view's useReveals() hands nodes to, and it sets
 *    data-motion-ready on <html>. Until that attribute exists motion.css keeps
 *    every [data-reveal] element visible - so a bundle that dies between here
 *    and mount shows content rather than a black page.
 * 3. startField() after mount, deferred to idle. It must never cost a frame at
 *    first paint; it is a background.
 */
import '@design/tokens.css';
import '@design/motion.css';
import './base.css';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';

import { bootField, bootMotion, stopField } from '@/motion/boot';
import { router } from '@/router';

bootMotion();

const host = document.getElementById('root');
if (!host) throw new Error('#root is missing from index.html');

createRoot(host).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

bootField();

/* A dev reload that leaves the old WebGL context alive costs a context per
 * save, and browsers cap them at around sixteen - after which the canvas is
 * black and it looks like the shader broke. */
if (import.meta.hot) {
  import.meta.hot.dispose(() => stopField());
}
