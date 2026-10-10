# P01: restore the missing orchestration plugin

Status: Codex approved bounded P01 preservation implementation on 2026-10-09. This decision does not recover the original source or accept P01. The bounded search is recorded in [recovery-evidence.json](recovery-evidence.json).

## Why this is a preservation repair

The repository has 16 hook/MCP checks and four installed-runtime checks that skip when the external `agentmux-orchestration` plugin is absent. Historical commit `bc81405c81faef89dcbe638415a5dba8974d1e7f` says those suites passed, but contains no plugin source. A replacement must be shipped, documented and maintained as actual product code. Creating a directory of test doubles would not restore the capability.

This bounded P01 proposal restores the existing local orchestration integration. It does not implement the P06 plugin framework, NATS transport migration, terminal-wide automation, new security authority or broader host qualification. Existing runtime policy remains authoritative. Delivery autonomy does not authorize skills to bypass product approval or permission rules. No release or merge is authorized.

## Source hierarchy and limits

1. Current runtime source defines executable behavior. This review used committed candidate `9647b4240a43c60c246512efa1553e8f4cb58530`; implementation must bind its evidence to the final candidate.
2. `docs/CONTRACTS_agents.md` sections C1–C8 and C10 explain the original definition, roster, posture and hiring contracts. Historical statements must be checked against current code. For example, current deletion always checks the stored checksum, and current definition writes use caller identity.
3. Commit `ef513e0606c49e7527ba0415fa830fed564c458b` names the first four skills; `bc81405c81faef89dcbe638415a5dba8974d1e7f` names the remaining five. Their names are known; their original SKILL.md files, descriptions, examples and complete packaging are not.
4. The unchanged external-plugin tests supply additional observable contracts, not a complete specification or proof of security.

The linked Claude architecture artifact in the old contract was not retrieved in this bounded search. No claim is made about its contents. The original marketplace version, license metadata and precise skill trigger text remain unknown. New authorship and provenance must be explicit; do not invent an upstream version or attribute replacement text to the original author.

## All nine workflows

| Skill | Intended workflow and required result | Authoritative sources and uncertainty |
| --- | --- | --- |
| `agent-new` | Inspect existing definitions and problems; create a complete definition in a writable scope using `coordination agentdef SCOPE NAME`. Explain posture, tool restrictions, role and worktree choices. Preserve collision and validation errors. No direct file writes to bypass the endpoint. | Name: ef513e0. Contract C1/C2/C4; `taskmgmt/agentdefs.py`; `dashboard/boardagents.py:agentdef`; `coordination.py:cmd_agentdef`. Exact original prompts unknown. |
| `agent-roster` | List definitions with `coordination agents`; fetch `agents NAME` for full persona/checksum. Distinguish definitions from live panes and a task's team roster; report discovery problems without hiding collisions. | Name: ef513e0. Contract C1/C2; `cmd_agents`; `/api/board/agents` versus `/api/agents`. Whether the original skill also exposed task rosters is unknown; the replacement must make that distinction explicit. |
| `agent-edit` | Read the full definition first, retain all intended fields, submit full replacement and fetched checksum through `agentdef`. Refuse stale writes and edits affecting live attached/detached workers; show server recovery hints. Claude-owned scope remains read-only. | Name: ef513e0. C4; `cmd_agentdef`; `boardagents._check_checksum`, `_target`, `agentdef`; original hook tests. No partial-update invention. |
| `agent-remove` | Inspect the target and effects, then use `coordination agentdrop SCOPE NAME --checksum VALUE`. Respect actual task authorization, caller identity and live-worker guards. Preserve failures rather than unlinking files directly. | Name: ef513e0. Current `cmd_agentdrop` fetches checksum if omitted; `boardagents.agentdrop` always verifies it. Historical C4's optional-checksum wording is not permission for unchecked deletion. Original interaction wording unknown. |
| `team-compose` | Read task needs and definitions; `recruit KEY` proposes the deterministic roster, `roster KEY` exposes members/gaps, `approve KEY --member NAME` records authorized approval. Report unsupported requirements and capacity limits. Do not manufacture approvals or change policy to get work through. | Name: bc81405. C3/C4/C7/C10; `agentdefs.choose_roster`; `boardteams.recruit`, `approve`; `cmd_team`. Current `teamRequireApproval=false` can approve during recruitment; preserve that explicit runtime policy rather than requiring a redundant approval. |
| `team-dispatch` | Inspect readiness and roster; use the existing `dispatch dispatch KEY --dry-run` before authorized execution where applicable. Use `coordination hire KEY --name NAME` for an approved additional member. Report actual refusal and progress; no retries that disable gates. | Name: bc81405. ef513e0 explains narrow hire surface. `dispatch_one`, CLI parser; `boardteams.hire`; C8. Never add cli/cwd/model/argv/actor overrides to hire. Dispatch's existing `--cli` is a separate interface, not a hire escape. |
| `team-merge` | Inspect task/roster state and evidence; invoke the existing `dispatch collect KEY` reconciliation when authorized. It integrates completed member work into the lead's integration tree, preserves conflicts, and leaves the card for review. Explain working/idle/parked/unresolved outcomes honestly. | Name: bc81405; ef08abc describes integration. Current `dispatch.py:collect_one`, `integrate_members`, `teardown_member`. There is no `merge` CLI subcommand: do not invent one. Collection can reap panes/release claims and is not a read-only status operation. Repository delivery no-merge rules still prohibit transferring this rearchitecture branch to main. |
| `agent-config` | Read settings first with `coordination config`; make only authorized typed changes through that command. Explain dispatch/approval/posture consequences. Use the installed `setup-auth` command for explicit provider setup or verification; do not extract or echo credentials. | Name: bc81405. `cmd_config`; `taskmgmt/setup_auth.py:main`; C10; launcher tests explicitly name setup-auth. The original skill's complete configuration/authentication scope is unknown; this is a proposed supported workflow using existing commands. |
| `agent-doctor` | Run `coordination doctor --strict`, inspect definition problems and dispatch status, explain failed prerequisites and bounded remedies. Report missing runtime, dashboard, client, enforcement or plugin capabilities rather than declaring readiness. | Name: bc81405. `cmd_doctor`, `dispatch status`, definition API. Exact original diagnostic sequence unknown; no new automatic repair or credential access is implied. |

All nine skills need explicit trigger and near-miss descriptions, required inputs, commands, expected outcomes, refusal handling, side effects and evidence examples. Skill prose is reconstructed guidance, not recovered text. The existing `coordination` CLI performs identity and policy checks; skills must not open the board database or reimplement its state transitions.

## Proposed smallest maintained layout

Use `plugins/agentmux-orchestration/` inside this repository:

```text
.claude-plugin/plugin.json
.mcp.json
hooks/hooks.json
hooks/agentmux-hook.sh
bin/agentmux-plugin
skills/<each-of-the-nine-names>/SKILL.md
skills/agent-config/scripts/runtime.py
README.md
PROVENANCE.md
```

Additional implementation modules are allowed only when they simplify review; do not duplicate runtime business logic. `PROVENANCE.md` must identify new authorship, the missing-original limitation, historical commits and source contracts. Package license metadata must follow the actual repository license review. No marketplace publication or personal host installation is part of this proposal. Tests can use the existing explicit `AGENTMUX_PLUGIN_ROOT` override to exercise a relocated real package.

The package must find its own files relative to its installed location or `${CLAUDE_PLUGIN_ROOT}`, never the author's checkout. Runtime selection is an explicit absolute `AGENTMUX_REPO` binding. The launcher permits exactly `coordination`, `dispatch`, `setup-auth`, maps them to the three installed taskmgmt scripts, checks their existence, forwards argv without a shell and preserves stdout, stderr and exit code. Missing/relative bindings and unknown selectors fail clearly. The selected checkout is a trusted installation; this launcher is not a sandbox for arbitrary code.

## Hook and MCP contract

- Register PreToolUse shell and edit tools under both tested host naming conventions. An irrelevant shell command exits successfully with no output or external process; the original test also fixes the early exit's location at shim line 3. Preserve that compatibility while reviewing the entire filter for bypasses.
- Relevant malformed input, unsupported ambiguous shell syntax and failed required lookups must refuse. A hired name must be unique, literal and currently approved for the specified task. Reject dynamic task identifiers, multiple hires, duplicate name flags and direct HTTP hire/definition mutations. Do not execute or evaluate command text while parsing it.
- Protect matching `.agentmux/agents` and `.claude/agents` definitions from CLI writes, edit tools, patch destinations and shell deletion when an attached or detached worker uses that definition. Preserve allowed unrelated edits and stale-worker behavior. Query failures cannot permit a protected mutation.
- These hooks are defense in depth, not authenticated authorization or complete shell containment. The legacy dashboard is locally accessible; absent host hooks cannot be advertised as enforcement. A check before a later mutation also has a race: authoritative runtime checks remain necessary. Record unsupported host behavior explicitly.
- Roster MCP exposes exactly `agent_roster` and `team_roster` from the original tests. Discovery and initialize work without runtime binding or a live dashboard. Reads use `/api/board/agents` (optional encoded name) and `/api/board/roster?id=...`; they do not mutate state or enumerate secrets.
- Handle newline JSON-RPC initialization, notifications, tools/list, tools/call and ping. Preserve tool-level service errors, JSON-RPC invalid-parameter/unknown-method errors and continued service after a bad request. Keep protocol stdout clean; diagnostics go to stderr. Add bounded frame, response size and timeout handling as reviewed implementation details.

## Windows and WSL boundary

P01's intended operational environment is the existing WSL runtime with Windows-owned AI clients reached through the established forwarders. The shell hook and Python scripts execute where their paths and interpreter actually exist. A Linux absolute binding and `/bin/sh` hook must not be advertised as directly executable by a native Windows host.

Qualify relocation in WSL, spaces in package/runtime paths, explicit environment forwarding and the actual host's plugin loading/validation separately. If a Windows-owned client launches native Windows hook commands, provide an explicit reviewed WSL launch configuration or declare that path unsupported; do not silently use a native Linux AI client or assume automatic path conversion. Keep private CODEX_HOME/CLAUDE_CONFIG_DIR isolation; do not read default credentials or perform inference for packaging checks. The prior Windows UNC SQLite limitation remains separate and unresolved by a plugin package.

No cross-platform or all-terminal claim follows from Claude/Codex tool matcher names. Full P06 framework and supported-host qualification remain later work.

## Compatibility gate before accepting the replacement

1. Record Codex's scope decision and provenance review; map all nine workflows and original 20 checks to the real package. Preserve the missing-source history permanently.
2. Run all unchanged 16 hook/MCP and four launcher tests with `AGENTMUX_PLUGIN_ROOT` pointing to the package; require zero skips. Do not alter assertions to make a replacement pass.
3. Run the existing real disposable dashboard/CLI suites for definitions, teams, dispatch, collection and authentication/configuration. Verify that skills use actual supported command syntax and preserve current identity, checksum and policy requirements. No paid providers are needed for these checks.
4. Exercise create/read/edit/delete, proposed/approved/rejected roster behavior and allowed/refused hire requests against an isolated dashboard. Use synthetic workers or the existing bounded process fixtures for side effects, clearly separating them from real-provider qualification. Test stale checksums, wrong scope, name collision, unavailable dashboard and disabled hiring without policy mutation.
5. Verify collection with disposable Git repositories: wrong integration branch, dirty member/lead trees, unmanaged/missing branches, conflicts, absent evidence, live members and repeat collection. Preserve work on every refusal; no main-branch merge is involved.
6. Add hook negatives for command substitution, quoting, compound commands, duplicate options, malformed JSON, oversized inputs, path traversal/normalization, patch move destinations and lookup timeout. Show irrelevant commands still avoid spawning Python. Do not treat lexical tests as proof of universal shell containment.
7. Add MCP malformed-frame, notification, unknown-tool, invalid-argument, HTTP failure/timeout, query encoding and continued-session tests. Confirm discovery never reads credentials and protocol stdout is valid JSON only.
8. Validate package metadata using the installed host's real validator where available, capture version/result, and inspect registered hooks/MCP/skills from a private relocated installation. Check all nine names and trigger near misses. A validator pass is packaging evidence, not live execution or cross-host qualification.
9. Repeat focused failures before the full affected dashboard gate on a frozen candidate. Record source/package hashes, actual test counts, skips, host limits and cleanup. Retain all earlier failed and skipped runs. No P01 acceptance until remaining independent phase criteria also pass.

## Review decisions still needed

Codex must choose the explicit WSL host launch configuration, confirm package licensing/metadata, and approve any parser refusal beyond the legacy observable contract. The nine names and core runtime workflows are supported by source; original prose, hooks' full parser coverage and upstream package metadata are not. These unknowns must remain visible in the replacement's provenance rather than being filled with claims of historical equivalence.


## Codex scope decision

Codex approves the maintained replacement described above as a P01 preservation repair of the existing nine workflows. The unchanged20checks and the additional compatibility gate are mandatory. New code must use current runtime contracts, retain unknown-original limitations and pass independent review. This approval does not assert historical source equality or pull the P06 framework into P01.

Ship the package in this branch; do not publish it or install it into personal client configuration. The initial supported hook execution context is a Linux/macOS process or an explicitly selected WSL process. Native Windows hook launch remains declared unqualified until its actual-host P06 integration. Windows-installed AI clients still remain Windows-owned. Relocated installation and metadata validation are tested separately from inference.

No repository license file was found. Omit an upstream license claim and fabricated upstream version/author metadata; describe this as a newly maintained local package with explicit provenance. Any release licensing decision remains outside this local repair and no release is authorized. Unsupported ambiguous mutation syntax may fail closed with a clear refusal; preserve unrelated command bypass and current server-authorized work.
