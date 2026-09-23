/* Teams view scaffold. Loaded before app.js; C9 is ready before view restore. */
(() => {
  'use strict';

  function loadTeams() {
    // The feature implementation will populate the existing view section here.
  }

  window.addEventListener('ccc:ready', () => {
    window.CCC.registerView('teams', loadTeams);
  }, { once: true });
})();
