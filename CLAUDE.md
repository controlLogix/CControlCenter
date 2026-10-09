<!-- design-patterns-context:start -->
## Enterprise design pattern rules

Follow `.claude/rules/design-patterns.md`. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before pattern or architecture work. Update the registry and diagrams in the same change as affected code or documentation.
<!-- design-patterns-context:end -->

## Plain English for All Communication

Always use plain English for human-readable chat responses and generated content in this repository. Read and follow [the plain-language rules](.claude/rules/plain-language.md). This includes progress updates, documentation, plans, presentations, UI text, comments, and descriptions or labels in generated data.

Preserve technical meaning and exact code, commands, identifiers, schemas, and source quotations. Apply the same rules to delegated work. Use the language the user requests while keeping the writing clear.

## Platform Rearchitecture Branch and Merge Gate

All planning and implementation work stays on `feat/agentmux-platform-rearchitecture`. Do not merge, squash, cherry-pick or otherwise transfer it into `main` or another integration or release branch until MERGE-01 in [the implementation plan](docs/planning/2026-10-09/implementation-plan.md) is satisfied. Do not enable automatic merging.

Before merging, the entire approved plan must be functional and its required phase acceptance and verification checks must pass. Ryan and Nick must connect their own real instances, each successfully delegate a simple, non-destructive orchestration to the other, and review the recorded execution and acceptance evidence together. A local simulation or worker completion alone is insufficient. Ryan must then explicitly authorize the merge. No phase pass, commit, push or earlier plan approval substitutes for this final approval.
