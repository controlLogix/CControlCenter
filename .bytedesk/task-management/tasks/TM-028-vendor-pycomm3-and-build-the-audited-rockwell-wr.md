---
id: "TM-028"
kind: "task"
status: "open"
created: "2026-09-25T21:16:53.690Z"
board: "controllogix/ccontrolcenter"
title: "Vendor pycomm3 and build the audited Rockwell wrapper"
epic: "EP-002"
acceptance: [{"text":"pycomm3 is vendored py3-none-any with a recorded URL, sha256, version and licence, and has no runtime dependencies","done":true,"at":"2026-09-25T21:16:58.642Z"},{"text":"check_vendor.sh verifies the vendored bytes offline, refuses compiled extensions and committed bytecode, and proves the import comes from field/vendor with site-packages stripped","done":true,"at":"2026-09-25T21:16:58.903Z"},{"text":"field/rockwell.py is the only importer of pycomm3, asserted by a check that parses rather than greps","done":true,"at":"2026-09-25T21:16:59.112Z"},{"text":"Tag browsing reports controller-sourced instance ids, and UDT templates and members decode with offsets and bit positions","done":true,"at":"2026-09-25T21:16:59.327Z"},{"text":"Every write journals an intent before transmission, fails closed, and maps a controller refusal to rejected and a transport failure to unknown with no retry path exposed","done":true,"at":"2026-09-25T21:16:59.553Z"},{"text":"A write-capable method that is not declared in WRITE_CAPABLE fails the gate","done":true,"at":"2026-09-25T21:16:59.780Z"},{"text":"Vendored files are -text so git never rewrites the bytes the manifest pins","done":true,"at":"2026-09-25T21:17:00.001Z"}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:17:00.019Z"
---

Done 2026-09-25, plan §4.2–§4.4. Commits `9855905` and `838c5f9`.

**Vendored** pycomm3 1.2.16 under `field/vendor/`, ADR-0024 discipline: `py3-none-any`, sha256-pinned, extracted not installed, licence from the hash-checked sdist because the wheel ships none. **Zero runtime dependencies** — checked on PyPI, not assumed; one would have meant vendoring its dependencies too and the policy would have quietly become a package manager.

**`dashboard/check_vendor.sh`** verifies it **offline**. The wheel hashes are provenance — they let anyone re-derive the files from PyPI — but the gate checks `MANIFEST.sha256`, because the whole point of vendoring is the boxes that cannot reach PyPI and a check needing PyPI would not run there. It also refuses compiled extensions, refuses committed bytecode, requires a licence, and proves the vendoring is not decorative by importing with `site-packages` stripped and requiring the module to come from `field/vendor`.

**`field/rockwell.py`** — the only module permitted to import pycomm3.

Read side closes exactly the gaps `logix.py` names in its own docstring: instance IDs from the controller (`:6-7`), template discovery and member layout decoding (`:10-11`), handle and element size read from the cached template rather than guessed (`:11-12`), revision read once on connect, backplane routing. `logix.py` stays as a second independent decoder — a verification oracle, since two decoders agreeing is stronger evidence than either alone.

Write side: `write_tag`, `write_member`, `write_struct`, each requiring `confirm=True` and a nonempty actor, each journalling an intent through `writejournal` before transmission and settling `success | rejected | unknown`. A controller error is `rejected` (nothing changed); an exception is `unknown` (we do not know) — recorded differently because they are acted on differently.

**The layers, stated honestly.** `AuditedLogixSession` never hands out the driver and defangs `write`/`generic_message` on the instance. **That is defence in depth, not a fence** — Python has no private and the module says so. It exists to catch our own future mistakes, which is the real threat model; nobody is attacking a loopback sidecar from inside itself. What stops an unaudited write from outside is that `field/app.py` exposes no route for one.

`check_field_writes.sh` watches both, because they are properties of what is **absent** and nothing visibly depends on them. It **parses** rather than greps — every file that matters mentions `generic_message` in prose, since explaining why the escape hatch is closed is what those docstrings are for.

**`test_rockwell.py`, 20 assertions**, against a recorded controller with no network. The whitelist test is written for whoever adds the next method: a new write-capable method fails it until somebody classifies it.

**A bug I introduced and then found.** The previous commit pinned `field/vendor/** text eol=lf`. pycomm3 ships `slc_driver.py` with CRLF and every other file with LF; the pin normalised that one file on commit, so the checked-out bytes stopped matching the wheel and the vendor gate failed on a tree where nothing was wrong. Now `-text`. The repo now has both forms and the distinction is written down: `text eol=lf` makes a file **parseable**, `-text` makes it **identical**, and vendored bytes need the second.

**Not done here:** the ticket mechanism and the write route (plan §4.4 layer 4). `field/app.py` still has no write route at all, which is the correct order — a write route that predates its ticket is a write route with no gate.