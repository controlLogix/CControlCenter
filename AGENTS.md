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

All planning and implementation work stays on `feat/agentmux-platform-rearchitecture`. Do not merge, squash, cherry-pick or otherwise transfer it into `main` or another integration or release branch until MERGE-01 in [the implementation plan](docs/planning/2026-10-09/implementation-plan.md) is satisfied. Do not enable automatic merging.

Before merging, the entire approved plan must be functional and its required phase acceptance and verification checks must pass. Ryan and Nick must connect their own real instances, each successfully delegate a simple, non-destructive orchestration to the other, and review the recorded execution and acceptance evidence together. A local simulation or worker completion alone is insufficient. Ryan must then explicitly authorize the merge. No phase pass, commit, push or earlier plan approval substitutes for this final approval.
