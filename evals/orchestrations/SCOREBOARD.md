# Orchestration scoreboard

Every live run of `hub/demo/orchestrate.py`. ERROR-FREE means all of E1-E6 held (see the script header).

| run | scenario | error-free | failed checks | agents | work items | deliveries | acked | bells | modal answers | extra Enters | seconds | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260929-221859-calib | calib | no | E6_verified | 1 | 1 | 1 | 1 | {"deferred": 3, "submitted": 1} | 1 | 0 | 70 | - |
| 20260929-222043-team | team | no | E1_all_top_done, E4_no_blocked_or_died, E5_all_acked, E6_verified | 3 | 1 | 3 | 2 | {"deferred": 7, "submitted": 2} | 0 | 0 | 1801 | agent calc-lead-claude_2220 dead: {"from":"ready","note":"terminal gone"}; delivery 01M3R58DVCCQXZHGX6F8PK7AC2>calc-lead-claude_2220 ended queued |
| 20260929-225538-team | team | no | E3_no_failed_bell | 3 | 3 | 5 | 5 | {"deferred": 8, "failed": 1, "submitted": 5} | 2 | 2 | 180 | bell calc-reviewer-grok_2255 failed: text still in the input box after submit |
| 20260929-225924-crossrepo | crossrepo | YES | - | 3 | 3 | 5 | 5 | {"deferred": 8, "submitted": 7} | 2 | 1 | 210 | - |
| 20260929-230317-team | team | YES | - | 3 | 3 | 5 | 5 | {"deferred": 8, "submitted": 7} | 1 | 2 | 240 | - |
| 20260929-230742-swarm | swarm | no | E1_all_top_done, E4_no_blocked_or_died, E5_all_acked, E6_verified | 3 | 4 | 3 | 0 | {"deferred": 2} | 0 | 0 | 0 | agent calc-worker-claude_2307 dead: {"from":"starting","note":"terminal gone"}; delivery 01M3R7YF6TBM7PD4KGDP222TYC>calc-worker-codex_2307 ended queued; deliver |
| 20260929-230935-swarm | swarm | YES | - | 3 | 4 | 3 | 3 | {"deferred": 14, "submitted": 4} | 1 | 0 | 90 | - |
| 20260929-231132-crossrepo | crossrepo | no | E1_all_top_done, E4_no_blocked_or_died, E5_all_acked, E6_verified | 3 | 1 | 3 | 2 | {"blocked": 18, "deferred": 8, "submitted": 3} | 1 | 0 | 660 | bell report-lead-claude_2311 blocked: modal login: needs a person; bell report-lead-claude_2311 blocked: modal login: needs a person; bell report-lead-claude_23 |
| 20260929-232307-crossrepo | crossrepo | YES | - | 3 | 3 | 5 | 5 | {"deferred": 14, "submitted": 5} | 1 | 2 | 290 | - |
| 20260930-140310-team | team | no | E4_no_blocked_or_died | 3 | 3 | 5 | 5 | {"blocked": 52, "deferred": 10, "submitted": 5} | 1 | 2 | 1100 | bell calc-lead-codexb_1403 blocked: modal update appeared while typing; bell calc-worker-codex_1403 blocked: modal update appeared while typing; bell calc-lead- |
| 20260930-142203-team | team | YES | - | 3 | 3 | 5 | 5 | {"deferred": 9, "submitted": 5} | 2 | 2 | 250 | - |
| 20261002-094245-calib | calib | YES | - | 1 | 1 | 1 | 1 | {"deferred": 3, "submitted": 1} | 1 | 0 | 50 | - |
| 20261002-094337-team | team | YES | - | 3 | 3 | 5 | 5 | {"deferred": 8, "submitted": 7} | 2 | 2 | 160 | - |
| 20261002-094624-crossrepo | crossrepo | YES | - | 3 | 3 | 6 | 6 | {"deferred": 10, "submitted": 7} | 2 | 2 | 190 | - |
| 20261002-094942-swarm | swarm | YES | - | 3 | 4 | 3 | 3 | {"deferred": 12, "submitted": 4} | 2 | 0 | 110 | - |
| 20261002-095139-calib | calib | YES | - | 1 | 1 | 1 | 1 | {"deferred": 3, "submitted": 1} | 1 | 0 | 70 | - |
| 20261002-095252-team | team | YES | - | 3 | 3 | 5 | 5 | {"deferred": 8, "submitted": 7} | 2 | 2 | 210 | - |
| 20261002-095629-crossrepo | crossrepo | YES | - | 3 | 3 | 6 | 6 | {"deferred": 8, "submitted": 6} | 2 | 2 | 170 | - |
| 20261002-095926-swarm | swarm | no | E5_all_acked | 3 | 4 | 6 | 5 | {"deferred": 23, "submitted": 5} | 2 | 0 | 190 | delivery 01M3YJ3JR56W3HA4NDBX7272M8>calc-worker-grok_0959 ended queued |
| 20261002-100423-swarm | swarm | YES | - | 3 | 4 | 3 | 3 | {"deferred": 12, "submitted": 4} | 2 | 0 | 140 | - |
| 20261002-100651-swarm | swarm | YES | - | 3 | 4 | 6 | 6 | {"deferred": 17, "submitted": 6} | 2 | 1 | 150 | - |

**14 of 21 runs error-free.**
