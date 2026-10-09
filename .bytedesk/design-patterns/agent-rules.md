# Enterprise design-pattern rules

These rules apply to every architecture, implementation, refactoring, review, and documentation change in an initialized repository.

1. Read `.context/design-patterns.md` and `.context/design-patterns-diagrams.md` before pattern or architecture work.
2. Use the pinned Dofactory and Enterprise Integration Patterns catalogs in `.bytedesk/design-patterns/catalog.json` as the only sources for discovering, naming, recommending, or diagnosing design patterns.
3. Select a pattern only for an evidenced design pressure. Record its applicability, simpler alternative, costs, and repository-specific tradeoffs. Do not add patterns for coverage or appearance.
4. Discover greenfield architecture through the project interview. Do not default every project to one architecture, framework, broker, or deployment model.
5. Record every planned, applied, observed, referenced, evaluated, replaced, or retired pattern in `.context/design-patterns.md`, including how, where, and why it is used.
6. Update `.context/design-patterns-diagrams.md` in the same change when an applied or observed pattern, its location, or a documented relationship changes.
7. Preserve registry and remediation history. Retire or resolve entries with evidence instead of deleting them.
8. New and changed code must satisfy the enterprise baseline. Unchanged brownfield violations require owned, dated remediation with evidence.
9. Run `node .bytedesk/design-patterns/check.mjs check --root .` before reporting completion. Treat a failing check as incomplete work.
10. Do not edit generated catalog data, diagram managed sections, baseline digests, or review evidence merely to silence enforcement.
11. For web and desktop presentation code, follow `.bytedesk/design-patterns/frontend-rules.md`: reusable components live only in `src/components/{atoms,molecules,organisms,templates}`, lower tiers never import higher tiers, and route/data/service orchestration remains in pages, screens, and features.
