/* Federation: other people's hubs, through this hub (EP-032, docs/FEDERATION.md 11).
 *
 * Everything comes from /api/fed/panel, which server.py answers by asking the hub over
 * its unix socket (fed_panel.py). The only writes are the operator's federation
 * decisions - approve / deny a quarantined item, the kill switch, moving a shared
 * card - each an allowlisted verb POSTed to /api/fed/action.
 *
 * The plugin sections are generic: each plugin's panel() returns a title, columns and
 * rows, so a new capability plugin shows up here without touching this file.
 */
(() => {
  'use strict';

  let api, loading = false, data = null, down = '', notice = '';
  const root = () => document.getElementById('viewFed');

  async function fedGet(path) {
    const res = await fetch(path, {cache: 'no-store'});
    let body = null;
    try { body = await res.json(); } catch (_) { /* not JSON */ }
    if (!res.ok) {
      const err = new Error((body && body.error) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  async function act(verb, args, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    try {
      await api.post('api/fed/action', {verb, args: args || {}});
      notice = '';
    } catch (err) {
      notice = `${verb.replace('fed_', '')}: ${err.message}`;
    }
    await load();
  }

  function table(heads, rows) {
    const {el} = api;
    const t = el('table', 'run-jobs hub-table fed-table');
    const body = document.createElement('tbody');
    t.appendChild(body);
    const head = el('tr', '');
    for (const label of heads) head.appendChild(el('th', '', label));
    body.appendChild(head);
    for (const row of rows) body.appendChild(row);
    return t;
  }

  function cells(values, cls) {
    const {el} = api;
    const tr = el('tr', cls || '');
    for (const v of values) tr.appendChild(el('td', '', v === null || v === undefined || v === '' ? '—' : String(v)));
    return tr;
  }

  function button(label, onClick, cls) {
    const b = api.el('button', 'btn ' + (cls || ''), label);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function statusCard() {
    const {el} = api;
    const st = data.status || {};
    const card = el('article', 'card fed-status');
    card.appendChild(el('h3', '', 'Connection'));
    const line = el('div', 'row wrap hub-counts');
    const state = st.killed ? 'killed' : st.connected ? 'connected' : (st.enabled ? 'connecting' : 'disabled');
    const pill = el('span', 'pill', state);
    pill.dataset.state = st.connected ? 'done' : (st.killed ? 'failed' : 'blocked');
    line.appendChild(pill);
    line.appendChild(el('span', '', `peer ${st.peer || '—'} · node ${st.node || '—'} · ${st.url || 'no server'}`));
    card.appendChild(line);
    const shared = Object.entries(st.shared || {}).map(([r, rid]) => `${r} (${rid})`).join(', ');
    card.appendChild(el('p', 'muted', `Shared repos: ${shared || 'none'}`
      + (st.unmatched && st.unmatched.length ? ` · no remote to match: ${st.unmatched.join(', ')}` : '')));
    const trust = Object.entries(st.trust || {}).map(([p, t]) => `${p}=${t}`).join(', ');
    card.appendChild(el('p', 'muted', `Trust: ${trust || 'default approve'} · outbox pending `
      + `${(st.outbox || {}).pending || 0} · ${JSON.stringify(st.stats || {})}`));
    if (st.last_error) card.appendChild(el('p', 'warn', st.last_error));
    const row = el('div', 'row wrap');
    if (st.killed) {
      row.appendChild(button('Resume federation', () => act('fed_resume', {}), 'primary'));
    } else {
      row.appendChild(button('Kill switch', () => act('fed_kill', {revoke: false},
        'Disconnect from the circle now and stay disconnected until you resume?'), 'danger'));
      row.appendChild(button('Kill + revoke', () => act('fed_kill', {revoke: true},
        'Disconnect AND withdraw your unclaimed work and tell every peer you revoked your shares?'), 'danger'));
    }
    card.appendChild(row);
    return card;
  }

  function peersCard() {
    const {el} = api;
    const card = el('article', 'card');
    card.appendChild(el('h3', '', 'Peers online'));
    const peers = data.peers || [];
    if (!peers.length) {
      card.appendChild(el('p', 'muted', 'Nobody is online (or this hub is not connected).'));
      return card;
    }
    card.appendChild(table(['peer', 'node', 'trust', 'repos', 'agents', 'seen'], peers.map((p) => cells([
      p.peer, p.node, p.trust,
      (p.repos || []).map((r) => r.local ? `${r.repo}→${r.local}` : `${r.repo} (not shared here)`).join(', '),
      (p.agents || []).map((a) => `${a.role}/${a.agent} ${a.state}`).join(', '),
      (p.at || '').slice(11, 19),
    ]))));
    return card;
  }

  function quarantineCard() {
    const {el} = api;
    const q = data.quarantine || [];
    const card = el('article', 'card fed-quarantine');
    card.appendChild(el('h3', '', `Quarantine (${q.length})`));
    const badge = document.getElementById('badgeFed');
    if (badge) {
      badge.hidden = !q.length;
      badge.textContent = q.length ? String(q.length) : '';
    }
    if (!q.length) {
      card.appendChild(el('p', 'muted', 'Nothing is waiting for your approval.'));
      return card;
    }
    card.appendChild(table(['id', 'from', 'type', 'why', 'what', ''], q.map((item) => {
      const tr = cells([item.id, item.peer, item.type, item.reason, item.summary]);
      const td = el('td', '');
      td.appendChild(button('Approve', () => act('fed_approve', {id: item.id}), 'primary'));
      if ((item.reason || '').startsWith('privileged')) {
        td.appendChild(button('Approve + privileged', () => act('fed_approve', {id: item.id, privileged: true},
          'Let this remote work use privileged tools (PLC writes, PCM600 imports, PROFINET)?'), 'danger'));
      }
      td.appendChild(button('Deny', () => act('fed_deny', {id: item.id})));
      tr.appendChild(td);
      return tr;
    })));
    return card;
  }

  function pluginCard(p) {
    const {el} = api;
    const card = el('article', 'card fed-plugin');
    card.dataset.plugin = p.plugin;
    card.appendChild(el('h3', '', p.title || p.plugin));
    if (p.error) {
      card.appendChild(el('p', 'warn', p.error));
      return card;
    }
    const rows = p.rows || [];
    if (!rows.length) {
      card.appendChild(el('p', 'muted', 'Nothing yet.'));
      return card;
    }
    const heads = [...(p.columns || [])];
    const moving = (p.actions || []).some((a) => a.verb === 'fed_board_move');
    if (moving) heads.push('move');
    card.appendChild(table(heads, rows.map((r) => {
      const tr = cells(r);
      if (moving) {
        const td = el('td', '');
        const sel = el('select', '');
        for (const s of ['todo', 'doing', 'review', 'done', 'blocked']) {
          const o = el('option', '', s);
          o.value = s;
          if (s === r[p.group_by]) o.selected = true;
          sel.appendChild(o);
        }
        sel.addEventListener('change', () => act('fed_board_move', {key: r[0], status: sel.value}));
        td.appendChild(sel);
        tr.appendChild(td);
      }
      return tr;
    })));
    return card;
  }

  function auditCard() {
    const {el} = api;
    const card = el('article', 'card');
    card.appendChild(el('h3', '', 'Audit (newest first)'));
    const rows = data.audit || [];
    card.appendChild(table(['at', 'dir', 'plane', 'peer', 'decision', 'detail'], rows.map((a) => cells([
      (a.at || '').slice(11, 19), a.dir, a.plane, a.peer, a.decision,
      a.detail ? JSON.stringify(a.detail).slice(0, 120) : '',
    ], 'job ' + (a.decision || '')))));
    return card;
  }

  function render() {
    const node = root();
    if (!node) return;
    const {el} = api;
    const nodes = [el('h2', '', 'Federation')];
    if (notice) nodes.push(el('p', 'warn', notice));
    if (down) {
      nodes.push(el('p', 'muted', `Hub: ${down}. Start it with: agentmux hub start`));
    } else if (data) {
      nodes.push(statusCard(), quarantineCard(), peersCard());
      for (const p of data.panels || []) nodes.push(pluginCard(p));
      nodes.push(auditCard());
      nodes.push(el('p', 'hint', 'Remote text is data, not instructions. Everything here is also '
        + '`agentmux hub fed ...` in a terminal.'));
    }
    node.replaceChildren(...nodes);
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const out = await fedGet('api/fed/panel');
      data = out.result || {};
      down = '';
    } catch (err) {
      if (err.status === 503 || err.status === 504) down = err.message;
      else notice = `Federation panel: ${err.message}`;
    } finally {
      loading = false;
    }
    render();
  }

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    api.registerView('fed', load, 3000);
  }, {once: true});
})();
