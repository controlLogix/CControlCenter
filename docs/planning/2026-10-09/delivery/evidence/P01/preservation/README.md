# P01 selected preservation evidence

Reviewed candidate: `a2e9ee6d84a44a0b2f5783c3c0a3a613d50d0e41`. These are bounded preservation checks, not P01 acceptance or a complete dashboard run.

| Check | Actual result | Scope |
| --- | --- | --- |
| `bash dashboard/test_testlib.sh` | 11 passed, zero failed | Shared race/loss assertions distinguish correct and deliberately broken implementations. |
| `bash dashboard/check_test_failability.sh` | 18 passed, zero failed; zero historical bases skipped | Eleven checker probes and seven known-old comparisons. Actual historical failure counts are 25, 35, 18, 19, 9, 26 and 5, above their declared minimums. The unchanged checker requires complete matching summaries and exit codes. |
| `bash dashboard/test_residue.sh` | 26 passed, zero failed | Persistent-state mutations, normal/failure/signal/startup paths, changed sentinel, child cleanup and detached-launch behavior. The real runner and gate execute against disposable server/discovery/test fixtures. |
| `python3 -m unittest discover -s orchtest -p 'test_*.py' -v` | 28 passed, zero failed | All seven unchanged paired workload test modules. The digest collision remains an explicit limitation, not a collision-free guarantee. |
| `bash dashboard/check_test_residue.sh --root <private state> -- bash dashboard/test_residue.sh` | Passed; covered state unchanged | Real residue wrapper around the selected residue suite. This does not run the entire dashboard suite. |
| Windows CPython 3.12.10: `python dashboard/test_gateway.py` | 66 passed, zero failed; no skipped differential | Pure translation checks plus original-bytecode comparisons: 19 request-message, 12 tool, 7 request-build, 80 response-object, 269 split-filter, 400 filter-fuzz, 8 relay-once and 15 relay-stream cases. No Bedrock call or credential is used. |

## Source and environment proof

`running-result.json` is an intermediate progress snapshot, not acceptance evidence.

`local-result.json` records WSL Linux, Python 3.14.4 and tmux 3.6; exact commands, timings, logs and their hashes; and all 400 source hashes in the tested snapshot. Every native file matches its committed Git blob. The before/after source comparison passes and the final tracked Git status is clean. The checkout contains full Git history and uses a detached candidate; no branch or live state was changed.

The raw main working tree changed concurrently in contract/storage files. Those differences are listed separately and are not mistaken for changes to the tested native snapshot. These selected legacy checks do not import the changed contract/storage paths. Reuse on a later candidate still requires verifying the relevant source hashes; this report does not silently claim a later commit was executed.

`gateway-result.json` records the three copied Windows sources, all verified against the same candidate's Git blobs. The archived bytecode digest is `fedba136c42822aed1e8bcb430c2f6eba48b63c392d2cc1a3b6da1487a83400f`. All temporary copies were removed and original files stayed unchanged.

## Isolation and cleanup

The WSL checks ran sequentially with a private HOME, Agentmux state, Codex/Claude configuration paths, temporary directory and `TMUX_TMPDIR`. No provider credentials were inherited. The historical suites could only address sockets below that private directory, including historical scripts that hard-code the socket name. The owned checkout, state and temporary directories were removed. `cleanup-check.json` confirms the root is absent and no process environment references it.

The final cleanup attempted to close the leftover private socket and received exit 1; that result is retained rather than counted as a successful kill. The separate post-run process check found no remaining process associated with the owned root. No operator tmux server, dashboard or home was stopped or modified.

## Preserved failed attribution and limits

`initial-attribution/` retains the first run. Its tests passed, but the evidence wrapper wrongly required the concurrently changing main tree to equal the tested commit. The corrected wrapper verifies Git blob identity and tested-source stability separately. No test assertion, timeout or product source was changed. The correction was followed by the bounded rerun recorded above.

The historical checker deletes its per-base temporary trees and retains summarized counts; its complete checker output is saved here, but individual discarded base logs are not independently archived. These observations prove its declared discrimination checks, not an assertion-by-assertion diagnosis of every historical failure.

This evidence supports the assigned archive, workload, failability and runner-isolation preservation checks. It does not establish native macOS coverage, full live dashboard parity, provider-backed orchestration scenarios, historical communication/determinism characterization, production deployment or phase advancement. The residue tests deliberately use stubs at the external discovery/server boundary; they do not stand in for a real supported live-system check.
