# Two-language contract conformance

This suite sends the same wire requests to the independent Python and TypeScript CLIs. It checks canonical bytes against literal expected vectors, strict JSON admission, every public schema example and required field, cross-language Ed25519 verification, admission constraints, and binding between signed claims and the outer envelope. Registered payload tests cover all ten core IDs and semantic tests retain the 21 P00 rejection vectors plus identity-uniqueness cases.

Install the pinned dependencies and build the TypeScript client using each SDK's setup instructions. Run from the repository root. Missing dependencies, absent executables, timeouts, empty selections and skipped tests fail the run; they never count as qualification.

```bash
export AGENTMUX_CONTRACT_PYTHON=/path/to/prepared/python
export AGENTMUX_CONTRACT_TS_CLI=/path/to/built/cli.js
# Optional; defaults to node on PATH.
export AGENTMUX_CONTRACT_NODE=node
python tests/contracts/run.py --evidence /path/to/results.json
```

The default Python client is the harness interpreter with `sdk/python` on its import path. The default TypeScript entry is `sdk/typescript/dist/cli.js`. Both run with the repository root as their working directory. The current prepared WSL installations can be selected without installing dependencies again:

```bash
export AGENTMUX_CONTRACT_PYTHON=/home/ryan/.cache/agentmux-governance/p01-contracts-python/bin/python
export AGENTMUX_CONTRACT_TS_CLI=/home/ryan/.cache/agentmux-governance/typescript-sdk/dist/cli.js
python3 tests/contracts/run.py --evidence $HOME/.cache/agentmux-contract-evidence/conformance.json
```

For focused iteration, use ordinary unittest selection:

```bash
python3 tests/contracts/run.py --match depth_boundary --evidence $HOME/.cache/agentmux-contract-evidence/depth.json
```

The harness uses only Python's standard library. Node's built-in crypto derives the public key from a fresh ephemeral seed; signing and verification are performed by the two SDKs in both directions. The evidence file records source hashes, all compiled JavaScript hashes, runtime versions and test outcomes, never the seed or request bodies. The build directory must retain src/*.ts, package.json, package-lock.json and tsconfig.json matching the repository; the evidence records each comparison. An evidence run fails if its source or compiled files change while testing, or if build sources differ. Keep evidence output outside the source directories that the harness hashes. Use the persistent Linux home cache or the repository evidence directory for retained reports; WSL temporary files can disappear between invocations.

The valid examples are schema fixtures, not real authority records. The harness replaces their placeholder digest/signature when testing authenticated admission. A nonempty error code is required on rejection; language-specific error names need not match.

Strict invalid UTF-8 is sent as actual malformed bytes to the outer CLI stream. Escaped duplicate keys and lone surrogates are also tested inside a raw JSON string passed to `parse`. JSON has no standard nonfinite number syntax, so all nonfinite cases must be refused. Depth tests count the root container as depth one. Canonical vectors cover UTF-16 key ordering, escapes, negative zero, small exponential notation and safe integer limits. The 1 MiB outer framing limit excludes its newline delimiter. Both exact-limit acceptance and oversized-frame recovery of the following request are tested. Focused evidence records its match and fullSuite=false; it never substitutes for the complete conformance run. Each SDK's unit suite must separately verify payload/canonical size limits because nested CLI string escaping changes the frame's byte size.

This suite does not prove live NATS delivery, enrollment, key rotation, current-grant authorization, revocation, remote-host isolation or production storage recovery. P01's real-broker and persistence fixtures remain separate. Local success does not qualify an unexecuted platform or terminal host.

`test_payloads.py` separates valid signed-message structure from registry rejection: kind, target and identity mutations keep inner/outer claim bindings consistent. Correctly signed unknown contracts and confused delivery receipts are also refused. Payload shape acceptance does not prove a legal state transition or grant authority; the five state models and real-broker recovery remain separate fixtures.

## Native test input mirror

`run.py` copies only `contracts/v1` and `sdk/python` into an owned temporary directory on the test host. It checks every copied input against repository bytes before and after the run, records those hashes, and removes the copy in a finally-protected lifetime. Python imports that exact copy; TypeScript uses its schema directory. This avoids repeated cross-filesystem schema scans on WSL while retaining content-change detection and the same 60-second subprocess bound. Reports remain in the requested persistent evidence directory. A changed or mismatched copy fails the run. The TypeScript compiled build and cache-source comparison remain separate checks.
