/* Agents view scaffold. Loaded before app.js; C9 is ready before view restore. */
(() => {
  'use strict';

  function loadAgents() {
    // The feature implementation will populate the existing view section here.
  }

  window.addEventListener('ccc:ready', () => {
    window.CCC.registerView('agents', loadAgents);
  }, { once: true });
})();
