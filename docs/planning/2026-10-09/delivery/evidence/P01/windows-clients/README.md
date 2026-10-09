# Windows-backed WSL AI clients

Installed for RyanHelms / Ubuntu-26.04 / Linux user ryan. Launchers: claude, codex, grok, kimi, goose, dsh, trueforge. Pi was not found in PATH or the examined Windows npm/bin locations.

Both ~/.local/bin and /usr/local/bin entries forward directly to Windows executables or Windows node.exe plus the installed Windows package entry point. The targets use stable Windows install paths, so Windows updates take effect in WSL. No versioned desktop Codex path is selected. Existing native Codex remains at /home/ryan/.codex/lib/node_modules/@openai/codex/bin/codex.js; only its former /usr/local/bin symlink was replaced and recorded.

Windows runtime metadata confirms USERPROFILE and home stay C:\Users\RyanHelms and Linux working directories arrive as WSL UNC paths. No credentials were copied, refreshed or linked. Defaults use the Windows profile. Explicit CODEX_HOME and CLAUDE_CONFIG_DIR overrides are transferred per invocation with WSLENV path conversion; other WSLENV entries remain intact. Automatic Grok/Kimi config overrides are not qualified. No model prompt was submitted. Existing provider configuration remains authoritative; a successful version/help probe does not prove authenticated inference.

26 help/version probes passed from Windows-mounted and Linux directories, followed by seven bare-name checks and Codex no-daemon verification. Windows npm Codex update was observed from 0.147.0 to 0.162.1 without installing a WSL package. Argument probes cover spaces, quoting, empty arguments, Unicode, newlines, shell characters, end-of-options, JSON values and explicit path conversion.

Restore from Windows PowerShell:

    wsl -d Ubuntu-26.04 --user root --exec python3 /home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119/restore.py

The restore script validates every entry before changing any, restores saved files/symlinks and their ownership, and refuses to overwrite later edits. It leaves Windows installs and the native Codex package untouched. The restore manifest contains every previous entry and backup hash. Restore has been validated but not executed.

Remaining orchestration boundary: repository agentmux.cmd hard-codes Ubuntu and /home/nick/.local/bin/agentmux. Windows provider tool calls need a scoped callback to the correct Ubuntu-26.04 harness, with preserved agent identity and private hub environment. That callback has not been changed here. cmd.exe cannot retain a Linux UNC working directory; these forwarders avoid it. No claim is made that model-issued tools already run in WSL.

Artifacts: clients.json, forward.py, restore-manifest.json, restore.py, setup.py (initial installation), system-links.py (bare-exec follow-up), verify.py, results.json, forwarding-verification.json, codex-update-propagation.json and bare-exec-verification.json.

Explicit override verification uses harmless Windows Node metadata, including Linux UNC paths and existing Windows paths. It does not establish authenticated inference. Basis: https://learn.microsoft.com/en-us/windows/wsl/filesystems#wslenv-flags.

Live launcher and client map are stored durably at /home/ryan/.local/share/agentmux/windows-clients, not in the evidence cache. All fourteen symlinks target its forward.py. Backups and historical setup evidence remain in the cache. Variadic Claude path options and Codex comma-separated/variadic image arguments have focused checks. Restore verifies both installed entries and original backup hashes before changing anything.

Independent review: the update report records `wrapperUnchanged: false`. The stable alias and Windows target stayed the same, but argument hardening happened during the update check. This shows the updated Windows version reached WSL; it does not prove a Windows-only update with the final wrapper unchanged. Concurrent tmux sessions, host isolation, authenticated model calls and working hub callbacks remain unverified here. This is P01 environment evidence and does not accept P06 or any phase.

Archive note: `archive.json` preserves the original external file snapshot. This README was later edited for independent review; its original and reviewed hashes are recorded in `review.json`. Other archived evidence was not changed by this review.
