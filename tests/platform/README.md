# P01 environment inventory contract

Run the standalone synthetic suite on Windows, WSL, Linux or macOS:

```sh
python -m unittest discover -s tests/platform -p "test_*.py" -v
python tests/platform/inventory.py tests/platform/fixtures/wsl-inventory.json
```

This reusable validator reads a caller-selected JSON file and prints its result without modifying the input or machine. It starts no broker, terminal client, model or network connection. The fixture is explicitly synthetic: its commits, hashes, commands and versions are test values, not execution evidence. CI may run it with the commands above. It is separate from SDK wire-contract qualification.

Version 1 is a closed record format defined by `inventory.validate`. Required inventory fields describe the platform, runtime placement, observation time, full candidate commit, record kind, explicit limitations and clients. Each client records search scope, installation/configuration/authentication ownership, a stable target, its runtime launcher, copying/duplicate-install flags, interop limitations and probe observations. Each probe records the surface, command, exit code, version, installation identity and evidence SHA-256. Do not include credential values, private configuration, model reasoning or environment dumps.

Installation identity includes both `executableTarget` and `stableTarget`. For a direct executable they are the same. For an npm client, `executableTarget` is the stable Windows Node path and `stableTarget` is the package's stable script entry point. Both probes must bind both paths through `executable` and `installation`; equal Node paths alone cannot establish the same client. A direct probe command must start with the executable and, for a script client, that package entry point. A WSL probe command starts with the recorded launcher. These are recorded identities requiring evidence review, not an independent inspection of executable contents.

For WSL, the runtime stays Linux and each installed Windows client remains owned by Windows, including authentication and configuration. Both direct Windows and WSL probes must identify the same stable Windows installation; successful observed clients must report the same version. A Windows drive path is required for the installation and an absolute Linux path for its launcher. Explicit version directories are rejected. This syntactic check cannot prove that an arbitrary path or update alias is stable; actual host review remains necessary. Native Linux and macOS records retain native runtime and client ownership and require their own native probe.

A missing client is a valid inventory observation only when it records the search boundary and has no invented installation or probes. An unavailable client retains failed probe results, including a null version for a failed probe. Neither status means client support passed. The `linuxDuplicateInstalled` flag means a duplicate introduced for Windows forwarding, not the mere presence of an unrelated retained Linux installation. All claims and source evidence still require independent review; supplied hashes alone do not authenticate an observation.

Every record retains explicit unverified P06 limitations for authenticated workflows, hub callbacks, concurrent sessions and unchanged-launcher Windows updates. `p06Accepted` must remain false. This P01 format intentionally cannot certify P06; a later qualification format must retain the original observations rather than relabel them. The existing `delivery/evidence/P01/windows-clients` archive provides machine-specific observations, not a completed record in this format. Collect any missing direct-Windows/WSL identity evidence before calling a real inventory complete.

The tests reject mismatched ownership, installations or versions; invented missing-client success; Linux substitution; credential copying; duplicate-install claims; missing evidence or limits; and placement changes. They also verify native placements and a read-only failing CLI invocation. This is a plain validation boundary and data record, not a new product plugin or runtime design-pattern location.
