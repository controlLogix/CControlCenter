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

after(async () => {
  await new Promise((resolve) => server.close(resolve));
});

// Raw request: the path is sent exactly as written (fetch/URL would normalise "..").
function request(path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path, method: 'GET' }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve({
        status: res.statusCode,
        type: res.headers['content-type'] || '',
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
  assert.match(res.type, /^application\/json/);
  assert.deepEqual(JSON.parse(res.body), { ok: true });
});

test('GET /api/agents returns the four agents', async () => {
  const res = await request('/api/agents');
  assert.equal(res.status, 200);
  assert.match(res.type, /^application\/json/);
  const agents = JSON.parse(res.body);
  assert.deepEqual(
    agents.map(({ id, role, provider }) => ({ id, role, provider })),
    [
      { id: 'conductor', role: 'orchestrator', provider: 'Claude' },
      { id: 'developer', role: 'full-stack developer', provider: 'Claude' },
      { id: 'imager', role: 'image generator', provider: 'Grok' },
      { id: 'reviewer', role: 'final reviewer', provider: 'Grok' },
    ],
  );
  for (const agent of agents) {
    assert.deepEqual(Object.keys(agent).sort(), ['avatar', 'id', 'name', 'provider', 'role']);
    assert.equal(typeof agent.name, 'string');
    assert.ok(agent.name.length > 0);
    assert.equal(agent.avatar, `/avatars/${agent.id}.svg`);
  }
});

test('GET / serves the page from web/', async () => {
  const res = await request('/');
  assert.equal(res.status, 200);
  assert.match(res.type, /^text\/html/);
  assert.match(res.body, /<title>Agent Roll Call<\/title>/);
});

test('static assets are served with their content types', async () => {
  const js = await request('/app.js');
  assert.equal(js.status, 200);
  assert.match(js.type, /^text\/javascript/);
  const css = await request('/style.css');
  assert.equal(css.status, 200);
  assert.match(css.type, /^text\/css/);
});

test('unknown paths return 404', async () => {
  for (const path of ['/does-not-exist', '/nope/index.html', '/api/unknown', '/avatars/nobody.svg']) {
    const res = await request(path);
    assert.equal(res.status, 404, path);
  }
});

test('path traversal is rejected', async () => {
  for (const path of [
    '/../BRIEF.md',
    '/../server/index.js',
    '/avatars/../../BRIEF.md',
    '/%2e%2e/BRIEF.md',
    '/%2E%2E%2FBRIEF.md',
    '/..%2f..%2fetc%2fpasswd',
    '/..%5cBRIEF.md',
  ]) {
    const res = await request(path);
    assert.equal(res.status, 403, path);
    assert.doesNotMatch(res.body, /Brief: Agent Roll Call|createServer/, path);
  }
});
