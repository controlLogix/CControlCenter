---
id: "TM-022"
kind: "task"
status: "done"
created: "2026-09-25T19:14:44.047Z"
board: "controllogix/ccontrolcenter"
title: "Build YAML mode profiles, with diagnostics instead of a blank rail"
epic: "EP-002"
acceptance: [{"text":"Three modes load and each narrows the rail to its own view set, verified against a real server","done":true,"at":"2026-09-25T19:32:29.552Z"},{"text":"Selecting a mode applies its theme, and clearing the selection restores every view","done":true,"at":"2026-09-25T19:32:30.556Z"},{"text":"A YAML syntax error yields a diagnostic carrying file, line and column, and the other modes still load","done":true,"at":"2026-09-25T19:32:31.930Z"},{"text":"An invalid field yields a field-level diagnostic and a safe default rather than a crash","done":true,"at":"2026-09-25T19:32:33.733Z"},{"text":"A file that fails to parse keeps its last good compile so the rail is never blanked","done":true,"at":"2026-09-25T19:32:35.169Z"},{"text":"Missing PyYAML disables modes with a message naming the fix, rather than failing the dashboard's boot","done":true,"at":"2026-09-25T19:32:36.637Z"},{"text":"modes.js does not throw against the DOM stub and the full gate is green","done":true,"at":"2026-09-25T19:32:38.385Z"}]
evidence: [".bytedesk/task-management/evidence/TM-022-tm022.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T19:32:39.557Z"
assignee: "claude"
evidenceSources: {".bytedesk/task-management/evidence/TM-022-tm022.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm022.txt","sha256":"cb9439566c7ed0b4e8384227e494c3dd14cc351d69d5cc5db19f303ff194a859","bytes":2215,"at":"2026-09-25T19:32:13.686Z"}}
closed: "2026-09-25T19:32:39.525Z"
---

`modes/*.yaml` compiled by `dashboard/modes.py`, served at `GET /api/modes`, applied by `dashboard/modes.js`. Three shipped: **research**, **plc**, **investing**. Adding a mode is adding a file; no code changes.

A mode sets which views are on the rail, the theme, which agents/skills/MCP servers are in scope, and how the blade opens. Measured end to end against a real server:

    all views  : terminals status board runs organization iiot github settings
    plc        : terminals board runs organization iiot settings   theme cc-dark    chip PLC
    investing  : status board runs settings                        theme abyss      chip Investing
    research   : status board runs github settings                 theme parchment  chip Research
    cleared    : back to all eight

**An invalid file is never fatal.** A console that will not start because of a YAML typo is worse than one that starts degraded and says which file is wrong and where. Verified by injecting two bad files alongside the three good ones:

    broken.yaml:4:1   expected ',' or ']', but got '<stream end>'
    wrongid.yaml      [id] id "mismatch" does not match the filename "wrongid"
    wrongid.yaml      [views] unknown view(s): nosuchview
    wrongid.yaml      [default_view] default_view "nosuchview" is not in views
    wrongid.yaml      [blade.default_state] must be one of: hidden, overlay, pinned
    wrongid.yaml      [blade.width] must be an integer between 320 and 900

All three good modes still loaded. A file that fails to parse keeps its **last good compile** so an editor save mid-keystroke does not blank the rail, and the switcher marks it "(last good)". Diagnostics surface as a hoverable chip in the titlebar rather than in a console nobody opens.

**Two things stated rather than assumed.**

- **Hiding a view is not security.** A mode narrows the rail so the console matches the work in front of you. Every endpoint stays exactly as reachable as it was — the server does not know which mode is selected — and nothing here should ever be mistaken for an access control.
- **No watcher.** `modes/` is on `/mnt/c`, a 9p mount, where inotify does not fire for Windows-side writes. It restats on read, and `/api/modes` reports `watch: "poll"` so the UI knows the freshness it is getting.

**PyYAML is optional, deliberately.** `SPEC_agentmux.md`'s rule is that the dashboard installs from a clone with no network and no pip. PyYAML is a system package here, not vendored, so a plant box may not have it — missing PyYAML disables modes and says so, exactly the posture `modbus_rtu.py:86-88` takes for pyserial. Vendoring it is the proper fix and is worth its own task.

The mode only ever *opens* the blade, never forces it shut: someone who closed it deliberately should not have it reappear because a mode said pinned.