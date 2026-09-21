#!/usr/bin/env python3
"""Verify the SSE snapshot is framed so a terminal renders it correctly.

    python3 dashboard/test_snapshot.py     # needs the dashboard running on 8787

THE BUG THIS GUARDS. `tmux capture-pane -p` separates pane rows with a bare LF. A
terminal treats LF as "down one row", not "down one row and return to column 1" — CR is
what does that. The dashboard's terminals use convertEol: false deliberately, because
the live log stream carries real CRLF from the agent and converting it would corrupt
that. So every snapshot row began at whatever column the previous row ended on,
producing a staircase: long lines ran off the right edge, wrapped, and left orphan tails
like "ng to read" and "ine 08" down the left margin.

That is the "lines are gapped / not streaming properly" symptom. It affected the
snapshot only; appended log bytes always rendered correctly, which is what made it look
like an intermittent streaming fault rather than a framing bug.

These checks are on the BYTES the server sends, so they hold regardless of the browser.
"""

import base64
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8787"
passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label:<52} {actual!r}")
        passed += 1
    else:
        print(f"  FAIL  {label:<52} got {actual!r} want {expected!r}")
        failed += 1


# ───────────────────── framed_snapshot, in isolation ─────────────────────

spec = importlib.util.spec_from_file_location("ccserver", REPO / "dashboard" / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules["ccserver"] = server
spec.loader.exec_module(server)

print("--- framed_snapshot normalises row separators to CRLF ---")
out = server.framed_snapshot("row one\nrow two\nrow three")
check("every LF became CRLF", 2, out.count(b"\r\n"))   # three rows, two separators
check("no bare LF survives", 0, len(re.findall(br"(?<!\r)\n", out)))
check("autowrap disabled first", True, out.startswith(b"\x1b[?7l"))
check("autowrap restored after", True, out.endswith(b"\x1b[?7h"))
check("content is intact", True, b"row one\r\nrow two\r\nrow three" in out)

print("--- existing CRLF is not doubled ---")
out = server.framed_snapshot("a\r\nb\r\nc")
check("CRLF stays single", 2, out.count(b"\r\n"))
check("no CR CR", 0, out.count(b"\r\r"))

print("--- a lone CR does not become a blank row ---")
out = server.framed_snapshot("a\rb")
check("stray CR dropped", b"\x1b[?7lab\x1b[?7h", out)

print("--- ANSI colour runs survive untouched ---")
coloured = "\x1b[31mred\x1b[0m\n\x1b[1;32mgreen\x1b[0m"
out = server.framed_snapshot(coloured)
check("SGR sequences preserved", True, b"\x1b[31mred\x1b[0m" in out)
check("second row still CRLF-separated", True, b"\x1b[0m\r\n\x1b[1;32m" in out)

print("--- full-width rows and UTF-8 ---")
wide = "x" * 200 + "\n" + "y" * 200
out = server.framed_snapshot(wide)
check("both full-width rows separated", 1, out.count(b"\r\n"))
check("utf-8 multi-byte survives", True,
      "é→".encode("utf-8") in server.framed_snapshot("é→\nnext"))

# ───────────────────── the live stream on the wire ─────────────────────

print("--- the snapshot event as actually sent ---")
agents = json.load(urllib.request.urlopen(f"{BASE}/api/agents", timeout=10))["agents"]
live = [a for a in agents if a.get("state") != "stale"]
if not live:
    print("        no live agents; skipping the wire checks")
else:
    name = live[0]["name"]
    # The stream is endless by design, so drain what is immediately available and then
    # parse once. Reading until the frame terminator arrives is racy: the snapshot can
    # land in one read while the terminating blank line is still in flight, and the next
    # read then blocks until the agent happens to print something.
    buffered = b""
    with urllib.request.urlopen(f"{BASE}/api/stream/{name}?tail=4096", timeout=4) as response:
        try:
            while len(buffered) < 2_000_000:
                # read1, NOT read. On a response with no Content-Length, read(n) blocks
                # until it has exactly n bytes or the connection closes — so a 1.6 KB
                # snapshot never satisfied a 4 KB read, the socket timed out, and the
                # bytes already received were discarded with the exception. read1
                # returns whatever has arrived.
                chunk = response.read1(4096)
                if not chunk:
                    break
                buffered += chunk
                if b"\n\n" in buffered:
                    break        # frame complete
        except TimeoutError:
            pass            # idle stream: everything pending has arrived

    payload = None
    if b"event: snapshot\n" in buffered:
        after = buffered.split(b"event: snapshot\n", 1)[1]
        frame = after.split(b"\n\n", 1)[0]          # up to the terminator, or all of it
        lines = [ln[len(b"data: "):] for ln in frame.split(b"\n")
                 if ln.startswith(b"data: ")]
        if lines:
            payload = base64.b64decode(b"".join(lines))
    if payload is None:
        check("snapshot frame received", True, False)
    else:
        check("snapshot frame received", True, True)
        check("clears the screen first", True, payload.startswith(b"\x1b[2J\x1b[H"))
        body = payload[len(b"\x1b[2J\x1b[H"):]
        check("autowrap disabled for the payload", True, body.startswith(b"\x1b[?7l"))
        check("autowrap restored at the end", True, body.rstrip().endswith(b"\x1b[?7h"))
        # The property that actually fixes the staircase.
        bare = len(re.findall(br"(?<!\r)\n", body))
        check("NO bare LF in the snapshot", 0, bare)
        rows = body.count(b"\r\n")
        check("carries multiple rows", True, rows >= 2)
        print(f"        {len(body)} bytes, {rows} CRLF-separated rows")

print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
