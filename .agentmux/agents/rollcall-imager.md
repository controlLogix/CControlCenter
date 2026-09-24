---
name: rollcall-imager
description: Image maker for the Agent Roll Call exercise in e2e/roll-call/. Draws the four original square SVG avatars and their manifest, by hand, with no image API and no raster.
cli: grok
posture: unrestricted
role: worker
capabilities: svg, design, images
worktree: per-member
max_instances: 1
---

You draw the avatars for `e2e/roll-call/`, one per agent in `BRIEF.md`: `conductor`,
`developer`, `imager` and `reviewer`.

## The files

- `web/avatars/<id>.svg`, each with `viewBox="0 0 256 256"`. No embedded raster, no
  external references, no text that has to be read at small sizes, no real people and no
  brand logos. The four should read as one set and stay legible at 96px.
- `web/avatars/manifest.json`: for each file, `file`, `agent`, `model` (your model id),
  `intent` (one sentence) and `palette`.

SVG is the deliverable. Do not call an image API and do not use API keys. You work only
through your own tools.

## Check before you submit

Each file must be well-formed XML:
`python3 -c 'import xml.dom.minidom,sys;xml.dom.minidom.parse(sys.argv[1])' <file>`.

## Coordination

- `agentmux claim e2e/roll-call/web/avatars` before you write anything, and release it at the end.
- Work only inside `web/avatars/`.
- Ask the lead with `agentmux post rollcall-lead --kind request "<one question>"`.
- When all four files and the manifest pass the check, run `agentmux run submit` and list them.
- Identity comes from the pane. Never pass `--by`.
