"""Synthetic positive/negative placement contract tests; no client execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from inventory import validate

ROOT = Path(__file__).resolve().parent


class InventoryContract(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / "fixtures/wsl-inventory.json").read_text())
        self.client = self.record["clients"][0]

    def rejects(self, phrase):
        self.assertTrue(any(phrase in error for error in validate(self.record)), validate(self.record))

    def test_wsl_observation_contract(self):
        self.assertEqual(validate(self.record), [])

    def test_missing_client_is_explicit_inventory_not_support(self):
        self.client.update(status="missing", probes=[])
        for key in ("installationOwner", "configOwner", "authOwner", "stableTarget", "executableTarget", "launcher"):
            self.client[key] = None
        self.assertEqual(validate(self.record), [])
        self.client["installationOwner"] = "windows"
        self.rejects("missing client must not claim")

    def test_missing_search_boundary_is_rejected(self):
        self.client["searchScope"] = ""
        self.rejects("search scope")

    def test_missing_client_cannot_claim_probe(self):
        self.client["status"] = "missing"
        self.rejects("must not claim executed probes")

    def test_unavailable_records_failed_interop_without_success(self):
        self.client["status"] = "unavailable"
        self.client["probes"][1].update(exitCode=1, version=None)
        self.assertEqual(validate(self.record), [])
        self.client["status"] = "observed"
        self.rejects("successful probes")

    def test_unavailable_requires_actual_failed_observation(self):
        self.client["status"] = "unavailable"
        self.rejects("requires a failed probe")

    def test_duplicate_linux_installation_is_rejected(self):
        self.client["linuxDuplicateInstalled"] = True
        self.rejects("duplicate Linux")

    def test_ownership_mismatches_are_rejected(self):
        for field in ("installationOwner", "configOwner", "authOwner"):
            with self.subTest(field=field):
                self.client[field] = "linux"
                self.rejects("ownership mismatch")
                self.client[field] = "windows"

    def test_credentials_copy_is_rejected(self):
        self.client["credentialsCopied"] = True
        self.rejects("credential copying")

    def test_different_installation_is_rejected(self):
        self.client["probes"][1]["installation"] = "C:/Other/client.exe"
        self.rejects("installation differs")

    def test_version_mismatch_is_rejected(self):
        self.client["probes"][1]["version"] = "example 1.2.2"
        self.rejects("version mismatch")

    def test_versioned_target_is_rejected(self):
        self.client["stableTarget"] = "C:/Tools/v1.2.3/client.exe"
        self.rejects("version-specific target")

    def test_linux_client_cannot_substitute_for_windows(self):
        self.client["stableTarget"] = "/usr/local/bin/client"
        self.rejects("Windows installation")

    def test_missing_limits_and_p06_claim_are_rejected(self):
        for limit in list(self.record["limits"]):
            with self.subTest(limit=limit):
                self.record["limits"].remove(limit)
                self.rejects("explicit P06")
                self.record["limits"].append(limit)
        self.client["interopLimits"] = []
        self.rejects("interop limitations")
        self.record["p06Accepted"] = True
        self.rejects("cannot accept P06")

    def test_runtime_and_probe_surface_placement(self):
        self.record["runtime"] = "windows"
        self.rejects("runtime placement")
        self.client["probes"][1]["surface"] = "linux"
        self.rejects("exact platform probe surfaces")

    def test_probe_evidence_cannot_be_omitted_or_duplicated(self):
        self.client["probes"][0]["evidenceSha256"] = ""
        self.rejects("evidence digest")
        self.client["probes"] = self.client["probes"][:1] * 2
        self.rejects("exact platform probe surfaces")

    def test_native_platform_placement_stays_native(self):
        for platform in ("linux", "macos"):
            with self.subTest(platform=platform):
                record = copy.deepcopy(self.record)
                record.update(platform=platform, runtime=platform)
                client = record["clients"][0]
                client.update(installationOwner=platform, configOwner=platform, authOwner=platform,
                              stableTarget="/usr/local/bin/example-client", executableTarget="/usr/local/bin/example-client",
                              launcher="/usr/local/bin/example-client")
                client["probes"] = [dict(client["probes"][0], surface=platform, installation=client["stableTarget"],
                                        executable=client["executableTarget"], command=[client["stableTarget"], "--version"])]
                self.assertEqual(validate(record), [])

    def test_closed_format_and_duplicate_identity(self):
        self.record["clients"].append(copy.deepcopy(self.client))
        self.rejects("duplicate client id")
        self.record["secret"] = "synthetic forbidden extra field"
        self.rejects("exact fields")

    def test_malformed_records_return_errors(self):
        for value in (None, [], {}, {"schemaVersion": 1}):
            with self.subTest(value=value):
                self.assertTrue(validate(value))
        for field, value in (("limits", None), ("clients", []), ("observedAt", "yesterday"),
                             ("candidateCommit", "short"), ("p06Accepted", 0)):
            with self.subTest(field=field):
                record = copy.deepcopy(self.record)
                record[field] = value
                self.assertTrue(validate(record))

    def test_failed_probe_cannot_fabricate_version(self):
        self.client["status"] = "unavailable"
        self.client["probes"][1]["exitCode"] = 1
        self.rejects("failed probe must not claim version")

    def test_malformed_field_types_fail_without_exception(self):
        groups = (
            ((), ("platform", "limits", "candidateCommit", "observedAt", "clients")),
            (("clients", 0), ("id", "interopLimits", "probes", "status", "stableTarget", "executableTarget",
                              "launcher", "installationOwner", "configOwner", "authOwner")),
            (("clients", 0, "probes", 0), ("surface", "command", "exitCode", "version", "installation",
                                          "executable", "evidenceSha256")),
        )
        for path, fields in groups:
            for field in fields:
                for value in (None, [], {}):
                    with self.subTest(path=path, field=field, value=value):
                        record = copy.deepcopy(self.record)
                        target = record
                        for key in path:
                            target = target[key]
                        target[field] = value
                        self.assertTrue(validate(record))

    def test_npm_identity_binds_node_and_package(self):
        node, package = "C:/Tools/node.exe", "C:/Tools/node_modules/example/cli.js"
        self.client.update(executableTarget=node, stableTarget=package)
        for probe in self.client["probes"]:
            probe.update(executable=node, installation=package)
        self.client["probes"][0]["command"] = [node, package, "--version"]
        self.assertEqual(validate(self.record), [])
        self.client["probes"][1]["installation"] = "C:/Tools/node_modules/different/cli.js"
        self.rejects("installation differs")
        self.client["probes"][1]["installation"] = package
        self.client["probes"][0]["command"][1] = "C:/Tools/node_modules/different/cli.js"
        self.rejects("bind package entry point")
        self.client["probes"][1]["executable"] = "C:/Other/node.exe"
        self.rejects("executable differs")

    def test_cli_reports_failure_and_does_not_modify_input(self):
        self.client["probes"][1]["version"] = "different"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory with spaces.json"
            original = json.dumps(self.record).encode()
            path.write_bytes(original)
            result = subprocess.run([sys.executable, str(ROOT / "inventory.py"), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)["p06Accepted"])
            self.assertFalse(json.loads(result.stdout)["validInventory"])
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
