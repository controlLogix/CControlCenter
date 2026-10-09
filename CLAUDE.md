<!-- design-patterns-context:start -->
## Enterprise design pattern rules

Follow `.claude/rules/design-patterns.md`. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before pattern or architecture work. Update the registry and diagrams in the same change as affected code or documentation.
<!-- design-patterns-context:end -->

## Plain English for All Communication

Always use plain English for human-readable chat responses and generated content in this repository. Read and follow [the plain-language rules](.claude/rules/plain-language.md). This includes progress updates, documentation, plans, presentations, UI text, comments, and descriptions or labels in generated data.

Preserve technical meaning and exact code, commands, identifiers, schemas, and source quotations. Apply the same rules to delegated work. Use the language the user requests while keeping the writing clear.

## Platform Rearchitecture Branch and Delivery Review

Maintain [delivery/tasks.json](docs/planning/2026-10-09/delivery/tasks.json) using [the tracking procedure](docs/planning/2026-10-09/delivery/README.md). Update status, blockers, evidence and commit references as work changes and regenerate the board. Each phase must pass its separate review/verification gate; commit and push its candidate and verify the remote commit before advancement. This repository tracker replaces Jira and records Codex review and final branch acceptance under MERGE-01.

Follow [the local testing workflow](docs/LOCAL_TESTING.md): focused fail-fast tests while editing, failed-test reruns while fixing, then affected integration suites and required phase verification on the stable candidate. Reuse prepared dependencies and disposable fixtures. Do not rerun unrelated full suites or rebuild presentations after each edit. A fast pass never substitutes for phase acceptance.

All planning and implementation work stays on `feat/agentmux-platform-rearchitecture`. Do not merge, squash, cherry-pick or otherwise transfer it into `main` or another integration or release branch. Do not enable automatic merging. Final acceptance authorizes only the final commit and push to this feature branch.

The user's latest delivery instruction supersedes the earlier Ryan/Nick review gates: work autonomously through all phases, with Codex as reviewer and advancement authority. Ryan and Nick are not required for any delivery task, review, phase transition or final commit/push. Use subagents for bounded parallel work and independent review within the single active phase. Do not work on a later phase until the current phase passes its evidence gate and its candidate is committed, pushed and verified remotely.

Keep all acceptance, security, preservation, recovery and supported-environment checks. Codex must review actual evidence and resolve findings; worker completion or a passing narrow test is not phase acceptance. Preserve the full user scope. Product approval and authorization policies remain product requirements. MERGE-01 retains its historical identifier but now means final branch acceptance: independently enroll two real agent-operated hubs, demonstrate safe bilateral orchestration with exact-candidate evidence, complete every required phase, and record Codex's final review. Mocks cannot replace the real-hub demonstration. No merge or release is authorized.
