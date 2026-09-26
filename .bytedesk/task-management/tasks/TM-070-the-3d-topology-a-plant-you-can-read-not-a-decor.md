---
id: "TM-070"
kind: "task"
status: "open"
created: "2026-09-26T02:27:05.683Z"
board: "controllogix/ccontrolcenter"
title: "The 3D topology: a plant you can read, not a decoration"
epic: "EP-005"
acceptance: [{"text":"Origin is encoded in the material, so a guessed device and a confirmed one do not look alike without a click","done":false},{"text":"A device two sources disagree about renders as TWO linked nodes, never averaged into one","done":false},{"text":"dispose() releases every geometry, material, texture, listener and the RAF, proved by a test that asserts each created object was disposed","done":false},{"text":"Pauses on document.hidden and degrades to nothing silently on no WebGL or a lost context","done":false},{"text":"No hex literal: the palette is read from design/tokens.css, so retheming the product rethemes the scene","done":false},{"text":"prefers-reduced-motion removes auto-rotate, idle drift and focus easing","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:27:05.783Z"
---

packages/scene - standalone three.js, framework-agnostic, mounted by the
React app.

What makes it honest: devicetree.py already merges a segment scan, CIP
ListIdentity discovery and OPC UA endpoints while KEEPING the origin of every
contribution and RECORDING conflicts rather than resolving them. A port sweep
is an inference; a device that answered ListIdentity made a statement.
Rendering both with equal confidence would be the un-aged-value lie in three
dimensions.