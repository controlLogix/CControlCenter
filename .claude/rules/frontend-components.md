---
paths:
  - "**/*.{ts,tsx,js,jsx,vue,svelte,html,css,scss,razor,xaml,cs,swift,kt}"
---

# Frontend component architecture

For web and desktop presentation work, follow `.bytedesk/design-patterns/frontend-rules.md` and `src/components/{atoms,molecules,organisms,templates}`. Reusable visual components cannot live in feature-local, `common`, `shared`, `widgets`, or alternate `ui` component directories.

Search for an existing component before creating one. Keep route/navigation, data loading, application state, and service orchestration in pages, screens, and features. Keep atoms, molecules, organisms, and templates reusable through explicit inputs, outputs, composition, accessibility behavior, and tests.

Run the installed governance check after adding, moving, or changing frontend components.
