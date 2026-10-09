# Portable enterprise gate

The baseline is uniform. Repositories cannot disable rules or supply waivers. Adoption permits owned, dated remediation only for unchanged legacy source. CI enforces the deterministic gate; Claude SessionStart initializes project governance, and Claude pre-commit-command, Stop, and SubagentStop hooks run the same installed gate.

## Files

- `.bytedesk/design-patterns/project.json`: baselineVersion `1.1.0`, owner, surfaces (`web`, `desktop`, `backend`, `codesys`, `library`), languages, `frontendRoots[]` for web/desktop source roots, architecture `{decision,rationale,alternatives[],constraints[]}`, toolchains `[{name,version}]`, verification `{build:[],test:[]}`, decisionEvidence `[repo-relative files]`, adoptionCommit (full Git SHA, or null for greenfield).
- `.bytedesk/design-patterns/catalog.json` and `.bytedesk/design-patterns/agent-rules.md`: pinned pattern identities/sources and shared Claude/Codex behavior rules.
- `.context/design-patterns.md` and `.context/design-patterns-diagrams.md`: lifecycle registry plus abstract/concrete Mermaid and PlantUML views.
- `.claude/rules/design-patterns.md`, `CLAUDE.md`, and `AGENTS.md`: Claude project rules and Codex project guidance pointing at the governed context.
- `.bytedesk/design-patterns/frontend-rules.md` and `.claude/rules/frontend-components.md`: shared atomic component policy and path-scoped Claude enforcement for web/desktop code.
- `.bytedesk/design-patterns/review.json`: reviewer, sourceDigest, rules and current confirmed findings. Each applicable rule DP001–DP010 has `{status:"pass"|"findings",rationale,evidence:[files]}`. Status is `findings` iff that rule has active findings. DP009/DP010 may be `not-applicable` with a reason only when project surfaces exclude web/desktop or CODESYS respectively. All other rules remain applicable.
- A finding is `{id,rule,path,symbol,summary}`. Include more context in the linked assessment. Paths must be existing repository-relative files; symlinks and paths outside the repository are rejected.
- `.bytedesk/design-patterns/remediation.json`: array of `{id,status:"open",owner,issue,due:"YYYY-MM-DD",sourceHash}`. `sourceHash` is SHA-256 of the finding's file at adoptionCommit. The current file must still match. Resolved entries retain id/owner/issue, use `status:"resolved"` and `resolutionEvidence:[files]`.
- `.bytedesk/design-patterns/check.mjs`: pinned, standalone Node gate copied from the plugin. Review changes to this file as policy changes. Consuming repositories need Node 20+ and Git, not a plugin cache or sibling repository.

Toolchain versions are exact numeric versions such as `24.19.0`, `10.0.401` or `3.5.22.30`, optionally with a prerelease/build suffix. Store descriptive profile names in the decision evidence; ranges and channels are rejected.

Hashes cover actual working-tree bytes. Keep reviewed text line endings consistent across development and CI (for example, repository `.gitattributes` with `* text=auto eol=lf` after reviewing existing binary/text attributes). Otherwise a CRLF/LF conversion correctly appears as a different snapshot and requires a fresh review. Do not disable freshness checks to hide checkout differences.

Run `node .bytedesk/design-patterns/check.mjs digest --root .` after finishing source and project metadata changes. Inspect the resulting code, then write its sourceDigest into the review. Do not automatically bless changed code. Review/remediation JSON are excluded from the digest to avoid self-reference; they are validated separately. Tracked and unignored files are included, so ignore build products before generating evidence. A submodule/symlink requires a separate review strategy; this initial gate refuses to traverse it.

To calculate a legacy file fingerprint, hash the **raw bytes** returned by `git show <adoptionCommit>:<path>` with SHA-256. Do not pipe binary output through PowerShell text conversion. The checker recomputes it itself and compares the current file.

## CI

Add to the repository's existing pipeline alongside its real builds/tests. Example for GitHub Actions (merge commits or branch heads):

```yaml
name: Enterprise architecture records
on: [push, pull_request]
permissions:
  contents: read
jobs:
  enterprise-records:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v5
        with:
          node-version: '22'
      - name: Check records and legacy adoption
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
        shell: bash
        run: |
          if [ -n "$BASE_SHA" ]; then
            node .bytedesk/design-patterns/check.mjs check --root . --base "$BASE_SHA"
          else
            node .bytedesk/design-patterns/check.mjs check --root .
          fi
```

Use a trusted base from CI metadata, never PR-supplied shell text. For another CI provider use its merge-base commit and the same command. Fetch sufficient history; missing bases fail rather than silently skipping changed-file checks. Configure the CI job as a required branch check through normal repository administration; creating this YAML alone does not change server-side branch protection.

Local command: `node .bytedesk/design-patterns/check.mjs check --root .`. The gate rejects stale reviews, invalid applicability, missing evidence, expired/unowned/untracked debt and legacy files changed since adoption. PR mode additionally prevents changing adoptionCommit and rejects a changed file carrying a confirmed finding.

Passing means review **records** and remediation passed deterministic checks. Architectural conclusions are review attestations; build/test commands are documented, not executed by this gate. Required build/test/security/platform jobs remain separate. Reviewers must verify the underlying claims. No arbitrary compliance score or certification is produced.

## Policy upgrades

Baseline and checker updates are reviewed enterprise releases. Adopt a new version through a deliberate PR across consumers, retain adoptionCommit and remediation history, rerun affected assessments and tests. Do not solve failures by pinning a weaker local policy. This plugin does not silently auto-update consumer repositories or claim to centrally administer branch protection.
