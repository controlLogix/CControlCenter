# Dispatch sandbox policy (TM-068)

Dispatch currently requires `unrestricted` posture. Sandboxed `workspace-write`
and `read-only` workers cannot reliably reach the tmux socket or the claim and
journal files outside their workspace. Dispatch refuses these postures before
spawning, claiming files, or starting the card, including during `--dry-run`.
`AGENTMUX_NO_BYPASS=1` also refuses dispatch; it is never silently overridden.
Team spawns (`spawn --team`) enforce the same rule after the environment clamp.
Standalone sandboxed panes remain available for work that does not require dispatch
coordination. This is an explicit limitation, not an automatic permission upgrade.

Lead selection is global: `choose_roster` sorts all loaded definitions with
`role: lead` by name and chooses the first. It does not match a lead to card labels.
Adding an alphabetically earlier lead can therefore change every subsequent card's
CLI, model, auth and posture. With no lead definitions, the built-in fallback is
unrestricted. Use `role: worker` for unrelated specialist definitions; treat adding
or renaming a lead as a dispatch policy change. A CLI override preserves posture.
Dispatch now prints the selected lead, its source path (or built-in fallback), CLI
and posture, so the choice is visible on both real and dry runs.

Liveness failures raise `TmuxUnavailable` with the socket, original diagnostic,
and a sandbox/availability hint. Permission denial, timeouts and missing binaries
are unknown liveness, never evidence that a worker died. Successful empty listings
and tmux's missing-socket ENOENT (“No such file or directory”), “no server running”
or “no sessions” answers mean no live agents. A missing tmux binary still raises.
Collectors abort on unknown liveness rather than releasing claims or parking cards.
Best-effort notifications report the error without invalidating a completed claim.

Regression suite: `python3 dashboard/test_sandbox_coordination.py`. It uses mocks
and private temporary roots, never the shared server or live tmux socket.
