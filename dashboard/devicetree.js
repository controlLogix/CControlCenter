/* The device tree: several kinds of knowing, rendered so they never look alike.
 *
 * WHAT THIS PANEL IS FOR. The Ethernet scanner above it answers "what is
 * listening?" - a TCP connect and an OUI lookup. That is an INFERENCE. CIP
 * ListIdentity answers "what are you?" - the device's own vendor, product,
 * revision and serial. That is a STATEMENT. Both are useful and they are not
 * the same thing, so every row here says which one it is standing on.
 *
 * The rule this panel follows, and the reason it exists at all: a guess and a
 * statement must never be rendered with the same confidence. It is the same
 * rule as the age on the tag table. A screen that looks equally sure about
 * both is worse than one that shows less, because the operator cannot tell
 * which half to trust and eventually stops trusting either.
 *
 * DISAGREEMENT IS SHOWN, NEVER RESOLVED. If the OUI table and the device give
 * different vendors, both appear and the row is marked. Picking a winner is how
 * the wrong one ends up on screen with nothing to say it was ever in doubt.
 *
 * NOTHING HERE PUTS TRAFFIC ON A WIRE BY ITSELF. The tree is a GET over what is
 * already known. Discovery is a button, because a UDP broadcast onto a plant
 * segment should never happen because somebody opened a tab.
 */
(() => {
  'use strict';
  const root = document.getElementById('devicePanel');
  if (!root) return;

  let api, status, groups, discoverBtn, message;
  let snapshot = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function build() {
    root.replaceChildren();
    const intro = el('p', null,
      'The Ethernet scan and CIP discovery, merged. Every row says which of them '
      + 'reported it: a device that answered ListIdentity told you what it is, one '
      + 'with only an open port did not.');
    root.appendChild(intro);

    status = el('p');
    status.className = 'field-state';
    status.setAttribute('aria-live', 'polite');
    root.appendChild(status);

    const bar = el('div', 'row');
    discoverBtn = el('button', 'btn', 'Discover (CIP broadcast)');
    discoverBtn.title = 'Sends one UDP ListIdentity broadcast on this segment and '
      + 'records what answers. Read-only: ListIdentity has no write form.';
    discoverBtn.addEventListener('click', () => onDiscover());
    bar.appendChild(discoverBtn);
    root.appendChild(bar);

    message = el('p', 'muted', '');
    message.setAttribute('aria-live', 'polite');
    root.appendChild(message);

    groups = el('div', 'device-groups');
    root.appendChild(groups);
  }

  // ── the two empty states, which are different answers ──────────────────────
  //
  // "Nothing has scanned yet" and "the scan found nothing" mean opposite things
  // and used to look identical everywhere in this dashboard. An empty list with
  // no explanation reads as the second when it is usually the first.
  function emptyText(snap) {
    const scanned = snap.scan_state && snap.scan_state !== 'idle';
    const discovered = snap.discovery && snap.discovery.at;
    if (!scanned && !discovered) {
      return 'Nothing has looked yet. Run the Ethernet scanner above, or press '
           + 'Discover for a CIP broadcast.';
    }
    return 'Nothing answered. The scan and discovery ran and found no devices on '
         + 'this segment.';
  }

  function sourceChip(source) {
    const chip = el('span', 'src-chip', source);
    chip.dataset.source = source;
    // The tooltip is where the distinction is actually spelled out, because the
    // chip has room for a name and not for a caveat.
    chip.title = {
      'cip-listidentity': 'The device answered a broadcast with its own vendor, '
        + 'product, revision and serial. It told you.',
      'segment-scan': 'A TCP connect succeeded and the MAC resolved through an OUI '
        + 'table. Something is listening and the NIC was sold by that vendor - '
        + 'that is an inference, not the device speaking.',
      'opcua-endpoints': 'The device listed its OPC UA endpoints. Self-reported, '
        + 'and optional: the embedded server is firmware- and SKU-dependent.',
      'promoted': 'You already saved this one to the device list.',
    }[source] || source;
    return chip;
  }

  function renderDevice(device) {
    const row = el('div', 'device-row');
    row.dataset.selfReported = String(device.sources.includes('cip-listidentity')
      || device.sources.includes('opcua-endpoints'));

    const head = el('div', 'device-head');
    head.appendChild(el('span', 'device-addr', device.address));

    const identity = device.identity || {};
    // What it calls itself, or the honest absence of that. Never a blank.
    const name = identity.product_name || device.hostname;
    head.appendChild(el('span', 'device-name', name || 'unidentified'));
    if (!name) {
      head.lastChild.title = 'Nothing reported a product name or a hostname for '
        + 'this address. It is an open port, not a known device.';
    }

    const chips = el('span', 'device-sources');
    for (const source of device.sources) chips.appendChild(sourceChip(source));
    head.appendChild(chips);
    row.appendChild(head);

    const detail = el('div', 'device-detail');
    if (device.vendor) {
      // The vendor ALWAYS travels with where it came from. A vendor with no
      // provenance beside it is the exact thing this panel exists to avoid.
      detail.appendChild(el('span', 'kv', `vendor: ${device.vendor}`));
      detail.appendChild(el('span', 'kv-src', `(${device.vendor_source})`));
    }
    for (const [label, value] of [['rev', identity.revision], ['serial', identity.serial],
                                  ['type', identity.device_type]]) {
      if (value) detail.appendChild(el('span', 'kv', `${label}: ${value}`));
    }
    if (device.ports.length) {
      detail.appendChild(el('span', 'kv',
        'ports: ' + device.ports.map(p => `${p.port}/${p.service}`).join(', ')));
    }
    row.appendChild(detail);

    // Disagreement, shown rather than resolved.
    for (const conflict of device.conflicts) {
      const warn = el('div', 'device-conflict');
      warn.appendChild(el('span', 'conflict-label', `${conflict.field}: sources disagree`));
      for (const entry of conflict.values) {
        warn.appendChild(el('span', 'conflict-value', `${entry.value} — ${entry.source}`));
      }
      row.appendChild(warn);
    }

    if (device.promoted) {
      row.appendChild(el('div', 'device-saved',
        `saved as "${device.promoted.name}" (${device.promoted.protocol || 'no protocol'})`));
    }
    return row;
  }

  function render() {
    if (!snapshot || !status) return;
    const snap = snapshot;
    const scanned = snap.scan_state && snap.scan_state !== 'idle';
    const discovery = snap.discovery || {};

    // The banner says what has actually happened, so an empty tree is never
    // mistaken for an answer about the network.
    const parts = [];
    parts.push(scanned ? `scan: ${snap.scan_state}` : 'scan: not run');
    if (discovery.available === false) {
      parts.push(`CIP discovery unavailable: ${discovery.error || 'unknown'}`);
    } else if (discovery.at) {
      parts.push(`CIP discovery: ${discovery.count} answered`);
    } else {
      parts.push('CIP discovery: not run');
    }
    if (snap.conflicts) parts.push(`${snap.conflicts} disagreement(s)`);
    status.textContent = parts.join(' · ');
    status.dataset.state = snap.conflicts ? 'warn'
      : (snap.total ? 'ok' : 'idle');

    groups.replaceChildren();
    if (!snap.total) {
      groups.appendChild(el('p', 'empty', emptyText(snap)));
      return;
    }
    for (const group of snap.groups) {
      const block = el('div', 'device-group');
      const heading = el('h4', null, group.network);
      // The count that matters: how many told us what they are, versus how many
      // merely answered a port.
      heading.appendChild(el('span', 'group-count',
        `${group.count} found · ${group.self_reported} identified themselves`));
      block.appendChild(heading);
      for (const device of group.devices) block.appendChild(renderDevice(device));
      groups.appendChild(block);
    }
  }

  async function onDiscover() {
    discoverBtn.disabled = true;
    message.textContent = 'Broadcasting ListIdentity…';
    try {
      const response = await fetch('/api/devices/discover', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      message.textContent = `${data.count} device(s) answered.`;
      await refresh();
    } catch (err) {
      // Named, not swallowed. A discovery that could not run is a different
      // fact from one that found nothing.
      message.textContent = `Discovery did not run: ${err.message}`;
    } finally {
      discoverBtn.disabled = false;
    }
  }

  async function refresh() {
    if (!status) build();
    try {
      const response = await fetch('/api/devices/tree');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      snapshot = await response.json();
      render();
    } catch (err) {
      if (status) {
        status.textContent = `Could not read the device tree: ${err.message}`;
        status.dataset.state = 'bad';
      }
    }
  }

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    // Slower than the tag table: this merges what other panels have already
    // gathered and nothing here is time-critical.
    api.registerCard('iiot', refresh, 4000);
  }, {once: true});
})();
