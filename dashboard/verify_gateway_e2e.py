#!/usr/bin/env python3
"""End-to-end: run BOTH gateways as real servers against a fake Bedrock.

    python3 dashboard/verify_gateway_e2e.py

NOT IN run_tests.sh, deliberately: it binds two loopback ports plus a fake upstream,
which is more than a unit suite should need. It joins `test_models.py`,
`test_stream_slots.sh` and the `?fit=1` readability matrix in the set of checks run on
purpose rather than on every pass.

WHAT IT ADDS over dashboard/test_gateway.py
-------------------------------------------
That suite compares the reconstructed `taskmgmt/bedrock_gateway.py` against the
preserved 2026-09-19 bytecode at the function level, including `relay_once` and
`relay_stream` driven through a fake socket. What it cannot reach is the HTTP surface:
routing and path aliases, trailing slashes, query strings, body handling, status codes,
and the mapping of an upstream failure onto a 502.

So this runs both implementations as real `ThreadingHTTPServer`s, points
`bedrock_url()` at a local fake Bedrock rather than AWS, issues identical requests to
each and compares status and body. 16 cases, including a streamed response and an
upstream 400.

No network and no credential: the fake upstream is loopback, and the bearer token is a
literal placeholder that never leaves the process.

Perishable in the same way the differential is - once CPython will not load the
2026-09-19 bytecode there is nothing left to compare against. Its value is now, while
both halves still run.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = "/mnt/c/Dev/agentmux"
os.environ["AWS_BEARER_TOKEN_BEDROCK"] = "fake-key-for-local-test"

MODE = {"kind": "once"}          # flipped per scenario by the fake upstream


class FakeBedrock(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        kind = MODE["kind"]
        if kind == "http_error":
            body = b'{"message":"bad model"}'
            self.send_response(400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if kind == "stream":
            chunks = [
                {"choices": [{"delta": {"content": "hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"usage": {"prompt_tokens": 2, "completion_tokens": 3}},
            ]
            payload = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n"
                               for c in chunks) + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        body = json.dumps({
            "id": "up_1",
            "choices": [{"message": {"content": "hello from bedrock"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def load(name, path, sourceless=False):
    if sourceless:
        loader = importlib.machinery.SourcelessFileLoader(name, path)
        spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeBedrock)
threading.Thread(target=upstream.serve_forever, daemon=True).start()
UPSTREAM_URL = f"http://127.0.0.1:{upstream.server_address[1]}/chat"

old = load("gw_original", f"{REPO}/taskmgmt/recovered/bedrock_gateway.cpython-312.pyc.bin", True)
new = load("gw_new", f"{REPO}/taskmgmt/bedrock_gateway.py")

servers = {}
for label, module in (("original", old), ("rewrite", new)):
    module.bedrock_url = lambda: UPSTREAM_URL          # redirect off the internet
    module.STATE.update(region="us-west-2", model_default="m-default", verbose=False,
                        log=None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Gateway)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    servers[label] = f"http://127.0.0.1:{server.server_address[1]}"

VOLATILE = re.compile(r'(resp_gw_\d+|"created_at":\s*\d+|"id":\s*"resp_gw[^"]*")')
checked = mismatched = 0
failures = []


def fetch(base, method, path, body=None, headers=None):
    url = base + path
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, method=method, data=data,
                                     headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")
    except Exception as err:
        return "exc", f"{type(err).__name__}"


def compare(label, method, path, body=None, headers=None, mode="once"):
    global checked, mismatched
    checked += 1
    results = []
    for which in ("original", "rewrite"):
        MODE["kind"] = mode
        status, text = fetch(servers[which], method, path, body, headers)
        results.append((status, VOLATILE.sub("X", text)))
    if results[0] != results[1]:
        mismatched += 1
        failures.append((label, results[0], results[1]))
    else:
        print(f"  ok    {label:<44} {str(results[0][0]):>4}  "
              f"{results[0][1][:60]!r}")


compare("GET /health", "GET", "/health")
compare("GET /v1/health", "GET", "/v1/health")
compare("GET /health/ (trailing slash)", "GET", "/health/")
compare("GET /v1/models", "GET", "/v1/models")
compare("GET /nope -> 404", "GET", "/nope")
compare("GET /", "GET", "/")

compare("POST /v1/responses", "POST", "/v1/responses", {"input": "hi"})
compare("POST /responses (alias)", "POST", "/responses", {"input": "hi"})
compare("POST /v1/responses?x=1", "POST", "/v1/responses?x=1", {"input": "hi"})
compare("POST /v1/responses/ (slash)", "POST", "/v1/responses/", {"input": "hi"})
compare("POST /wrong -> 404", "POST", "/wrong", {"input": "hi"})
compare("POST invalid JSON -> 400", "POST", "/v1/responses", b"{not json")
compare("POST empty body", "POST", "/v1/responses", b"")
compare("POST with model + tools", "POST", "/v1/responses", {
    "model": "m1", "input": "hi",
    "tools": [{"type": "namespace", "name": "ns", "tools": [
        {"type": "function", "name": "shell", "parameters": {}}]}]})
compare("POST streaming", "POST", "/v1/responses",
        {"input": "hi", "stream": True}, mode="stream")
compare("POST upstream 400 -> 502", "POST", "/v1/responses", {"input": "hi"},
        mode="http_error")

print()
print(f"compared {checked} end-to-end HTTP cases")
print(f"mismatches: {mismatched}")
for label, a, b in failures:
    print()
    print(f"  MISMATCH {label}")
    print(f"    original: {str(a)[:300]}")
    print(f"    rewrite:  {str(b)[:300]}")
sys.exit(1 if mismatched else 0)
