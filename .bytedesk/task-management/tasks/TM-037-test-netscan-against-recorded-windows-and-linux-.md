---
id: "TM-037"
kind: "task"
status: "in_progress"
created: "2026-09-26T02:03:23.290Z"
board: "controllogix/ccontrolcenter"
title: "Test netscan against recorded Windows and Linux output before it changes hosts"
epic: "EP-002"
acceptance: [{"text":"Recorded arp output from Windows and from Linux is committed as a fixture","done":false},{"text":"_parse_arp is tested against Linux ip neigh, Linux arp -an, and Windows arp -a dash-separated MACs","done":false},{"text":"The running_under_wsl inversion is tested for both answers, not just the current one","done":false},{"text":"A raising journal callback does not abort the scan - netscan.py:352-356 swallows it deliberately","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "tm/TM-037-test-netscan-against-recorded-windows-and-linux-"
worktree: "/mnt/c/Dev/agentmux/.bytedesk/worktrees/TM-037-test-netscan-against-recorded-windows-and-linux-"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:08:37.832Z"
session: "pool-tm-037"
dispatched: {"backend":"tmux","run":"tmux:tm-TM-037","session":"pool-tm-037","at":"2026-09-26T03:08:37.756Z"}
---

Phase 1.1. running_under_wsl() at netscan.py:202 INVERTS once the module runs on
Windows, and neighbour_table() shells ip neigh / arp whose Windows output uses
dash-separated MACs (netscan.py:213). Both are silent failures: the scan returns
fewer neighbours and nothing says why.

Record real output from both hosts and test the parsers against it BEFORE the
move, not after - afterwards there is no way to tell a parser bug from a host
difference.