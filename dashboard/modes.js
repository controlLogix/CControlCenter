/* Mode profiles: the shape of the console for one kind of work.
 *
 * A mode decides which views are on the rail, the theme, and how the blade
 * opens. The files live in modes/*.yaml and the server compiles them; this only
 * applies the result, so adding a mode is adding a file and reloading.
 *
 * DEGRADES, NEVER BLANKS. /api/modes never fails - an unparseable file comes
 * back as a diagnostic with its line and column, and the modes that did compile
 * still arrive. If the endpoint itself is unreachable, or PyYAML is missing, the
 * switcher hides and every view stays on the rail. The rail you had is always a
 * safe fallback; a mode is a narrowing of it.
 *
 * HIDING A VIEW IS NOT SECURITY. A mode narrows the rail so the console matches
 * the work in front of you. Every endpoint is exactly as reachable as it was -
 * the server does not know or care which mode is selected, and nothing here
 * should ever be mistaken for an access control.
 */
(() => {
  'use strict';

  const MODE_KEY = 'agentmux.mode';
  let api = null;
  let data = { modes: [], diagnostics: [] };
  let current = null;

  function remembered() {
    try { return localStorage.getItem(MODE_KEY) || ''; } catch (err) { return ''; }
  }
  function remember(id) {
    try {
      if (id) localStorage.setItem(MODE_KEY, id);
      else localStorage.removeItem(MODE_KEY);
    } catch (err) { /* a forgotten mode is not worth a broken boot */ }
  }

  // ── applying a mode ────────────────────────────────────────────────────────
  function applyViews(mode) {
    const items = Array.from(document.querySelectorAll('.nav-item'));
    let activeHidden = false;
    for (const item of items) {
      const view = item.dataset.view;
      const wanted = !mode || mode.views.includes(view);
      item.hidden = !wanted;
      if (!wanted && item.classList.contains('active')) activeHidden = true;
    }
    // If the mode just hid the view you were on, move rather than leaving the
    // rail with nothing selected and a panel nobody can navigate back to.
    if (activeHidden && mode) {
      const target = items.find(i => i.dataset.view === mode.default_view)
        || items.find(i => !i.hidden);
      if (target) target.click();
    }
  }

  function applyTheme(mode) {
    if (!mode || !mode.theme) return;
    // app.js owns the theme machinery, including validation and the token
    // application; reuse it rather than writing tokens from here.
    const select = document.getElementById('themeSelect');
    if (select && Array.from(select.options).some(o => o.value === mode.theme)) {
      select.value = mode.theme;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function applyBlade(mode) {
    const blade = window.AGENTMUX_BLADE;
    if (!blade || !mode || !mode.blade) return;
    // Only opens the blade; it never forces it shut. Someone who closed it
    // deliberately should not have it reappear because a mode said pinned.
    if (mode.blade.default_state !== 'hidden' && blade.state().state === 'hidden') {
      blade.open(mode.blade.panels && mode.blade.panels[0]);
    }
  }

  function apply(mode) {
    current = mode;
    applyViews(mode);
    applyTheme(mode);
    applyBlade(mode);
    const chip = document.getElementById('bladeMode');
    if (chip) chip.textContent = mode ? mode.title : '';
    remember(mode ? mode.id : '');
    window.dispatchEvent(new CustomEvent('agentmux:mode', { detail: { mode } }));
  }

  // ── the switcher ───────────────────────────────────────────────────────────
  function draw() {
    const host = document.getElementById('modeSwitch');
    if (!host) return;
    host.replaceChildren();

    if (!data.modes.length) {
      // Nothing to choose between. Say why if the server told us.
      if (data.diagnostics.length) {
        const warn = api.el('span', 'mode-warn', 'modes unavailable');
        warn.title = data.diagnostics.map(d =>
          `${d.file || 'modes'}${d.line ? ':' + d.line : ''} ${d.message}`).join('\n');
        host.appendChild(warn);
      }
      return;
    }

    const select = api.el('select', 'mode-select');
    select.setAttribute('aria-label', 'Mode');
    select.title = 'Which views, theme and console layout this work needs';
    const none = api.el('option', null, 'All views');
    none.value = '';
    select.appendChild(none);
    for (const mode of data.modes) {
      const opt = api.el('option', null, mode.title + (mode.stale ? ' (last good)' : ''));
      opt.value = mode.id;
      opt.title = mode.description || '';
      select.appendChild(opt);
    }
    select.value = current ? current.id : '';
    select.addEventListener('change', () => {
      apply(data.modes.find(m => m.id === select.value) || null);
    });
    host.appendChild(select);

    if (data.diagnostics.length) {
      // Visible, not buried in a console nobody opens. A mode file that is
      // wrong is something the operator can fix in ten seconds if told where.
      const warn = api.el('span', 'mode-warn', `${data.diagnostics.length} mode issue(s)`);
      warn.title = data.diagnostics.map(d =>
        `${d.file || 'modes'}${d.line ? ':' + d.line + ':' + (d.col || 1) : ''}`
        + `${d.field ? ' [' + d.field + ']' : ''} ${d.message}`).join('\n');
      host.appendChild(warn);
    }
  }

  function load() {
    return api.getJSON('api/modes').then((payload) => {
      data = {
        modes: Array.isArray(payload && payload.modes) ? payload.modes : [],
        diagnostics: Array.isArray(payload && payload.diagnostics) ? payload.diagnostics : [],
      };
      const want = remembered();
      const mode = data.modes.find(m => m.id === want) || null;
      draw();
      if (mode) apply(mode); else draw();
    }).catch(() => {
      // Unreachable endpoint: every view stays on the rail, switcher hidden.
      data = { modes: [], diagnostics: [] };
      draw();
    });
  }

  window.AGENTMUX_MODES = {
    current() { return current; },
    reload: load,
    all() { return data.modes.slice(); },
  };

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    if (!api) return;
    load();
  });
})();
