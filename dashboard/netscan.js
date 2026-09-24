/* The Ethernet segment scanner.
 *
 * Answers the question you ask before pointing any other panel on this view at
 * anything: what is actually on this wire, and what does it speak. A device that
 * answers on 502 is a Modbus device; one that answers on 44818 is EtherNet/IP; one
 * that answers on neither is not the thing you were told it was.
 *
 * THE SCAN IS UNPRIVILEGED AND SAYS SO. Ordinary TCP connects, no raw frames, no
 * ICMP - none of which this server could do anyway. That has a real consequence
 * the panel states rather than hides: a device that is present but has every
 * scanned port closed will not appear. MAC addresses come from the host's own ARP
 * table afterwards, which the sweep itself populates for on-link addresses, so
 * they appear for devices on this segment and not for anything behind a router.
 *
 * PRIVATE RANGES ONLY, enforced on the server. A plant segment is private by
 * definition, so this costs nothing, and it means a mistyped prefix cannot point
 * the scanner at the public internet.
 *
 * AN OPERATOR NAME IS REQUIRED, and every scan is journalled with its range and
 * ports - a scan is a visible event on somebody else's network, and "what was
 * that traffic" deserves an answer a week later.
 */
(() => {
  'use strict';

  let api, ui = null, snap = null, notice = '';
  const root = document.getElementById('scanPanel');
  if (!root) return;

  // Remembered per browser: the range and operator name you scan from do not
  // change between visits, and retyping a CIDR every time is how a typo happens.
  const PREF_KEY = 'ccc.netscan.v1';
  function prefs() {
    try { return JSON.parse(localStorage.getItem(PREF_KEY) || '{}') || {}; }
    catch (_) { return {}; }
  }
  function savePrefs(next) {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(next)); } catch (_) {}
  }

  function build() {
    const {el} = api;
    const saved = prefs();
    root.replaceChildren();

    root.appendChild(el('p', '', 'TCP connect sweep of a private IPv4 range, plus the host’s ARP table for MAC and vendor. Unprivileged: a device with every scanned port closed will not appear, and MACs only resolve for devices on this segment.'));

    const bar = el('div', 'row');
    const range = el('input', 'rin');
    range.type = 'text'; range.size = 18; range.placeholder = '192.168.1.0/24';
    range.value = saved.range || '';
    range.setAttribute('aria-label', 'Range to scan');
    const actor = el('input', 'rin');
    actor.type = 'text'; actor.size = 14; actor.maxLength = 64;
    actor.placeholder = 'Operator / actor';
    actor.value = saved.actor || '';
    actor.setAttribute('aria-label', 'Operator name');
    const start = el('button', 'btn', 'Scan');
    const stop = el('button', 'btn', 'Stop');
    const download = el('button', 'btn', 'Export CSV');
    bar.append(range, actor, start, stop, download);
    root.appendChild(bar);

    const ports = el('details', 'subcard');
    ports.appendChild(el('summary', '', 'Ports to probe'));
    ports.appendChild(el('p', '', 'Tick what to ask for. Fewer ports is a faster and quieter scan; the defaults are the controls protocols worth asking about.'));
    const portBox = el('div', 'row wrap port-grid');
    ports.appendChild(portBox);
    // The ticked list is the protocols worth naming, not the only ports that exist.
    // A gateway on 8080 or a vendor service on 9600 is exactly the thing you are
    // hunting for when the standard ports come back empty.
    const extraRow = el('div', 'row');
    extraRow.appendChild(el('span', 'rlabel', 'Also probe'));
    const extra = el('input', 'rin');
    extra.type = 'text'; extra.size = 22;
    extra.placeholder = 'e.g. 8080, 9000-9002';
    extra.value = saved.extra || '';
    extra.setAttribute('aria-label', 'Additional ports');
    extraRow.appendChild(extra);
    ports.appendChild(extraRow);
    root.appendChild(ports);

    const progress = el('p', 'field-state');
    progress.setAttribute('aria-live', 'polite');
    root.appendChild(progress);

    const table = el('table', 'scan-table');
    const head = el('tr', '');
    for (const title of ['Address', 'Hostname', 'MAC', 'Vendor', 'Answers on']) {
      head.appendChild(el('th', '', title));
    }
    const thead = el('thead', '');
    thead.appendChild(head);
    const body = el('tbody', '');
    table.append(thead, body);
    root.appendChild(table);

    const status = el('p', '');
    status.setAttribute('aria-live', 'polite');
    root.appendChild(status);

    ui = {range, actor, start, stop, download, portBox, extra, progress, body, status,
          checks: new Map()};

    start.addEventListener('click', onStart);
    stop.addEventListener('click', onStop);
    download.addEventListener('click', onDownload);
    for (const field of [range, actor, extra]) {
      field.addEventListener('change', remember);
    }
  }

  function remember() {
    savePrefs({range: ui.range.value.trim(), actor: ui.actor.value.trim(),
               extra: ui.extra.value.trim(), ports: chosenPorts()});
  }

  function buildPorts() {
    const {el} = api;
    if (ui.checks.size || !snap) return;
    const saved = prefs().ports;
    const entries = Object.entries(snap.services)
      .map(([port, service]) => [Number(port), service])
      .sort((a, b) => a[0] - b[0]);
    for (const [port, service] of entries) {
      const label = el('label', 'toggle');
      const box = el('input', '');
      box.type = 'checkbox';
      box.checked = Array.isArray(saved) ? saved.includes(port)
        : snap.default_ports.includes(port);
      box.addEventListener('change', remember);
      label.append(box, document.createTextNode(` ${port} ${service}`));
      ui.checks.set(port, box);
      ui.portBox.appendChild(label);
    }
  }

  function chosenPorts() {
    return [...ui.checks.entries()].filter(([, box]) => box.checked).map(([port]) => port);
  }

  // "8080, 9000-9002" -> [8080, 9000, 9001, 9002]. Ranges are accepted because
  // that is how anybody writes a handful of neighbouring ports, and rejecting the
  // notation would just mean typing them out. A malformed entry is named rather
  // than dropped: silently scanning fewer ports than asked for reads as "nothing
  // is there", which is the one wrong answer this panel must not give.
  function extraPorts() {
    const text = ui.extra.value.trim();
    if (!text) return [];
    const out = [];
    for (const part of text.split(',')) {
      const piece = part.trim();
      if (!piece) continue;
      const range = /^(\d{1,5})\s*-\s*(\d{1,5})$/.exec(piece);
      const single = /^\d{1,5}$/.test(piece);
      if (!range && !single) throw new Error(`"${piece}" is not a port or a port range`);
      const low = Number(range ? range[1] : piece);
      const high = Number(range ? range[2] : piece);
      if (!(low >= 1 && high <= 65535 && low <= high)) {
        throw new Error(`"${piece}" is outside 1-65535`);
      }
      if (high - low > 64) throw new Error(`"${piece}" spans more than 64 ports`);
      for (let port = low; port <= high; port++) if (!out.includes(port)) out.push(port);
    }
    return out;
  }

  function allPorts() {
    const chosen = chosenPorts();
    return [...chosen, ...extraPorts().filter(port => !chosen.includes(port))];
  }

  function render() {
    const {el} = api;
    if (!snap) return;
    buildPorts();
    const running = snap.state === 'running';
    ui.start.disabled = running;
    ui.stop.disabled = !running;
    ui.download.disabled = !snap.hosts.length;

    const parts = [];
    if (running) {
      parts.push(`SCANNING ${snap.request.range}`);
      parts.push(`${snap.scanned} of ${snap.total} addresses`);
    } else if (snap.state === 'idle') {
      parts.push('IDLE');
    } else {
      parts.push(snap.state.toUpperCase());
      if (snap.request) parts.push(snap.request.range);
      parts.push(`${snap.hosts.length} host(s) answered of ${snap.total} scanned`);
      if (snap.finished_at) {
        parts.push(`finished ${new Date(snap.finished_at * 1000).toLocaleTimeString()}`);
      }
    }
    if (snap.error) parts.push(snap.error);
    if (!running && snap.hosts.length) {
      parts.push(`${snap.resolved}/${snap.hosts.length} MAC${snap.resolved === 1 ? '' : 's'} resolved`);
    }
    ui.progress.textContent = parts.join(' · ');

    // WHERE THE MACs CAME FROM, SAID OUT LOUD. A TCP scan cannot see layer 2; the
    // addresses come from an ARP cache. Under WSL2's NAT this machine is not on
    // the plant segment at all, so its own cache holds one useless entry and the
    // real table is the Windows host's, one NAT hop away. Presenting those as
    // something this host observed would be a small lie in the one column an
    // operator uses to identify a device.
    const existing = root.querySelector('.scan-note');
    if (existing) existing.remove();
    if (snap.mac_source && snap.mac_source !== 'this host') {
      const note = el('p', 'scan-note hint',
        `MAC addresses read from ${snap.mac_source}. A device this machine has `
        + `never exchanged traffic with will have no MAC here, and none of them are `
        + `observed by this scan directly.`);
      ui.progress.after(note);
    } else if (snap.under_wsl && !running && snap.hosts.length && !snap.resolved) {
      const note = el('p', 'scan-note hint',
        'No MAC addresses resolved. This machine is behind a NAT, so it is not on '
        + 'the scanned segment and has no ARP entries for it.');
      ui.progress.after(note);
    }
    ui.progress.dataset.state = snap.state === 'error' ? 'bad'
      : running ? 'warn' : snap.state === 'done' ? 'ok' : '';

    ui.body.replaceChildren();
    for (const host of snap.hosts) {
      const row = el('tr', '');
      row.appendChild(el('td', 'mono', host.address));
      row.appendChild(el('td', '', host.hostname || '—'));
      row.appendChild(el('td', 'mono', host.mac || '—'));
      row.appendChild(el('td', '', host.vendor || (host.mac ? 'unknown OUI' : '—')));
      const services = el('td', '');
      for (const entry of host.ports) {
        const chip = el('span', 'status-chip', `${entry.port} ${entry.service}`);
        chip.title = `TCP ${entry.port} accepted a connection`;
        services.appendChild(chip);
      }
      row.appendChild(services);
      ui.body.appendChild(row);
    }
    if (!snap.hosts.length) {
      const row = el('tr', '');
      const cell = el('td', 'empty', snap.state === 'done'
        ? 'Nothing answered on the chosen ports. A device with all of them closed is invisible to this scan.'
        : 'No results yet.');
      cell.colSpan = 5;
      row.appendChild(cell);
      ui.body.appendChild(row);
    }
    if (notice) { ui.status.textContent = notice; notice = ''; }
  }

  async function onStart() {
    let ports;
    try {
      ports = allPorts();
    } catch (err) {
      ui.status.textContent = err.message;
      return;
    }
    if (!ports.length) { ui.status.textContent = 'Choose at least one port to probe.'; return; }
    const range = ui.range.value.trim();
    if (!window.confirm(
        `Scan ${range}?\n\nThis opens a TCP connection to every address in that range on `
        + `${ports.length} port(s). It is visible on the network and is journalled `
        + `against your name.`)) return;
    ui.start.disabled = true;
    try {
      snap = await api.post('api/netscan/start',
                            {range, ports, actor: ui.actor.value.trim()});
      notice = 'Scan started.';
      render();
    } catch (err) {
      ui.status.textContent = err.message;
      ui.start.disabled = false;
    }
  }

  async function onStop() {
    try {
      snap = await api.post('api/netscan/stop', {});
      notice = 'Stop requested. Addresses already in flight will still finish.';
      render();
    } catch (err) { ui.status.textContent = err.message; }
  }

  function onDownload() {
    if (!snap || !snap.hosts.length) return;
    const rows = [];
    for (const host of snap.hosts) {
      for (const entry of host.ports) {
        rows.push({address: host.address, hostname: host.hostname || '',
                   mac: host.mac || '', vendor: host.vendor || '',
                   port: entry.port, service: entry.service});
      }
    }
    const header = 'address,hostname,mac,vendor,port,service';
    const cell = (value) => /[",\n]/.test(String(value))
      ? `"${String(value).replace(/"/g, '""')}"` : String(value);
    const csv = [header, ...rows.map(r => Object.values(r).map(cell).join(','))].join('\r\n') + '\r\n';
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    api.download(`ccc-scan-${stamp}.csv`, csv, 'text/csv;charset=utf-8');
    notice = `Exported ${rows.length} row(s).`;
    render();
  }

  async function refresh() {
    if (!ui) build();
    try {
      snap = await api.getJSON('api/netscan');
      render();
    } catch (err) {
      ui.progress.textContent = `Scanner unavailable: ${err.message}`;
      ui.progress.dataset.state = 'bad';
    }
  }

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    api.registerCard('iiot', refresh, 1500);
  }, {once: true});
})();
