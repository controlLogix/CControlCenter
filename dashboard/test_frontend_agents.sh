#!/usr/bin/env bash
# Dependency-free registration and DOM behaviour checks; no live board writes.
set -euo pipefail
# run_tests.sh invokes this through process substitution from the repo root.
if ! command -v node >/dev/null 2>&1; then
  agents_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  if [ -n "$agents_node_dir" ]; then
    export PATH="$agents_node_dir:$PATH"
  fi
fi
if ! command -v node >/dev/null 2>&1; then
  echo '  (node not on PATH; skipping Agents frontend checks)'
  echo 'passed 0, failed 0'
  exit 0
fi
if node <<'JS'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('dashboard/agents.js', 'utf8');
const app = fs.readFileSync('dashboard/app.js', 'utf8');
const html = fs.readFileSync('dashboard/index.html', 'utf8');
assert.match(source, /async function loadAgents\(/);
assert.match(source, /window\.CCC\.registerView\('agents', loadAgents\)/);
assert.match(app, /VIEW_LOADERS\[name\] = loader/);
assert.match(html, /src="agents.js"/);
assert.match(html, /href="agents.css"/);
assert.match(html, /id="viewAgents"/);
assert.match(html, /data-view="agents"/);
assert.doesNotMatch(source, /innerHTML|createElement|setInterval|setTimeout|VIEW_POLL_MS/);
assert.doesNotMatch(app.match(/const VIEW_POLL_MS = \{[^}]*\}/)[0], /agents/);
class Node {
  constructor(tag, cls, text) { this.tag = tag; this.cls = cls; this.textContent = text || ''; this.children = []; this.events = {}; }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, fn) { this.events[key] = fn; }
}
const root = new Node('section');
const flatten = node => [node, ...node.children.flatMap(flatten)];
const text = node => flatten(node).map(n => n.textContent).join('\n');
let ready, loader, calls = 0, failure;
let payload = {
  agents: ['repo', 'global', 'claude'].map(scope => ({name: scope + '-agent', scope,
    description: '<img src=x onerror=alert(1)>', cli: 'codex', posture: 'read-only', role: 'reviewer', path: '/' + scope + '/agent.md'})),
  problems: [
    {path: '/repo/dup.md', scope: 'repo', error: "duplicate name 'dup'; all entries unusable: /repo/dup.md, /global/dup.md"},
    {path: '/repo/bad.md', scope: 'repo', error: "unknown key 'tool'"},
    {path: '/repo/invalid.md', scope: 'repo', error: 'posture must be valid'}
  ]
};
vm.runInNewContext(source, {
  document: {getElementById: id => { assert.equal(id, 'viewAgents'); return root; }},
  window: {
    addEventListener: (event, fn, options) => { assert.equal(event, 'ccc:ready'); assert.equal(options.once, true); ready = fn; },
    CCC: {
      el: (...args) => new Node(...args), say: (node, value) => { node.textContent = value; },
      getJSON: async url => { assert.equal(url, 'api/board/agents'); calls++; if (failure) throw failure; return payload; },
      registerView: (...args) => { assert.equal(args[0], 'agents'); assert.equal(args.length, 2); loader = args[1]; }
    }
  }
});
(async () => {
  assert.equal(calls, 0);
  ready();
  await loader();
  const content = root.children[2];
  assert.equal(content.children[0].cls, 'agents-problems');
  assert.equal(content.children[1].cls, 'agents-list');
  for (const value of ['/repo/dup.md', '/global/dup.md', "unknown key 'tool'", 'Remove or correct', 'Rename one', 'Correct the reported error']) assert.ok(text(content).includes(value), value);
  assert.equal(flatten(content).filter(n => n.cls === 'agents-definition').length, 3);
  for (const scope of ['repo', 'global', 'claude']) assert.ok(flatten(content).some(n => n.cls === 'agents-scope' && n.textContent === scope));
  for (const value of ['codex', 'read-only', 'reviewer', '<img src=x onerror=alert(1)>']) assert.ok(text(content).includes(value));
  const refresh = root.children[0].children[1];
  const oldChildren = content.children;
  failure = new Error('offline');
  await refresh.events.click();
  assert.equal(content.children, oldChildren);
  assert.match(text(root), /out of date/);
  assert.equal(refresh.disabled, false);
  failure = null;
  payload = {};
  await loader();
  assert.equal(content.children, oldChildren);
  assert.match(text(root), /agents and problems arrays/);
  payload = {agents: [], problems: []};
  await refresh.events.click();
  assert.equal(content.children.length, 1);
  assert.match(text(content), /No usable agent definitions/);
  assert.equal(calls, 4);
  assert.equal(refresh.disabled, false);
  console.log('PASS: Agents loader, registry, diagnostics, scopes, safe text, manual refresh, empty and failure states');
})().catch(error => { console.error(error); process.exitCode = 1; });
JS
then
  echo 'passed 1, failed 0'
else
  echo 'passed 0, failed 1'
  exit 1
fi
