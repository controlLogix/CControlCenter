---
id: "TM-002"
kind: "task"
status: "done"
created: "2026-09-25T15:18:46.550Z"
board: "controllogix/ccontrolcenter"
title: "Repo hygiene: empty junk dirs, stale .bak files, and tmp/"
epic: "EP-002"
acceptance: [{"text":"Both empty C:Users... directories are removed from the repo root","done":true,"at":"2026-09-25T16:15:40.892Z"},{"text":"tmp/ is confirmed gitignored and its 676 MB Linux Chromium is deleted","done":true,"at":"2026-09-25T16:15:56.486Z"},{"text":"du -sh tmp reports under 10 MB","done":true,"at":"2026-09-25T16:16:02.455Z"},{"text":"run_tests.sh still reports all suites passed, from an ext4 clone","done":true,"at":"2026-09-25T16:19:17.546Z"},{"text":"The three stale .bak files are out of the working tree and preserved in .backup-2026-09-25/ — they were never tracked by git, so deleting them would have been irreversible","done":true,"at":"2026-09-25T16:16:06.648Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-002-1790352936544.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:19:27.336Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-002-1790352936544.log":{"source":null,"sha256":"1fb1c5ad518eb6764003e47fd661a9a71eaa8721bad9a2fbfceb83a236c6adbb","bytes":1892,"at":"2026-09-25T16:15:36.545Z"}}
assignee: "claude"
closed: "2026-09-25T16:19:27.287Z"
---

Zero-risk cleanup that clears the working tree before the rename commits land, so the rebrand diff is readable.

Verified on disk:
- `C:UsersNickAppDataLocalTemptmp57mb63qvbackups` and `C:UsersNickAppDataLocalTemptmpzmeefxalbackups` at repo root are **completely empty** (0 entries including hidden), untracked, created one minute apart on 2026-09-24. Residue of a path join that treated a Windows absolute path as a relative segment. The draft plan implied they had contents to inspect; they do not.
- `dashboard/app.js.prerebrand.bak` is 39,339 B against today's `app.js` at 172,837 B — a 4.4x divergence. It is a fossil, not a rollback path; git holds the history.
- `tmp/` is 681 MB, of which 676 MB is `tmp/TM-039-browser` — a vendored **Linux** Chromium. `git ls-files tmp/` returns nothing and `.gitignore:63` already excludes it, so this is a disk item, not a repo-size item.