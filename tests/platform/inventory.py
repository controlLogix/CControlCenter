"""Validate P01 environment observations; never grant P06 client support."""
import argparse
import datetime
import json
from pathlib import Path
import re

LIMITS = {
    "authenticated_workflows_unverified",
    "hub_callbacks_unverified",
    "concurrent_sessions_unverified",
    "unchanged_launcher_update_unverified",
}


def validate(record):
    """Return all detected errors in this closed, versioned evidence format.

    Assertions describe recorded observations, not authenticated execution.
    No client, shell, configuration file or network service is accessed.
    """
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    def shape(value, keys, label):
        if not isinstance(value, dict) or set(value) != set(keys):
            errors.append(label + ": exact fields required")
            return False
        return True

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    if not shape(record, ("schemaVersion", "kind", "platform", "runtime", "observedAt",
                          "candidateCommit", "p06Accepted", "limits", "clients"), "inventory"):
        return errors
    require(record["schemaVersion"] == 1 and type(record["schemaVersion"]) is int, "schemaVersion must be 1")
    require(record["kind"] in ("synthetic", "observation"), "kind must distinguish synthetic from observation")
    platform = record["platform"]
    if platform not in ("wsl", "linux", "macos"):
        return errors + ["unsupported platform"]
    runtime = "linux" if platform == "wsl" else platform
    require(record["runtime"] == runtime, "runtime placement differs from platform contract")
    require(record["p06Accepted"] is False, "P01 inventory cannot accept P06")
    require(isinstance(record["candidateCommit"], str) and bool(re.fullmatch(r"[0-9a-f]{40}", record["candidateCommit"])),
            "candidateCommit must be a full Git commit")
    try:
        stamp = datetime.datetime.fromisoformat(record["observedAt"].replace("Z", "+00:00"))
        require(stamp.utcoffset() is not None, "observedAt requires a timezone")
    except (ValueError, TypeError, AttributeError):
        errors.append("observedAt must be an ISO timestamp")
    limits = record["limits"]
    require(isinstance(limits, list) and all(isinstance(x, str) for x in limits)
            and len(limits) == len(set(x for x in limits if isinstance(x, str)))
            and LIMITS.issubset(x for x in limits if isinstance(x, str)), "explicit P06 limitations required")
    clients = record["clients"]
    if not isinstance(clients, list) or not clients:
        return errors + ["clients must be a nonempty inventory"]
    ids = set()
    for client in clients:
        if not shape(client, ("id", "status", "searchScope", "installationOwner", "configOwner", "authOwner",
                              "credentialsCopied", "linuxDuplicateInstalled", "stableTarget", "executableTarget", "launcher",
                              "probes", "interopLimits"), "client"):
            continue
        name = client["id"]
        if not text(name):
            errors.append("client id required")
        elif name in ids:
            errors.append("duplicate client id: " + name)
        else:
            ids.add(name)
        require(text(client["searchScope"]), "client search scope required")
        require(client["status"] in ("observed", "missing", "unavailable"), "invalid client status")
        require(client["credentialsCopied"] is False, "credential copying forbidden")
        require(client["linuxDuplicateInstalled"] is False, "duplicate Linux client installation forbidden")
        require(isinstance(client["interopLimits"], list) and bool(client["interopLimits"])
                and all(text(x) for x in client["interopLimits"]), "client interop limitations required")
        probes = client["probes"]
        if client["status"] == "missing":
            require(probes == [], "missing client must not claim executed probes")
            require(all(client[k] is None for k in ("installationOwner", "configOwner", "authOwner", "stableTarget", "executableTarget", "launcher")),
                    "missing client must not claim installation or ownership")
            continue
        owner = "windows" if platform == "wsl" else platform
        require(all(client[k] == owner for k in ("installationOwner", "configOwner", "authOwner")),
                "installation/config/auth ownership mismatch")
        target, executable = client["stableTarget"], client["executableTarget"]
        for location in (target, executable):
            require(text(location), "stable target required")
            if text(location):
                require(not re.search(r"(?i)(?:^|[/\\])v?\d+\.\d+(?:\.\d+)?(?:[/\\]|$)", location),
                        "version-specific target forbidden")
                if platform == "wsl":
                    require(bool(re.match(r"^[A-Za-z]:[/\\]", location)), "WSL client target must be a Windows installation")
                else:
                    require(location.startswith("/"), "native target must be absolute")
        require(text(client["launcher"]) and client["launcher"].startswith("/"), "absolute runtime launcher required")
        expected = {"windows", "wsl"} if platform == "wsl" else {platform}
        if not isinstance(probes, list):
            errors.append("probes must be a list")
            continue
        surfaces, versions, outcomes = [], [], []
        for probe in probes:
            if not shape(probe, ("surface", "command", "exitCode", "version", "installation", "executable", "evidenceSha256"), "probe"):
                continue
            surfaces.append(probe["surface"])
            require(isinstance(probe["surface"], str), "probe surface must be a string")
            command = probe["command"]
            require(isinstance(command, list) and bool(command) and all(text(x) for x in command), "probe command required")
            if isinstance(command, list) and command:
                if probe["surface"] == "wsl":
                    require(command[0] == client["launcher"], "WSL probe command must use recorded launcher")
                else:
                    require(command[0] == executable, "direct probe must use recorded executable")
                    if target != executable:
                        require(len(command) > 1 and command[1] == target, "direct probe must bind package entry point")
            require(type(probe["exitCode"]) is int, "probe exitCode must be an integer")
            require(probe["installation"] == target, "probe installation differs from stable target")
            require(probe["executable"] == executable, "probe executable differs from stable executable")
            require(isinstance(probe["evidenceSha256"], str) and bool(re.fullmatch(r"[0-9a-f]{64}", probe["evidenceSha256"])),
                    "probe evidence digest required")
            outcomes.append(probe["exitCode"] == 0)
            if probe["exitCode"] == 0:
                require(text(probe["version"]), "successful probe version required")
                versions.append(probe["version"])
            else:
                require(probe["version"] is None, "failed probe must not claim version")
        require(all(isinstance(x, str) for x in surfaces) and set(x for x in surfaces if isinstance(x, str)) == expected
                and len(surfaces) == len(expected), "exact platform probe surfaces required")
        if client["status"] == "observed":
            require(bool(outcomes) and all(outcomes), "observed client requires successful probes")
            require(bool(versions) and all(v == versions[0] for v in versions), "Windows/WSL version mismatch")
        elif client["status"] == "unavailable":
            require(bool(outcomes) and not all(outcomes), "unavailable client requires a failed probe")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.inventory.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    print(json.dumps({"validInventory": not errors, "p06Accepted": False, "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
