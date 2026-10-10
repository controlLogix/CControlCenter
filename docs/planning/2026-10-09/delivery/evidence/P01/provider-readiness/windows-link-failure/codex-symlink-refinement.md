# Windows Codex file-link candidate

Read-only proposal; no links, configuration, login, refresh, or model calls were created or run.

The candidate can keep session files private while referencing canonical Windows authentication and configuration. Use a unique Windows NTFS CODEX_HOME containing only Windows-created file symlinks for auth.json and config.toml. Other directories remain real private directories. Do not link the whole profile or use Linux-created NTFS links. This is shared read/write ownership of the two targets, not read-only access.

Version-pinned upstream source for installed 0.162.1 shows two distinct behaviors:

- File authentication saves open auth.json with truncate/write/create, then flush. A normal valid Windows file symlink should remain while writes reach its target. This is an inference from source and OS semantics, not an executed Windows refresh proof. Refresh can change the canonical authentication file, and concurrent writers can race. Do not simulate a real refresh against the account just to test links.
- Configuration edits follow a valid symlink chain and atomically replace the resolved target. The profile link remains, but canonical config can change. Error/cycle fallback uses the original path and can replace the link, so validate a single absolute non-cyclic target before and after a probe. This also means startup prompts or model-choice persistence cannot be assumed harmless to shared settings.
- Auto/keyring auth selection uses CODEX_HOME to derive its key. A private home is not necessarily the same keyring identity. A process-only cli_auth_credentials_store="file" override is needed if this proof is specifically about the auth.json link. It must not be represented as qualification of auto/keyring refresh behavior.

Proposed proof before real inference:

1. With approval to create fixture state, first use Windows-native file symlinks pointing only to disposable synthetic files. Use the installed CLI's file-auth save path with a plainly dummy API key and its config edit path with a harmless feature setting. Capture only equality, link targets/type, and before/after synthetic values. Prove the link remains and only the disposable target changes. This tests installed persistence behavior without touching real credentials or calling a model. Do not call it authentication success.
2. Only after that passes, create a second private NTFS home with absolute links to the existing Windows files. Snapshot link metadata and privately compare canonical bytes before/after; emit equality booleans only. Never archive config or credentials. Check private directory ACLs. Use a process-local environment and explicit file store; do not change registry/user environment or the live forwarding wrapper.
3. A bounded `codex -c cli_auth_credentials_store="file" login status` can test reading through the link without a model prompt. The inspected login-status path loads auth and prints the mode; it does not explicitly call refresh for ordinary stored ChatGPT mode. Workload-identity and other inherited provider paths must be ruled out first. Capture output privately and report only exit/status mode, since API-key mode prints a partial key. Config loading can still perform ancillary work; verify target equality afterward rather than claiming it is inherently write-free.
4. Full interactive startup without a prompt is a separate probe, with a short timeout and exact child-process cleanup. It may contact services, refresh auth, run configured hooks/MCP, or persist notices/config. It therefore cannot be called a guaranteed no-mutation probe merely because no prompt is sent. Before doing it, inspect the active configuration categories safely and decide which process-only controls preserve the original workflow. A byte difference is a finding to report, not something to overwrite from a stale backup: restoring a rotated token could invalidate the live login.
5. After startup is reviewed, verify all new sessions, SQLite state and logs remain under the private home, both links still reference canonical files, callbacks reach the private WSL hub with the correct per-agent identity, and canonical changes (if any) are explicitly accounted for. Only then run bounded original calib.

No proof above establishes future token refresh correctness without an actual refresh. It does establish the installed file-write behavior and link-read readiness while preserving that limitation. No profile link should be removed by recursive cleanup that follows targets; remove only the fixture link entries and verified fixture directory.

Sources retained beside this report:

- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/login/src/auth/storage.rs (file store save, auto store, key derivation)
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/core/src/config/edit.rs (apply_blocking_to_resolved_file)
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/utils/path-utils/src/lib.rs (resolve_symlink_write_paths, write_atomically)
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/cli/src/login.rs (run_login_status)
- Installed Windows Codex 0.162.1 login and app-server help. The public source tag is version-matched evidence; Windows link persistence still needs the proposed installed-binary probe.
