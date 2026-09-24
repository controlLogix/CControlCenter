/* Agent chatter. Scaffold: registers the view so the nav entry works before
   TM-081 fills it. Loaded before app.js, which fires ccc:ready. */
(() => {
  'use strict';
  function load() { /* TM-081 populates #viewChatter here. */ }
  window.addEventListener('ccc:ready',
    () => window.CCC.registerView('chatter', load), { once: true });
})();
