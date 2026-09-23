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
assert.match(css, /\.iiot-grid\s*\{[^}]*align-items: start/);
assert.match(css, /\.card > summary:focus-visible/);
const cards = [...html.matchAll(/<details class="card" data-collapse-key="([^"]+)"( open)?>([\s\S]*?)<\/details>/g)];
assert.equal(cards.length, 8);
assert.equal(new Set(cards.map(m => m[1])).size, 8);
assert.doesNotMatch(html, /<section class="card">/);
for (const card of cards) assert.match(card[3], /^\s*<summary><h3>[^<]+<\/h3><\/summary>/);
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('PASS: ' + name); }
class Details {
  constructor(key, open = true) {
    this.dataset = {collapseKey: key}; this.open = open; this.events = [];
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
test('all eight markup cards toggle independently and survive fresh initialization', () => {
  const nodes = cards.map(m => new Details(m[1], Boolean(m[2])));
  page(nodes);
  for (const node of nodes) assert.equal(node.open, true);
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
console.log(`passed ${passed}, failed 0`);
JS
