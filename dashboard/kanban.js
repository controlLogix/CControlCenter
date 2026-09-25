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
      // The shell post helper discards structured 409 remedies. Keep every hint.
      const response = await fetch('api/board/status', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: key, status: destination, actor: 'dashboard'}),
      });
      const reply = await response.json();
      if (!response.ok) {
        notice.replaceChildren(api.el('p', '', reply.error || `HTTP ${response.status}`));
        for (const item of reply.missing || []) {
          notice.append(api.el('p', '', String(item.field || '')),
                        api.el('pre', '', String(item.hint || '')));
        }
        return;
      }
      notice.replaceChildren(api.el('p', '', `${key} moved to ${destination.replace('_', ' ')}.`));
      await load(); // Only the accepted server snapshot can relocate a card.
    } catch (error) {
      notice.replaceChildren(api.el('p', '', `Could not move ${key}: ${error.message}`));
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
    node.append(api.el('strong', 'board-key', task.key),
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

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    // No polling: a redraw during dragging would detach the source node.
    api.registerPanel('board', 'kanban', load, 0);
  }, {once: true});
})();
