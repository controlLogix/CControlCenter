---
id: "ADR-0024"
kind: "adr"
status: "proposed"
created: "2026-09-25T14:46:17.215Z"
board: "controllogix/ccontrolcenter"
title: "WSL bridge: use Enable mirrored networking"
epic: "EP-001"
decisionKey: "84062e584306"
date: "2026-09-25"
updated: "2026-09-25T14:46:17.244Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: With the API in WSL and the field sidecar on Windows, they have to reach each other. This host runs WSL 2.3.26.0 with **no `.wslconfig`** — so NAT mode, `localhostForwarding=true`. That means Windows→WSL works (it is how you view the dashboard today, verified HTTP 200), but **WSL→Windows does not work on `127.0.0.1`** — it needs the host gateway, which changes on every WSL restart. So "the sidecar binds loopback only" and "the API is in WSL" cannot both be true as written. Notably, `modbus_rtu.py:97-98` names the escape hatch itself: *"On WSL2, USB serial/RS-485 adapters need usbipd attachment; a Windows COM mapping may not be usable."*

## Decision

**With the API in WSL and the field sidecar on Windows, they have to reach each other. This host runs WSL 2.3.26.0 with **no `.wslconfig`** — so NAT mode, `localhostForwarding=true`. That means Windows→WSL works (it is how you view the dashboard today, verified HTTP 200), but **WSL→Windows does not work on `127.0.0.1`** — it needs the host gateway, which changes on every WSL restart. So "the sidecar binds loopback only" and "the API is in WSL" cannot both be true as written. Notably, `modbus_rtu.py:97-98` names the escape hatch itself: *"On WSL2, USB serial/RS-485 adapters need usbipd attachment; a Windows COM mapping may not be usable."*** → chose **Enable mirrored networking**.

Rejected:
- **usbipd: put everything in WSL** — Attach the RS-485 adapter into WSL with `usbipd` — the route `modbus_rtu.py:97` names — and the Windows sidecar disappears entirely. One host, one filesystem, no cross-boundary anything, no shared secret, no networking mode change. Costs: usbipd must actually work with your adapter, and the field stack sits behind WSL2 NAT on the plant network.
- **Keep NAT, bind the vEthernet address** — No config change to your machine. The Windows sidecar binds the `vEthernet (WSL)` address with a firewall rule scoping it to the WSL subnet, and the API resolves the gateway at startup from `ip route show default`. Works today, but it is strictly weaker than loopback-only and the address churns on every WSL restart.
- **Decide it in Phase 1 on evidence** — Plan for mirrored networking, but make Phase 1.1's first task a spike that tries all three on this machine and records what actually worked — including whether usbipd binds your adapter. Costs a day up front; the repo's own convention is to measure before theorising.

**`dashboard/SPEC_CC.md:19` is a standing constraint: **"No secret is ever entered through the browser. Credentialed actions are displayed as commands with a 'your terminal' tag."** Phase 5 needs a logged-in Fidelity Playwright session, and that means a 2FA challenge. A code typed into the dashboard breaks that constraint outright. (Note Fidelity does not offer a retail API, and historically uses SMS/push rather than TOTP — so an unattended seed may not even be available.) How should the session get authenticated?** → chose **Persistent profile, manual re-login**.

Rejected:
- **Terminal-relayed 2FA prompt** — When Playwright hits the challenge, the session manager prints the prompt to your terminal with the "your terminal" tag the constraint already describes, and reads the code from stdin. Honors the letter and spirit of `:19`, and automates everything except the six digits. More moving parts than a persistent profile.
- **TOTP seed in the OS keyring** — Fully unattended — the seed lives in Windows DPAPI / the keyring and codes are generated on demand. Fastest path, but it stores the second factor beside the first, which removes most of what 2FA is for on an account that can move real money. Also may not be offered: Fidelity has historically used SMS/push.
- **Relax the constraint, prompt in the blade** — Amend `SPEC_CC.md:19` to allow a 2FA code (not a password) through the dashboard, rendered as a confirmation card in the blade. Most convenient, and honest about changing the rule rather than working around it — but it is the one constraint standing between the browser surface and your credentials.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._