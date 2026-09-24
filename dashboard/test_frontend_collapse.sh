#!/usr/bin/env bash
# Run from the repo root. Executes production persistence/init code with a small
# DOM fixture; native details keyboard/layout behavior is supplied by the browser.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  collapse_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$collapse_node_dir" ] || export PATH="$collapse_node_dir:$PATH"
fi
node <<'JS'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app = fs.readFileSync('dashboard/app.js', 'utf8');
const html = fs.readFileSync('dashboard/index.html', 'utf8');
const css = fs.readFileSync('dashboard/style.css', 'utf8');
const code = app.slice(app.indexOf('const OPEN_KEY ='), app.indexOf('function stateChip('));
assert.ok(code.includes('function initCollapsibles('));
assert.doesNotMatch(code, /innerHTML/);
assert.equal((app.match(/^initCollapsibles\(\);/gm) || []).length, 1);
assert.ok(app.indexOf('\ninitCollapsibles();') < app.indexOf('if (!window.Terminal)'));
// The IIOT panels are packed into COLUMNS, not laid out in grid rows. A grid row
// is as tall as its tallest card, so short cards left a band of dead space across
// the middle of the page - measured at 307px wasted and a 255px hole under the
// PROFINET card. `align-items: start` used to be asserted here; it stopped cards
// STRETCHING into that space but could not stop the space existing.
assert.match(css, /\.iiot-grid\s*\{[^}]*column-width/);
assert.match(css, /\.iiot-grid > \.card\s*\{[^}]*break-inside: avoid/);
// .board keeps its grid, and keeps the no-stretch rule that goes with one.
assert.match(css, /\.board\s*\{[^}]*align-items: start/);
assert.match(css, /\.card > summary:focus-visible/);
// Five IIOT field cards and five Settings cards. The count is asserted so that a
// card added without a collapse key - which is how one ends up permanently open -
// fails here rather than being noticed by an operator.
const CARD_COUNT = 10;
const cards = [...html.matchAll(/<details class="card" data-collapse-key="([^"]+)"( open)?>([\s\S]*?)<\/details>/g)];
assert.equal(cards.length, CARD_COUNT);
assert.equal(new Set(cards.map(m => m[1])).size, CARD_COUNT);
// Every IIOT panel is a card, and they all carry the same bold <h3> summary. The
// PROFINET panel used to build its own <details> in JS with a bare-text summary,
// so it alone rendered unbold and out of line with the rest.
const iiot = cards.filter(m => m[1].startsWith('iiot:')).map(m => m[1]);
assert.deepEqual(iiot, ['iiot:modbus', 'iiot:dcp', 'iiot:mqtt', 'iiot:scan', 'iiot:codesys']);
assert.doesNotMatch(html, /<section class="card">/);
for (const card of cards) assert.match(card[3], /^\s*<summary><h3>[^<]+<\/h3><\/summary>/);
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('PASS: ' + name); }
class Details {
  constructor(key, open = true) {
    this.dataset = {collapseKey: key}; this.open = open; this.events = [];
    this.key = key;
    this.children = [{id: 'existing-control'}];
  }
  addEventListener(type, fn) { assert.equal(type, 'toggle'); this.events.push(fn); }
  toggle(open) { this.open = open; this.events.forEach(fn => fn()); }
}
const storage = {value: null, writes: 0,
  getItem(key) { assert.equal(key, 'ccc.authOpen'); return this.value; },
  setItem(key, value) { assert.equal(key, 'ccc.authOpen'); this.value = value; this.writes++; }
};
function page(nodes, store = storage) {
  const context = {document: {querySelectorAll(selector) {
    assert.equal(selector, 'details[data-collapse-key]'); return nodes;
  }}, el(tag, cls) { assert.equal(tag, 'details'); const node = new Details(); node.className = cls; return node; }};
  Object.defineProperty(context, 'localStorage', {get() { if (store instanceof Error) throw store; return store; }});
  vm.createContext(context); vm.runInContext(code, context); context.initCollapsibles(); return context;
}
test('every markup card toggles independently and survives fresh initialization', () => {
  const nodes = cards.map(m => new Details(m[1], Boolean(m[2])));
  page(nodes);
  // Against the MARKUP default, not a blanket "everything is open". The CODESYS
  // card ships closed on purpose: opening it is what makes an SSH connection.
  nodes.forEach((node, i) => assert.equal(node.open, Boolean(cards[i][2])));
  nodes.forEach((node, i) => node.toggle(i % 2 === 0));
  const reload = cards.map(m => new Details(m[1], Boolean(m[2])));
  page(reload);
  reload.forEach((node, i) => assert.equal(node.open, i % 2 === 0));
  reload.forEach(node => node.toggle(!node.open));
  const again = cards.map(m => new Details(m[1])); page(again);
  again.forEach((node, i) => assert.equal(node.open, i % 2 !== 0));
});
test('new markup keys and default-closed cards require no registration', () => {
  const nodes = [new Details('future:topic'), new Details('future:closed', false)];
  page(nodes); assert.equal(nodes[0].open, true); assert.equal(nodes[1].open, false);
  nodes[0].toggle(false); nodes[1].toggle(true);
  const reload = [new Details('future:topic'), new Details('future:closed', false)];
  page(reload); assert.equal(reload[0].open, false); assert.equal(reload[1].open, true);
});
test('repeat init neither resets live state nor duplicates listeners or controls', () => {
  const node = new Details('repeat'); const child = node.children[0]; const ctx = page([node]);
  node.open = false; ctx.initCollapsibles();
  assert.equal(node.open, false); assert.equal(node.events.length, 1);
  assert.equal(node.children[0], child);
  const before = storage.writes; node.toggle(false); assert.equal(storage.writes, before + 1);
});
test('imperative auth callers and markup share persistence in both directions', () => {
  const ctx = page([]); const auth = ctx.collapsible('p:legacy', 'auth-provider', true);
  assert.equal(auth.open, true); assert.equal(auth.className, 'auth-provider'); auth.toggle(false);
  const markup = new Details('p:legacy'); page([markup]); assert.equal(markup.open, false);
  markup.toggle(true); assert.equal(page([]).collapsible('p:legacy', 'auth-provider', false).open, true);
  assert.equal(ctx.collapsible('m:new', 'auth-method', false).open, false);
  assert.equal(JSON.parse(storage.value)['future:topic'], false);
});
test('invalid storage shapes and nonboolean entries fall back to markup defaults', () => {
  for (const value of ['bad json', 'null', '[]', '42', '"string"', '{"x":"false"}']) {
    storage.value = value;
    const node = new Details('x'); page([node]); assert.equal(node.open, true);
    node.toggle(false); assert.equal(JSON.parse(storage.value).x, false);
  }
});
test('blocked storage getter, reads and writes leave every card usable', () => {
  for (const store of [new Error('blocked getter'),
    {getItem() { throw Error('blocked read'); }, setItem() { throw Error('blocked write'); }},
    {getItem() { return '{"x":false}'; }, setItem() { throw Error('quota'); }}]) {
    const nodes = [new Details('x'), new Details('y', false)]; const ctx = page(nodes, store);
    for (const node of [...nodes, ctx.collapsible('p:blocked', 'auth-provider', true)]) {
      node.toggle(false); assert.equal(node.open, false); node.toggle(true); assert.equal(node.open, true);
    }
  }
});
test('empty keys are ignored without preventing later cards from initializing', () => {
  const nodes = [new Details(''), new Details('valid')]; page(nodes);
  assert.equal(nodes[0].events.length, 0); assert.equal(nodes[1].events.length, 1);
});

test('bounded storage evicts least recently touched choices across page reloads', () => {
  storage.value = '{}';
  let ctx = page([]);
  for (let i = 0; i < 512; i++) ctx.rememberOpen(`feed:${i}`, false);
  ctx.rememberOpen('feed:0', true);
  ctx = page([]); // Recency must survive a fresh page, not only a session cache.
  ctx.rememberOpen('feed:512', true);
  const state = JSON.parse(storage.value);
  assert.equal(Object.keys(state).length, 512);
  assert.equal(state['feed:0'], true);
  assert.equal(state['feed:1'], undefined);
  assert.equal(state['feed:512'], true);
  assert.equal(ctx.collapsible('feed:1', '', false).open, false);
});
test('serialized size cap migrates large legacy maps and handles oversized keys', () => {
  const legacy = {};
  for (let i = 0; i < 100; i++) legacy[`queue:${i}:` + '"\\😀'.repeat(1000)] = false;
  storage.value = JSON.stringify(legacy);
  const ctx = page([]);
  ctx.rememberOpen('journal:recent', true);
  assert.ok(storage.value.length <= 64 * 1024);
  assert.equal(JSON.parse(storage.value)['journal:recent'], true);
  assert.ok(Object.keys(JSON.parse(storage.value)).length < 100);
  ctx.rememberOpen('queue:' + 'x'.repeat(70000), true);
  assert.ok(storage.value.length <= 64 * 1024);
  ctx.rememberOpen('ticket:next', false);
  assert.equal(JSON.parse(storage.value)['ticket:next'], false);
});

// Exercise the production list renderers, not copies of their key expressions.
class Node {
  constructor(tag, cls, text) { this.tag = tag; this.className = cls; this.textContent = text; this.children = []; this.events = {}; this.open = false; this.dataset = {}; }
  appendChild(n) { this.children.push(n); return n; }
  append(...nodes) { nodes.forEach(n => this.appendChild(n)); }
  replaceChildren() { this.children = []; }
  addEventListener(type, fn) { this.events[type] = fn; }
  toggle(open) { this.open = open; this.events.toggle(); }
}
function renderer(store, rows) {
  const els = {};
  for (const name of ['feedList', 'queueList', 'journalList', 'ticketList', 'planPin',
                      'queueKind', 'queueStamp', 'journalStamp', 'ticketStamp',
                      'queueFollow', 'jiraBase', 'queueSearch', 'journalSearch',
                      'journalFilterKind', 'ticketSearch']) els[name] = new Node('div');
  for (const name of ['queueKind', 'jiraBase', 'queueSearch', 'journalSearch',
                      'journalFilterKind', 'ticketSearch']) els[name].value = '';
  // Each Status tab hands the export button the rows it is showing; the renderers
  // call it on every draw, so the fixture has to accept it.
  const published = {};
  const ctx = {els, el: (tag, cls, text) => new Node(tag, cls, text),
    feedEntries: rows.feed, feedPrefs: {max: 500}, feedPasses: () => true,
    publishRows: (name, list) => { published[name] = list; }, published,
    updateFeedBadge() {}, markQueueSeen() {}, clock: x => x, say() {},
    MSG_KINDS: new Set(['status']), JOURNAL_KINDS: new Set(['note']),
    issueLink: key => new Node('a', 't-key', key), ticketActions: () => new Node('div', 'ticket-actions'),
    async getJSON(url) {
      if (url.startsWith('api/messages')) return {messages: rows.queue};
      if (url.startsWith('api/journal')) return {journal: rows.journal};
      if (url.startsWith('api/tickets')) return {configured: true, base_url: 'https://jira.example', issues: rows.ticket};
      return {epics: []};
    }};
  Object.defineProperty(ctx, 'localStorage', {get() { if (store instanceof Error) throw store; return store; }});
  vm.createContext(ctx); vm.runInContext(code, ctx);
  for (const [start, end] of [['function drawFeed()', '// The badge counts'],
    ['async function loadQueue()', '// The badge exists'], ['async function loadJournal()', '// ═'],
    ['async function loadTickets(force)', '// ═']]) {
    const offset = app.indexOf(start);
    vm.runInContext(app.slice(offset, app.indexOf(end, offset)), ctx);
  }
  return ctx;
}
(async () => {
  const rows = {
    ticket: [{key: 'ABC-1', summary: 'one'}, {key: 'ABC-2', summary: 'two'}],
    queue: [{id: 'message-one', at: 'same', body: 'one'}, {id: 'message-two', at: 'same', body: 'two'},
      {at: 'legacy', sender: 'a', body: 'legacy one'}, {at: 'legacy', sender: 'b', body: 'legacy two'}],
    journal: [{id: 1, at: 'same', subject: 'one', body: 'body'}, {id: 2, at: 'same', subject: 'two', body: 'body'}],
    feed: [{at: 'same', source: 'journal', who: 'a', text: 'one'}, {at: 'same', source: 'chatter', who: 'b', text: 'two'}]
  };
  async function draw(ctx) { ctx.drawFeed(); await ctx.loadQueue(); await ctx.loadJournal(); await ctx.loadTickets(); }
  const lists = ['ticketList', 'queueList', 'journalList', 'feedList'];
  storage.value = null;
  const ctx = renderer(storage, rows); await draw(ctx);
  const remembered = {};
  for (const name of lists) {
    const nodes = ctx.els[name].children;
    assert.ok(nodes.length >= 2);
    nodes.forEach(n => { assert.equal(n.tag, 'details'); assert.equal(n.open, false); assert.equal(n.children[0].tag, 'summary'); });
    nodes[0].toggle(true); assert.equal(nodes[1].open, false);
    remembered[name] = nodes.map(n => n.open).reverse();
  }
  Object.values(rows).forEach(list => list.reverse());
  const reload = renderer(storage, rows); await draw(reload);
  for (const name of lists) assert.deepEqual(reload.els[name].children.map(n => n.open), remembered[name]);
  passed++; console.log('PASS: all four list renderers toggle independently and preserve identity across reload/reorder');
  for (const store of [new Error('blocked getter'), {getItem() {throw Error('read');}, setItem() {throw Error('write');}},
    {getItem() {return 'bad json';}, setItem() {throw Error('quota');}}]) {
    const blocked = renderer(store, rows); await draw(blocked);
    for (const name of lists) {
      assert.equal(blocked.els[name].children.length, rows[name.replace('List', '')].length);
      for (const node of blocked.els[name].children) { node.toggle(true); assert.equal(node.open, true); node.toggle(false); assert.equal(node.open, false); }
    }
  }
  passed++; console.log('PASS: all four list renderers survive blocked/malformed storage and failed writes');
  console.log(`passed ${passed}, failed 0`);
})().catch(err => { console.error(err); process.exitCode = 1; });

JS
