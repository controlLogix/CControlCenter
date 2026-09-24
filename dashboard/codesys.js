/* CODESYS remote targets. Scaffold: registers the view so the nav entry works
   before TM-079 fills it. Loaded before app.js, which fires ccc:ready. */
(() => {
  'use strict';
  function load() { /* TM-079 populates #viewCodesys here. */ }
  window.addEventListener('ccc:ready',
    () => window.CCC.registerView('codesys', load), { once: true });
})();
