# Bounded runtime comparison

P00 engineering evidence, October 9, 2026. These small clients are not a kernel implementation or complete SDK.

Three independently implemented clients (Go, Python and TypeScript) send the same JSON object through Core NATS to a Python service. The object includes context IDs, a version, Unicode, a boolean and a list. Each client checks the returned object. Each also must fail when no service subscribes. A temporary token-protected broker binds loopback only; the runner owns and stops its process and removes its disposable configuration. It never uses the user's hub, credentials, provider accounts or project data.

The runner also compiles the Go client for Linux and macOS on amd64 and arm64, with CGO disabled. Only Linux/amd64 executes here. Building a binary is not qualification on that platform. No throughput/latency, JetStream, reconnect, account-isolation, lifecycle, plugin-context or deployment claim follows from these tests.

## Recorded environment and result

- Ubuntu 26.04 on WSL2, x86_64; Python 3.14.4; Node 22.22.1.
- Go 1.27.2 from the official checksum-verified archive; [toolchain provenance](toolchain-source.json).
- NATS Server 2.15.0; Python packages from the repository's `hub/requirements.lock`.
- Go dependencies in `go.mod`/`go.sum`; TypeScript/Node dependencies in `package.json`/`package-lock.json`.
- [comparison-result.json](comparison-result.json) records source hashes, three successful clients, three absent-service failures, four build identities and the limits above.

## Repeat without changing the product installation

Use a separate working directory; do not put compiled binaries or node_modules in the repository. The current runner expects the prepared tools under `~/.cache/agentmux-governance`: `tools/nats-server`, `venv/bin/python` and `runtime-comparison/go/bin/go`. The Python environment must use the exact repository lock. Copy this directory's source and lock files into `~/.cache/agentmux-governance/runtime-comparison/work`.

From that disposable copy:

```sh
npm ci --ignore-scripts --no-audit --no-fund
GOTOOLCHAIN=local ../go/bin/go mod download
GOTOOLCHAIN=local ~/.cache/agentmux-governance/venv/bin/python compare.py
```

The runner runs `go build -trimpath` for four targets, strict TypeScript compilation and the six broker checks. A fresh result file is written only after all checks pass. Copy back only the reviewed result and any deliberately changed source/lock file; never copy temporary credentials or binaries. Verify every `sourceSha256` against the retained source before using a result.

The first setup used `npm install --ignore-scripts --no-audit --no-fund` and `go mod tidy` to produce the retained exact locks. Subsequent runs should use those locks. Official Go archive SHA-256 was checked before extraction into the user cache; no system-wide toolchain was replaced.
