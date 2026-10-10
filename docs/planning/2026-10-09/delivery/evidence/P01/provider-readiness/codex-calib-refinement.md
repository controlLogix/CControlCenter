# Codex calibration readiness refinement

No inference, configuration changes, authentication operations, or credential reads were performed. Only installed CLI help, repository source, and public version-pinned source were inspected. The Windows installation is Codex 0.162.1. Its npm package contains no configuration schema; a copy of the official rust-v0.162.1 schema is retained beside this report.

The proposed per-process sqlite_home override is useful but does not provide complete isolation. The version-pinned schema supports sqlite_home, log_dir and history.persistence. These can place the database and logs in a private NTFS directory and disable history.jsonl. The same release's rollout recorder independently constructs session paths from CODEX_HOME/sessions/year/month/day. No independent session-directory setting appears among the schema's top-level properties. Therefore leaving the existing Windows CODEX_HOME in place preserves authentication lookup but can still add session files to personal state. Authentication refresh writes also remain possible. This is a supported partial separation, not proof of a zero-write personal profile.

Installed `codex exec --help` exposes --ephemeral and --ignore-user-config. The interactive top-level help does not expose those flags. The original agentmux launcher runs the interactive client with --no-daemon, then receives hub doorbells in tmux. Replacing that with exec would change the original workflow. Do not treat it as qualification of the unchanged calibration scenario.

Launch-only proposal, not executed: a fixture-private codex wrapper could forward original arguments to the existing Windows-owned executable and append `-c sqlite_home="C:/Users/RyanHelms/AppData/Local/Temp/agentmux-calib-UNIQUE/sqlite"`, `-c log_dir="C:/Users/RyanHelms/AppData/Local/Temp/agentmux-calib-UNIQUE/log"`, and `-c history.persistence="none"`. Use an argv list and TOML quoting, preserve --no-daemon, and leave the default Windows authentication location alone. Current generic forwarding does not interpret TOML path values, so supply Windows paths explicitly. Help parsing alone cannot prove that startup honors these values or avoids all other profile writes. A no-personal-state-write prerequisite remains unresolved.

The original calibration task itself is compatible in principle with an NTFS project: set HUBDEMO_BASE to a unique `/mnt/c/.../agentmux-calib-UNIQUE/hubdemo` path, register calc there, and let Windows access the same files through `C:/...`. Keep the hub database, private HOME, and tmux socket in native Linux storage. Original setup and verification use HUBDEMO_BASE, and the median prompt is relative to the repository. This avoids a Windows UNC project cwd without changing the requested function or assertions. It still requires an actual two-way file/cwd check, available Windows Python/Git commands, consistent git configuration, and the already-reviewed private callback launcher/environment reaching Windows tool subprocesses. The welcome message includes a Linux checkout path; do not assume the model will translate that path or choose the correct shell.

Crossrepo is a separate problem: its prompt and generated report code refer to ~/hubdemo/calc. A Windows home expands differently from private WSL HOME. Placing repositories on NTFS does not repair that semantic mismatch. Calibration success cannot qualify crossrepo, Claude, Grok, or native Windows plugin hooks.

Before a paid calibration run, resolve the accepted personal-state write boundary or prove a supported separate session/auth arrangement; test actual NTFS file/cwd equivalence and Windows tool availability; verify per-agent callback identity and environment with no model; and bind launch arguments, source hashes, timeout and child-process cleanup to the fixture. No credential copy, native Linux AI installation, profile rewrite, or new plugin framework is proposed.

Sources:

- https://developers.openai.com/codex/config-reference/
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/core/config.schema.json
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/rollout/src/recorder.rs (new_inner and precompute_new_rollout_path)
- https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/core/src/rollout.rs
- Installed Windows Codex top-level and exec help; repository agentmux.sh, hub/server.py, hub/demo/orchestrate.py and setup_repos.sh.
