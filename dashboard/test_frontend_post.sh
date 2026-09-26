#!/usr/bin/env bash
set -euo pipefail
# nvm keeps node off a NON-INTERACTIVE PATH, so `node` is missing here while it works
# fine in a terminal. Nine of the eleven node-using suites already do this; the two
# that did not were the two that broke. Same shape as test_frontend_board.sh:4-6.
if ! command -v node >/dev/null 2>&1; then
  node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$node_dir" ] || export PATH="$node_dir:$PATH"
fi
node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('dashboard/app.js', 'utf8');
let response;
const context = {fetch: async () => response};
vm.runInNewContext(source.slice(source.indexOf('async function post('), source.indexOf('function clock(')), context);
let checks = 0;
(async () => {
  // Name the extraction failure rather than letting it surface as a TypeError three
  // lines down: source.indexOf(marker) returns -1 when a marker comment moves, and
  // the resulting slice defines nothing at all.
  assert.equal(typeof context.post, 'function',
    'post() was not extracted from app.js - has the marker moved?');
  const payload = {error:'Gate refused', missing:[{field:'body',hint:'exact <hint>'}]};
  response = {ok:false,status:409,json:async()=>payload};
  await assert.rejects(context.post('api/board/status',{}), error => error.status === 409 && error.payload === payload && error.message === 'Gate refused');
  checks++;
  response = {ok:false,status:503,json:async()=>{throw Error('not json');}};
  await assert.rejects(context.post('api/board/status',{}), error => error.status === 503 && error.message === 'HTTP 503');
  checks++;
  response = {ok:true,status:200,json:async()=>payload};
  assert.equal(await context.post('api/board/status',{}),payload);
  checks++;
  console.log('PASS post preserves 409 status payload and existing message');
  // Counted, not asserted as a literal, so the summary cannot drift from what ran.
  console.log(`passed ${checks}, failed 0`);
  if (!checks) process.exitCode = 1;
})().catch(error => { console.error(error); console.log(`passed ${checks}, failed 1`); process.exitCode=1; });
JS
