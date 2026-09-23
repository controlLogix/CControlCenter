'use strict';

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { createServer } = require('../server/index.js');

let server;
let port;

before(async () => {
  server = createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  port = server.address().port;
});

after(() => new Promise((resolve) => server.close(resolve)));

// Raw request so the path reaches the server exactly as written (fetch would normalize "..").
function request(path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path, method: 'GET' }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on('error', reject);
    req.end();
  });
}

test('GET /api/agents returns exactly the four agents', async () => {
  const res = await request('/api/agents');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^application\/json/);
  const agents = JSON.parse(res.body);
  assert.ok(Array.isArray(agents));
  assert.equal(agents.length, 4);
  assert.deepEqual(agents.map((a) => a.id), ['conductor', 'developer', 'imager', 'reviewer']);
  for (const agent of agents) {
    assert.deepEqual(Object.keys(agent).sort(), ['avatar', 'id', 'name', 'provider', 'role']);
    for (const key of ['id', 'name', 'role', 'provider', 'avatar']) {
      assert.equal(typeof agent[key], 'string');
      assert.ok(agent[key].length > 0, `${agent.id}.${key} is empty`);
    }
    assert.equal(agent.avatar, `/avatars/${agent.id}.svg`);
  }
  const providers = Object.fromEntries(agents.map((a) => [a.id, a.provider]));
  assert.deepEqual(providers, {
    conductor: 'Claude', developer: 'Claude', imager: 'Grok', reviewer: 'Grok',
  });
});

test('GET /api/health returns { ok: true }', async () => {
  const res = await request('/api/health');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^application\/json/);
  assert.deepEqual(JSON.parse(res.body), { ok: true });
});

test('GET / serves the page from web/', async () => {
  const res = await request('/');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^text\/html/);
  assert.match(res.body, /<script src="\/app\.js"><\/script>/);
});

test('unknown paths return 404', async () => {
  for (const path of ['/no-such-file.html', '/api/nope', '/avatars/nobody.svg']) {
    const res = await request(path);
    assert.equal(res.status, 404, path);
  }
});

test('path traversal is rejected', async () => {
  const attempts = [
    '/../BRIEF.md',
    '/../server/index.js',
    '/avatars/../../BRIEF.md',
    '/%2e%2e/BRIEF.md',
    '/%2E%2E%2FBRIEF.md',
    '/..%2fserver%2findex.js',
    '/..%5cBRIEF.md',
  ];
  for (const path of attempts) {
    const res = await request(path);
    assert.equal(res.status, 400, path);
    assert.doesNotMatch(res.body, /Agent Roll Call|require\(/, path);
  }
});
