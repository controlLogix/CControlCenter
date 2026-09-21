#!/usr/bin/env python3
"""Seed ~/.agentmux/queue/*.jsonl with this session's real orchestration traffic.

Not filler: these are the actual plan, hand-offs and findings from the CCC pass,
written in the format agents use so the Message Queue view is exercised against
genuine data. Run once; re-running appends duplicates.

Format, one JSON object per line: {at, sender, recipient, kind, body, ref}
kind: plan | request | reply | status | finding | error
"""
import json
import os
import pathlib

QUEUE = pathlib.Path(os.path.expanduser("~/.agentmux/queue"))
DAY = "2026-09-19T"


def at(hhmmss):
    return f"{DAY}{hhmmss}+00:00"


TRAFFIC = {
    "orchestrator": [
        (at("20:41:00"), None, "plan",
         "Controls Control Center (CCC) rebrand - initial pass, near enterprise ready.\n"
         "\n"
         "Roles:\n"
         "  claude  orchestrator + frontend  theme system, shell, all seven views\n"
         "  codex   backend + images         SQLite store, API endpoints, PLC logo SVGs\n"
         "  grok    analyst                  correctness + security review\n"
         "\n"
         "Sequence:\n"
         "  1. capacity check, then SPEC_CC.md as the contract\n"
         "  2. codex phase 1: cc.db + endpoints   (done, 107 checks)\n"
         "  3. codex: PLC logo, thin-line, currentColor + orange LEDs  (done, 4 SVGs)\n"
         "  4. claude: themes.json, index.html shell, style.css, app.js router\n"
         "  5. codex phase 2: MQTT 3.1.1 on stdlib TCP, BOOTP notice, device CRUD\n"
         "  6. grok: review the whole pass\n"
         "\n"
         "Standing constraints: stdlib only, 127.0.0.1 only, no secret through the\n"
         "browser, terminals stay read-only, every mutating endpoint keeps the\n"
         "/api/resize guards."),
        (at("20:44:10"), "codex", "request", "Phase 1: build ccstore.py and the Control Center endpoints per SPEC_CC.md."),
        (at("21:02:30"), "codex", "request",
         "Logo brief: a PLC. Four SVGs - 32/24/16 and a wordmark. Thin line, "
         "currentColor for structure so it follows the theme, #ff9b4c only for the "
         "status LEDs. No <text> elements."),
        (at("21:16:00"), None, "status",
         "Frontend landed: themes.json (4 themes), left activity bar, 7 views, "
         "showView router, theme engine writing tokens onto documentElement."),
    ],
    "codexdev": [
        (at("20:58:05"), "orchestrator", "reply",
         "ccstore.py: 5 tables (epics, tasks, journal, messages, devices), WAL, "
         "foreign_keys ON, user_version=1, a new connection per request because the "
         "server is threaded. 8 endpoints, 107 HTTP checks passing."),
        (at("21:15:40"), "orchestrator", "reply",
         "4 logo SVGs written to dashboard/assets/. Structure on currentColor, "
         "three #ff9b4c LEDs on the 32px mark, no text elements."),
        (at("21:18:20"), "orchestrator", "finding",
         "BUG (confirmed live): the initial SSE tail window started at a raw byte "
         "offset, which can land mid-UTF-8. At offset 439220 the byte was 0xa1, a "
         "continuation byte, so the browser rendered a replacement char. Fixed by "
         "advancing to a clean resync point (newline) before sending the first "
         "chunk, bounded to 4096 bytes. Only the first chunk was affected."),
    ],
    "grokrev": [
        (at("20:52:15"), "orchestrator", "finding",
         "BLOCKER: the SSE eof handler latched panes dead - rec.closed = true with "
         "no reopen path, so an agent that restarted never streamed again."),
        (at("21:05:50"), "orchestrator", "finding",
         "Hardlink leak confirmed by canary: run/pwn.cwd hardlinked to a secret was "
         "served through /api/agents. read_field now rejects st_nlink > 1; open_log "
         "had the same hole and now rejects it too."),
        (at("21:12:05"), "orchestrator", "finding",
         "grok-plugins check reported ok falsely. The negative-lookahead expect "
         "regex matched later in the output under re.M. Replaced with a positive "
         "name@marketplace pattern."),
    ],
}


def main():
    QUEUE.mkdir(parents=True, exist_ok=True)
    total = 0
    for agent, rows in TRAFFIC.items():
        path = QUEUE / f"{agent}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for stamp, recipient, kind, body in rows:
                handle.write(json.dumps({
                    "at": stamp, "sender": agent, "recipient": recipient,
                    "kind": kind, "body": body, "ref": None,
                }) + "\n")
                total += 1
        os.chmod(path, 0o600)
        print(f"  {path}  ({len(rows)} messages)")
    print(f"{total} messages seeded")


if __name__ == "__main__":
    main()
