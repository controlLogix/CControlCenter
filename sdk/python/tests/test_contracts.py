import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nacl.signing import SigningKey

from agentmux_contracts import (ContractError, canonical_bytes, payload_digest,
                               sign_claims, strict_loads, validate,
                               verify_attestation, verify_envelope)


SEED = bytes(range(32))  # Public test data, never an enrollment credential.
NOW = datetime(2026, 10, 9, 12, 0, 2, tzinfo=timezone.utc)


def example():
    ref = {"id": "fixture-ref", "ownerHubId": "hub-one", "revision": 1}
    operation = {
        "schemaVersion": "1.0.0", "operationId": "operation-one",
        "payloadDigest": payload_digest({"taskId": "task-one"}), "expectedVersion": 1,
        "caller": {"principalId": "user-one", "kind": "human", "authenticatedIdentityRef": ref},
        "effectiveActorRef": ref, "scope": {"organizationId": "org-one", "projectId": "project-one", "workspaceId": None},
        "taskId": "task-one", "runId": None, "attemptId": None, "delegationRef": None,
        "grantRef": ref, "approvalRefs": [], "traceId": "trace-one", "causationId": "cause-one",
        "deadline": "2026-10-09T12:05:00Z", "cancellationRef": ref,
    }
    claims = {
        "purpose": "agentmux-ingress-v1", "issuerHubId": "hub-one", "signingKeyRef": ref,
        "authenticationMethod": "nats-credential-mapping", "authenticatedTransportRef": ref,
        "audience": {"hubId": "hub-one", "serviceId": "task-owner"},
        "issuedAt": "2026-10-09T12:00:01Z", "expiresAt": "2026-10-09T12:05:00Z",
        "messageId": "message-one", "kind": "command", "contractId": "task-inspect", "contractMajor": 1,
        "sourceHubId": "hub-one", "sourceInstanceId": "ingress-one", "sentAt": "2026-10-09T12:00:01Z",
        "correlationId": "operation-one", "operation": operation,
    }
    attestation = {"schemaVersion": "1.0.0", "algorithm": "Ed25519",
                   "canonicalization": "RFC8785-JCS-UTF8", "claims": claims,
                   "signature": sign_claims(claims, SEED)}
    envelope = {key: copy.deepcopy(claims[key]) for key in (
        "messageId", "kind", "contractId", "contractMajor", "sourceHubId",
        "sourceInstanceId", "sentAt", "correlationId", "operation")}
    envelope.update(schemaVersion="1.0.0", destinationHubId="hub-one", destinationServiceId="task-owner",
                    ingressAttestation=attestation, payload={"taskId": "task-one"})
    return envelope


class WireTests(unittest.TestCase):
    def test_duplicate_keys_include_escaped_nested_names(self):
        for raw in ('{"a":1,"a":2}', '{"outer":{"a":1,"\\u0061":2}}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ContractError, "duplicate_key"):
                strict_loads(raw)

    def test_bad_unicode_and_nonfinite_numbers(self):
        for raw in (b'"\xff"', '"\\ud800"', '{"\\udfff":1}', 'NaN', 'Infinity', '1e400'):
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                strict_loads(raw)
        self.assertEqual(strict_loads('"\\ud83d\\ude00"'), "😀")

    def test_raw_large_integer_is_not_rounded(self):
        with self.assertRaisesRegex(ContractError, "unsafe_integer"):
            strict_loads('{"n":9007199254740993}')
        self.assertEqual(canonical_bytes(strict_loads('1e30')), b'1e+30')

    def test_rfc_number_and_utf16_ordering(self):
        value = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27, -0.0]}
        self.assertEqual(canonical_bytes(value), b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,0]}')
        self.assertEqual(canonical_bytes({"\ue000": 1, "😀": 2}), '{"😀":2,"\ue000":1}'.encode())

    def test_limits_and_non_json_objects(self):
        self.assertEqual(canonical_bytes(strict_loads('[' * 64 + ']' * 64)), ('[' * 64 + ']' * 64).encode())
        with self.assertRaisesRegex(ContractError, "depth_limit"):
            strict_loads('[' * 65 + ']' * 65)
        for raw in ('[' * 65 + '0' + ']' * 65, '"' + 'x' * 1_048_576 + '"'):
            with self.assertRaises(ContractError):
                strict_loads(raw)
        for value in ({1: "x"}, {"v": float("nan")}, (1, 2)):
            with self.assertRaises(ContractError):
                canonical_bytes(value)


class AttestationTests(unittest.TestCase):
    def setUp(self):
        self.env = example()
        self.key = bytes(SigningKey(SEED).verify_key)
        self.audience = {"hubId": "hub-one", "serviceId": "task-owner"}

    def check(self, env=None, now=NOW):
        return verify_envelope(env or self.env, self.key, self.audience, now)

    def test_signed_envelope(self):
        self.assertEqual(self.check(), self.env["ingressAttestation"]["claims"])

    def test_signature_and_payload_tampering(self):
        for mutate in (
            lambda e: e["ingressAttestation"]["claims"].update(contractId="task-write"),
            lambda e: e["payload"].update(query="changed"),
            lambda e: e["operation"]["caller"].update(principalId="other-user"),
            lambda e: e.update(destinationServiceId="other-owner"),
        ):
            env = copy.deepcopy(self.env)
            mutate(env)
            with self.assertRaises(ContractError):
                self.check(env)

    def test_expiry_is_exclusive(self):
        with self.assertRaisesRegex(ContractError, "attestation_time_invalid"):
            self.check(now=datetime(2026, 10, 9, 12, 5, tzinfo=timezone.utc))

    def test_signed_invalid_issuer_and_lifetime(self):
        for mutate in (
            lambda c: c["signingKeyRef"].update(ownerHubId="other-hub"),
            lambda c: c.update(expiresAt="2026-10-09T12:06:00Z"),
            lambda c: c.update(issuedAt="2026-10-09T12:01:00Z"),
            lambda c: c.update(sentAt="2026-10-09T12:01:00Z"),
        ):
            att = copy.deepcopy(self.env["ingressAttestation"])
            mutate(att["claims"])
            att["signature"] = sign_claims(att["claims"], SEED)
            with self.assertRaises(ContractError):
                verify_attestation(att, self.key, self.audience, NOW, self.env["payload"])

    def test_no_remote_schema_resolution_and_unknown_schema(self):
        with self.assertRaisesRegex(ContractError, "unknown_schema"):
            validate("https://caller.invalid/schema", {})

    def test_cli_error_does_not_echo_bad_input(self):
        process = subprocess.run([sys.executable, "-m", "agentmux_contracts"],
                                 input='{"op":"sign","seedHex":"secret-do-not-echo"}\n',
                                 text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(process.stdout), {"ok": False, "error": "invalid_request"})
        self.assertEqual(process.stderr, "")

    def test_cli_size_limit_excludes_only_line_delimiter(self):
        prefix = '{"op":"canonical","value":"'
        suffix = '"}'
        exact = prefix + 'x' * (1_048_576 - len(prefix) - len(suffix)) + suffix
        too_large = prefix + 'x' * (1_048_577 - len(prefix) - len(suffix)) + suffix
        process = subprocess.run([sys.executable, "-m", "agentmux_contracts"],
                                 input=exact + '\n' + too_large + '\n' + '{"op":"parse","raw":"true"}\n',
                                 text=True, capture_output=True, check=True)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertTrue(responses[0]['ok'])
        self.assertEqual(responses[1], {'ok': False, 'error': 'size_limit'})
        self.assertEqual(responses[2], {'ok': True, 'result': True})
        self.assertEqual(process.stderr, '')

    def test_schema_cache_invalidates_changed_bytes_with_same_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'copied.schema.json'
            schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
                      '$id': 'urn:agentmux:test:copied', 'const': 'allowed'}
            path.write_text(json.dumps(schema), encoding='utf-8')
            previous = path.stat()
            validate('copied', 'allowed', directory)
            schema['const'] = 'changed'
            path.write_text(json.dumps(schema), encoding='utf-8')
            os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            with self.assertRaisesRegex(ContractError, 'schema_invalid'):
                validate('copied', 'allowed', directory)
            validate('copied', 'changed', directory)
            path.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(ContractError, 'schema_configuration_error'):
                validate('copied', 'changed', directory)


class SemanticTests(unittest.TestCase):
    def test_cross_field_invariants(self):
        fixture = Path(__file__).resolve().parents[2] / "typescript" / "test-examples.json"
        values = json.loads(fixture.read_text(encoding="utf-8"))
        values["plugin-manifest"]["dependencies"] = [{"packageId": "dependency-one", "minimumVersion": "1.0.0", "exclusiveMaximumVersion": "2.0.0", "optional": False}]
        mutations = [
            ("plugin-manifest", lambda v: v["dependencies"][0].update(packageId=v["packageId"])),
            ("plugin-manifest", lambda v: v["dependencies"][0].update(exclusiveMaximumVersion=v["dependencies"][0]["minimumVersion"])),
            ("plugin-manifest", lambda v: v["requestedCapabilities"][0].update(resourceClass="kernel-status", action="publish")),
            ("plugin-context", lambda v: v["effectiveGrant"].update(subjectInstanceId="other-instance")),
            ("plugin-context", lambda v: v["effectiveGrant"].update(expiresAt=v["effectiveGrant"]["issuedAt"])),
            ("operation-context", lambda v: v.update(deadline="2026-02-30T12:00:00Z")),
            ("owner-record", lambda v: v.update(outcome="rejected")),
            ("owner-record", lambda v: v["effects"].append(dict(v["effects"][0], contractId="other-effect"))),
            ("protected-assembly", lambda v: v["plugins"][0].update(id="other-plugin")),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name, mutate=mutate):
                value = copy.deepcopy(values[name])
                validate(name, value)
                mutate(value)
                with self.assertRaises(ContractError):
                    validate(name, value)


if __name__ == "__main__":
    unittest.main()
