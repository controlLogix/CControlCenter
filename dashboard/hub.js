/* Hub: the dashboard as a client of agentmux-hub (TM-216).
 *
 * Everything on this view comes from /api/hub/*, which server.py answers by asking
 * the hub over its unix socket. The page never sees hub.db and neither does the
 * server - see hub_panel.py for why. Read-only: no claim, post or cancel from here.
 *
 * Polls every 2 s while the view is on screen (app.js stops the timer when it is
 * not). The event feed is incremental: the first load asks for the tail, and each
 * poll after that asks only for events after the last sequence number it has.
 */
(() => {
  'use strict';

  const FEED_MAX = 300;
  let api, loading = false;
  let status = null, work = null, down = '', notice = '';
  let events = [], nextSeq = null;
  let selected = null, detail = null;

  const root = () => document.getElementById('viewHub');

  // A 503 carries {"error": "hub not running"}; getJSON would throw that body away.
  async function hubGet(path) {
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

  function clock(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleTimeString();
  }

  function table(heads, rows) {
    const {el} = api;
    const t = el('table', 'run-jobs hub-table');
    const body = document.createElement('tbody');
    t.appendChild(body);
    const head = el('tr', '');
    for (const label of heads) head.appendChild(el('th', '', label));
    body.appendChild(head);
    for (const row of rows) body.appendChild(row);
    return t;
  }

  function counts(title, map) {
    const {el} = api;
    const line = el('div', 'row wrap hub-counts');
    line.appendChild(el('span', 'rlabel', title));
    const keys = Object.keys(map || {}).sort();
    if (!keys.length) line.appendChild(el('span', 'muted', 'none'));
    for (const k of keys) {
      const pill = el('span', 'pill', `${k} ${map[k]}`);
      pill.dataset.state = k;
      line.appendChild(pill);
    }
    return line;
  }

  function agentsCard() {
    const {el, markAgent} = api;
    const card = el('article', 'card hub-agents');
    card.appendChild(el('h3', '', 'Agents'));
    const agents = (status && status.agents) || [];
    if (!agents.length) {
      card.appendChild(el('p', 'muted', 'No agents registered with the hub.'));
      return card;
    }
    card.appendChild(table(['session', 'cli', 'state', 'note', 'last output'], agents.map((a) => {
      const row = el('tr', 'job ' + (a.state || ''));
      row.appendChild(markAgent(el('td', 'j-who', a.session), a.session));
      row.appendChild(el('td', '', a.cli || '—'));
      row.appendChild(el('td', 'j-state', a.state || '—'));
      row.appendChild(el('td', '', a.state_note || ''));
      row.appendChild(el('td', 'j-last', clock(a.last_output)));
      return row;
    })));
    return card;
  }

  function workCard() {
    const {el, markAgent} = api;
    const card = el('article', 'card hub-work');
    card.appendChild(el('h3', '', 'Work items'));
    const items = (work || []).slice().reverse();      // newest first
    if (!items.length) {
      card.appendChild(el('p', 'muted', 'No work items.'));
      return card;
    }
    card.appendChild(table(['id', 'state', 'title', 'target', 'claimed by', 'parent'], items.map((w) => {
      const row = el('tr', 'job ' + w.state);
      const idCell = el('td', 'j-id');
      const link = el('button', 'cbtn', w.id);
      link.title = 'Show this item and its children';
      link.addEventListener('click', () => showDetail(w.id));
      idCell.appendChild(link);
      row.appendChild(idCell);
      row.appendChild(el('td', 'j-state', w.state));
      row.appendChild(el('td', '', w.title));
      row.appendChild(el('td', '', w.target));
      row.appendChild(markAgent(el('td', 'j-who', w.claimed_by || '—'), w.claimed_by));
      row.appendChild(el('td', 'j-id', w.parent_id || ''));
      return row;
    })));
    if (selected) card.appendChild(detailBox());
    return card;
  }

  function detailBox() {
    const {el} = api;
    const box = el('div', 'subcard hub-detail');
    const head = el('div', 'row');
    head.appendChild(el('strong', '', selected));
    const close = el('button', 'btn', 'close');
    close.addEventListener('click', () => { selected = null; detail = null; render(); });
    head.appendChild(close);
    box.appendChild(head);
    if (!detail) { box.appendChild(el('p', 'muted', 'loading…')); return box; }
    if (detail.error) { box.appendChild(el('p', 'error', detail.error)); return box; }
    const w = detail.result;
    const lines = [
      `state ${w.state} · attempts ${w.attempts}/${w.max_attempts} · priority ${w.priority}`,
      `created by ${w.created_by} · ${clock(w.created)} · updated ${clock(w.updated)}`,
    ];
    if (w.lease_until) lines.push(`lease until ${clock(w.lease_until)}`);
    if (w.blocked_reason) lines.push(`reason: ${w.blocked_reason}`);
    for (const line of lines) box.appendChild(el('p', 'muted', line));
    if (w.body) box.appendChild(el('pre', 'hub-body', w.body));
    if (w.result) box.appendChild(el('pre', 'hub-body', `result: ${w.result}`));
    const kids = w.children || [];
    if (kids.length) {
      box.appendChild(el('h4', '', 'Children'));
      box.appendChild(table(['id', 'state', 'title', 'target', 'claimed by'], kids.map((c) => {
        const row = el('tr', 'job ' + c.state);
        row.appendChild(el('td', 'j-id', c.id));
        row.appendChild(el('td', 'j-state', c.state));
        row.appendChild(el('td', '', c.title));
        row.appendChild(el('td', '', c.target));
        row.appendChild(el('td', 'j-who', c.claimed_by || '—'));
        return row;
      })));
    }
    return box;
  }

  async function showDetail(id) {
    selected = id;
    detail = null;
    render();
    try { detail = await hubGet(`api/hub/work/${encodeURIComponent(id)}`); }
    catch (err) { detail = {error: err.message}; }
    render();
  }

  function eventText(e) {
    let d = null;
    try { d = e.detail ? JSON.parse(e.detail) : null; } catch (_) { d = null; }
    let text = `${e.entity_id} ${e.event}`;
    if (d && e.entity === 'bell') {
      text += d.reason ? ` (${d.reason})` : '';
    } else if (d && e.entity === 'delivery') {
      if (d.from) text += ` from ${d.from}`;
      if (d.error) text += ` · ${d.error}`;
    } else if (d && e.entity === 'work') {
      if (d.from) text += ` from ${d.from}`;
    }
    return text;
  }

  function feedCard() {
    const {el} = api;
    const card = el('article', 'card hub-events');
    card.appendChild(el('h3', '', 'Events — bells, deliveries, work'));
    const list = el('div', 'feed');
    list.setAttribute('role', 'log');
    if (!events.length) list.appendChild(el('p', 'muted', 'No events yet.'));
    for (const e of events.slice().reverse()) {     // newest on top
      const cls = e.event === 'dead' || e.event === 'failed' ? 'feed-row error'
        : (e.event === 'blocked' ? 'feed-row warn' : 'feed-row');
      const row = el('div', cls);
      row.appendChild(el('span', 'f-at', clock(e.at)));
      row.appendChild(el('span', 'f-src', e.entity));
      row.appendChild(el('span', 'f-who', e.actor || ''));
      row.appendChild(el('span', 'f-text', eventText(e)));
      row.appendChild(el('span', 'f-ref', `#${e.seq}`));
      list.appendChild(row);
    }
    card.appendChild(list);
    return card;
  }

  function render() {
    const {el} = api;
    const node = root();
    const nodes = [];
    const header = el('div', 'vhead');
    header.appendChild(el('h2', '', 'Hub'));
    const stamp = el('span', 'stamp');
    stamp.setAttribute('aria-live', 'polite');
    stamp.textContent = down ? down : (status ? `updated ${new Date().toLocaleTimeString()} · every 2s` : 'loading…');
    header.appendChild(stamp);
    header.appendChild(el('span', 'spacer'));
    const refresh = el('button', 'btn', 'Refresh');
    refresh.addEventListener('click', load);
    header.appendChild(refresh);
    nodes.push(header);

    if (down) {
      const p = el('p', 'notice hub-down', down === 'hub not running'
        ? 'hub not running. Start it with: agentmux hub start'
        : `Hub unavailable: ${down}`);
      p.setAttribute('role', 'status');
      nodes.push(p);
    }
    if (notice) nodes.push(el('p', 'error', notice));
    if (status && !down) {
      nodes.push(counts('Work', status.work));
      nodes.push(counts('Deliveries', status.deliveries));
      if ((status.dead || []).length) {
        nodes.push(el('p', 'error', `${status.dead.length} dead letter(s): `
          + status.dead.map((d) => `${d.message_id} to ${d.recipient}`).join(', ')));
      }
      nodes.push(agentsCard(), workCard(), feedCard());
      nodes.push(el('p', 'hint', 'Read over the hub socket (the dashboard is the operator). '
        + 'Nothing here writes to the hub; use agentmux hub ... in a terminal for that.'));
    }
    node.replaceChildren(...nodes);
  }

  async function loadEvents() {
    const path = nextSeq === null ? 'api/hub/events?tail=200'
      : `api/hub/events?since=${encodeURIComponent(nextSeq)}&limit=500`;
    const out = await hubGet(path);
    const rows = Array.isArray(out.result) ? out.result : [];
    events = (nextSeq === null ? rows : events.concat(rows)).slice(-FEED_MAX);
    if (typeof out.next === 'number') nextSeq = out.next;
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const [s, w] = await Promise.all([hubGet('api/hub/status'), hubGet('api/hub/work')]);
      status = s.result || {};
      work = Array.isArray(w.result) ? w.result : [];
      await loadEvents();
      down = '';
      notice = '';
    } catch (err) {
      if (err.status === 503 || err.status === 504) {
        down = err.message;
        // A restarted hub is a new database as far as sequence numbers go.
        nextSeq = null;
      } else {
        notice = `Hub panel: ${err.message}`;
      }
    } finally {
      loading = false;
    }
    render();
  }

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    api.registerView('hub', load, 2000);
  }, {once: true});
})();
