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

// Raw request: the path is sent exactly as given (no URL normalisation), so
// traversal attempts actually reach the server.
function request(path, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path, method }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: res.headers,
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    req.on('error', reject);
    req.end();
  });
}

test('GET /api/health returns { ok: true }', async () => {
  const res = await request('/api/health');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^application\/json/);
  assert.deepEqual(JSON.parse(res.body), { ok: true });
});

test('GET /api/agents returns exactly the 4 agents', async () => {
  const res = await request('/api/agents');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^application\/json/);
  const agents = JSON.parse(res.body);
  assert.ok(Array.isArray(agents));
  assert.equal(agents.length, 4);
  for (const a of agents) {
    assert.deepEqual(Object.keys(a).sort(), ['avatar', 'id', 'name', 'provider', 'role']);
    for (const v of Object.values(a)) assert.equal(typeof v, 'string');
    assert.equal(a.avatar, `/avatars/${a.id}.svg`);
  }
  assert.deepEqual(
    agents.map(({ id, role, provider }) => ({ id, role, provider })),
    [
      { id: 'conductor', role: 'orchestrator', provider: 'Claude' },
      { id: 'developer', role: 'full-stack developer', provider: 'Claude' },
      { id: 'imager', role: 'image generator', provider: 'Grok' },
      { id: 'reviewer', role: 'final reviewer', provider: 'Grok' },
    ],
  );
});

test('GET / serves the page', async () => {
  const res = await request('/');
  assert.equal(res.status, 200);
  assert.match(res.headers['content-type'], /^text\/html/);
  assert.match(res.body, /<title>Agent Roll Call<\/title>/);
});

test('static assets are served with the right type', async () => {
  const js = await request('/app.js');
  assert.equal(js.status, 200);
  assert.match(js.headers['content-type'], /javascript/);
  const css = await request('/style.css');
  assert.equal(css.status, 200);
  assert.match(css.headers['content-type'], /^text\/css/);
});

test('unknown paths return 404', async () => {
  for (const p of ['/nope.html', '/api/nope', '/avatars/nobody.svg', '/missing/dir/']) {
    const res = await request(p);
    assert.equal(res.status, 404, p);
  }
});

test('path traversal is rejected, including encoded forms', async () => {
  const attempts = [
    '/../server/index.js',
    '/../../etc/passwd',
    '/avatars/../../server/index.js',
    '/%2e%2e/server/index.js',
    '/%2E%2E/server/index.js',
    '/%2e%2e%2fserver%2findex.js',
    '/avatars/..%2f..%2fserver%2findex.js',
    '/..%5cserver%5cindex.js',
    '/%252e%252e/server/index.js',
    '/.%2e/server/index.js',
  ];
  for (const p of attempts) {
    const res = await request(p);
    assert.ok([400, 403, 404].includes(res.status), `${p} -> ${res.status}`);
    assert.doesNotMatch(res.body, /createServer|root:/, p);
  }
  // The unambiguous forms must be an explicit rejection, not just "not found".
  for (const p of ['/../server/index.js', '/%2e%2e/server/index.js', '/avatars/..%2f..%2fserver%2findex.js']) {
    const res = await request(p);
    assert.equal(res.status, 403, p);
  }
});

test('malformed percent-encoding is a 400, not a crash', async () => {
  const res = await request('/%E0%A4%A');
  assert.equal(res.status, 400);
  const health = await request('/api/health');
  assert.equal(health.status, 200);
});
