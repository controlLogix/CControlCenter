# Windows profile junction probe

The installed Windows Codex client saved a dummy API key and edited a harmless feature setting through a Windows directory junction. All 16 checks passed. The junction was created without elevation; no native file symlink was needed. Both alias files identify the same physical files as the synthetic Windows-owned targets. There is one physical synthetic auth file.

The fixture is retained. `probe.py` is the executed producer; `result.json` contains checked paths, command arguments, logs, file hashes and outcomes. The result SHA-256 is `e682fa9ea33153ebd67bf5ef3d5f8eaadf309f4d459680f6c890eb5157ec1846`.

Only disposable dummy auth/config files were used. The client commands were `login --with-api-key` and `features enable shell_snapshot`, both with `cli_auth_credentials_store="file"`. No inference, login status, credential refresh or service command was issued. Proxy variables pointed to port 9 on localhost. This was not a packet capture or a universal network-denial proof. The dummy login success means the command saved the supplied string; it does not prove a valid API key or authenticate a user.

The source hashes cover the Node executable, installed Codex JavaScript entry point and producer, and remained unchanged. They do not cover every loaded native dependency. No real profile or installed client was edited. No Linux client was installed and no credential was copied into WSL. Repository files remained unchanged.

A whole-profile junction shares the profile log and any future session files as well as auth/config. A codex-login.log was written under the synthetic canonical profile. This experiment therefore does not prove private per-agent session state, actual WSL launch, tool paths, shared credential refresh, concurrency, Windows-only update behavior or the four required real-provider orchestration scenarios. It is a working directory-junction prerequisite, not P06 acceptance.
