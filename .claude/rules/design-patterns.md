---
description: Enterprise design-pattern governance for all project files
---

# Enterprise design-pattern governance

Follow `.bytedesk/design-patterns/agent-rules.md` for every architecture or design-pattern task. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before changing an architecture boundary or a registered implementation. Use `/design-patterns:catalog` for approved pattern lookup and `/design-patterns:architecture-map` to refresh diagrams.

When code or documentation uses, names, evaluates, replaces, or retires a Dofactory or Enterprise Integration Patterns pattern, update the registry and its evidence in the same change. Run `node .bytedesk/design-patterns/check.mjs check --root .` before completion.
