/* IIOT field panels: the shared Modbus tag table, and PROFINET station schema.
 *
 * Every panel on this view is a card with the same shape - a bold <h3> summary, a
 * body that only refreshes while the card's view is open, and no browser-local
 * configuration. What a panel is pointed at is server-side and shared, so two
 * people looking at the same dashboard are looking at the same thing.
 */

// ── Modbus ───────────────────────────────────────────────────────────────────
//
// One shared, persisted tag table. The server owns the poll; this renders what it
// has and shows explicitly whether each value is live or stale, because a number
// on screen with no age next to it is the single most dangerous thing a panel like
// this can display.
(() => {
  'use strict';
  const root = document.getElementById('modbusHint');
  if (!root) return;

  let api, status, editor, rows, writeEditor, actor, message;
  let config = null, initialized = false, snapshot = null, receivedAt = 0;

  function node(tag, text, parent) {
    const e = document.createElement(tag);
    if (text) e.textContent = text;
    (parent || root).appendChild(e);
    return e;
  }

  function build() {
    root.replaceChildren();
    node('p', 'Modbus TCP / RTU — zero-based addresses. Polling continues on the server.');
    status = node('p');
    status.className = 'field-state';
    status.setAttribute('aria-live', 'polite');
    node('p', 'Shared tag table (JSON). word_order: high = high word first; low = low word first. Scaling: raw × scale + offset.');

    const rtu = node('details');
    rtu.className = 'subcard';
    node('summary', 'Serial (RTU) transport', rtu);
    node('p', 'Replace host/port with transport: "rtu", device: "/dev/ttyUSB0", baud: 9600, parity: "E", stopbits: 1. Use one master per bus and an RS-485 adapter with automatic direction control. WSL2 USB adapters require usbipd attachment; a listed COM port does not guarantee access.', rtu);

    editor = node('textarea');
    editor.setAttribute('aria-label', 'Modbus tag table JSON');
    editor.rows = 12;
    editor.className = 'code-area';
    const example = {host: '127.0.0.1', port: 502, interval: 2, tags: [
      {name: 'Pressure', unit: 1, address: 0, function: 3, type: 'float32',
        word_order: 'high', scale: 1, offset: 0, engineering_unit: 'bar'}]};
    editor.value = JSON.stringify(example, null, 2);

    const bar = node('div');
    bar.className = 'row';
    const save = node('button', 'Save shared table', bar);
    save.className = 'btn';
    save.addEventListener('click', onSave);

    rows = node('div');
    rows.className = 'tag-rows';

    const write = node('details');
    write.className = 'subcard danger';
    node('summary', 'Explicit write — affects equipment', write);
    node('p', 'Raw coil/register values, functions 5, 6, 15 and 16. The target comes from the saved table, never from this box.', write);
    writeEditor = node('textarea', '', write);
    writeEditor.setAttribute('aria-label', 'Modbus write JSON');
    writeEditor.rows = 4;
    writeEditor.className = 'code-area';
    writeEditor.value = JSON.stringify({unit: 1, function: 6, address: 0, values: [0]}, null, 2);
    const writeBar = node('div', '', write);
    writeBar.className = 'row';
    actor = node('input', '', writeBar);
    actor.className = 'rin';
    actor.placeholder = 'Operator / actor (required)';
    actor.setAttribute('aria-label', 'Write actor');
    const go = node('button', 'Review and confirm write', writeBar);
    go.className = 'btn';
    go.addEventListener('click', () => onWrite(go));
    message = node('p', '', write);
    message.setAttribute('aria-live', 'polite');
  }

  async function call(path, body) {
    const response = await fetch(`/api/modbus/${path}`, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function render() {
    if (!snapshot || !status) return;
    const expired = config && Date.now() - receivedAt >= config.interval * 1000;
    const connected = snapshot.connected && !expired && snapshot.tags.every(t =>
      t.last_good !== null && Date.now() / 1000 - t.last_good < config.interval);
    status.textContent = `${connected ? 'CONNECTED' : 'DISCONNECTED'}${snapshot.error ? ': ' + snapshot.error : ''}`;
    status.dataset.state = connected ? 'ok' : 'bad';
    rows.replaceChildren();
    for (const tag of snapshot.tags) {
      const stale = !connected || tag.stale;
      const row = document.createElement('div');
      row.className = 'tag-row';
      row.dataset.stale = String(stale);
      const name = document.createElement('span');
      name.className = 'tag-name';
      name.textContent = tag.name;
      const value = document.createElement('span');
      value.className = 'tag-value';
      value.textContent = `${tag.value === null ? '—' : tag.value} ${tag.engineering_unit || ''}`.trim();
      const state = document.createElement('span');
      state.className = `status-chip ${stale ? 'bad' : 'ok'}`;
      state.textContent = stale ? 'STALE' : 'live';
      const seen = document.createElement('span');
      seen.className = 'tag-seen';
      seen.textContent = tag.last_good === null ? 'never read'
        : `last good ${new Date(tag.last_good * 1000).toLocaleTimeString()}`;
      row.append(name, value, state, seen);
      rows.appendChild(row);
    }
    if (!snapshot.tags.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'No tags in the shared table.';
      rows.appendChild(empty);
    }
  }

  async function onSave(event) {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await call('tags', JSON.parse(editor.value));
      message.textContent = 'Shared table saved.';
      await refresh();
    } catch (err) {
      message.textContent = err.message;
    } finally { button.disabled = false; }
  }


  // The current value of each register this write is about to overwrite, matched
  // out of the live tag table by unit + address. Returns null when nothing
  // matches, and the card then says so rather than implying it read something.
  function currentFor(unitId, address) {
    // `snapshot` is the module's existing poll result; no second copy.
    const tags = (snapshot && snapshot.tags) || [];
    return tags.find(t => t.unit === unitId && t.address === address) || null;
  }

  // ADR-0020: a confirmation is a CARD in the blade, never a browser dialog. A
  // dialog blocks the page, cannot render what is being overwritten, and cannot
  // be left open while you walk over and look at the panel.
  async function confirmWrite(body, where) {
    const blade = window.AGENTMUX_BLADE;
    const values = Array.isArray(body.values) ? body.values : [body.values];
    const rendering = values.map((after, i) => {
      const address = Number(body.address) + i;
      const tag = currentFor(body.unit, address);
      return {
        label: (tag && tag.name) ? `${tag.name} (${body.unit}:${address})`
                                 : `unit ${body.unit} address ${address}`,
        // The server's own staleness verdict. Never Date.now() minus a server
        // clock - that subtracts two different clocks and iiot.js:95 already
        // does it once too often.
        before: tag ? `${tag.value === null ? '—' : tag.value}`
                      + (tag.stale ? ' (stale)' : '') : null,
        after: String(after),
        unit: tag ? (tag.engineering_unit || '') : '',
        changed: !tag || String(tag.value) !== String(after),
      };
    });
    const anyRead = rendering.some(r => r.before !== null);

    if (!blade || typeof blade.confirm !== 'function') {
      // Degrade, but say so: a weaker gate that announces itself beats one that
      // silently replaces a stronger one.
      const ok = window.confirm(
        `The agent console is unavailable, so this is the weaker confirmation.\n\n`
        + `Write to physical device ${where}?\n${JSON.stringify(body, null, 2)}`);
      if (!ok) return;
      await send(body);
      return;
    }

    blade.confirm({
      kind: 'industrial_write',
      risk: 'critical',
      title: `Modbus write to ${where}`,
      action: {
        tool: `modbus function ${body.function}`,
        target: {system: 'modbus', device: where, path: `unit ${body.unit} @ ${body.address}`},
        after: values.join(', '),
      },
      rendering,
      readBackAt: anyRead ? 'as last polled' : null,
      killSwitch: {scope: 'industrial', engaged: false},
      onDecide: async (outcome) => {
        if (outcome !== 'committed') {
          message.textContent = 'Write rejected. Nothing was sent.';
          return;
        }
        await send(body);
      },
    });
    message.textContent = 'Waiting on your confirmation in the console →';
  }

  async function send(body) {
    try {
      await call('write', {...body, confirm: true});
      message.textContent = 'Write acknowledged and journalled.';
    } catch (err) {
      message.textContent = `${err.message} — do not retry an uncertain write without checking equipment.`;
    }
  }

  async function onWrite(button) {
    button.disabled = true;
    try {
      if (!config) throw new Error('Save a device configuration first.');
      if (!actor.value.trim()) throw new Error('Actor is required.');
      const body = {...JSON.parse(writeEditor.value), actor: actor.value.trim(),
        target: config.transport === 'rtu'
          ? Object.fromEntries(['transport', 'device', 'baud', 'parity', 'stopbits'].map(k => [k, config[k]]))
          : {host: config.host, port: config.port}};
      const where = config.transport === 'rtu' ? config.device : `${config.host}:${config.port}`;
      await confirmWrite(body, where);
    } catch (err) {
      message.textContent = `${err.message} — do not retry an uncertain write without checking equipment.`;
    } finally { button.disabled = false; }
  }

  async function refresh() {
    if (!status) build();
    try {
      snapshot = await call('tags');
      receivedAt = Date.now();
      config = snapshot.config;
      if (!initialized) {
        if (config) editor.value = JSON.stringify(config, null, 2);
        initialized = true;
      }
      render();
    } catch (err) {
      if (snapshot) snapshot.connected = false;
      render();
      if (status) {
        status.textContent = `DISCONNECTED: ${err.message}`;
        status.dataset.state = 'bad';
      }
    }
  }

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    // A second, every time the card's view is open - and NOTHING while it is not.
    // The old version recursed on a 100ms setTimeout that never stopped, so the
    // page kept polling a PLC from a tab nobody was looking at.
    api.registerCard('iiot', refresh, 1000);
  }, {once: true});
})();

// ── PROFINET DCP ─────────────────────────────────────────────────────────────
//
// Mirrors the Modbus panel deliberately: one shared server-side JSON document the
// team edits together, and a live table rendered against it. The difference is
// what "live" means. Modbus reads the device; DCP Identify needs a raw socket on a
// real NIC, which this unprivileged server does not have, so the observed side is
// an IMPORT and every part of this panel says so.
//
// The value it adds over a plain table is the reconciliation: expected against
// observed, joined on MAC, with mismatches first. Forty stations in a table do not
// answer "which one is wrong" by eye.
(() => {
  'use strict';
  const root = document.getElementById('profinetPanel');
  if (!root) return;

  let api, ui = null, state = null, notice = '';

  const HELP_IDENTIFY = 'sudo python3 taskmgmt/pn_dcp.py --iface eth0 identify > dcp.jsonl';
  const HELP_SET = [
    'sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac <MAC> --name <station-name>',
    'sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac <MAC> --ip <IP> --subnet <MASK> --gateway <GATEWAY>',
  ].join('\n');

  function build() {
    const {el} = api;
    root.replaceChildren();

    root.appendChild(el('p', '', 'Expected stations are a shared, server-side schema. Observed stations are an imported DCP Identify snapshot — not live device status. Nothing on this panel touches the plant network.'));

    const summary = el('div', 'field-state');
    summary.setAttribute('aria-live', 'polite');
    root.appendChild(summary);

    const table = el('table', 'dcp-table');
    const head = el('tr', '');
    for (const title of ['', 'MAC', 'Station name', 'IP', 'Subnet', 'Gateway', 'Vendor', 'Role']) {
      head.appendChild(el('th', '', title));
    }
    const thead = el('thead', '');
    thead.appendChild(head);
    const body = el('tbody', '');
    table.append(thead, body);
    root.appendChild(table);

    // -- the schema editor, shaped exactly like the Modbus tag table ----------
    const schemaBox = el('details', 'subcard');
    schemaBox.appendChild(el('summary', '', 'Expected stations (shared schema)'));
    schemaBox.appendChild(el('p', '', 'Saved on the server for everyone. Keys: segment, controller, stations[{mac, name, ip, subnet, gateway, vendor, role, note}]. MAC is required and is the join key — the station name is the field most likely to be wrong, so it cannot be the one things are matched on.'));
    const schemaEditor = el('textarea', 'code-area');
    schemaEditor.rows = 10;
    schemaEditor.setAttribute('aria-label', 'PROFINET station schema JSON');
    schemaBox.appendChild(schemaEditor);
    const schemaBar = el('div', 'row');
    const saveSchema = el('button', 'btn', 'Save shared schema');
    schemaBar.appendChild(saveSchema);
    schemaBox.appendChild(schemaBar);
    root.appendChild(schemaBox);

    // -- the import half ------------------------------------------------------
    const importBox = el('details', 'subcard');
    importBox.appendChild(el('summary', '', 'Import a DCP Identify snapshot'));
    importBox.appendChild(el('p', '', 'Run Identify on Linux with a real NIC on the plant segment. This dashboard stays unprivileged; WSL NAT cannot carry DCP frames.'));
    importBox.appendChild(el('pre', 'cmd-block', HELP_IDENTIFY));
    const input = el('textarea', 'code-area');
    input.rows = 6;
    input.setAttribute('aria-label', 'DCP JSON lines');
    input.placeholder = 'Paste the JSON lines from dcp.jsonl';
    importBox.appendChild(input);
    const importBar = el('div', 'row');
    const file = el('input', '');
    file.type = 'file';
    file.accept = '.jsonl,.json,application/json';
    file.setAttribute('aria-label', 'DCP saved output');
    const actor = el('input', 'rin');
    actor.placeholder = 'Operator / actor';
    actor.maxLength = 64;
    actor.setAttribute('aria-label', 'Import actor');
    const load = el('button', 'btn', 'Import snapshot');
    importBar.append(file, actor, load);
    importBox.appendChild(importBar);
    root.appendChild(importBox);

    // -- the write half, which stays a terminal action ------------------------
    const writeBox = el('details', 'subcard danger');
    writeBox.appendChild(el('summary', '', 'Changing a station — terminal only'));
    writeBox.appendChild(el('p', '', 'Set writes a running device permanently. Choose one explicit MAC yourself. The helper reads old values, displays the change, requires typing that MAC on the terminal, and journals the write. A wrong station name disconnects a machine from its controller.'));
    writeBox.appendChild(el('pre', 'cmd-block', HELP_SET));
    writeBox.appendChild(el('p', '', 'Journal: /var/log/pn-dcp.jsonl (or --journal PATH). After an unknown outcome, inspect the device and the journal before retrying. Reset-to-factory is intentionally unavailable.'));
    root.appendChild(writeBox);

    const status = el('p', '');
    status.setAttribute('aria-live', 'polite');
    root.appendChild(status);

    ui = {summary, body, schemaEditor, saveSchema, input, file, actor, load, status};

    saveSchema.addEventListener('click', onSaveSchema);
    load.addEventListener('click', () => onImport(input.value));
    file.addEventListener('change', async () => {
      const selected = file.files[0];
      if (!selected) return;
      if (selected.size > 1024 * 1024) { ui.status.textContent = 'Import failed: snapshot limit is 1 MiB.'; return; }
      const text = await selected.text();
      input.value = text;
      onImport(text);
    });
  }

  const STATUS_LABEL = {match: 'match', mismatch: 'MISMATCH', missing: 'MISSING',
                       unexpected: 'UNEXPECTED'};

  function render() {
    const {el} = api;
    if (!state) return;
    const counts = state.reconciliation.counts;
    const when = state.imported_at
      ? new Date(state.imported_at * 1000).toLocaleString()
      : 'never';
    ui.summary.dataset.state = (counts.mismatch || counts.missing) ? 'bad'
      : counts.unexpected ? 'warn' : 'ok';
    ui.summary.textContent =
      `${counts.match} matching, ${counts.mismatch} mismatched, ${counts.missing} missing, ` +
      `${counts.unexpected} unexpected · snapshot imported ${when}` +
      (state.imported_by ? ` by ${state.imported_by}` : '');

    ui.body.replaceChildren();
    for (const row of state.reconciliation.rows) {
      const tr = el('tr', `dcp-row ${row.status}`);
      const chip = el('span', `status-chip ${row.status === 'match' ? 'ok' : 'bad'}`,
                      STATUS_LABEL[row.status]);
      const first = el('td', '');
      first.appendChild(chip);
      tr.appendChild(first);
      const source = row.actual || row.expected;
      tr.appendChild(el('td', '', row.mac));
      for (const field of ['name', 'ip', 'subnet', 'gateway']) {
        const cell = el('td', '', source[field] == null ? '—' : String(source[field]));
        if (row.differences.includes(field)) {
          cell.className = 'diff';
          cell.title = `expected ${row.expected[field]}, observed ${row.actual[field] ?? 'nothing'}`;
          cell.appendChild(el('span', 'was', ` (expected ${row.expected[field]})`));
        }
        tr.appendChild(cell);
      }
      tr.appendChild(el('td', '', (source.vendor || '—')));
      tr.appendChild(el('td', '', (row.expected && row.expected.role) || '—'));
      ui.body.appendChild(tr);
    }
    if (!state.reconciliation.rows.length) {
      const tr = el('tr', '');
      const cell = el('td', 'empty', 'No expected stations and no imported snapshot yet.');
      cell.colSpan = 8;
      tr.appendChild(cell);
      ui.body.appendChild(tr);
    }
    if (document.activeElement !== ui.schemaEditor) {
      ui.schemaEditor.value = JSON.stringify(state.schema, null, 2);
    }
    if (notice) { ui.status.textContent = notice; notice = ''; }
  }

  async function onSaveSchema(event) {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      state = await api.post('api/profinet/schema', JSON.parse(ui.schemaEditor.value));
      notice = 'Shared schema saved.';
      render();
    } catch (err) {
      ui.status.textContent = `Save failed: ${err.message}`;
    } finally { button.disabled = false; }
  }

  // Parsed here, not on the server, so a bad line is named by NUMBER while the
  // operator still has the file in front of them.
  function parseLines(text) {
    if (text.length > 1024 * 1024) throw new Error('snapshot limit is 1 MiB');
    const lines = text.split(/\r?\n/).filter(line => line.trim());
    if (!lines.length || lines.length > 2000) throw new Error('provide 1-2000 JSON records');
    return lines.map((line, index) => {
      try { return JSON.parse(line); }
      catch (_) { throw new Error(`line ${index + 1} is not JSON`); }
    });
  }

  async function onImport(text) {
    ui.load.disabled = true;
    try {
      const records = parseLines(text);
      state = await api.post('api/profinet/snapshot',
                             {records, actor: ui.actor.value.trim() || null});
      notice = `Imported ${state.snapshot.length} station record(s). Snapshot only.`;
      render();
    } catch (err) {
      ui.status.textContent = `Import failed: ${err.message}`;
    } finally { ui.load.disabled = false; }
  }

  async function refresh() {
    if (!ui) build();
    try {
      state = await api.getJSON('api/profinet');
      render();
    } catch (err) {
      ui.status.textContent = `Station schema unavailable: ${err.message}`;
    }
  }

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    // No poll. The observed side only changes when somebody imports, and the
    // expected side only when somebody saves - re-fetching on a timer would imply
    // a liveness this panel does not have.
    api.registerCard('iiot', refresh, 0);
  }, {once: true});
})();
