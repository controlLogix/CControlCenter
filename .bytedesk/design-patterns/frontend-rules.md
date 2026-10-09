# Strict frontend component architecture

This rule applies to web and desktop presentation code. It is ADAG enterprise policy, not a claim that Dofactory mandates Atomic Design.

## Required structure

Every frontend source root uses this structure:

```text
src/
  components/
    atoms/
    molecules/
    organisms/
    templates/
  pages/                 # route-aware web compositions
  screens/               # navigation-aware desktop/mobile compositions
  features/              # use cases, state, services and domain-facing adapters
```

Use `pages` for routed web entry points and `screens` for desktop or mobile navigation entry points. A project may have one or both. All reusable visual components belong under one of the four `src/components` tiers. Do not create parallel `common`, `shared`, `widgets`, `ui`, or feature-local component directories.

Each component has one PascalCase directory containing its implementation, focused test, public `index`, and—when used by the project—story and colocated styles. Export public components from their own `index` and a tier-level index. Do not use a repository-wide wildcard barrel that exposes internal helpers.

## Tier contracts

- **Atoms:** One semantic UI primitive. No routing, remote I/O, application state, domain service, or feature workflow knowledge. Accept presentation data and events through an explicit public contract.
- **Molecules:** A small reusable composition of atoms with one interaction or presentation responsibility. No routing, remote I/O, or application state ownership.
- **Organisms:** A reusable, cohesive section built from atoms and molecules. It may coordinate local UI state and domain-shaped input, but receives application data and actions through explicit inputs rather than importing feature services.
- **Templates:** Layout and placement expressed through slots, children, or equivalent composition. No remote I/O, route loading, feature decisions, or domain mutation.
- **Pages and screens:** Composition roots connecting routes/navigation, use cases, state, services, and reusable components. They are not exported as reusable components.
- **Features:** Application use cases, state, validation, service adapters, and orchestration. Features may depend on public component contracts; components must not depend on feature implementations.

Dependencies flow `pages/screens -> features + templates/organisms -> molecules -> atoms`. A lower tier cannot import a higher tier. Components at the same tier must not form cycles.

## Atomization rule

Before adding a component, search existing tiers for a component or composition that satisfies the contract. Extract a lower-level component when a stable visual or interaction responsibility repeats, has a meaningful independent contract, or needs independent testing. Do not split markup solely to maximize component counts; a one-use fragment without an independent responsibility stays with its owner.

Reuse must preserve semantics, accessibility, state ownership, and failure behavior. Do not create option-heavy universal components combining unrelated responsibilities. Prefer composition, explicit variants, and small public contracts.

All new or moved frontend component files follow this structure immediately. Brownfield violations remain visible through DP011 findings and owned remediation until migrated; changed violating files cannot remain deferred.
