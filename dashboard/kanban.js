/* Status columns share the board snapshot; the Tasks epic layout stays independent. */
(() => {
  'use strict';
  const STATUSES = ['backlog', 'open', 'in_progress', 'blocked', 'parked', 'done'];
  let api, root, columns, notice, refresh, tasks = [];
  let expanded = false, loading = false, pending = false, dragging = null;

  async function move(event, destination) {
    event.preventDefault();
    const key = event.dataTransfer.getData('text/plain');
    const task = tasks.find(row => row.key === key);
    if (!task || task.status === destination || pending || loading) return;
    pending = true;
    refresh.disabled = true;
    notice.replaceChildren(api.el('p', '', `Moving ${key}…`));
    try {
      const reply = await api.post('api/board/status', {id: key, status: destination, actor: 'dashboard'});
      notice.replaceChildren(api.el('p', '', reply.bypassed
        ? `Gate bypassed: ${reply.bypassed.reason || 'override'}`
        : `${key} moved to ${destination.replace('_', ' ')}.`));
      await load(); // Only the accepted server snapshot can relocate a card.
    } catch (error) {
      showWriteError(notice, error, `Could not move ${key}: `);
    } finally {
      pending = false;
      refresh.disabled = false;
    }
  }

  function card(task) {
    const node = api.el('article', 'kanban-card');
    node.dataset.task = task.key;
    node.dataset.status = task.status;
    node.draggable = true;
    const keyLink = api.el('button', 'kanban-open', task.key);
    keyLink.type = 'button';
    keyLink.setAttribute('aria-label', `Open ${task.key} details`);
    keyLink.addEventListener('click', () => openCard(task.key));
    node.append(keyLink,
                api.el('p', '', String(task.title || '(untitled)')),
                api.el('span', `status-chip ${task.status}`, task.status.replace('_', ' ')));
    if (task.epic) node.append(api.el('p', 'kanban-meta', task.epic));
    if (task.assignee) node.append(api.el('p', 'kanban-meta', task.assignee));
    node.addEventListener('dragstart', event => {
      if (pending || loading) { event.preventDefault(); return; }
      dragging = task.key;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', task.key);
    });
    node.addEventListener('dragend', () => { dragging = null; });
    return node;
  }

  function draw() {
    columns.replaceChildren();
    for (const status of STATUSES) {
      const column = api.el('section', 'kanban-column');
      column.dataset.status = status;
      column.setAttribute('aria-label', status.replace('_', ' '));
      const rows = tasks.filter(task => task.status === status);
      if (status === 'done') rows.sort((a, b) =>
        (Date.parse(b.closed || b.updated) || 0) - (Date.parse(a.closed || a.updated) || 0));
      column.append(api.el('h3', '', `${status.replace('_', ' ')} (${rows.length})`));
      const shown = status === 'done' && !expanded ? rows.slice(0, 20) : rows;
      for (const task of shown) column.append(card(task));
      if (status === 'done' && rows.length > 20) {
        const more = api.el('button', 'btn kanban-more', expanded ? 'Show recent 20' : `Show all ${rows.length}`);
        more.setAttribute('aria-expanded', String(expanded));
        more.addEventListener('click', () => {
          if (pending || dragging) return;
          expanded = !expanded;
          draw();
        });
        column.append(more);
      }
      column.addEventListener('dragover', event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
      });
      column.addEventListener('drop', event => move(event, status));
      columns.append(column);
    }
  }

  async function load() {
    if (!root) {
      root = document.getElementById('viewKanban');
      refresh = api.el('button', 'btn', 'Refresh');
      refresh.addEventListener('click', () => { if (!pending && !dragging) return load(); });
      notice = api.el('div', 'kanban-notice');
      notice.setAttribute('role', 'status');
      columns = api.el('div', 'kanban');
      root.append(refresh, notice, columns);
    }
    if (loading) return;
    loading = true;
    try {
      const data = await api.getJSON('api/board/board');
      tasks = Array.isArray(data.tasks) ? data.tasks : [];
      draw();
    } catch (error) {
      notice.replaceChildren(api.el('p', '', `Could not refresh Kanban: ${error.message}. Previous snapshot retained.`));
    } finally { loading = false; }
  }

  function showWriteError(target, error, prefix = '') {
    target.replaceChildren(api.el('p', '', prefix + error.message));
    for (const item of error.payload?.missing || []) {
      target.append(api.el('p', '', String(item.field || '')),
                    api.el('pre', '', String(item.hint || '')));
    }
  }

  let drawer, detailContent, detailNotice, detailKey, detailAfter;
  let detailVersion = 0, saving = false, returnFocus;

  function closeCard() {
    detailVersion++;
    drawer.hidden = true;
    returnFocus?.focus();
  }

  function ensureDrawer() {
    if (drawer) return;
    drawer = api.el('aside', 'card-drawer');
    drawer.id = 'cardDrawer';
    drawer.setAttribute('aria-label', 'Card details');
    const close = api.el('button', 'btn', 'Close details');
    close.type = 'button';
    close.addEventListener('click', closeCard);
    window.addEventListener('keydown', ev => {
      if (!drawer.hidden && ev.key === 'Escape') { ev.preventDefault(); closeCard(); }
    });
    detailNotice = api.el('div', 'drawer-notice');
    detailNotice.setAttribute('role', 'status');
    detailContent = api.el('div', 'drawer-content');
    drawer.append(close, detailNotice, detailContent);
    document.getElementById('viewBoard').append(drawer);
  }

  // Public bridge for existing Tasks rows; afterSave refreshes their existing layout.
  // This is the only drawer global. It adds no node to the Tasks row itself.
  window.AGENTMUXOpenCard = openCard;
  async function openCard(key, afterSave = load) {
    if (!api) return;
    ensureDrawer();
    returnFocus = document.activeElement;
    drawer.hidden = false;
    detailKey = key;
    detailAfter = afterSave;
    saving = false;
    drawer.setAttribute('aria-busy', 'false');
    const version = ++detailVersion;
    detailNotice.replaceChildren();
    detailContent.replaceChildren(api.el('p', '', `Loading ${key}…`));
    try {
      const entity = await api.getJSON(`api/board/entity?id=${encodeURIComponent(key)}`);
      if (version !== detailVersion) return;
      renderDetail(entity);
      drawer.children[0].focus();
    } catch (error) {
      if (version === detailVersion) detailContent.replaceChildren(api.el('p', '', `Could not load ${key}: ${error.message}`));
    }
  }

  // Status wraps its entity; unchanged move and delete do not return one.
  async function writtenEntity(op, reply, key) {
    if (op === 'delete') return null;
    if (reply?.entity?.key === key) return reply.entity;
    if (reply?.key === key) return reply;
    return api.getJSON(`api/board/entity?id=${encodeURIComponent(key)}`);
  }

  async function writeDetail(op, fields) {
    if (saving) return;
    saving = true;
    const key = detailKey, version = detailVersion, after = detailAfter;
    let written = false;
    drawer.setAttribute('aria-busy', 'true');
    detailNotice.replaceChildren(api.el('p', '', 'Saving…'));
    try {
      const reply = await api.post(`api/board/${op}`, {id: key, ...fields, actor: 'dashboard'});
      const entity = await writtenEntity(op, reply, key);
      if (version !== detailVersion) return;
      if (!entity) closeCard();
      else {
        renderDetail(entity);
        detailNotice.replaceChildren(api.el('p', '', reply?.bypassed
          ? `Gate bypassed: ${reply.bypassed.reason || 'override'}` : 'Saved.'));
      }
      written = true;
    } catch (error) {
      if (version === detailVersion) showWriteError(detailNotice, error);
    } finally {
      if (version === detailVersion) { saving = false; drawer.setAttribute('aria-busy', 'false'); }
    }
    // The server response completes the write. A slow board refresh must not
    // silently discard the next edit made to the newly rendered entity.
    if (written) {
      try { await after(); }
      catch (error) {
        if (version === detailVersion) detailNotice.append(api.el('p', '', `Saved, but board refresh failed: ${error.message}`));
      }
    }
  }

  function control(label, value = '', type = 'text') {
    const wrap = api.el('label', 'drawer-field', label);
    const input = api.el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.value = value == null ? '' : String(value);
    input.setAttribute('aria-label', label);
    wrap.append(input);
    return {wrap, input};
  }

  function editor(field, label, inputs, op, values, remove = false) {
    const form = api.el('form', 'drawer-editor');
    form.dataset.field = field;
    for (const item of inputs) form.append(item.wrap);
    const save = api.el('button', 'btn', label);
    save.type = 'submit';
    form.append(save);
    form.addEventListener('submit', ev => { ev.preventDefault(); return writeDetail(op, values(true)); });
    if (remove) {
      const drop = api.el('button', 'btn', 'Remove');
      drop.type = 'button';
      drop.addEventListener('click', () => writeDetail(op, values(false)));
      form.append(drop);
    }
    detailContent.append(form);
  }

  function renderDetail(entity) {
    detailContent.replaceChildren(api.el('h2', '', `${entity.key} — ${entity.title || ''}`));
    // Never markAgent or data-agent here: hidden drawers precede first-match browser selectors.
    const meta = ['kind', 'actor', 'branch', 'worktree'].filter(k => entity[k])
      .map(k => `${k}: ${entity[k]}`).join(' · ');
    detailContent.append(api.el('p', 'drawer-meta', meta));
    const jira = entity.jira_key;
    const base = (document.getElementById('jiraBase')?.value || '').trim().replace(/\/+$/, '');
    let jiraURL;
    try {
      const parsed = new URL(base);
      if (parsed.protocol === 'https:' && !parsed.username && !parsed.password
          && parsed.pathname === '/' && !parsed.search && !parsed.hash
          && /^https:\/\/[^\s/]+$/.test(base)) jiraURL = parsed.origin;
    } catch (_) {}
    if (jira && /^[A-Z][A-Z0-9_]*-\d+$/.test(jira) && jiraURL) {
      const link = api.el('a', 'drawer-jira', jira);
      link.href = `${jiraURL}/browse/${encodeURIComponent(jira)}`;
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      detailContent.append(link);
    } else if (jira) detailContent.append(api.el('p', '', jira));

    for (const field of ['title', 'body', ...(entity.kind === 'task' ? ['assignee', 'priority', 'estimate'] : [])]) {
      const item = control(field, entity[field], field === 'body' ? 'textarea' : field === 'estimate' ? 'number' : 'text');
      if (field === 'estimate') { item.input.min = '0'; item.input.step = 'any'; }
      editor(field, `Save ${field}`, [item], 'update', () => ({patch: {
        [field]: field === 'estimate' ? (item.input.value === '' ? null : Number(item.input.value)) : item.input.value,
      }}));
    }
    const status = control('status', entity.status), reason = control('reason', '');
    editor('status', 'Change status', [status, reason], 'status', () => ({status: status.input.value, reason: reason.input.value}));

    const acceptance = api.el('section', 'drawer-acceptance');
    acceptance.append(api.el('h3', '', 'Acceptance'));
    (entity.acceptance || []).forEach((item, index) => {
      const row = api.el('div', 'drawer-criterion');
      row.dataset.index = String(index + 1);
      const label = api.el('label', '', item.text), tick = api.el('input');
      tick.type = 'checkbox'; tick.checked = !!item.done;
      tick.addEventListener('change', () => {
        const done = tick.checked;
        tick.checked = !!item.done; // The server, including a refusal, owns the checked state.
        return writeDetail('acceptance', {index: Number(row.dataset.index), done});
      });
      label.append(tick);
      const remove = api.el('button', 'btn', 'Remove criterion');
      remove.type = 'button';
      remove.addEventListener('click', () => writeDetail('acceptance', {index: Number(row.dataset.index), remove: true}));
      row.append(label, remove); acceptance.append(row);
    });
    detailContent.append(acceptance);
    const ac = control('New acceptance criterion');
    editor('acceptance', 'Add criterion', [ac], 'acceptance', () => ({text: ac.input.value}));

    const label = control('Label');
    editor('labels', 'Add label', [label], 'label', present => ({label: label.input.value, present}), true);
    if (entity.kind === 'task') {
      const dep = control('Blocking task');
      editor('deps', 'Add dependency', [dep], 'dep', present => ({blockedBy: dep.input.value, present}), true);
      const epic = control('Epic', entity.epic);
      editor('epic', 'Move to epic', [epic], 'move', () => ({epic: epic.input.value || null}));
    }
    for (const [field, op, key] of [['evidence', 'evidence', 'ref'], ['commits', 'commit', 'ref'], ['comments', 'comment', 'text'], ['touches', 'touch', 'path']]) {
      const item = control(field, '', field === 'comments' ? 'textarea' : 'text');
      editor(field, `Add ${field}`, [item], op, () => ({[key]: item.input.value}));
    }
    const type = control('Link type'), target = control('Link target');
    editor('links', 'Add link', [type, target], 'link', present => ({type: type.input.value, target: target.input.value, present}), true);
    for (const field of ['labels', 'blockedBy', 'evidence', 'commits', 'comments', 'links', 'touches']) {
      const section = api.el('section', 'drawer-values');
      section.append(api.el('h3', '', field === 'blockedBy' ? 'Dependencies' : field));
      for (const item of entity[field] || []) {
        section.append(api.el('p', '', typeof item === 'string' ? item
          : field === 'comments' ? `${item.author || ''} ${item.ts || ''}: ${item.text}`
          : `${item.type || ''}: ${item.id || ''}`));
      }
      detailContent.append(section);
    }
    const remove = api.el('button', 'btn drawer-delete', 'Delete card');
    remove.type = 'button';
    remove.addEventListener('click', () => { if (window.confirm(`Delete ${entity.key}?`)) return writeDetail('delete', {}); });
    detailContent.append(remove);
    void secondaryDetails(entity);
  }

  async function secondaryDetails(entity) {
    const version = detailVersion;
    const jobs = ['history', ...(entity.kind === 'task' ? ['why', 'roster'] : [])].map(name => {
      const section = api.el('section', 'drawer-secondary');
      section.dataset.section = name;
      section.append(api.el('h3', '', name === 'why' ? 'Readiness' : name === 'roster' ? 'Roster' : 'History'), api.el('p', '', 'Loading…'));
      detailContent.append(section);
      return {name, section};
    });
    await Promise.allSettled(jobs.map(async ({name, section}) => {
      const path = `api/board/${name}?id=${encodeURIComponent(entity.key)}${name === 'history' ? '&limit=200' : ''}`;
      try {
        const data = await api.getJSON(path);
        if (version !== detailVersion) return;
        const rows = name === 'history' ? data.events : name === 'roster' ? data.members : data.reasons;
        section.replaceChildren(section.children[0]);
        for (const row of rows || []) section.append(api.el('p', '', name === 'history'
          ? `${row.ts || ''} ${row.actor || ''} ${row.event || ''} ${Object.entries(row.detail || {}).map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`).join(' · ')}`
          : name === 'roster' ? `${row.agent_name || ''} · ${row.role || ''} · ${row.status || ''}` : row.text));
        if (!rows?.length) section.append(api.el('p', '', 'No entries.'));
      } catch (error) {
        if (version === detailVersion) section.replaceChildren(section.children[0], api.el('p', '', `Could not load ${name}: ${error.message}`));
      }
    }));
  }

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    // No polling: a redraw during dragging would detach the source node.
    api.registerPanel('board', 'kanban', load, 0);
  }, {once: true});
})();
