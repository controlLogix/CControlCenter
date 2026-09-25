#!/usr/bin/env bash
set -euo pipefail
node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('dashboard/app.js', 'utf8');
let response;
const context = {fetch: async () => response};
vm.runInNewContext(source.slice(source.indexOf('async function post('), source.indexOf('function clock(')), context);
(async () => {
  const payload = {error:'Gate refused', missing:[{field:'body',hint:'exact <hint>'}]};
  response = {ok:false,status:409,json:async()=>payload};
  await assert.rejects(context.post('api/board/status',{}), error => error.status === 409 && error.payload === payload && error.message === 'Gate refused');
  response = {ok:false,status:503,json:async()=>{throw Error('not json');}};
  await assert.rejects(context.post('api/board/status',{}), error => error.status === 503 && error.message === 'HTTP 503');
  response = {ok:true,status:200,json:async()=>payload};
  assert.equal(await context.post('api/board/status',{}),payload);
  console.log('PASS post preserves 409 status payload and existing message');
  console.log('passed 1, failed 0');
})().catch(error => { console.error(error); process.exitCode=1; });
JS
