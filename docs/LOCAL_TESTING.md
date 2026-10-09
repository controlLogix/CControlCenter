# Faster local testing during implementation

Use a small test selection while editing. Run the wider affected suites once the fix works, then collect the required phase evidence on a stable candidate. Do not regenerate presentations, re-run unrelated suites or reinstall dependencies during each debug cycle.

## Commands

From PowerShell at the repository root:

```powershell
# Default: fast unit and governance regressions, stopping at the first failure.
./hub/tests/local.ps1

# One class or one method while fixing a specific behavior.
./hub/tests/local.ps1 hub.tests.test_governance.WorkProtocol
./hub/tests/local.ps1 hub.tests.test_governance.WorkProtocol.test_origin_reservation_and_grant_rollback_together

# Repeat the last failing selection after a fix.
./hub/tests/local.ps1 --failed

# Broader checks after relevant changes; full collects all hub failures.
./hub/tests/local.ps1 --profile offline
./hub/tests/local.ps1 --profile live
./hub/tests/local.ps1 --profile full
```

On macOS/Linux or inside WSL, use the same arguments with `python -m hub.tests.run_local`, using the prepared virtual environment. `--list` prints the selection without starting fixtures; `--keep-going` disables fail-fast for a focused run.

| Selection | When to use it | Coverage |
| --- | --- | --- |
| One method/class | Each edit while fixing a known problem | Explicitly selected behavior |
| `fast` (default) | Quick confidence after related edits | Runner checks, governance regressions and federation unit tests |
| `offline` | Store, local API, leases, migration or local transport changes | Fast selection plus the full existing hub offline suite, including real local processes |
| `live` | Broker, subjects, identity, delivery, reconnection or work protocol changes | Existing Core NATS and JWT federation suites using disposable brokers and hubs |
| `full` | Stable hub candidate before its verification handoff | Every existing hub suite plus runner checks; all tests run even after failures |

These profiles select tests; they do not weaken assertions, shorten correctness timeouts or replace live checks with mocks. A full hub run is only one part of a phase gate. Dashboard, harness, platform and Ryan/Nick acceptance requirements remain separate. Use existing targeted dashboard tests for dashboard edits, and `dashboard/run_tests.sh` when that component's full environment is needed. Preserve its lock and isolated server behavior; do not parallelize its shared tmux fixtures.

## Environment and evidence

The PowerShell launcher uses the default WSL distribution. It chooses the repository `.venv`, then the persistent environment already prepared at `~/.cache/agentmux-governance/venv`, then `python3`. It also adds the existing cache's NATS tools to PATH. Set `AGENTMUX_TEST_PYTHON` inside WSL to select another interpreter. There is no implicit installation, upgrade, Docker restart or production service reuse. Maintain dependencies with `hub/requirements.lock`; prepare missing broker tools once, not on each run.

Keep the virtual environment and downloaded tools in the Linux home directory. Test stores and broker state remain disposable. The local runner refuses the cluster-reset mode `AGENTMUX_FED_KIND=1`; use the separate qualified procedure for a disposable cluster.

Each run writes a log and JSON result under `~/.cache/agentmux-tests/<checkout-id>/<run-id>/` (or `XDG_CACHE_HOME`). Reports include selection, Python version, source hashes, failures, skips, total duration and the ten slowest tests. The total includes loading and fixture setup; individual timings include each test's setup/teardown but not shared class setup. Missing dependencies that cause skips, expected failures or an empty selection return a nonzero status. Logs stay local until deliberately reviewed and attached as evidence.

`--failed` uses the last unsuccessful selection. A successful unrelated run does not erase it. After that selection passes, it is cleared. This shortcut never substitutes for the wider affected suite. Use one runner at a time per checkout when relying on this shared failure list; concurrent runs have separate evidence folders but the last failure-list writer wins.

## Agent workflow

1. Reproduce the problem with the smallest meaningful existing test, or add a regression at the affected boundary.
2. Edit, run that test with fail-fast, and use `--failed` during repair. Read the failure before broadening the run.
3. Once fixed, run the relevant profile. A broker change needs live tests; a store change needs offline tests. Run independent checks together only when their fixtures do not share mutable state.
4. At the verification handoff, run the required wider suites once on unchanged source, update component and pattern evidence, then run the governance gate. Expand or repeat only for new changes, failures or unresolved concerns.
5. Update the plan and presentation when behavior or scope changes, not for each internal edit. Keep all phase acceptance and MERGE-01 requirements intact.

Measured on this WSL environment: the final fast profile passed 44 tests in 5.37 seconds; a focused reservation regression passed in 0.50 seconds. The full hub profile passed 124 tests in 63.96 seconds before the final retry-metadata correction; focused checks then covered that correction. These smaller selections do not provide identical coverage. Cold WSL startup and tool-call overhead are outside these timings. See [the measurement record](planning/2026-10-09/local-test-runner-evidence.json) for exact selections and source hashes.
