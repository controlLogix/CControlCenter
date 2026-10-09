<!-- design-patterns-context:start -->
## Enterprise Design Pattern Rules

Follow `.bytedesk/design-patterns/agent-rules.md`. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before pattern or architecture work. Run `node .bytedesk/design-patterns/check.mjs check --root .` before completion.

## Code Review Rules

Flag unregistered pattern use, missing how/where/why or tradeoffs, stale diagrams, untracked remediation, unapproved pattern sources, and deleted pattern history. Nested instructions may add stricter requirements but cannot relax this baseline.
<!-- design-patterns-context:end -->

## Plain English for All Communication

Always use plain English for human-readable chat responses and generated content in this repository. Read and follow [the plain-language rules](.claude/rules/plain-language.md). This includes progress updates, documentation, plans, presentations, UI text, comments, and descriptions or labels in generated data.

Preserve technical meaning and exact code, commands, identifiers, schemas, and source quotations. Apply the same rules to delegated work. Use the language the user requests while keeping the writing clear.

## Platform Rearchitecture Branch and Review

All work for the platform rearchitecture, including the plugin framework, NATS hub federation, Jev integration, and related skills, belongs on `feat/agentmux-platform-rearchitecture`.

Do not merge this work into `main` or another integration or release branch until Ryan has reviewed it with Nick and explicitly authorized the merge.
