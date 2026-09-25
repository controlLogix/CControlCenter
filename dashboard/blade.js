/* The blade: a right-side agent console that reflows rather than covers.
 *
 * THREE STATES, AND WHY PINNED IS NOT AN OVERLAY. hidden | overlay | pinned.
 * Pinned is a flex child of .shell, so the main content NARROWS. That matters
 * for exactly the two things this page is for: a terminal grid measures its own
 * container to pick a font size, and a chart measures its own container to pick
 * a scale. A panel sitting on top of either is useless. Overlay is the same
 * element taken out of flow, for a glance that must not disturb a layout you
 * arranged by hand.
 *
 * NO CSS TRANSFORM, EVER. fitmatrix.js records that a transform resamples
 * terminal glyphs into mush. Width is animated instead, and the re-fit is
 * dispatched on transitionend rather than per frame - four earlier attempts at
 * fitting oscillated because a measurement taken at the current size fed the
 * choice of the next size.
 *
 * CONVERSATION SURVIVES NAVIGATION because this element is never unmounted -
 * switching views hides a .view, it does not touch .shell's third child. It
 * survives a RELOAD because the transcript is server-side; the browser only
 * remembers which session it was attached to.
 *
 * CONFIRMATIONS ARE CARDS, NEVER DIALOGS. A browser dialog blocks the page,
 * cannot render a dry run, and cannot be left open while you go and check
 * something at the equipment. Every industrial write and every trade renders
 * here, with a typed phrase derived from the action itself - so muscle memory
 * cannot commit a different write than the one on screen.
 */
(() => {
  'use strict';

  const STATE_KEY = 'agentmux.blade.v1';
  const MIN_W = 320;
  const MAX_W = 900;
  const DEFAULT_W = 420;

  let api = null;
  let ui = {};
  let state = { state: 'hidden', width: DEFAULT_W, panel: 'conversation', last: 'pinned' };

  // ── persisted, per browser ─────────────────────────────────────────────────
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STATE_KEY) || '{}') || {};
      if (raw.state === 'pinned' || raw.state === 'overlay' || raw.state === 'hidden') {
        state.state = raw.state;
      }
      if (raw.last === 'pinned' || raw.last === 'overlay') state.last = raw.last;
      const w = Number(raw.width);
      if (Number.isFinite(w)) state.width = Math.min(MAX_W, Math.max(MIN_W, Math.round(w)));
      if (typeof raw.panel === 'string') state.panel = raw.panel;
    } catch (err) { /* private mode: defaults are fine */ }
  }
  function save() {
    try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); }
    catch (err) { /* losing a remembered width is smaller than a page that will not boot */ }
  }

  // ── panels ─────────────────────────────────────────────────────────────────
  // Registered rather than hard-coded, so a mode can choose which appear and in
  // what order without this file changing.
  const PANELS = [];
  function registerPanel(id, title, render) {
    PANELS.push({ id, title, render });
  }

  function activePanels() {
    return PANELS;
  }

  function drawTabs() {
    ui.tabs.replaceChildren();
    for (const panel of activePanels()) {
      const tab = api.el('button', 'blade-tab', panel.title);
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      tab.dataset.panel = panel.id;
      tab.setAttribute('aria-selected', String(panel.id === state.panel));
      tab.addEventListener('click', () => { state.panel = panel.id; save(); drawPanels(); drawTabs(); });
      ui.tabs.appendChild(tab);
    }
  }

  function drawPanels() {
    ui.panels.replaceChildren();
    const panel = activePanels().find(p => p.id === state.panel) || activePanels()[0];
    if (!panel) return;
    state.panel = panel.id;
    const host = api.el('div', 'blade-panel');
    host.dataset.panel = panel.id;
    ui.panels.appendChild(host);
    try { panel.render(host); }
    catch (err) {
      host.replaceChildren(api.el('p', 'blade-empty',
        `The ${panel.title} panel failed to render: ${err.message}`));
    }
  }

  // The registration test runs every view script against a DOM stub that has no
  // .style, and a script that throws at registration takes the whole page's boot
  // with it. Guard the one place that touches CSS rather than assuming a browser.
  function setWidth(px) {
    if (ui.blade && ui.blade.style && typeof ui.blade.style.setProperty === 'function') {
      ui.blade.style.setProperty('--blade-w', px + 'px');
    }
  }

  // ── the three states ───────────────────────────────────────────────────────
  function apply(next, { remember = true } = {}) {
    if (next !== 'hidden' && next !== 'overlay' && next !== 'pinned') return;
    if (next !== 'hidden' && remember) state.last = next;
    state.state = next;
    if (ui.blade.dataset) ui.blade.dataset.state = next;
    setWidth(state.width);
    if (ui.toggle && ui.toggle.setAttribute) ui.toggle.setAttribute('aria-expanded', String(next !== 'hidden'));
    if (ui.pin) ui.pin.textContent = next === 'overlay' ? 'pin' : 'float';
    if (ui.pin) ui.pin.title = next === 'overlay'
      ? 'Pin it, so the content reflows instead of being covered'
      : 'Float it over the content instead of reflowing';
    save();
    if (next !== 'hidden') { drawTabs(); drawPanels(); }
  }

  function toggle() {
    apply(state.state === 'hidden' ? state.last : 'hidden', { remember: false });
  }

  // ── resize ─────────────────────────────────────────────────────────────────
  // Snapped to 20px and clamped. The re-fit that terminals need is dispatched
  // on transitionend, not here - see the header.
  function beginResize(startEvent) {
    startEvent.preventDefault();
    const startX = startEvent.clientX;
    const startW = state.width;
    const move = (ev) => {
      const next = Math.round((startW + (startX - ev.clientX)) / 20) * 20;
      state.width = Math.min(MAX_W, Math.max(MIN_W, next));
      setWidth(state.width);
    };
    const done = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', done);
      save();
      announceResize();
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', done);
  }

  // The terminal grid and any chart listen for this rather than polling their
  // own size. Dispatched once the width has settled.
  function announceResize() {
    window.dispatchEvent(new CustomEvent('agentmux:blade-resize', {
      detail: { state: state.state, width: state.width },
    }));
  }

  // ── boot ───────────────────────────────────────────────────────────────────
  function boot() {
    api = window.AGENTMUX;
    ui = {
      blade: document.getElementById('blade'),
      toggle: document.getElementById('bladeToggle'),
      pin: document.getElementById('bladePin'),
      close: document.getElementById('bladeClose'),
      resize: document.getElementById('bladeResize'),
      tabs: document.getElementById('bladeTabs'),
      panels: document.getElementById('bladePanels'),
      mode: document.getElementById('bladeMode'),
    };
    if (!ui.blade || !api) return;

    load();

    ui.toggle.addEventListener('click', toggle);
    ui.close.addEventListener('click', () => apply('hidden', { remember: false }));
    ui.pin.addEventListener('click', () =>
      apply(state.state === 'overlay' ? 'pinned' : 'overlay'));
    ui.resize.addEventListener('mousedown', beginResize);
    ui.resize.addEventListener('keydown', (ev) => {
      const step = ev.shiftKey ? 100 : 20;
      if (ev.key === 'ArrowLeft') { state.width = Math.min(MAX_W, state.width + step); }
      else if (ev.key === 'ArrowRight') { state.width = Math.max(MIN_W, state.width - step); }
      else return;
      ev.preventDefault();
      setWidth(state.width);
      save(); announceResize();
    });

    // Ctrl+` toggles; Ctrl+Shift+` swaps pinned and overlay. Chosen because the
    // backtick is not bound anywhere else on this page and does not collide
    // with a terminal's own key handling.
    window.addEventListener('keydown', (ev) => {
      if (!ev.ctrlKey || ev.key !== '`') return;
      ev.preventDefault();
      if (ev.shiftKey) {
        if (state.state !== 'hidden') apply(state.state === 'pinned' ? 'overlay' : 'pinned');
      } else { toggle(); }
    });

    ui.blade.addEventListener('transitionend', (ev) => {
      if (ev.propertyName === 'width' || ev.propertyName === 'flex-basis') announceResize();
    });

    apply(state.state, { remember: false });
  }

  // ── confirmations ──────────────────────────────────────────────────────────
  // ONE typed shape for every kind, because the questions a PLC write and a trade
  // ask are identical: who, what exactly, what would it do, does it still match
  // what was rendered, and is the kill switch clear. Only `target` and the dry-run
  // rows differ, and those are data.
  const cards = new Map();

  // The typed phrase is DERIVED from the action, never "yes". It carries the
  // target AND the value, so muscle memory cannot commit a different write than
  // the one on screen. Reserved for the kinds that cost money or move equipment -
  // requiring a phrase for a status change trains people to type phrases, which
  // is exactly how the phrase stops being read.
  function phraseFor(card) {
    const a = card.action || {};
    const t = a.target || {};
    if (card.kind === 'industrial_write') {
      return `${t.device || t.system || '?'}:${t.path || '?'}=${a.after}`;
    }
    if (card.kind === 'trade') {
      return `${a.side} ${a.quantity} ${a.symbol} ${a.orderType} ${a.limitPrice ?? ''}`.trim();
    }
    return null;
  }

  function renderCard(card) {
    const node = api.el('div', 'confirm-card');
    node.dataset.risk = card.risk || 'medium';
    if (card.decided) node.dataset.decided = card.decided;

    const head = api.el('div');
    head.appendChild(api.el('strong', null, card.title || card.kind));
    node.appendChild(head);

    const a = card.action || {};
    const t = a.target || {};
    node.appendChild(api.el('div', 'confirm-what',
      `${a.tool || card.kind}\n${[t.system, t.device, t.path].filter(Boolean).join('  ')}`));

    // BEFORE and AFTER, with the age of the before-value. iiot.js is right that a
    // number with no age next to it is the most dangerous thing a panel can show,
    // and that applies hardest to the value you are about to overwrite.
    if (Array.isArray(card.rendering) && card.rendering.length) {
      const dl = api.el('dl', 'confirm-diff');
      for (const row of card.rendering) {
        dl.appendChild(api.el('dt', null, row.label));
        const dd = api.el('dd', row.changed ? 'changed' : null,
          `${row.before ?? '—'} → ${row.after}${row.unit ? ' ' + row.unit : ''}`);
        dl.appendChild(dd);
      }
      node.appendChild(dl);
    }
    node.appendChild(api.el('div', 'confirm-age', card.readBackAt
      ? `current value read ${card.readBackAt}`
      : 'no current value was read — this is a blind write'));

    if (card.killSwitch && card.killSwitch.engaged) {
      node.appendChild(api.el('div', 'confirm-killed',
        `kill switch engaged (${card.killSwitch.scope}) — nothing can be committed`));
    }

    if (card.decided) {
      node.appendChild(api.el('div', 'confirm-note', `${card.decided} — ${card.decidedNote || ''}`));
      return node;
    }

    const phrase = phraseFor(card);
    const row = api.el('div', 'confirm-phrase');
    let input = null;
    if (phrase) {
      input = api.el('input');
      input.type = 'text';
      input.placeholder = phrase;
      input.setAttribute('aria-label', `Type ${phrase} to commit`);
      row.appendChild(input);
    }
    const commit = api.el('button', 'btn', phrase ? 'commit' : 'confirm');
    commit.type = 'button';
    commit.disabled = Boolean(card.killSwitch && card.killSwitch.engaged);
    const reject = api.el('button', 'btn', 'reject');
    reject.type = 'button';
    row.appendChild(commit); row.appendChild(reject);
    node.appendChild(row);

    if (phrase) {
      node.appendChild(api.el('div', 'confirm-note', `type exactly:  ${phrase}`));
    }

    commit.addEventListener('click', () => {
      if (phrase && (input.value || '').trim() !== phrase) {
        input.setCustomValidity('that is not the phrase');
        input.reportValidity();
        return;
      }
      decide(card, 'committed');
    });
    reject.addEventListener('click', () => decide(card, 'rejected'));
    return node;
  }

  function decide(card, outcome) {
    card.decided = outcome;
    card.decidedNote = new Date().toLocaleTimeString();
    if (typeof card.onDecide === 'function') {
      try { card.onDecide(outcome, card); } catch (err) { /* the card still settles */ }
    }
    window.AGENTMUX_BLADE.redraw();
  }

  registerPanel('confirmations', 'Confirm', (host) => {
    const pending = [...cards.values()].filter(c => !c.decided);
    const settled = [...cards.values()].filter(c => c.decided).slice(-5);
    if (!pending.length && !settled.length) {
      host.appendChild(api.el('p', 'blade-empty',
        'Nothing is waiting on you. Industrial writes and trades appear here as cards — never as a browser dialog, so you can leave one open while you go and check.'));
      return;
    }
    for (const card of pending) host.appendChild(renderCard(card));
    for (const card of settled) host.appendChild(renderCard(card));
  });

  // ── runs ───────────────────────────────────────────────────────────────────
  registerPanel('runs', 'Runs', (host) => {
    host.appendChild(api.el('p', 'blade-empty', 'loading runs…'));
    api.getJSON('api/runs').then((data) => {
      host.replaceChildren();
      const runs = (data && data.runs) || [];
      if (!runs.length) {
        host.appendChild(api.el('p', 'blade-empty', 'No runs in flight.'));
        return;
      }
      for (const run of runs.slice(0, 12)) {
        const row = api.el('div', 'blade-msg');
        row.appendChild(api.el('div', 'who', `${run.id} · ${run.state || 'open'}`));
        row.appendChild(api.el('div', 'body', run.detail || run.blocking || ''));
        host.appendChild(row);
      }
    }).catch((err) => {
      host.replaceChildren(api.el('p', 'blade-empty', `Runs unavailable: ${err.message}`));
    });
  });

  // ── conversation ───────────────────────────────────────────────────────────
  // The transcript lives server-side; this element only remembers which session
  // it is attached to. That is deliberate - the browser must never be the source
  // of truth for a conversation that can move equipment.
  const convo = [];
  let busy = false;

  function drawConvo(host) {
    const log = api.el('div');
    if (!convo.length) {
      log.appendChild(api.el('p', 'blade-empty',
        'Ask for something. This console can navigate, read status and run agents; anything that moves equipment or money comes back as a confirmation card.'));
    }
    for (const msg of convo) {
      const row = api.el('div', 'blade-msg');
      row.dataset.who = msg.who;
      row.appendChild(api.el('div', 'who', msg.who));
      row.appendChild(api.el('div', 'body', msg.text));
      log.appendChild(row);
    }
    host.appendChild(log);

    const compose = api.el('div', 'blade-compose');
    const box = api.el('textarea');
    box.placeholder = busy ? 'working…' : 'Ask the console…';
    box.setAttribute('aria-label', 'Message the agent console');
    const send = api.el('button', 'btn', busy ? 'stop' : 'send');
    send.type = 'button';
    compose.appendChild(box); compose.appendChild(send);
    host.appendChild(compose);

    const submit = () => {
      const text = (box.value || '').trim();
      if (!text || busy) return;
      convo.push({ who: 'operator', text });
      busy = true;
      window.AGENTMUX_BLADE.redraw();
      api.post('api/blade/send', { text }).then((reply) => {
        convo.push({ who: 'console', text: (reply && reply.text) || '(no reply)' });
      }).catch((err) => {
        convo.push({ who: 'console', text: `unavailable: ${err.message}` });
      }).finally(() => {
        busy = false;
        window.AGENTMUX_BLADE.redraw();
      });
    };
    send.addEventListener('click', submit);
    box.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); submit(); }
    });
    setTimeout(() => { if (!busy) box.focus(); }, 0);
  }

  registerPanel('conversation', 'Console', drawConvo);

  // Exposed so other modules can raise a confirmation or add a panel without
  // reaching into this file's internals.
  window.AGENTMUX_BLADE = {
    registerPanel,
    // Raise a confirmation. Returns the card so a caller can settle it.
    confirm(card) {
      const id = card.id || ('c' + Date.now() + Math.random().toString(16).slice(2, 6));
      const full = { id, kind: 'industrial_write', risk: 'high', ...card };
      cards.set(id, full);
      state.panel = 'confirmations';
      apply(state.state === 'hidden' ? state.last : state.state, { remember: false });
      drawTabs(); drawPanels();
      return full;
    },
    open(panel) {
      if (panel) state.panel = panel;
      apply(state.state === 'hidden' ? state.last : state.state, { remember: false });
      drawTabs(); drawPanels();
    },
    redraw() { if (state.state !== 'hidden') { drawTabs(); drawPanels(); } },
    state() { return { ...state }; },
  };

  window.addEventListener('agentmux:ready', boot);
})();
