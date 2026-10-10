# P01 preservation repairs

Codex reviewed these changes against candidate `37e0d8cd7439d31a491ac673e73438f7885cd04e`. P01 remains open. Original failures and missing prerequisites remain in the evidence; they are not rewritten as successful runs.

- `dashboard/test_field_panels.py`: the loopback scan could finish between two HTTP requests. The replacement holds the actual scan worker behind an event, checks both HTTP 400 and the original refusal message, and releases and joins workers in `finally`. Production scanner code is unchanged. Removing the production concurrency guard in a disposable copy causes both rejection assertions to fail. The full field-panel suite passes 213 checks with the guard present.
- `dashboard/test_e2e.mjs`: the existing UI already includes Federation after Hub. The old expected navigation list omitted it. The replacement retains an exact ordered comparison and all original views, adding Federation at its actual position. The focused Firefox suite passes 49 checks. This changes no UI behavior.
- `hub/tests/test_hub_offline.py`: all existing methods remain. Three additional methods cover all eight address forms, canonical round trips, explicit NATS subjects, malformed identities and maximum name lengths in both agent spellings. The new tests exposed seven trailing-newline cases and three oversized hyphenated name cases in the old implementation.
- `hub/names.py`: `fullmatch` prevents a trailing newline from being accepted as a name. The hyphenated session parser now checks the same per-part limits as the slash form. Valid address forms and explicit normalization remain unchanged. Previously accepted malformed names are now rejected; this is a validation repair, not a new identity adapter.
- `tests/storage/run.py`: the report's limitation text now refers to its recorded host platform. Earlier native macOS reports retain the incorrect static “no native macOS” sentence, with that discrepancy explained in their archive review. All storage assertions remain unchanged.
- `tests/contracts/README.md`: documents the additional original-hub CI checks and pinned NSC prerequisite. Existing contract and broker qualification requirements remain.

Native CI now adds original hub/federation execution and report admission to the existing checks. It supplies the broker and NSC, isolates runtime state, and rejects skipped tests. The next committed candidate still needs its actual macOS and Linux results reviewed. Fixture storage tests do not establish production enrollment, cross-organization authorization or final bilateral acceptance.

Evidence locations: `dashboard-full-fba373a/`, `field-race-review/`, `pattern-negative-result.json`, and `../native/37e0d8c/review.json`. Further full-run and name-regression reports retain their own source hashes and outcomes. The architecture negative fixture passed its unchanged baseline, rejected each of the three deliberate mutations, and passed after restoration; the original review and registry stayed unchanged.

Missing external `agentmux-orchestration` plugin coverage and real-provider scenario repetitions remain open. An unrelated installed orchestration plugin is not equivalent evidence. No phase advancement or merge is authorized by this checkpoint.

## Follow-up fixture timing repairs

The second full dashboard run passed the scanner and browser checks, but exposed two additional timing races in unchanged tests. That failed run remains in `dashboard-full-repaired/`.

- `dashboard/test_mqtt.py` now waits for the actual DISCONNECT packet before inspecting the broker's completed packet sequence. It retains all original checks, including exactly one PUBLISH and the exact topic, payload and QoS. HTTP completion for QoS 0 did not mean the broker's thread had read the bytes. Two focused runs passed 57 checks each; deliberately suppressing PUBLISH failed the original exact-count assertion. See `dashboard-full-mqtt/`.
- `dashboard/test_residue.sh` now makes its fake readiness probe wait for the fixture server's startup record. The old stub returned success before the server started, allowing SIGINT to arrive before there was a process to clean up. All 26 assertions remain. Two ordinary runs and one with a deliberate half-second server startup delay passed. See `dashboard-full-residue/`.

Production MQTT, scanner and dashboard cleanup code did not change. No further full dashboard run is claimed after these repairs. Windows-owned client forwarding changes how isolated client configurations must be passed; that boundary must be checked before another full run.


## Windows-backed rerun and storage boundary follow-up

The later source-identical Windows-backed dashboard runner passed all 62 suite entries on `09fe9c7` using a short private temporary root. Both the preceding socket-path failure and passing rerun are retained in `../dashboard-windows/`. Twenty external-plugin tests remain skipped; configuration routing does not qualify provider inference or Windows state storage over Linux UNC.

Native Ubuntu CI on `09fe9c7` exposed a real backup filename race: seconds and milliseconds were sampled separately across a second boundary. `Store.backup_to` now uses one captured time. Seven focused backup checks pass, and the new deterministic rotation check fails against the original implementation. The unchanged original governance methods and independent review are recorded in `../parent-change-review.json`; raw proof is archived in `../backup-boundary/`.

The existing storage fixture now checks complete incoming blocked state, exact origin and one claim intent before a single conditional publish. All prior cases and assertions remain, with two added Python/TypeScript cases. Construction failures leave no record; a simulated caller exception after commit reconciles one retained complete record. Twenty positive cases pass, and an injected partial publication fails. See `../incoming-storage/`, `../incoming-storage-negative/` and the independent review. This is fixture persistence proof, not process-kill, production authorization or provider dispatch proof.

A bounded local full hub run passed 129 tests, and conformance passed 45 tests before the subsequent callback admission repair. Those reports are retained separately in `../hub-current-pre-followup/` and `../conformance-reviewed/`. Changed callback sources require fresh affected verification, and final native candidate results remain required. P01 stays open.
