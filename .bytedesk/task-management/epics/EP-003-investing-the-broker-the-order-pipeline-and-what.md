---
id: "EP-003"
kind: "epic"
status: "open"
created: "2026-09-26T02:01:34.581Z"
board: "controllogix/ccontrolcenter"
title: "Investing: the broker, the order pipeline, and what must never be in this repo"
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
updated: "2026-09-26T02:01:34.626Z"
---

Plan Phase 5. Split from EP-002 because it has a different failure mode from
everything else in this project: unlike every other write path here, a bad trade
cannot be reversed by writing the old value back.

Three standing constraints govern everything under this epic.

1. THE REPO IS PUBLIC. No research pack, position, balance, account number,
   order record or credential may ever land in the tree. Everything runtime
   lives in %LOCALAPPDATA%\agentmux\broker\ and $AGENTMUX_HOME/investing/.
   dashboard/check_no_financial_artifacts.sh is in the gate and must stay green.
   Note that agentmux-broker/ itself is SOURCE and is correctly tracked -
   mistaking it for an artifact path has already broken three tools at once.

2. NO SECRET IS EVER ENTERED THROUGH THE BROWSER (SPEC_CC.md:19). This drives
   the 2FA design - persistent profile, manual re-login - and the credential
   store. The API key must never go in ~/.agentmux/env, which is sourced into
   every agent pane and would hand it to every worker.

3. ADR-0019 recorded that automating Fidelity's web UI was chosen over the
   recommended read-only option. That decision stands and is not reopened. The
   ADR records dry-run default, kill switch on by default, and typed
   confirmation as NON-OPTIONAL; this plan adds read-back verification and
   server-side guardrails to that list.

Built before this epic existed, and back-filled as tasks so the work is
attributable: agentmux-broker/killswitch.py, agentmux-broker/guardrails.py,
docs/investing-boundary.md, and the boundary gate (TM-034).