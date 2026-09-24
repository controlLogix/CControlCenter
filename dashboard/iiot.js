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
  node('p', 'Modbus TCP / RTU — zero-based addresses. Polling continues on the server.');
  const status = node('p');
  status.setAttribute('aria-live', 'polite');
  node('p', 'Shared tag table (JSON). word_order: high = high word first; low = low word first. Scaling: raw × scale + offset.');
  node('p', 'For RTU, replace host/port with transport: \"rtu\", device: \"/dev/ttyUSB0\", baud: 9600, parity: \"E\", stopbits: 1. Use one master per bus and an RS-485 adapter with automatic direction control. WSL2 USB adapters require usbipd attachment; a listed COM port does not guarantee access.');
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
        target: config.transport === 'rtu'
          ? Object.fromEntries(['transport', 'device', 'baud', 'parity', 'stopbits'].map(k => [k, config[k]]))
          : {host: config.host, port: config.port}};
      if (!window.confirm(`Write to physical device ${config.transport === 'rtu' ? config.device : `${config.host}:${config.port}`}?\n${JSON.stringify(body, null, 2)}`)) return;
      await api('write', {...body, confirm: true});
      message.textContent = 'Write acknowledged and journalled.';
    } catch (err) { message.textContent = `${err.message} — do not retry an uncertain write without checking equipment.`; }
    finally { write.disabled = false; }
  });
  setInterval(render, 50);
  refresh();
})();

/* PROFINET DCP is a privileged, operator-run helper. Import snapshots only. */
(() => {
  'use strict';
  const root = document.querySelector('#viewIiot .iiot-grid');
  if (!root) return;
  function element(tag, text, parent) {
    const e = document.createElement(tag);
    if (text) e.textContent = text;
    parent.appendChild(e);
    return e;
  }
  const panel = element('details', '', root);
  panel.className = 'card'; panel.open = true;
  panel.dataset.collapseKey = 'iiot:dcp';
  element('summary', 'PROFINET DCP', panel);
  element('p', 'Run Identify on Linux with a real NIC on the plant segment. This dashboard stays unprivileged; WSL NAT cannot carry DCP frames.', panel);
  element('code', 'sudo python3 taskmgmt/pn_dcp.py --iface eth0 identify > dcp.jsonl', panel);
  element('p', 'Paste JSON lines or load the saved output. These are imported snapshots, not live device status. Nothing is sent to the plant network by this panel.', panel);
  const input = element('textarea', '', panel);
  input.rows = 6; input.style.width = '100%';
  input.setAttribute('aria-label', 'DCP JSON lines');
  const file = element('input', '', panel);
  file.type = 'file'; file.accept = '.jsonl,.json,application/json';
  file.setAttribute('aria-label', 'DCP saved output');
  const load = element('button', 'Import DCP snapshot', panel);
  load.className = 'btn';
  const status = element('p', '', panel);
  status.setAttribute('aria-live', 'polite');
  const table = element('table', '', panel);
  const columns = ['mac', 'name', 'ip', 'subnet', 'gateway', 'vendor', 'vendor_id', 'device_id', 'at'];
  const head = element('tr', '', element('thead', '', table));
  for (const title of ['MAC', 'Station name', 'IP', 'Subnet', 'Gateway', 'Vendor', 'Vendor ID', 'Device ID', 'Observed at']) {
    element('th', title, head);
  }
  const body = element('tbody', '', table);
  function render(text) {
    if (text.length > 1024 * 1024) throw new Error('Snapshot limit is 1 MiB.');
    const lines = text.split(/\r?\n/).filter(line => line.trim());
    if (!lines.length || lines.length > 2000) throw new Error('Provide 1–2000 JSON records.');
    const records = lines.map((line, index) => {
      const r = JSON.parse(line);
      if (!r || r.kind !== 'dcp-identify' || !/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(r.mac) ||
          columns.some(key => r[key] !== null && r[key] !== undefined && !['string', 'number'].includes(typeof r[key]))) {
        throw new Error(`Line ${index + 1}: expected DCP Identify output.`);
      }
      return r;
    });
    body.replaceChildren();
    for (const r of records) {
      const row = element('tr', '', body);
      for (const key of columns) element('td', r[key] == null ? '—' : String(r[key]), row);
    }
    status.textContent = `Imported ${records.length} station record(s). Snapshot only.`;
  }
  load.addEventListener('click', () => {
    try { render(input.value); }
    catch (err) { status.textContent = `Import failed: ${err.message}`; }
  });
  file.addEventListener('change', async () => {
    try {
      const selected = file.files[0];
      if (!selected) return;
      if (selected.size > 1024 * 1024) throw new Error('Snapshot limit is 1 MiB.');
      const text = await selected.text();
      render(text); input.value = text;
    } catch (err) { status.textContent = `Import failed: ${err.message}`; }
  });
  element('p', 'Set writes a running device permanently. Choose one explicit MAC yourself. The helper reads old values, displays the change, requires typing that MAC on the terminal, and journals the write. A wrong station name can disconnect a machine from its controller.', panel);
  element('pre', 'sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac <MAC> --name <station-name>\n' +
    'sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac <MAC> --ip <IP> --subnet <MASK> --gateway <GATEWAY>', panel);
  element('p', 'Journal: /var/log/pn-dcp.jsonl (or --journal PATH). After an unknown outcome, inspect the device and journal before retrying. Reset-to-factory is intentionally unavailable.', panel);
})();
