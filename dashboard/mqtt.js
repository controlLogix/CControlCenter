/* MQTT: a live topic monitor and browser.
 *
 * WHAT THIS REPLACED, AND WHY IT HAD TO GO. The old panel had two buttons. One
 * published. The other "subscribed" - meaning it opened a socket, listened for
 * three seconds, closed it, and printed whatever happened to arrive in that
 * window, into a flat log that scrolled away. On a plant broker where a tag
 * updates every thirty seconds, that reliably showed you nothing at all, and there
 * was no way to tell "nothing was published" from "we were not listening".
 *
 * So the socket moved to the server and stays open. This page shows three views of
 * one stream:
 *
 *   TREE     - every topic seen, folded on '/', with the latest value on each
 *              leaf, its age, its QoS and whether it was retained. This is the
 *              browse-what-is-on-this-broker view, and it is the reason the panel
 *              exists: you do not usually know the topic you want.
 *   INSPECT  - one topic selected from the tree, with its value large enough to
 *              read, pretty-printed when it is JSON, and its own history.
 *   LOG      - every message in arrival order, filtered, for watching a value
 *              change rather than reading what it is now.
 *
 * AGE IS NEVER OPTIONAL. Every value carries how long ago it arrived and goes
 * visibly stale, because a payload on screen with no age beside it is the most
 * dangerous thing a panel like this can show - it reads as current no matter how
 * old it is, and someone will make a decision on it.
 *
 * STILL NO TLS AND NO CREDENTIALS, and the panel says so where you connect rather
 * than in a footnote.
 */
(() => {
  'use strict';

  let api, ui = null, snap = null, selected = null, notice = '';
  const history = new Map();          // topic -> [{at, value}], newest first
  const HISTORY_MAX = 50;
  // The highest sequence number already folded into `history`. The Log tab needs
  // the WHOLE buffer every poll, so the request cannot be narrowed with `since`;
  // this does the same job on the client without hiding rows from the log.
  let folded = 0;

  const root = document.getElementById('mqttPanel');
  if (!root) return;

  const STATE_LABEL = {stopped: 'STOPPED', connecting: 'CONNECTING',
                       connected: 'CONNECTED', error: 'ERROR'};

  function ago(at) {
    if (!at) return 'never';
    const seconds = Math.max(0, (Date.now() / 1000) - at);
    if (seconds < 1) return 'just now';
    if (seconds < 90) return `${Math.round(seconds)}s ago`;
    if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
    return `${Math.round(seconds / 3600)}h ago`;
  }

  // A value is stale when it is older than the operator would expect for its own
  // update rate, which we do not know - so this is a plain, stated threshold
  // rather than a guess dressed up as one.
  const STALE_SECONDS = 120;
  function isStale(at) {
    return !at || (Date.now() / 1000) - at > STALE_SECONDS;
  }

  function pretty(value) {
    const text = String(value == null ? '' : value);
    if (!/^[\s]*[[{]/.test(text)) return text;
    try { return JSON.stringify(JSON.parse(text), null, 2); }
    catch (_) { return text; }
  }

  function build() {
    const {el} = api;
    root.replaceChildren();

    // -- connection -----------------------------------------------------------
    const bar = el('div', 'row mq-connect');
    const host = el('input', 'rin');
    host.type = 'text'; host.size = 16; host.placeholder = 'broker host';
    host.setAttribute('aria-label', 'Broker host');
    const port = el('input', 'rin');
    port.type = 'number'; port.value = '1883'; port.min = '1'; port.max = '65535';
    port.setAttribute('aria-label', 'Broker port');
    const filters = el('input', 'rin');
    filters.type = 'text'; filters.size = 18; filters.value = '#';
    filters.placeholder = 'topic filters, comma separated';
    filters.setAttribute('aria-label', 'Topic filters');
    const connect = el('button', 'btn', 'Monitor');
    const stop = el('button', 'btn', 'Stop');
    const clear = el('button', 'btn', 'Clear buffer');
    bar.append(host, port, filters, connect, stop, clear);
    root.appendChild(bar);

    const state = el('p', 'field-state');
    state.setAttribute('aria-live', 'polite');
    root.appendChild(state);
    const hint = el('p', 'hint', '');
    root.appendChild(hint);
    ui = ui || {};

    // -- tabs over the same stream -------------------------------------------
    const tabs = el('div', 'subtabs mq-tabs');
    const panes = {};
    const buttons = {};
    for (const [id, label] of [['tree', 'Topics'], ['inspect', 'Inspect'], ['log', 'Log']]) {
      const button = el('button', 'subtab' + (id === 'tree' ? ' active' : ''), label);
      button.type = 'button';
      button.addEventListener('click', () => select(id));
      buttons[id] = button;
      tabs.appendChild(button);
      const pane = el('div', 'mq-pane');
      pane.hidden = id !== 'tree';
      panes[id] = pane;
    }
    root.appendChild(tabs);

    const search = el('input', 'rin');
    search.type = 'search'; search.size = 20;
    search.placeholder = 'filter topics and payloads…';
    search.setAttribute('aria-label', 'Filter topics');
    const searchRow = el('div', 'row');
    searchRow.appendChild(search);
    root.appendChild(searchRow);

    for (const pane of Object.values(panes)) root.appendChild(pane);

    // -- publish, last and clearly separated ----------------------------------
    const publish = el('details', 'subcard danger');
    publish.appendChild(el('summary', '', 'Publish — affects equipment'));
    publish.appendChild(el('p', '', 'Sent on the session the monitor already holds, so it carries the same credentials and TLS. At QoS 0 the broker sends no acknowledgement, so success means the bytes reached the socket; at QoS 1 or 2 it is acknowledged and success means the broker took it.'));
    const pubRow = el('div', 'row');
    const pubTopic = el('input', 'rin');
    pubTopic.size = 18; pubTopic.placeholder = 'publish topic';
    pubTopic.setAttribute('aria-label', 'Publish topic');
    const pubPayload = el('input', 'rin');
    pubPayload.size = 22; pubPayload.placeholder = 'payload';
    pubPayload.setAttribute('aria-label', 'Publish payload');
    const pubQos = el('select', '');
    for (const value of ['0', '1', '2']) {
      const option = el('option', '', `QoS ${value}`);
      option.value = value;
      pubQos.appendChild(option);
    }
    pubQos.setAttribute('aria-label', 'Publish QoS');
    const pubRetainLabel = el('label', 'toggle', '');
    const pubRetain = el('input', '');
    pubRetain.type = 'checkbox';
    pubRetainLabel.append(pubRetain, document.createTextNode(' retain'));
    pubRetainLabel.title = 'A retained message is stored by the broker and replayed to every future subscriber. It outlives this session.';
    pubRetain.setAttribute('aria-label', 'Retain this message');
    const pubGo = el('button', 'btn', 'Publish');
    // A distinct accessible name: the Inspect pane also has a button whose label
    // starts with "Publish", and two controls that write to equipment must not be
    // reachable by the same description.
    pubGo.setAttribute('aria-label', 'Publish message');
    pubRow.append(pubTopic, pubPayload, pubQos, pubRetainLabel, pubGo);
    publish.appendChild(pubRow);
    root.appendChild(publish);

    const status = el('p', '');
    status.setAttribute('aria-live', 'polite');
    root.appendChild(status);

    ui = {host, port, filters, connect, stop, clear, state, tabs, buttons, panes,
          search, pubTopic, pubPayload, pubQos, pubRetain, pubGo, status, hint,
          tab: 'tree'};

    connect.addEventListener('click', onConnect);
    stop.addEventListener('click', () => command('api/mqtt/monitor/stop', 'Monitor stopped.'));
    clear.addEventListener('click', () => {
      history.clear();
      folded = 0;
      command('api/mqtt/monitor/clear', 'Buffer cleared. The broker session is untouched.');
    });
    search.addEventListener('input', draw);
    pubGo.addEventListener('click', onPublish);
  }

  function select(tab) {
    ui.tab = tab;
    for (const [id, button] of Object.entries(ui.buttons)) {
      button.classList.toggle('active', id === tab);
      ui.panes[id].hidden = id !== tab;
    }
    draw();
  }

  // ── drawing ───────────────────────────────────────────────────────────────

  function drawState() {
    const {el} = api;
    if (!snap) return;
    const label = STATE_LABEL[snap.state] || snap.state;
    ui.state.dataset.state = snap.state === 'connected' ? 'ok'
      : snap.state === 'connecting' ? 'warn' : snap.state === 'stopped' ? '' : 'bad';
    const parts = [label];
    if (snap.config) parts.push(`${snap.config.host}:${snap.config.port}`);
    if (snap.config) parts.push(`filters: ${snap.config.filters.join(', ')}`);
    parts.push(`${snap.topic_count} topic${snap.topic_count === 1 ? '' : 's'}`);
    parts.push(`${snap.received} message${snap.received === 1 ? '' : 's'}`);
    if (snap.error) parts.push(snap.error);
    ui.state.textContent = parts.join(' · ');

    // Which client, and whether this broker has credentials on file. Both matter
    // when a connection is refused: "not authorised" reads very differently once
    // you know the server had no username to offer.
    const auth = snap.auth || {};
    const bits = [`${snap.client || 'client ?'} · MQTT 3.1.1`];
    if (auth.configured) {
      bits.push('credentials on file for this broker'
        + (auth.tls ? ', TLS' : '') + (auth.username ? ', username' : ''));
    } else {
      bits.push('anonymous CONNECT — no credentials on file for this broker');
    }
    bits.push(`a username, password or CA certificate is read from ${auth.path || 'the operator’s broker file'} (0600) and never entered here`);
    ui.hint.textContent = bits.join('. ') + '.';
    if (auth.problem) {
      ui.hint.textContent += ' ' + auth.problem;
      ui.hint.dataset.state = 'bad';
    } else {
      delete ui.hint.dataset.state;
    }

    // Refusals and caps are reported, never hidden. A tree silently showing 2000
    // of 40000 topics is lying about what is on the broker.
    const warnings = [];
    for (const [topic, grant] of Object.entries(snap.granted || {})) {
      if (grant === 'refused') warnings.push(`the broker refused the filter ${topic}`);
    }
    if (snap.dropped_topics) {
      warnings.push(`${snap.dropped_topics} topic(s) not shown — the ${snap.max_topics} topic cap was reached; narrow the filters`);
    }
    if (snap.dropped_messages) {
      warnings.push(`${snap.dropped_messages} older message(s) dropped from the log buffer`);
    }
    const existing = root.querySelector('.mq-warn');
    if (existing) existing.remove();
    if (warnings.length) {
      const box = el('p', 'mq-warn notice', warnings.join(' · '));
      ui.state.after(box);
    }
  }

  function matches(topic, value) {
    const needle = ui.search.value.trim().toLowerCase();
    if (!needle) return true;
    return `${topic} ${value == null ? '' : value}`.toLowerCase().includes(needle);
  }

  function leafRow(record) {
    const {el} = api;
    const row = el('div', 'mq-leaf');
    row.dataset.stale = String(isStale(record.at));
    const name = el('button', 'mq-topic', record.topic.split('/').pop() || record.topic);
    name.type = 'button';
    name.title = record.topic;
    name.addEventListener('click', () => { selected = record.topic; select('inspect'); });
    const value = el('span', 'mq-value', String(record.value == null ? '' : record.value));
    const meta = el('span', 'mq-meta',
      `${ago(record.at)} · ${record.count}× · QoS ${record.qos}`
      + (record.retain ? ' · retained' : '')
      + (record.truncated ? ' · truncated' : ''));
    row.append(name, value, meta);
    return row;
  }

  function drawTree() {
    const {el, collapsible} = api;
    const pane = ui.panes.tree;
    pane.replaceChildren();
    if (!snap || !snap.tree.length) {
      pane.appendChild(el('p', 'empty', snap && snap.state === 'connected'
        ? 'Connected, but nothing has been published on the watched filters yet.'
        : 'Point the monitor at a broker to browse its topics.'));
      return;
    }
    const build = (nodes, depth, parent) => {
      for (const node of nodes) {
        const visible = node.leaf
          ? matches(node.leaf.topic, node.leaf.value)
          : subtreeMatches(node);
        if (!visible) continue;
        if (node.leaf && !node.children.length) {
          parent.appendChild(leafRow(node.leaf));
          continue;
        }
        // Open down to three levels by default. A browser that shows you `plant`
        // and nothing else has not browsed anything - on a typical
        // site/line/device/tag topic you would have to click three times before a
        // single value appeared. Deeper than that stays collapsed so a broker with
        // a very deep tree does not render thousands of rows at once, and the
        // operator's own toggle per branch is remembered across reloads.
        const box = collapsible(`mqtt:branch:${node.path}`, 'mq-branch', depth < 3);
        const summary = el('summary', 'mq-branch-head');
        summary.append(el('span', 'mq-segment', node.segment),
                       el('span', 'mq-count', `${node.count}`));
        if (node.leaf) {
          summary.append(el('span', 'mq-value', String(node.leaf.value == null ? '' : node.leaf.value)),
                         el('span', 'mq-meta', ago(node.leaf.at)));
        }
        box.appendChild(summary);
        if (node.leaf) box.appendChild(leafRow(node.leaf));
        build(node.children, depth + 1, box);
        parent.appendChild(box);
      }
    };
    build(snap.tree, 0, pane);
    if (!pane.childElementCount) {
      pane.appendChild(el('p', 'empty', 'Nothing matches that filter.'));
    }
  }

  function subtreeMatches(node) {
    if (node.leaf && matches(node.leaf.topic, node.leaf.value)) return true;
    return node.children.some(subtreeMatches);
  }

  function drawInspect() {
    const {el} = api;
    const pane = ui.panes.inspect;
    pane.replaceChildren();
    if (!selected) {
      pane.appendChild(el('p', 'empty', 'Choose a topic in the Topics tab to inspect it.'));
      return;
    }
    const record = snap && snap.topics.find(t => t.topic === selected);
    pane.appendChild(el('h4', 'mq-inspect-topic', selected));
    if (!record) {
      pane.appendChild(el('p', 'empty', 'Nothing has arrived on that topic since the buffer was cleared.'));
      return;
    }
    const meta = el('p', 'mq-meta',
      `${ago(record.at)} · ${record.count} message(s) · QoS ${record.qos}`
      + (record.retain ? ' · retained' : '')
      + ` · ${record.bytes} byte(s)`
      + (record.truncated ? ` · truncated at the display cap` : ''));
    meta.dataset.state = isStale(record.at) ? 'bad' : 'ok';
    pane.appendChild(meta);
    if (isStale(record.at)) {
      pane.appendChild(el('p', 'notice',
        `Nothing new on this topic for ${ago(record.at)}. The value below is what was last published, not what is true now.`));
    }
    pane.appendChild(el('pre', 'mq-payload', pretty(record.value)));

    const rows = history.get(selected) || [];
    pane.appendChild(el('h4', '', `Recent values (${rows.length})`));
    const list = el('div', 'mq-history');
    for (const row of rows) {
      const line = el('div', 'mq-history-row');
      line.append(el('span', 'mq-meta', new Date(row.at * 1000).toLocaleTimeString()),
                  el('span', 'mq-value', row.value));
      list.appendChild(line);
    }
    if (!rows.length) list.appendChild(el('p', 'empty', 'No change recorded yet.'));
    pane.appendChild(list);

    const bar = el('div', 'row');
    const copy = el('button', 'btn', 'Copy topic');
    copy.addEventListener('click', () => {
      navigator.clipboard.writeText(selected).then(
        () => { ui.status.textContent = 'Topic copied.'; },
        () => { ui.status.textContent = 'Could not reach the clipboard.'; });
    });
    const reuse = el('button', 'btn', 'Publish to this topic');
    reuse.setAttribute('aria-label', 'Copy this topic into the publish form');
    reuse.addEventListener('click', () => { ui.pubTopic.value = selected; ui.pubTopic.focus(); });
    bar.append(copy, reuse);
    pane.appendChild(bar);
  }

  function drawLog() {
    const {el} = api;
    const pane = ui.panes.log;
    pane.replaceChildren();
    const rows = (snap ? snap.messages : []).filter(m => matches(m.topic, m.value));
    if (!rows.length) {
      pane.appendChild(el('p', 'empty', 'Nothing in the buffer matches.'));
      return;
    }
    for (const row of rows) {
      const line = el('div', 'mq-log-row');
      const topic = el('button', 'mq-topic', row.topic);
      topic.type = 'button';
      topic.addEventListener('click', () => { selected = row.topic; select('inspect'); });
      line.append(el('span', 'mq-meta', new Date(row.at * 1000).toLocaleTimeString()),
                  topic,
                  el('span', 'mq-value', row.value));
      if (row.retain) line.appendChild(el('span', 'status-chip', 'retained'));
      pane.appendChild(line);
    }
  }

  function draw() {
    if (!ui) return;
    drawState();
    if (ui.tab === 'tree') drawTree();
    else if (ui.tab === 'inspect') drawInspect();
    else drawLog();
    if (notice) { ui.status.textContent = notice; notice = ''; }
  }

  // ── talking to the server ─────────────────────────────────────────────────

  function remember(messages) {
    // Newest first, and only actual CHANGES: a sensor republishing the same number
    // every second would otherwise fill the history with fifty identical lines and
    // hide the change you opened it to find.
    for (const row of [...messages].reverse()) {
      if (row.seq <= folded) continue;
      folded = Math.max(folded, row.seq);
      const rows = history.get(row.topic) || [];
      if (!rows.length || rows[0].value !== row.value) {
        rows.unshift({at: row.at, value: row.value});
        if (rows.length > HISTORY_MAX) rows.length = HISTORY_MAX;
        history.set(row.topic, rows);
      }
    }
  }

  async function onConnect() {
    ui.connect.disabled = true;
    try {
      const filters = ui.filters.value.split(',').map(s => s.trim()).filter(Boolean);
      snap = await api.post('api/mqtt/monitor', {
        host: ui.host.value.trim(),
        port: Number(ui.port.value) || 1883,
        filters: filters.length ? filters : ['#'],
      });
      folded = 0;
      history.clear();
      notice = 'Monitor started. It reconnects on its own if the broker drops.';
      draw();
    } catch (err) {
      ui.status.textContent = err.message;
    } finally { ui.connect.disabled = false; }
  }

  async function command(path, message) {
    try {
      snap = await api.post(path, {});
      notice = message;
      draw();
    } catch (err) { ui.status.textContent = err.message; }
  }

  async function onPublish() {
    const topic = ui.pubTopic.value.trim();
    if (!topic) { ui.status.textContent = 'A publish topic is required.'; return; }
    if (!snap || !snap.config) { ui.status.textContent = 'Point the monitor at a broker first — the publish goes out on that same session.'; return; }
    if (snap.state !== 'connected') { ui.status.textContent = `The monitor is ${snap.state}; connect before publishing.`; return; }
    const {host, port} = snap.config;
    const qos = Number(ui.pubQos.value) || 0;
    const retain = ui.pubRetain.checked;
    if (!window.confirm(`Publish to ${host}:${port}\n  ${topic}\n  ${ui.pubPayload.value}\n\nQoS ${qos}${retain ? ', RETAINED — the broker stores this and replays it to every future subscriber' : ''}.\nThis may affect equipment subscribed to that topic.`)) return;
    ui.pubGo.disabled = true;
    try {
      const out = await api.post('api/mqtt/monitor/publish',
        {topic, payload: ui.pubPayload.value, qos, retain});
      ui.status.textContent = String(out.detail || 'Published.');
    } catch (err) {
      ui.status.textContent = `Publish failed: ${err.message}`;
    } finally { ui.pubGo.disabled = false; }
  }

  async function refresh() {
    if (!ui) build();
    try {
      const data = await api.getJSON('api/mqtt/monitor?limit=400');
      if (data.messages.length) remember(data.messages);
      snap = data;
      // Re-show the broker the server is already watching, so a page reload does
      // not present empty fields next to a live connection.
      if (data.config && !ui.host.value) {
        ui.host.value = data.config.host;
        ui.port.value = String(data.config.port);
        ui.filters.value = data.config.filters.join(', ');
      }
      draw();
    } catch (err) {
      if (ui.state) {
        ui.state.textContent = `Monitor unavailable: ${err.message}`;
        ui.state.dataset.state = 'bad';
      }
    }
  }

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    api.registerCard('iiot', refresh, 1000);
  }, {once: true});
})();
