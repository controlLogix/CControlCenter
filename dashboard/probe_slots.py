#!/usr/bin/env python3
"""Sample SSE slot availability while a browser is connected.

    python3 dashboard/probe_slots.py [seconds]

Opens one short stream per agent per round and records the status codes. A 503 means the
slot pool was momentarily full, which is the difference between "panes are flapping
because of contention" and "panes are flapping for some other reason".
"""
import collections
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

names = [a["name"] for a in
         json.load(urllib.request.urlopen(f"{BASE}/api/agents", timeout=10))["agents"]]
print(f"  {len(names)} agents; sampling for {SECONDS:g}s while the browser is attached")

codes = collections.Counter()
deadline = time.monotonic() + SECONDS
rounds = 0
while time.monotonic() < deadline:
    rounds += 1
    for name in names:
        try:
            request = urllib.request.Request(f"{BASE}/api/stream/{name}?tail=256")
            with urllib.request.urlopen(request, timeout=3) as response:
                codes[response.status] += 1
                response.read1(64)          # take one chunk, then hang up
        except urllib.error.HTTPError as err:
            codes[err.code] += 1
        except Exception:
            codes["timeout/err"] += 1
    time.sleep(0.4)

print(f"  {rounds} rounds")
for code, count in sorted(codes.items(), key=lambda kv: str(kv[0])):
    print(f"    {code}: {count}")
print("  503 present -> the pool is contended; none -> flapping has another cause")
