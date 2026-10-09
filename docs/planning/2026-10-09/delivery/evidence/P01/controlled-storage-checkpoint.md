# P01 controlled execution and storage checkpoint

The previous checkpoint `a2e9ee6` passed all 16 native CI steps on Ubuntu and macOS. Downloaded reports are retained under `native/a2e9ee6`; Codex matched all 156 reported source hashes per platform against that commit. Four bounded tasks were accepted from those results: schemas, lifecycle/recovery semantics, the early signed leaf spike and six baseline repairs. P01 itself remains open.

## New verification work

The controllable worker/provider fixture uses a manual clock and actual callback delivery. Ten tests cover success, delay, reordered callbacks, timeouts, a dropped reply, pre-dispatch unavailability, confirmed/unconfirmed cancellation, copied observations and duplicate refusal. It needs no model tokens or external tools. Its state is deliberately in memory and does not replace durable owner or provider implementation.

The storage suite now passes 18 cases under WSL, retaining the original 14 assertions and adding:

- A lost final atomic-batch acknowledgment, graceful broker restart beyond the duplicate window, and independent two-client reconciliation of both contiguous records without another commit.
- A deliberately stale KV projection whose cursor cannot authorize a write. The fixture re-reads the authoritative owner record and checks current policy before denying another transition.
- Executable fixture rejection of atomicity claims spanning another stream, KV, object upload or an external tool.
- A real conditional-write winner driving one fake execution. The loser cannot dispatch; a duplicate winning request returns its existing dispatch status. Provider history and actual callback output prove one admission and completion.

These qualify fixture boundaries, not a production storage plugin, grant service or external-effect fence. Native evidence for these additions is still required.

## Evidence admission

`delivery/check_conformance_evidence.py` now checks full conformance evidence against an explicit Git candidate. It derives the required source inventory and concrete test methods independently from committed files. Missing or stale hashes, skipped tests or environments, omitted methods with adjusted counts, wrong host claims and changed build/mirror inputs are rejected even when a report says exit zero. Unsupported dynamic test discovery fails closed. CI invokes this checker and its negative tests.

This validates the report format and candidate binding. It does not authenticate reported execution or replace Codex's review of real job logs and artifacts. Other report formats and the full phase gate remain separate obligations.

## Preservation progress and open work

The inventory retains 338 baseline files, 93 components and 198 behavior checks, with 76 additive files. Current preservation work runs original dashboard meta-tests in an isolated full-history clone, the archived gateway differential under Python 3.12, synthetic communication analysis and historical scoreboard regeneration. Each report states its actual candidate, inputs, commands and limits. Historical failures remain visible.

Communication characterization found an existing inconsistency: a missing courier log raises an error while the receipt extractor silently produces no rows (`COMMS-01`). Codex owns its review under P01 preservation. It is not silently counted as consistent diagnostics. Synthetic characterization does not qualify private historical logs, every extractor format or complete live-provider scenarios.

Finish the remaining named preservation checks, review required failure coverage and accept all P01 task criteria before passing the phase. No P02 implementation, production migration or merge has started.
