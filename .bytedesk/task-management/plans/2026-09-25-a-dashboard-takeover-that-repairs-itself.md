# A dashboard takeover that repairs itself

## Context

`dashboard/run_tests.sh` restarts the operator's dashboard onto a disposable
`AGENTMUX_HOME` for the duration of a gate run, then restores it. That design is sound
and deliberate — its own header says so, and `cleanup` even *verifies* the restore with
`suite_server.py --expect` rather than assuming it.

The defect is that the restore cannot survive the process being killed:

- `OPERATOR_ROOT` (line 30) comes from `suite_server.py --fallback`, which discovers the
  home by reading `/proc/<pid>/environ` of the live server. **Nothing is written to
  disk.** The operator's real home exists only as a shell variable in one process.
- `cleanup` runs from `trap … EXIT` with `trap 'exit 130' INT` / `'exit 143' TERM`
  (lines 76-78). EXIT, INT and TERM only — not HUP, and nothing survives SIGKILL.

So when the idle watchdog kills the pane holding a gate run, the trap never fires and
the only record of where the dashboard belonged dies with the shell. The dashboard keeps
serving `/tmp/tmp.XXXX`, which is then deleted. The board renders every column as `(0)`
with no error anywhere — `HANDOVER.md:111-113` already records this happening.

Observed live on 2026-09-24: the dashboard was left on `/tmp/tmp.L8TTmqijUs` and the
Kanban showed six empty columns. Nothing was lost; the real database was untouched. But
diagnosis took twenty minutes because the failure is completely silent.

**The fix: persist what the trap knows, so a later invocation can finish the job.**

## Decisions taken

| | |
|---|---|
| On detecting a stranded dashboard | Repair automatically, print one line saying so |
| Trigger | Every `agentmux` invocation — so the fast path must be a single `stat` |
| If nothing is listening at all | Still restore; the operator had a dashboard before the gate took over |

---

## 1. The marker

`$OPERATOR_ROOT/.dashboard-takeover.json`, `0600`, following the warrant convention in
`taskmgmt/coordination.py:272-309` — `"version": 1`, written via `mkstemp` in the same
directory then `chmod` then `os.replace`, reader returns `None` on every anomaly and
never raises.

```json
{ "version": 1,
  "operator_home": "/home/nick/.agentmux",
  "test_home":     "/tmp/tmp.XXXX",
  "gate_pid":      12345,
  "repo":          "/mnt/c/Dev/agentmux",
  "started_at":    1790300451 }
```

`repo` is not decoration: the repair has to run `dashboard/restart.sh`, and that script
refuses unless `dashboard/server.py` exists relative to the working directory
(`restart.sh:12-15`).

**It lives in the operator's home, and that placement does the access control for free.**
`run_tests.sh:80` exports `AGENTMUX_HOME=$TEST_ROOT`, so every `agentmux` call *inside*
the gate computes `ROOT` as the test home, finds no marker there, and takes the fast path.
Only invocations using the operator's own home can ever attempt a repair.

### Written and cleared by `suite_server.py`, not by bash

That module already owns "which home is the server on" and is already called at exactly
the two moments that matter. Two new modes:

- `--mark --operator <home> --test-home <dir> --gate-pid <n> --repo <path>`
- `--clear --operator <home>`
- `--stale --operator <home>` → prints `operator_home` + `repo` if a **stale** marker
  exists, exits non-zero otherwise. This keeps JSON parsing out of the shell.

Staleness is `kill -0 gate_pid` failing, the same test `courier.py:677-689` and
`dispatch.py:814-827` already use. A live gate pid means a gate is running: do nothing.

### Where the writes go in `run_tests.sh`

- **Mark** between line 84 (`RESTORE_NEEDED=1`) and line 85 (`restart_for_home
  "$TEST_ROOT"`). Before the takeover, because a crash *between* arming and restarting is
  precisely the window being protected.
- **Clear** inside `cleanup`, only once `restore_status` is 0 — i.e. after
  `suite_server.py --expect "$OPERATOR_ROOT"` has proved the restore. If the restore
  failed, the marker deliberately stays and the next invocation finishes the job. The
  existing failure branch (lines 68-70) already retains `$TEST_ROOT` for recovery; this
  makes that recovery automatic.

---

## 2. The check, in `agentmux.sh`

A new `check_stale_takeover()` plus **one call** in the preamble, after
`mkdir -p "$LOGDIR" "$RUNDIR"` (line 34) and before the dispatch (line 2306). There is no
shared init function in this script; lines 9-47 are the whole preamble.

```sh
check_stale_takeover() {
  [ "${AGENTMUX_NO_AUTO_RESTORE:-0}" = 1 ] && return 0
  [ -f "$ROOT/.dashboard-takeover.json" ] || return 0   # THE FAST PATH: one stat
  ...                                                    # only from here on
}
```

Everything past the second line runs only when a marker exists — during a gate run
(where it stops at one `kill -0`) or after a killed one. `agentmux help` costs one
`stat`.

**The message goes to stderr.** Not cosmetic: `cmd_run start` prints a run id to stdout
and callers capture it (`run_tests.sh` and the orchestrator both parse it). A repair line
on stdout would corrupt that.

```
agentmux: the dashboard on 8787 was serving /tmp/tmp.L8TT (left by a gate run
  that was killed). Restored to /home/nick/.agentmux.
```

Repair sequence: read the marker via `--stale`; `cd` to `repo`; run `restart.sh` with
`AGENTMUX_HOME=$operator_home` exactly as `restart_for_home` does at `run_tests.sh:37-42`
(including `200>&-`, which exists because fd 200 — the suite's `flock` — leaks into every
child); verify with `--expect`; clear the marker; print. On failure, print the manual
command and **leave the marker** so the next invocation retries.

Two agents can race here, so take the repo's existing atomic-`mkdir` lock idiom from
`agentmux.sh:1806-1816` (`.dashboard-takeover.repairing`, released on `trap … RETURN`).
The loser skips silently rather than waiting.

---

## 3. What this must not break

- **Residue.** `dashboard/residue_state.py:18-22,44-65` hashes every top-level file in
  `~/.agentmux`. The marker is absent before a run and absent after a clean one, so it is
  byte-identical and invisible to the gate. After a *killed* run it is present — and that
  is the correct signal, not a false positive.
- **`restart.sh` clobbers `/tmp/ccc-server.log`** (line 29). The repair inherits that;
  worth a line in the message only if it ever matters.
- **`suite_server.py` raises when it finds more than one dashboard home**
  (lines 33-35). The repair must treat that as "cannot safely act" and warn rather than
  guess — the same refusal the module already makes.

---

## Files

**Modified** — `dashboard/suite_server.py` (three modes; it is 58 lines today),
`dashboard/run_tests.sh` (one mark, one clear, both beside code that already exists),
`agentmux.sh` (one function plus one preamble line).

**New** — `dashboard/test_takeover_recovery.sh`, registered in `run_tests.sh` alongside
the other shell suites on a numbered fd with `tr -d '\r'`.

**Unchanged** — `dashboard/restart.sh` and `dashboard/server.py`. The repair drives
`restart.sh` exactly as the gate already does, and the server needs no knowledge of any
of this.

---

## Tests

Model the new suite on `dashboard/test_argguard.sh:30-38` — throwaway `AGENTMUX_HOME`,
CR-stripped harness copy, `trap … EXIT`, `testlib.sh` for `check`/`finish`. Stub
`restart.sh` and `suite_server.py` onto a fixture `PATH` the way
`dashboard/test_residue.sh:75-81` does, logging `{home, args}` per restart.

Each of these must be shown to fail when the line it covers is broken:

1. **A stale marker is repaired.** Fabricate one naming a dead pid; run `agentmux help`;
   assert `restart.sh` was invoked with the operator home, the marker is gone, and the
   line went to **stderr, not stdout**.
2. **A live gate is left alone.** Marker with `gate_pid = $$`; assert no restart.
3. **The fast path costs nothing.** No marker, and a `python3` stub that fails loudly if
   called; assert `agentmux help` still exits 0.
4. **stdout stays clean.** `agentmux run start` during a repair still prints only the run
   id on stdout.
5. **A failed repair keeps the marker** and says what to run by hand.
6. **`AGENTMUX_NO_AUTO_RESTORE=1` disables it.**
7. **Children inside a gate never repair** — marker in the operator home, but
   `AGENTMUX_HOME` set to the test home; assert the fast path.

Extend **`dashboard/test_residue.sh`**'s case matrix (line 67) with a `KILL` mode. It is
the only harness that drives the real `run_tests.sh`, already stubs
`suite_server.py`/`restart.sh`/`tmux`/`flock`, and already sends real signals at a
synchronised point. Assert that after `SIGKILL` the marker exists and names the live
home, and that a subsequent `agentmux` invocation restores it. Also assert the existing
`normal` case leaves **no** marker — that is what proves the clear path runs.

## Verification

1. `bash <(tr -d '\r' < dashboard/run_tests.sh)` must end **all suites passed** with
   nothing skipped. **Run it from an ext4 copy**, not `/mnt/c` — the 9p mount throws
   transient EIO under gate load, and `run_tests.sh` misreports that as
   `SKIP … (suite has not landed yet)` because `[ ! -f ]` is true when a file cannot be
   read. Measured 2026-09-25: 10 suites failed on `/mnt/c`, all passed on ext4.
2. Reproduce the original failure end to end: start a gate run, `kill -9` its process
   group mid-run, confirm the dashboard is stranded on the temp home and the board renders
   `(0)` in every column, then run any `agentmux` command and confirm it repairs and says
   so. Check the board is back to 84 done / 2 open.
3. Confirm `agentmux run start` still emits a bare run id on stdout while a repair fires.
4. `time agentmux help` with no marker present — the added cost must be unmeasurable.

## Risks

1. **stdout contamination.** The single most likely way this breaks something that works
   today. Test 4 exists for it.
2. **Repairing when a gate is legitimately running**, which would black out the board
   mid-gate. Guarded by the `kill -0` check and by the marker living in the operator home;
   tests 2 and 7 cover both halves.
3. **PID reuse** making a dead gate look alive. Accepted — it is the same exposure
   `courier.py` and `dispatch.py` already carry, and the failure mode is "does not repair
   yet", not "repairs wrongly".
4. **A repair storm** if several agents run `agentmux` at once after a kill. The
   `mkdir` lock makes one winner; the rest skip.
