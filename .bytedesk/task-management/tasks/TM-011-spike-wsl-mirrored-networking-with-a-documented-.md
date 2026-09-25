---
id: "TM-011"
kind: "task"
status: "open"
created: "2026-09-25T15:20:33.454Z"
board: "controllogix/ccontrolcenter"
title: "Spike WSL mirrored networking, with a documented rollback"
epic: "EP-002"
acceptance: [{"text":"A Windows listener on 127.0.0.1:9999 is reachable from WSL, and a WSL listener on 127.0.0.1:9998 is reachable from Windows, both verified by curl","done":false},{"text":"DNS resolution, any VPN client in use, and Docker Desktop are each verified working or the interaction is documented","done":false},{"text":"The rollback is exercised once: delete .wslconfig, wsl --shutdown, confirm NAT behaviour returns","done":false},{"text":"docs/wsl-networking.md records the decision, the verification commands and the rollback","done":true,"at":"2026-09-25T16:25:29.759Z"},{"text":"If mirrored mode is rejected, the fallback is implemented and every loopback-only claim in the docs is corrected to loopback plus the WSL adapter","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:25:32.219Z"
comments: [{"author":"main","ts":"2026-09-25T16:25:31.274Z","text":"Half done, and deliberately stopped short. The BEFORE state is measured and written up in docs/wsl-networking.md: WSL eth0 172.30.116.31/20, gateway 172.30.112.1, and both failing directions proven by curl - 127.0.0.1:9999 from WSL is unreachable, and so is the gateway address, because the Windows listener is loopback-bound. That second result is the one that matters: reaching Windows from WSL under NAT is not just using the gateway, the Windows service must also bind the vEthernet address. So loopback-only and API-in-WSL cannot both hold. The flip itself is NOT applied. Mirrored networking is a machine-wide change that brings WSL traffic under Windows Firewall and has known interactions with other hypervisors virtual adapters - and this host has VMware VMnet1 and VMnet8 up right now. It also needs wsl --shutdown, restarting every distro. Nothing in Phase 1 exists yet that needs the hop, so flipping it while the operator is away buys nothing and risks disturbing VMware networking nobody can observe. Apply it when Phase 1.1 stands the sidecar up, with the operator present. The procedure, both-direction verification, the VMware/Docker/VPN checks and the one-line rollback are all in the doc."}]
assignee: "claude"
---

The other Phase 1 prerequisite, and the one with blast radius outside this repo.

Measured: **no `%USERPROFILE%\.wslconfig` exists**, so WSL 2.3.26.0 is in default NAT mode. Windows to WSL works — the dashboard answers HTTP 200 from a Windows curl, which is how it is viewed today. **WSL to Windows does not work on `127.0.0.1`**; it needs the host gateway (`172.30.112.1` today), which changes on every WSL restart.

So "the field sidecar binds loopback only" and "the API runs in WSL" cannot both be true as written. ADR-0023 chose mirrored networking:
```ini
[wsl2]
networkingMode=mirrored
```
Supported here (WSL 2.3.26.0 >= 2.0.0, Windows 10.0.26200 >= 22H2). It also repairs `netscan.py`'s documented WSL degradation — `netscan.py:186-201` names mirrored mode as the case where the Linux ARP path is correct.

**Risk worth a spike rather than a leap:** it is a global networking change, brings WSL traffic under Windows Firewall, and has historically disturbed VPN split-tunnel and Docker Desktop — and `docker-desktop` is an installed distro on this host. Requires `wsl --shutdown`, which restarts every distro, so schedule it.

Fallback if rejected: services bind the `vEthernet (WSL)` address with a firewall rule scoped to the WSL subnet, and the API re-resolves the gateway on connection failure. If that path is taken, **stop calling it loopback-only in the docs** — say "loopback plus the WSL adapter", or someone later relies on a property the system does not have.