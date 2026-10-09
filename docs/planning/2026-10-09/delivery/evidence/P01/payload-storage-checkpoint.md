# P01 payload and storage checkpoint

This checkpoint extends the independent Python and TypeScript contracts and qualifies a bounded JetStream fixture. It does not accept P01 or advance to P02.

## Contract changes

Ten closed payload schemas and a local registry bind each supported command, event or reply to its contract major, message kind and logical destination. Full signed-envelope verification now also validates that payload and its task, attempt, delegation and reply correlation. An unknown contract or arbitrary object cannot pass full admission merely because its signature is valid.

Both SDKs also enforce structural rules carried forward from the P00 draft: exact protected membership, dependency intervals and identities, declared kernel access, context/grant binding, calendar dates, attestation binding and unique effect identities. A rejected owner operation cannot carry execution effects. These checks do not resolve current grants, enroll keys or implement domain state transitions.

The request actor's grant and a delegated execution grant are distinct records. Owners must validate the execution grant against the reservation; equality with the request actor's grant is not a valid shortcut. Unknown outcomes retain reservation and require reconciliation of the same operation and digest. A retry flag does not authorize a fresh execution.

The final `conformance-payload-result.json` records 21 tests and 622 subtests passing, with no skips or errors, in 35.158 seconds including report checks. Python's 14 unit tests and TypeScript's nine unit tests also passed during implementation. The cross-language result binds the exact schemas, SDK sources, compiled TypeScript files and fixture inputs.

The first expanded run took 339.705 seconds and hit the existing 60-second limit in one Python payload batch. `conformance-payload-before-mirror.json` retains that failure. Repeated schema reads through the WSL Windows mount were the bottleneck. The harness now makes an owned temporary copy of the Python SDK and contract inputs on the native filesystem, compares every copied input with the repository before and after testing, checks that the copy stayed unchanged, and removes it on exit. No SDK validation, vector or timeout was removed. The failed selection passed in 2.198 seconds before the full rerun. See `conformance-payload-focused.json`; focused success alone was not treated as full acceptance.

## Storage evidence and review

`storage-result.json` records fourteen executed scenarios against NATS Server 2.15.0, nats-py 2.16.0 and an independent TypeScript NATS client. The final run passed in 8.677 seconds on WSL. It uses one disposable file-backed broker, no real project data, synthetic provenance and private temporary credentials.

The scenarios prove a single winner for competing conditional writes, cross-language authoritative reads, recovery of an older operation after an omitted acknowledgment, graceful restart and duplicate-window expiry, changed-digest replay rejection, atomic batch visibility, failed and abandoned batches, stale conditions checked again at commit, cross-stream refusal and explicit history-gap errors. The owner fixture writes state, provenance and effect intent together. Its bounded history scan is not a production replay index.

Review found that a batch-opening acknowledgment can have an empty body. It means staging, not commitment. The TypeScript raw fixture now handles that response and still requires final commitment. A further review found that recording source and compiled hashes alone did not prove that cached build inputs matched this checkout. The runner now compares all TypeScript source, package, lock and compiler inputs, records their hashes and rejects changes during execution. The fourteen scenarios passed again after this fix. Staged-byte verification also caught a CRLF package file that Git would normalize. Its repository and cached copy were normalized to LF, and all fourteen scenarios passed again; the retained report now matches the actual staged source bytes.

These results do not prove replicated availability, leaf links, native macOS behavior, sudden power-loss durability, real tenant authorization, arbitrary retention or external-effect transactions. Those requirements remain open.

All 33 retained P00 acceptance source hashes still match. The component inventory covers 397 files, preserving 338 baseline files, 93 components and 198 behavior checks. All 22 tracker tests pass after explicitly reconciling the new inventory and retaining previous fingerprints. An earlier tracker run correctly rejected the not-yet-reconciled inventory; no criterion or dependency was removed to obtain the passing result.

## Remaining phase work

The five accepted lifecycle/work models still need promoted executable transition and ordered-history fixtures. Replay, deadline, cancellation and receipt-versus-result rules need complete model coverage. Real replicated/leaf topology and supported-environment evidence, compatibility checks, phase-wide preservation verification and the P01 gate also remain required. See `remaining-contract-work.md` and the authoritative task ledger. No merge is authorized.
