/* TM-081: one server-merged snapshot, identity-keyed collapsed conversations. */
(() => {
  'use strict';
  let api, root, list, status, agent, card, state, recipient, text, ref, result;
  let entries = [], loading = false;
  function draw() {
    list.replaceChildren();
    const groups = new Map();
    const shown = [];
    for (const row of entries) {
      if (agent.value && ![row.sender, row.recipient].includes(agent.value)) continue;
      if (card.value && row.ref !== card.value) continue;
      if (state.value && row.state !== state.value) continue;
      shown.push(row);
      if (!groups.has(row.thread)) groups.set(row.thread, []);
      groups.get(row.thread).push(row);
    }
    // Status owns the export button; every tab hands it what it is showing.
    api.publishRows('chatter', shown);
    for (const [id, rows] of groups) {
      const first = rows[0];
      const thread = api.collapsible(`chatter:thread:${id}`, 'chatter-thread', false);
      thread.append(api.el('summary', '', `${first.pair.join(' ↔ ')} · ${first.ref || 'No card'} · ${rows.length} events`));
      for (const row of rows) {
        const item = api.collapsible(`chatter:message:${row.id}`, `chatter-item state-${row.state}`, false);
        const summary = api.el('summary', '', `${row.at} · ${row.sender} → ${row.recipient || 'broadcast'} · `);
        summary.append(api.el('strong', '', row.state), document.createTextNode(` · ${row.kind}`));
        item.append(summary, api.el('pre', '', row.body));
        item.append(api.el('p', '', [row.reason, row.attempts != null ? `Attempts: ${row.attempts}` : '',
          row.next_at ? `Next attempt: ${new Date(row.next_at * 1000).toLocaleString()}` : '',
          `Sources: ${(row.sources || [row.source]).join(', ')}`].filter(Boolean).join(' · ')));
        thread.append(item);
      }
      list.append(thread);
    }
    if (!groups.size) list.append(api.el('p', 'empty', entries.length ? 'Nothing matches these filters.' : 'No conversation history yet.'));
  }
  function select(label, parent) {
    const wrap = api.el('label', '', label + ' '), input = api.el('select', '');
    wrap.append(input); parent.append(wrap);
    input.addEventListener('change', draw);
    return input;
  }
  function options(input, values) {
    const previous = input.value;
    input.replaceChildren();
    for (const value of ['', ...new Set([...values, ...(previous ? [previous] : [])])]) {
      const option = api.el('option', '', value || 'All'); option.value = value; input.append(option);
    }
    input.value = previous;
  }
  function field(label, tag, parent) {
    const wrap = api.el('label', '', label + ' '), input = api.el(tag, '');
    wrap.append(input); parent.append(wrap); return input;
  }
  function setup() {
    root = document.getElementById('viewChatter');
    const style = api.el('style', '');
    style.textContent = '#viewChatter{padding:16px}.chatter-controls,.chatter-compose{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.chatter-compose textarea{min-width:280px;min-height:70px}.chatter-thread{margin:8px 0;padding:10px;border:1px solid currentColor}.chatter-item{margin:8px;padding:8px;border-left:4px solid #888}.chatter-item pre{white-space:pre-wrap;overflow-wrap:anywhere}.state-delivered{border-color:#3a8}.state-queued{border-color:#59d}.state-retried{border-color:#da4}.state-dropped{border-color:#e55}.state-dead-recipient{border-color:#b6d}#viewChatter summary{cursor:pointer}';
    root.append(style);
    status = api.el('p', ''); status.setAttribute('role', 'status'); root.append(status);
    const controls = api.el('div', 'chatter-controls'); root.append(controls);
    agent = select('Agent', controls); card = select('Card', controls); state = select('State', controls);
    const refresh = api.el('button', '', 'Refresh'); refresh.addEventListener('click', load); controls.append(refresh);
    const form = api.el('form', 'chatter-compose'); root.append(form);
    recipient = field('Recipient', 'input', form); recipient.required = true; recipient.maxLength = 64;
    ref = field('Card (optional)', 'input', form); ref.maxLength = 256;
    text = field('Message', 'textarea', form); text.required = true; text.maxLength = 8192;
    const send = api.el('button', '', 'Send to pane'); send.type = 'submit'; form.append(send);
    result = api.el('p', ''); result.setAttribute('role', 'status'); root.append(result);
    form.addEventListener('submit', async event => {
      event.preventDefault(); send.disabled = true; result.textContent = 'Sending…';
      try {
        const reply = await api.post('api/board/chatsend', {recipient: recipient.value.trim(), text: text.value, ref: ref.value.trim()});
        result.textContent = reply.ok ? reply.detail : `${reply.error} Inspect the pane, then answer deliberately with: ${reply.key_hint}`;
        if (reply.ok) { text.value = ''; await load(); }
      } catch (error) { result.textContent = error.message; }
      finally { send.disabled = false; }
    });
    list = api.el('div', 'chatter-list'); root.append(list);
  }
  async function load() {
    if (!root) setup();
    if (loading) return;
    loading = true;
    try {
      const data = await api.getJSON('api/board/chatter?limit=2000');
      entries = data.entries || [];
      options(agent, data.agents || []); options(card, data.cards || []); options(state, data.states || []);
      status.textContent = `${entries.length} of ${data.total} recent events. ${data.note || ''}`;
      draw();
    } catch (error) { status.textContent = `Could not refresh chatter: ${error.message}. Previous snapshot retained.`; }
    finally { loading = false; }
  }
  window.addEventListener('ccc:ready', () => {
    api = window.CCC; api.registerPanel('status', 'chatter', load, 5000);
  }, {once: true});
})();
