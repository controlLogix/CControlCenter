---
id: "EP-005"
kind: "epic"
status: "open"
created: "2026-09-26T02:26:58.217Z"
board: "controllogix/ccontrolcenter"
title: "UI overhaul: motion, depth and 3D, without starting to lie"
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
updated: "2026-09-26T02:26:58.297Z"
---

The UI overhaul: motion, depth and a modern front end, without the product
starting to lie.

THE REFERENCE, AND WHAT MEASURING IT CHANGED. The brief was omen.ai - "these
animations and sleekness". Reading its actual CSS and bundles rather than a
screenshot turned up the useful fact: it is the SAME design language this
product already speaks. Near-black surfaces (#1a1a1a / #252525), a hot orange
accent (#ff5202), a cool blue-grey complement (#6a819b), and radii of 1 to 6px.
Not rounded, not pastel, no big gradient cards.

So SPEC_CC.md:26-33 - Valve-era Steam, flat dark slate, tight 1px borders,
dense information, a thin orange accent used sparingly and never as a fill - is
not being thrown away. It is being kept and extended with three things it does
not have: a warm ramp so orange can express MAGNITUDE rather than only
presence, motion specified as tokens, and depth at a strength that never
competes with a number.

Also measured, and it is why 3D is in scope rather than bolted on: the
reference ships three.js (its bundles carry three's own shader chunks verbatim -
skinIndex, linearToOutputTexel, fogColor), and its custom shaders are
DOM-REGISTERED rather than decorative - u_domBase, u_maskSize, u_glowRadius,
u_borderColor draw glow behind real HTML. Plus depth-map parallax (u_depth +
u_image), a gravity field (u_gravity) and domain-warped noise (u_warpScale,
u_noiseOffset, u_seed).

THE RULE THAT OUTRANKS EVERY AESTHETIC DECISION HERE. This product's entire
argument is that it does not lie to the operator: an age is measured at the
source, an unknown outcome is never retried, a port sweep is an inference and
says so. Motion is the easiest way to break that without noticing:

  - A value that animates between two numbers DISPLAYS NUMBERS THAT WERE NEVER
    TRUE for the length of the tween. On a live tag table that is a false
    reading, not a polish detail.
  - A decorative pulse meaning "live" is a freshness claim made by CSS instead
    of by measurement - the un-aged-value lie in another costume.
  - A reveal that has not finished is indistinguishable from data that has not
    arrived.

Each of those has a mechanical guard, not a convention. See design/tokens.css
and design/motion.css.

Built before this epic existed, and back-filled: design/tokens.css,
design/motion.css, design/motion.js, design/field.js.