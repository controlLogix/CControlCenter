# Portable visual review

Audience: Nick and Ryan reviewing the six proposed interfaces. This is a standalone review document, not a new product dashboard.

Mode: extension of the existing concept package. Preserve all six images, phase references, concept labels, current-capability distinctions and review restrictions. No source images are edited.

Design read: restrained developer-tool editorial layout for laptop reading. Visual variance 3 (stable full-width image sections); motion 1 (control feedback only); density 5 (short captions with optional notes); asset dependence 10 (all six existing images); brand fidelity 9 (existing dark slate, orange and dashboard mark).

Design decisions:

- Existing dashboard mark: `dashboard/assets/logo-ccc.svg`, embedded unchanged as an image. It identifies the existing dashboard lineage; no new logo is commissioned.
- UI imagery: the six final PNG files in `../concept-images/`, embedded unchanged.
- Background #1b2027; panel #22272e; text #d8dee6; bright text #f5f7fa; orange #ff9b4c; muted text #aeb9c7; border #3b4654.
- Typography: locally available Segoe UI or sans-serif; Consolas or monospace for compact labels. No downloaded fonts.
- Spacing: 8-pixel base, 16/24/32/48/64-pixel section rhythm. Body 17 pixels, title up to 76 pixels. Images lead each scene.
- Radius: 8 pixels on controls, 14 pixels on image containers. Borders establish hierarchy; no decorative gradients or animated effects.
- Layout: long-form responsive review, sticky section navigation, full-size image dialog and downloadable local notes. This is not a fixed-canvas slide deck.

Source structure follows the repository frontend policy. The repeated scene is an organism with an explicit presentation contract, public exports and focused escaping/accessibility tests. Native elements need no custom atom or molecule. One-use layout stays in the page; input state, local draft storage, image navigation and export belong to features. No runtime or product architecture pattern is added.

Claude Opus 5.5 authored the final page, scene markup, styles and interactions through a WSL terminal. The earlier choices above provided context, not a fixed layout. Its final design uses a title up to 84 pixels, large numbered scene headings, images wider than the reading column, and a side-by-side facts/notes layout that stacks on narrow screens. Fit, 100%, 150% and 200% image viewing is available. The source template defines the exact final tokens. See `design-provenance.json` for attribution and reviewed corrections.

Only the generated `../agentmux-visual-review.html` is needed for delivery. Build sources are retained here for future edits. The builder reads local assets and emits one file; the delivered page has no external runtime, remote font, telemetry or network request.

Review notes are local feedback, not an approval workflow. Local draft storage is best-effort; downloading notes is the durable sharing action. Keyboard access, reduced motion, responsive layout and non-script readability are provided.
