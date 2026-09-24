'use strict';

// Agent Roll Call: a dependency-free HTTP server.
// GET /api/agents, GET /api/health, everything else static from web/.

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const WEB_ROOT = path.resolve(__dirname, '..', 'web');
const DEFAULT_PORT = 4173;

const AGENTS = Object.freeze([
  { id: 'conductor', name: 'Conductor', role: 'orchestrator', provider: 'Claude' },
  { id: 'developer', name: 'Developer', role: 'full-stack developer', provider: 'Claude' },
  { id: 'imager', name: 'Imager', role: 'image generator', provider: 'Grok' },
  { id: 'reviewer', name: 'Reviewer', role: 'final reviewer', provider: 'Grok' },
].map((a) => Object.freeze({ ...a, avatar: `/avatars/${a.id}.svg` })));

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
};

function send(res, status, body, type = 'text/plain; charset=utf-8') {
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(String(body));
  res.writeHead(status, {
    'Content-Type': type,
    'Content-Length': buf.length,
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(buf);
}

function sendJson(res, status, value) {
  send(res, status, JSON.stringify(value), 'application/json; charset=utf-8');
}

// Resolve a request path to a file inside WEB_ROOT, or return an error status.
function resolveStatic(rawPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return { status: 400 };
  }
  // Reject traversal in any form: "..", encoded "%2e%2e", backslashes, NUL bytes.
  if (decoded.includes('\0') || decoded.includes('\\')) return { status: 400 };
  if (decoded.split('/').includes('..')) return { status: 403 };

  const rel = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
  const file = path.resolve(WEB_ROOT, rel);
  if (file !== WEB_ROOT && !file.startsWith(WEB_ROOT + path.sep)) return { status: 403 };
  return { file };
}

function handler(req, res) {
  const rawPath = (req.url || '/').split('?')[0].split('#')[0];

  if (rawPath === '/api/agents' || rawPath === '/api/health') {
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      res.setHeader('Allow', 'GET, HEAD');
      return sendJson(res, 405, { error: 'method not allowed' });
    }
    return sendJson(res, 200, rawPath === '/api/agents' ? AGENTS : { ok: true });
  }
  if (rawPath.startsWith('/api/')) return sendJson(res, 404, { error: 'not found' });

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    return send(res, 405, 'Method Not Allowed');
  }

  const { status, file } = resolveStatic(rawPath);
  if (status) return send(res, status, status === 400 ? 'Bad Request' : 'Forbidden');

  fs.stat(file, (err, stat) => {
    if (err || !stat.isFile()) return send(res, 404, 'Not Found');
    fs.readFile(file, (readErr, data) => {
      if (readErr) return send(res, 404, 'Not Found');
      const type = MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
      send(res, 200, data, type);
    });
  });
}

function createServer() {
  return http.createServer(handler);
}

module.exports = { createServer, AGENTS, WEB_ROOT, DEFAULT_PORT };

if (require.main === module) {
  const port = Number(process.env.PORT) || DEFAULT_PORT;
  createServer().listen(port, () => {
    console.log(`Agent Roll Call listening on http://localhost:${port}`);
  });
}
