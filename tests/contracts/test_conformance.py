"""Black-box wire/schema/signature conformance for two independent clients."""
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
VECTORS = Path(__file__).parent / 'vectors' / 'valid-examples.json'
NOW = '2026-10-09T12:01:00Z'


class Client:
    def __init__(self, language):
        self.language = language
        self.env = os.environ.copy()
        if language == 'python':
            self.command = [os.environ.get('AGENTMUX_CONTRACT_PYTHON', sys.executable), '-m', 'agentmux_contracts']
            source_root = Path(os.environ.get('AGENTMUX_CONTRACT_SOURCE_ROOT', str(ROOT)))
            self.env['PYTHONPATH'] = str(source_root / 'sdk/python')
        else:
            self.command = [os.environ.get('AGENTMUX_CONTRACT_NODE', 'node'),
                            os.environ.get('AGENTMUX_CONTRACT_TS_CLI', str(ROOT / 'sdk/typescript/dist/cli.js'))]

    def raw(self, data):
        process = subprocess.run(self.command, input=data, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=ROOT, env=self.env, timeout=60)
        if process.returncode:
            raise AssertionError(f'{self.language} CLI exited {process.returncode}; check setup locally')
        return [json.loads(line) for line in process.stdout.splitlines()]

    def many(self, requests):
        responses = self.raw(b''.join(json.dumps(r, ensure_ascii=True, allow_nan=False).encode() + b'\n' for r in requests))
        if len(responses) != len(requests):
            raise AssertionError(f'{self.language}: response count mismatch')
        return responses

    def call(self, request):
        return self.many([request])[0]


class Conformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clients = [Client('python'), Client('typescript')]
        cls.examples = json.loads(VECTORS.read_text(encoding='utf-8'))
        cls.seed = secrets.token_bytes(32).hex()
        # Node's built-in crypto derives only the public key. No SDK canonicalizer is used.
        derive = "const c=require('crypto');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{const k=c.createPrivateKey({key:Buffer.from('302e020100300506032b657004220420'+s.trim(),'hex'),format:'der',type:'pkcs8'});process.stdout.write(c.createPublicKey(k).export({format:'der',type:'spki'}).subarray(-32).toString('hex'))});"
        cls.public = subprocess.check_output([os.environ.get('AGENTMUX_CONTRACT_NODE', 'node'), '-e', derive], input=cls.seed.encode(), timeout=15).decode()

    def accepted(self, response):
        self.assertIs(response.get('ok'), True, response.get('error', 'invalid response'))
        return response['result']

    def rejected(self, response):
        self.assertIs(response.get('ok'), False)
        self.assertIsInstance(response.get('error'), str)
        self.assertNotIn('result', response)

    def test_independent_canonical_vectors(self):
        # Expected bytes are literals, not output from either implementation.
        vectors = [
            ({'z': 0, 'a': [True, None, 'line\nquote"\\']}, '{"a":[true,null,"line\\nquote\\"\\\\"],"z":0}'),
            ({'n': -0.0, 'x': 1e-7, 'y': 1e-6, 'v': 4.5}, '{"n":0,"v":4.5,"x":1e-7,"y":0.000001}'),
            ({'\ue000': 1, '\U0001f600': 2, 'a': 3}, '{"a":3,"\U0001f600":2,"\ue000":1}'),
            ({'s': '\b\t\n\f\r\x00'}, '{"s":"\\b\\t\\n\\f\\r\\u0000"}'),
            ({'max': 9007199254740991, 'min': -9007199254740991}, '{"max":9007199254740991,"min":-9007199254740991}'),
        ]
        for client in self.clients:
            replies = client.many([{'op': 'canonical', 'value': value} for value, _ in vectors])
            for i, (reply, (_, expected)) in enumerate(zip(replies, vectors)):
                with self.subTest(client=client.language, vector=i):
                    result = self.accepted(reply)
                    self.assertEqual(result['canonical'], expected)
                    self.assertEqual(result['sha256'], 'sha256:' + hashlib.sha256(expected.encode()).hexdigest())

    def test_strict_parser_rejections(self):
        vectors = [('duplicate', '{"x":1,"x":2}'),
                   ('escaped_duplicate', '{"a":1,"\\u0061":2}'),
                   ('comment', '{/*x*/"x":1}'), ('trailing', '{} true'),
                   ('trailing_comma', '[1,]'), ('lone_surrogate', '"\\ud800"'),
                   ('nan', 'NaN'), ('infinity', 'Infinity'), ('overflow', '1e999'),
                   ('unsafe_integer', '9007199254740992'),
                   ('depth', '[' * 70 + '0' + ']' * 70)]
        for client in self.clients:
            for (label, _), reply in zip(vectors, client.many([{'op': 'parse', 'raw': raw} for _, raw in vectors])):
                with self.subTest(client=client.language, vector=label):
                    self.rejected(reply)

    def test_raw_utf8_and_recovery(self):
        for client in self.clients:
            with self.subTest(client=client.language):
                replies = client.raw(b'{"op":"parse","raw":"\xff"}\n{"op":"parse","raw":"true"}\n')
                self.assertEqual(len(replies), 2)
                self.rejected(replies[0])
                self.assertIs(self.accepted(replies[1]), True)

    def test_escaped_unicode_valid(self):
        for client in self.clients:
            reply = client.call({'op': 'parse', 'raw': '{"emoji":"\\ud83d\\ude00","accent":"caf\\u00e9"}'})
            self.assertEqual(self.accepted(reply), {'emoji': '\U0001f600', 'accent': 'caf\u00e9'})

    def test_depth_boundary(self):
        for client in self.clients:
            replies = client.many([{'op': 'parse', 'raw': '[' * n + ']' * n} for n in (64, 65)])
            with self.subTest(client=client.language):
                self.accepted(replies[0])
                self.rejected(replies[1])

    def test_oversized_raw_cli_recovers(self):
        # Exercise transport framing, not the nested payload's independent size limit.
        for client in self.clients:
            replies = client.raw(b' ' * 1_048_577 + b'\n{"op":"parse","raw":"true"}\n')
            with self.subTest(client=client.language):
                self.assertEqual(len(replies), 2)
                self.rejected(replies[0])
                self.assertIs(self.accepted(replies[1]), True)

    def test_exact_size_frame_excludes_newline_delimiter(self):
        frame = b'{"op":"parse","raw":"true","padding":""}'
        frame = frame[:-2] + b'x' * (1_048_576 - len(frame)) + frame[-2:]
        self.assertEqual(len(frame), 1_048_576)
        for client in self.clients:
            with self.subTest(client=client.language):
                replies = client.raw(frame + b'\n')
                self.assertEqual(len(replies), 1)
                self.assertIs(self.accepted(replies[0]), True)

    def test_all_schema_examples(self):
        for client in self.clients:
            for schema, reply in zip(self.examples, client.many([{'op': 'validate', 'schema': name, 'value': value} for name, value in self.examples.items()])):
                with self.subTest(client=client.language, schema=schema):
                    self.assertIs(self.accepted(reply), True)

    def test_all_required_schema_fields_and_unknown_fields(self):
        cases = []
        for name, value in self.examples.items():
            schema = json.loads((ROOT / 'contracts/v1/schemas' / (name + '.schema.json')).read_text())
            for field in schema['required']:
                invalid = copy.deepcopy(value)
                del invalid[field]
                cases.append((name + ':missing:' + field, name, invalid))
            invalid = copy.deepcopy(value)
            invalid['unexpectedProperty'] = True
            cases.append((name + ':unknown', name, invalid))
            invalid = copy.deepcopy(value)
            invalid['schemaVersion'] = '99.0.0'
            cases.append((name + ':version', name, invalid))
        for client in self.clients:
            replies = client.many([{'op': 'validate', 'schema': name, 'value': value} for _, name, value in cases])
            for (label, _, _), reply in zip(cases, replies):
                with self.subTest(client=client.language, mutation=label):
                    self.rejected(reply)

    def signed(self, signer, claims=None):
        envelope = copy.deepcopy(self.examples['message-envelope'])
        attestation = copy.deepcopy(self.examples['ingress-attestation'])
        claims = copy.deepcopy(claims or attestation['claims'])
        digest = self.accepted(signer.call({'op': 'canonical', 'value': envelope['payload']}))['sha256']
        claims['operation']['payloadDigest'] = digest
        attestation['claims'] = claims
        attestation['signature'] = self.accepted(signer.call({'op': 'sign', 'claims': claims, 'seedHex': self.seed}))
        for field in ('operation', 'messageId', 'kind', 'contractId', 'contractMajor', 'sourceHubId', 'sourceInstanceId', 'sentAt', 'correlationId'):
            envelope[field] = copy.deepcopy(claims[field])
        envelope['destinationHubId'] = claims['audience']['hubId']
        envelope['destinationServiceId'] = claims['audience']['serviceId']
        envelope['ingressAttestation'] = attestation
        return envelope

    def verify_request(self, envelope, full=False):
        base = {'op': 'verifyEnvelope' if full else 'verify', 'publicKeyHex': self.public,
                'expectedAudience': {'hubId': 'hub-origin', 'serviceId': 'task-owner'}, 'now': NOW}
        if full:
            base['envelope'] = envelope
        else:
            base.update(attestation=envelope['ingressAttestation'], payload=envelope['payload'])
        return base

    def test_cross_signatures_both_directions(self):
        for signer, verifier in (self.clients, list(reversed(self.clients))):
            envelope = self.signed(signer)
            for full in (False, True):
                with self.subTest(signer=signer.language, verifier=verifier.language, envelope=full):
                    self.assertEqual(self.accepted(verifier.call(self.verify_request(envelope, full))), envelope['ingressAttestation']['claims'])
            other_signature = self.accepted(verifier.call({'op': 'sign', 'claims': envelope['ingressAttestation']['claims'], 'seedHex': self.seed}))
            self.assertEqual(other_signature, envelope['ingressAttestation']['signature'])

    def test_attestation_tampering_and_signed_policy_rejections(self):
        for signer, verifier in (self.clients, list(reversed(self.clients))):
            envelope = self.signed(signer)
            cases = []
            r = self.verify_request(copy.deepcopy(envelope)); r['payload'] = {'altered': True}; cases.append(('payload', r))
            r = self.verify_request(copy.deepcopy(envelope)); r['expectedAudience']['hubId'] = 'other-hub'; cases.append(('audience', r))
            r = self.verify_request(copy.deepcopy(envelope)); r['now'] = '2026-10-09T12:06:00Z'; cases.append(('expiry', r))
            r = self.verify_request(copy.deepcopy(envelope)); sig = r['attestation']['signature']; r['attestation']['signature'] = ('A' if sig[0] != 'A' else 'B') + sig[1:]; cases.append(('signature', r))
            claims = copy.deepcopy(envelope['ingressAttestation']['claims']); claims['issuerHubId'] = 'other-hub'
            cases.append(('signed_issuer', self.verify_request(self.signed(signer, claims))))
            for (label, _), reply in zip(cases, verifier.many([r for _, r in cases])):
                with self.subTest(signer=signer.language, verifier=verifier.language, mutation=label):
                    self.rejected(reply)

    def test_unsigned_envelope_cannot_override_verified_claims(self):
        for signer, verifier in (self.clients, list(reversed(self.clients))):
            base = self.signed(signer)
            mutations = []
            for field in ('messageId', 'sourceHubId', 'sourceInstanceId', 'correlationId', 'contractId'):
                env = copy.deepcopy(base); env[field] = 'forged-value'; mutations.append((field, env))
            for field, value in (('kind', 'event'), ('contractMajor', 2), ('sentAt', '2026-10-09T12:00:02Z'),
                                 ('destinationHubId', 'other-hub'), ('destinationServiceId', 'other-service')):
                env = copy.deepcopy(base); env[field] = value; mutations.append((field, env))
            env = copy.deepcopy(base); env['operation']['caller']['principalId'] = 'forged-user'; mutations.append(('caller', env))
            env = copy.deepcopy(base); env['operation']['scope']['projectId'] = 'other-project'; mutations.append(('scope', env))
            env = copy.deepcopy(base); env['operation']['grantRef']['revision'] += 1; mutations.append(('grant', env))
            for (label, _), reply in zip(mutations, verifier.many([self.verify_request(e, True) for _, e in mutations])):
                with self.subTest(signer=signer.language, mutation=label):
                    self.rejected(reply)


if __name__ == '__main__':
    unittest.main()
