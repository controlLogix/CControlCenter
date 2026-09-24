/* Shared server-side Modbus tag table. No browser-local configuration. */
(() => {
  'use strict';
  const root = document.getElementById('modbusHint');
  if (!root) return;
  root.replaceChildren();
  function node(tag, text, parent = root) {
    const e = document.createElement(tag);
    if (text) e.textContent = text;
    parent.appendChild(e);
    return e;
  }
  node('p', 'Modbus TCP — zero-based addresses. Polling continues on the server.');
  const status = node('p');
  status.setAttribute('aria-live', 'polite');
  node('p', 'Shared tag table (JSON). word_order: high = high word first; low = low word first. Scaling: raw × scale + offset.');
  const editor = node('textarea');
  editor.setAttribute('aria-label', 'Modbus tag table JSON');
  editor.rows = 12;
  editor.style.width = '100%';
  const example = {host: '127.0.0.1', port: 502, interval: 2, tags: [
    {name: 'Pressure', unit: 1, address: 0, function: 3, type: 'float32',
      word_order: 'high', scale: 1, offset: 0, engineering_unit: 'bar'}]};
  editor.value = JSON.stringify(example, null, 2);
  const save = node('button', 'Save shared table');
  save.className = 'btn';
  const rows = node('div');
  node('p', 'Explicit write — raw coil/register values. Functions 5, 6, 15, 16. Writes affect equipment.');
  const writeEditor = node('textarea');
  writeEditor.setAttribute('aria-label', 'Modbus write JSON');
  writeEditor.rows = 4;
  writeEditor.style.width = '100%';
  writeEditor.value = JSON.stringify({unit: 1, function: 6, address: 0, values: [0]}, null, 2);
  const actor = node('input');
  actor.placeholder = 'Operator / actor (required)';
  actor.setAttribute('aria-label', 'Write actor');
  const write = node('button', 'Review and confirm write');
  write.className = 'btn';
  const message = node('p');
  message.setAttribute('aria-live', 'polite');
  let config = null, initialized = false, snapshot = null, receivedAt = 0;
  async function api(path, body) {
    const response = await fetch(`/api/modbus/${path}`, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function render() {
    if (!snapshot) return;
    const expired = config && Date.now() - receivedAt >= config.interval * 1000;
    const connected = snapshot.connected && !expired && snapshot.tags.every(t =>
      t.last_good !== null && Date.now()/1000 - t.last_good < config.interval);
    status.textContent = `${connected ? 'CONNECTED' : 'DISCONNECTED'}${snapshot.error ? ': ' + snapshot.error : ''}`;
    rows.replaceChildren();
    for (const tag of snapshot.tags) {
      const stale = !connected || tag.stale;
      const row = node('p', `${tag.name}: ${tag.value === null ? '—' : tag.value} ${tag.engineering_unit} — ${stale ? 'STALE' : 'live'} — last good: ${tag.last_good === null ? 'never' : new Date(tag.last_good * 1000).toLocaleString()}`, rows);
      row.dataset.stale = String(stale);
      if (stale) row.style.fontWeight = 'bold';
    }
  }
  async function refresh() {
    try {
      snapshot = await api('tags'); receivedAt = Date.now(); config = snapshot.config;
      if (!initialized) {
        if (config) editor.value = JSON.stringify(config, null, 2);
        initialized = true;
      }
      render();
    } catch (err) {
      if (snapshot) snapshot.connected = false;
      render(); status.textContent = `DISCONNECTED: ${err.message}`;
    } finally { setTimeout(refresh, 100); }
  }
  save.addEventListener('click', async () => {
    save.disabled = true;
    try { await api('tags', JSON.parse(editor.value)); message.textContent = 'Shared table saved.'; }
    catch (err) { message.textContent = err.message; }
    finally { save.disabled = false; }
  });
  write.addEventListener('click', async () => {
    write.disabled = true;
    try {
      if (!config) throw new Error('Save a device configuration first.');
      if (!actor.value.trim()) throw new Error('Actor is required.');
      const body = {...JSON.parse(writeEditor.value), actor: actor.value.trim(),
        target: {host: config.host, port: config.port}};
      if (!window.confirm(`Write to physical device ${body.target.host}:${body.target.port}?\n${JSON.stringify(body, null, 2)}`)) return;
      await api('write', {...body, confirm: true});
      message.textContent = 'Write acknowledged and journalled.';
    } catch (err) { message.textContent = `${err.message} — do not retry an uncertain write without checking equipment.`; }
    finally { write.disabled = false; }
  });
  setInterval(render, 50);
  refresh();
})();
