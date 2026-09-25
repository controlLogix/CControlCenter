#!/usr/bin/env bash
# Execute the production Kanban module against a DOM that tracks node identity.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  kanban_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$kanban_node_dir" ] || export PATH="$kanban_node_dir:$PATH"
fi
node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('dashboard/kanban.js', 'utf8');
let passed = 0, failed = 0;
const tests = [], unfinished = new Set();
let suiteFinished = false;
function test(name, fn) {
  if (process.env.KANBAN_TEST && process.env.KANBAN_TEST !== name) return;
  const entry = {name, fn};
  tests.push(entry);
  unfinished.add(entry);
}
// Exit also covers an emptied event loop or early process.exit, even after passes.
process.on('exit', () => {
  for (const {name} of unfinished) console.error('FAIL ' + name + ': registered test did not finish');
  if (!suiteFinished || unfinished.size || failed || !passed) process.exitCode = 1;
});
async function runTest(entry) {
  const {name, fn} = entry;
  let timer;
  try {
    // An unresolved promise alone does not keep node alive: fail unfinished tests explicitly.
    await Promise.race([fn(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('async test did not finish')), 2000);
    })]);
    passed++; console.log('PASS ' + name);
  } catch (e) { failed++; console.error('FAIL ' + name, e); }
  finally { clearTimeout(timer); unfinished.delete(entry); }
}
class Node {
  constructor(tag, cls = '', text = '') {
    this.tag = tag; this.className = cls; this.textContent = text;
    this.children = []; this.dataset = {}; this.events = {}; this.attrs = {};
  }
  append(...nodes) {
    for (const n of nodes) {
      if (n.parent) n.parent.children = n.parent.children.filter(c => c !== n);
      n.parent = this; this.children.push(n);
    }
  }
  appendChild(n) { this.append(n); return n; }
  replaceChildren(...nodes) { this.children.forEach(n => n.parent = null); this.children = []; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(name, fn) { this.events[name] = fn; }
}
const all = n => [n, ...n.children.flatMap(all)];
const text = n => all(n).map(n => n.textContent).join('\n');
function setup(tasks = []) {
  const root = new Node('div'), requests = [], posts = [], registrations = [], storage = [];
  let ready, loader, rows = tasks, response = async () => ({ok: true, json: async () => ({})});
  const ctx = {
    document: {getElementById: id => { assert.equal(id, 'viewKanban'); return root; }},
    window: {addEventListener: (event, fn) => { assert.equal(event, 'ccc:ready'); ready = fn; }, CCC: {
      el: (...args) => new Node(...args),
      getJSON: async path => { requests.push(path); assert.equal(path, 'api/board/board'); return {tasks: rows}; },
      registerPanel: (...args) => { registrations.push(args); loader = args[2]; },
    }},
    fetch: async (path, opts) => { posts.push({path, ...opts, headers: {...opts.headers}, body: JSON.parse(opts.body)}); return response(); },
    localStorage: {getItem: () => null, setItem: (...args) => storage.push(args)},
  };
  vm.runInNewContext(source, ctx); ready();
  return {root, requests, posts, registrations, storage, load: () => loader(),
    rows: value => { rows = value; }, response: fn => { response = fn; },
    columns: () => all(root).filter(n => n.className === 'kanban-column'),
    column: status => all(root).find(n => n.className === 'kanban-column' && n.dataset.status === status),
    cards: status => all(root).filter(n => n.className === 'kanban-card' && (!status || n.dataset.status === status)),
    more: () => all(root).find(n => n.className === 'btn kanban-more'),
  };
}
function event(key = '') {
  const data = {'text/plain': key};
  return {prevented: false, preventDefault() { this.prevented = true; },
    dataTransfer: {getData: type => data[type], setData: (type, value) => { data[type] = value; }}};
}
const task = (key, status, extra = {}) => ({key, status, title: key, ...extra});
const done = () => Array.from({length: 25}, (_, i) => task(`TM-${i}`, 'done', {
  closed: i === 24 ? null : `2026-09-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
  updated: i === 24 ? '2026-10-01T00:00:00Z' : '2030-01-01T00:00:00Z',
}));
test('registration has zero polling', async () => {
  const p = setup();
  assert.equal(p.registrations.length, 1);
  assert.equal(p.registrations[0][0], 'board'); assert.equal(p.registrations[0][1], 'kanban');
  assert.equal(typeof p.registrations[0][2], 'function'); assert.equal(p.registrations[0][3], 0);
});
test('six empty columns remain drop targets with height', async () => {
  const p = setup(); await p.load();
  assert.deepEqual(p.columns().map(n => n.dataset.status), ['backlog', 'open', 'in_progress', 'blocked', 'parked', 'done']);
  for (const column of p.columns()) {
    assert.equal(typeof column.events.drop, 'function');
    const ev = event(); column.events.dragover(ev);
    assert.equal(ev.prevented, true); assert.equal(ev.dataTransfer.dropEffect, 'move');
    assert.match(text(column), /\(0\)/);
  }
  const css = fs.readFileSync('dashboard/kanban.css', 'utf8');
  assert.match(css, /\.kanban-column\s*\{[^}]*min-height:\s*220px/);
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i);
});
test('done caps at twenty with true count and recency fallback', async () => {
  const p = setup(done()); await p.load();
  assert.equal(p.cards('done').length, 20);
  assert.equal(p.column('done').children[0].textContent, 'done (25)');
  assert.deepEqual(p.cards('done').map(n => n.dataset.task), Array.from({length: 20}, (_, i) => `TM-${24-i}`));
});
test('expansion uses cached cards and resets on page load', async () => {
  const p = setup(done()); await p.load();
  await p.more().events.click();
  assert.equal(p.cards('done').length, 25); assert.equal(p.more().attrs['aria-expanded'], 'true');
  assert.equal(p.requests.length, 1); assert.deepEqual(p.storage, []);
  await p.more().events.click(); assert.equal(p.cards('done').length, 20);
  const fresh = setup(done()); await fresh.load(); assert.equal(fresh.cards('done').length, 20);
});
test('only done is capped and deleted is excluded', async () => {
  const rows = ['backlog', 'open', 'in_progress', 'blocked', 'parked'].flatMap(status =>
    Array.from({length: 23}, (_, i) => task(`${status}-${i}`, status)));
  const p = setup([...rows, task('deleted-card', 'deleted')]); await p.load();
  assert.equal(p.cards().length, 115);
  for (const status of ['backlog', 'open', 'in_progress', 'blocked', 'parked']) assert.equal(p.cards(status).length, 23);
  assert.equal(p.more(), undefined);
});
test('cards safely render metadata and transfer their key', async () => {
  const p = setup([task('TM-1', 'open', {title: '<img onerror=boom>', epic: 'EP-1', assignee: 'worker'})]); await p.load();
  const card = p.cards()[0], ev = event();
  assert.equal(card.dataset.status, 'open'); assert.equal(card.draggable, true);
  card.events.dragstart(ev); assert.equal(ev.dataTransfer.getData('text/plain'), 'TM-1');
  assert.equal(ev.dataTransfer.effectAllowed, 'move'); card.events.dragend();
  assert.ok(text(card).includes('<img onerror=boom>')); assert.ok(text(card).includes('EP-1')); assert.ok(text(card).includes('worker'));
  assert.doesNotMatch(source, /innerHTML/);
});
test('same column and unknown cards post nothing', async () => {
  const p = setup([task('TM-1', 'open')]); await p.load();
  await p.column('open').events.drop(event('TM-1'));
  await p.column('blocked').events.drop(event('unknown'));
  assert.equal(p.posts.length, 0); assert.equal(p.requests.length, 1);
});
test('accepted drop waits for response before refreshing', async () => {
  const p = setup([task('TM-1', 'open')]); await p.load();
  const original = p.cards()[0], parent = original.parent;
  let resolve;
  p.response(() => new Promise(r => { resolve = r; }));
  const moving = p.column('blocked').events.drop(event('TM-1'));
  assert.equal(p.posts.length, 1);
  assert.deepEqual(p.posts[0], {path: 'api/board/status', method: 'POST', headers: {'Content-Type': 'application/json'}, body: {id: 'TM-1', status: 'blocked', actor: 'dashboard'}});
  assert.equal(original.parent, parent); assert.equal(p.cards()[0], original); assert.equal(p.requests.length, 1);
  const duplicate = p.column('parked').events.drop(event('TM-1'));
  // Assert before awaiting: a broken guard opens a second deliberately deferred POST.
  assert.equal(p.posts.length, 1, 'a pending move must suppress the second POST');
  await duplicate;
  p.rows([task('TM-1', 'blocked')]); resolve({ok: true, json: async () => ({})}); await moving;
  assert.equal(p.requests.length, 2); assert.equal(p.cards('open').length, 0); assert.equal(p.cards('blocked').length, 1);
});
test('refusal keeps source identity and every remediation hint', async () => {
  const p = setup([task('TM-1', 'open')]); await p.load();
  const original = p.cards()[0], parent = original.parent;
  p.response(async () => ({ok: false, status: 409, json: async () => ({error: 'Gate refused', missing: [
    {field: 'evidence', hint: 'agentmux task evidence TM-1 "proof"'}, {field: 'future_field', hint: 'exact --unknown <hint>'},
  ]})}));
  await p.column('done').events.drop(event('TM-1'));
  assert.equal(p.cards()[0], original); assert.equal(original.parent, parent); assert.equal(p.cards('done').length, 0);
  assert.equal(p.requests.length, 1);
  for (const value of ['Gate refused', 'evidence', 'future_field', 'agentmux task evidence TM-1 "proof"', 'exact --unknown <hint>']) assert.ok(text(p.root).includes(value), value);
});
test('network refusal retains source and permits retry', async () => {
  const p = setup([task('TM-1', 'open')]); await p.load(); const original = p.cards()[0];
  p.response(async () => { throw Error('offline'); });
  await p.column('blocked').events.drop(event('TM-1'));
  assert.equal(p.cards()[0], original); assert.ok(text(p.root).includes('offline'));
  await p.column('blocked').events.drop(event('TM-1')); assert.equal(p.posts.length, 2);
});
(async () => {
for (const entry of tests) await runTest(entry);
suiteFinished = true;
console.log(`passed ${passed}, failed ${failed}`);
process.exitCode = failed || !passed ? 1 : 0;
})();
JS
