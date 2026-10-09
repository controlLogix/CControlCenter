<!-- design-patterns-context:start -->
## Enterprise Design Pattern Rules

Follow `.bytedesk/design-patterns/agent-rules.md`. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before pattern or architecture work. Run `node .bytedesk/design-patterns/check.mjs check --root .` before completion.

## Code Review Rules

Flag unregistered pattern use, missing how/where/why or tradeoffs, stale diagrams, untracked remediation, unapproved pattern sources, and deleted pattern history. Nested instructions may add stricter requirements but cannot relax this baseline.
<!-- design-patterns-context:end -->

## Plain English for All Communication

Always use plain English for human-readable chat responses and generated content in this repository. Read and follow [the plain-language rules](.claude/rules/plain-language.md). This includes progress updates, documentation, plans, presentations, UI text, comments, and descriptions or labels in generated data.

Preserve technical meaning and exact code, commands, identifiers, schemas, and source quotations. Apply the same rules to delegated work. Use the language the user requests while keeping the writing clear.

## Local test iteration

Follow [the local testing workflow](docs/LOCAL_TESTING.md). During debugging, use an explicit test or `hub/tests/local.ps1` (WSL) / `python -m hub.tests.run_local` (Linux/macOS). Rerun failures before broadening the selection. Run affected integration suites and required phase checks on the stable candidate; a fast pass never substitutes for them. Reuse prepared local dependencies, preserve disposable fixtures, and avoid unrelated full-suite runs or presentation rebuilds during each edit.

## Platform Rearchitecture Branch and Review

Track implementation work in [delivery/tasks.json](docs/planning/2026-10-09/delivery/tasks.json), following [the tracking procedure](docs/planning/2026-10-09/delivery/README.md). Update task status, blockers, evidence and commit references as work changes; regenerate the status board with `delivery/track.py`. Each phase has a separate verification task. Complete required review, commit and push the phase candidate, verify its remote commit, and record the gate before advancing. Keep historical evidence distinct from current acceptance. Repository tracking replaces Jira for this work.

All work for the platform rearchitecture, including the plugin framework, NATS hub federation, Jev integration, and related skills, belongs on `feat/agentmux-platform-rearchitecture`.

All planning and implementation work stays on `feat/agentmux-platform-rearchitecture`. Do not merge, squash, cherry-pick or otherwise transfer it into `main` or another integration or release branch. Do not enable automatic merging. Final acceptance authorizes only the final commit and push to this feature branch.

The user's latest delivery instruction supersedes the earlier Ryan/Nick review gates: work autonomously through all phases, with Codex as reviewer and advancement authority. Ryan and Nick are not required for any delivery task, review, phase transition or final commit/push. Use subagents for bounded parallel work and independent review within the single active phase. Do not work on a later phase until the current phase passes its evidence gate and its candidate is committed, pushed and verified remotely.

Keep all acceptance, security, preservation, recovery and supported-environment checks. Codex must review actual evidence and resolve findings; worker completion or a passing narrow test is not phase acceptance. Preserve the full user scope. Product approval and authorization policies remain product requirements. MERGE-01 retains its historical identifier but now means final branch acceptance: independently enroll two real agent-operated hubs, demonstrate safe bilateral orchestration with exact-candidate evidence, complete every required phase, and record Codex's final review. Mocks cannot replace the real-hub demonstration. No merge or release is authorized.
