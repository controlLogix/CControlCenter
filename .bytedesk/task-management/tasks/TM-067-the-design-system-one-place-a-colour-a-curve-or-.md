---
id: "TM-067"
kind: "task"
status: "open"
created: "2026-09-26T02:27:00.133Z"
board: "controllogix/ccontrolcenter"
title: "The design system: one place a colour, a curve or a duration is decided"
epic: "EP-005"
acceptance: [{"text":"Every colour, easing curve, duration, radius and z-index is a custom property in design/tokens.css","done":false},{"text":"prefers-reduced-motion and an explicit data-motion=off switch both zero every duration, the stagger, and the field","done":false},{"text":"The layout is correct with every duration at zero","done":false},{"text":"A reveal that never fires cannot blank the page - hiding only applies once the script claims the document, and a backstop reveals everything after a budget regardless","done":false},{"text":"The stagger is capped, because a 60-row table at 28ms a row takes 1.7s to arrive and is indistinguishable from one still loading","done":false},{"text":"The field degrades to nothing silently on no WebGL, a lost context or a compile failure, and pauses on a hidden tab","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:38.850Z"
session: "pool-tm-067"
---

BUILT - design/tokens.css, design/motion.css, design/motion.js, design/field.js.
Back-filled so the work is attributable.

Tokens rather than literals is not tidiness here. It is what makes the
reduced-motion block able to switch ALL motion off in one place - a duration
literal inside a component is a duration that cannot be switched off, and some
people are made ill by the ones this epic adds.

The field is raw WebGL, not three.js: a background does not need a scene graph,
and 600 KB on every page load for a gradient is a poor trade in a product whose
dependency policy is 'installs from a clone with no network'.