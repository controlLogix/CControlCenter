'use strict';

// Agent Roll Call: a dependency-free HTTP server for the API and the static page in web/.
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
].map((agent) => Object.freeze({ ...agent, avatar: `/avatars/${agent.id}.svg` })));

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
};

function send(res, status, body, contentType) {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Content-Length': Buffer.byteLength(body),
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(body);
}

function sendJson(res, status, value) {
  send(res, status, JSON.stringify(value), 'application/json; charset=utf-8');
}

function sendText(res, status, text) {
  send(res, status, text, 'text/plain; charset=utf-8');
}

// True when the request path tries to climb out of web/, in any spelling:
// raw "..", percent-encoded dots or slashes, or backslashes.
function isTraversal(rawPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return true; // Malformed escapes are treated as hostile.
  }
  if (decoded.includes('\0')) return true;
  return decoded.split(/[\\/]+/).includes('..');
}

function serveStatic(req, res, urlPath) {
  const relative = urlPath === '/' ? 'index.html' : decodeURIComponent(urlPath).replace(/^\/+/, '');
  const filePath = path.resolve(WEB_ROOT, relative);
  if (filePath !== WEB_ROOT && !filePath.startsWith(WEB_ROOT + path.sep)) {
    sendText(res, 403, 'Forbidden');
    return;
  }
  fs.stat(filePath, (statErr, stats) => {
    if (statErr || !stats.isFile()) {
      sendText(res, 404, 'Not Found');
      return;
    }
    fs.readFile(filePath, (readErr, data) => {
      if (readErr) {
        sendText(res, 500, 'Internal Server Error');
        return;
      }
      const type = MIME_TYPES[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
      res.writeHead(200, {
        'Content-Type': type,
        'Content-Length': data.length,
        'X-Content-Type-Options': 'nosniff',
      });
      res.end(req.method === 'HEAD' ? undefined : data);
    });
  });
}

function handle(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    sendText(res, 405, 'Method Not Allowed');
    return;
  }
  // Take the path straight from the request line, before any URL normalisation
  // could silently resolve a "..".
  const rawPath = (req.url || '/').split(/[?#]/)[0];
  if (!rawPath.startsWith('/') || isTraversal(rawPath)) {
    sendText(res, 403, 'Forbidden');
    return;
  }
  if (rawPath === '/api/agents') {
    sendJson(res, 200, AGENTS);
    return;
  }
  if (rawPath === '/api/health') {
    sendJson(res, 200, { ok: true });
    return;
  }
  if (rawPath.startsWith('/api/')) {
    sendJson(res, 404, { error: 'Not Found' });
    return;
  }
  serveStatic(req, res, rawPath);
}

function createServer() {
  return http.createServer(handle);
}

if (require.main === module) {
  const port = Number.parseInt(process.env.PORT, 10) || DEFAULT_PORT;
  createServer().listen(port, () => {
    console.log(`Agent Roll Call listening on http://localhost:${port}`);
  });
}

module.exports = { createServer, AGENTS, WEB_ROOT };
