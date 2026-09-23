'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { AGENTS } = require('./agents');

const WEB_ROOT = path.resolve(__dirname, '..', 'web');

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

function send(res, status, body, type) {
  res.writeHead(status, {
    'Content-Type': type,
    'Content-Length': Buffer.byteLength(body),
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(body);
}

function sendJson(res, status, value) {
  send(res, status, JSON.stringify(value), 'application/json; charset=utf-8');
}

function sendText(res, status, text) {
  send(res, status, text + '\n', 'text/plain; charset=utf-8');
}

// True when the raw request path tries to climb out of web/ — a ".." segment,
// literal or percent-encoded, with either slash style.
function isTraversal(rawPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return true; // malformed encoding is treated as hostile
  }
  return decoded.split(/[\\/]/).includes('..') || decoded.includes('\0');
}

function serveStatic(req, res, rawPath) {
  let relative = decodeURIComponent(rawPath);
  if (relative.endsWith('/')) relative += 'index.html';
  const filePath = path.resolve(WEB_ROOT, '.' + relative);
  // Belt and braces: the resolved file must still be inside web/.
  if (filePath !== WEB_ROOT && !filePath.startsWith(WEB_ROOT + path.sep)) {
    return sendText(res, 400, 'Bad Request');
  }
  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) return sendText(res, 404, 'Not Found');
    const type = MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
    res.writeHead(200, {
      'Content-Type': type,
      'Content-Length': stat.size,
      'X-Content-Type-Options': 'nosniff',
    });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(filePath).pipe(res);
  });
}

function handle(req, res) {
  const rawPath = (req.url || '/').split('?')[0].split('#')[0];

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    return sendText(res, 405, 'Method Not Allowed');
  }
  if (!rawPath.startsWith('/') || isTraversal(rawPath)) {
    return sendText(res, 400, 'Bad Request');
  }
  if (rawPath === '/api/agents') return sendJson(res, 200, AGENTS);
  if (rawPath === '/api/health') return sendJson(res, 200, { ok: true });
  if (rawPath === '/api' || rawPath.startsWith('/api/')) return sendText(res, 404, 'Not Found');
  return serveStatic(req, res, rawPath);
}

function createServer() {
  return http.createServer(handle);
}

if (require.main === module) {
  const port = Number(process.env.PORT) || 4173;
  createServer().listen(port, () => {
    console.log(`Agent Roll Call on http://localhost:${port}`);
  });
}

module.exports = { createServer };
