---
id: "TM-041"
kind: "task"
status: "open"
created: "2026-09-26T02:03:30.422Z"
board: "controllogix/ccontrolcenter"
title: "Migrate the board entities from cc.db into the task store"
epic: "EP-002"
acceptance: [{"text":"Epics are re-keyed EP-nnn to EP-(nnn+100); EP-015 and bytedesk EP-001 are MERGED, not imported, because they are the same body of work","done":false},{"text":"The eleven soft-deleted entities migrate as tombstones rather than being dropped","done":false},{"text":"cc.db stops minting keys when this lands, asserted rather than assumed","done":false},{"text":"874 history rows are archived verbatim to events.0-ccdb.jsonl and folded into each doc as a digest; exactly ONE live import event is emitted","done":false},{"text":"journal.entity_key is added nullable and backfilled by regex through the migration map, with the unmatched count reported","done":false},{"text":"A dry run into TM_ROOT=/tmp/tm-dry produces map.json and a manifest of id, path and sha256; re-running skips on matching sha and REFUSES, naming the row, on a mismatch","done":false},{"text":"cc.db is never mutated by the migrator; retiring the board tables is a separate later commit","done":false},{"text":"All 116 bodies are pre-flighted for tool-call markup, since write() throws on it and cc.db bodies were written by agents","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:03:30.538Z"
---

Phase 1.5. Writes go through the plugin's own store.mjs create(), which accepts
an explicit id, runs inside withLock, stamps board, patches index.json and logs
the event. bin/tm was rejected - 2,467 lines gated by requireEpic,
requireAcceptance and wipLimit 3 would refuse a bulk import row by row. Raw file
writes were rejected too: they skip the frontmatter contract, the atomic rename
and the tool-call-markup guard.

Census verified directly against cc.db: 93 tasks (84 done, 2 open, 7 DELETED),
23 epics (9 done, 6 open, 3 in_progress, 1 blocked, 4 DELETED), 254 acceptance,
130 comments, 77 evidence, 874 history, 2,283 journal.

Two things that census surfaced. Eleven soft-deleted entities: migrate them as
tombstones, because keys are never reused and dropping them leaves holes that
look like data loss to anyone auditing the sequence later. And board_counters has
3 rows that do not travel - the plugin derives nextId from filenames - but cc.db
must STOP minting once this lands, or the two stores issue the same key.