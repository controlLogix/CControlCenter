"""Promoted signed contracts transported over an owned, scoped NATS leaf."""
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

from nacl.signing import SigningKey
from nats.js.api import StreamConfig, StorageType
import run as leaf

ROOT, HERE = leaf.ROOT, leaf.HERE
CACHE = Path.home() / '.cache/agentmux-governance'
PYTHON = os.environ.get('AGENTMUX_CONTRACT_PYTHON', str(CACHE / 'p01-contracts-python/bin/python'))
NODE = os.environ.get('AGENTMUX_CONTRACT_NODE', 'node')
TS = Path(os.environ.get('AGENTMUX_CONTRACT_TS_CLI', str(CACHE / 'typescript-sdk/dist/cli.js')))
REPORT = Path(os.environ.get('AGENTMUX_EVIDENCE_DIR', str(ROOT / 'docs/planning/2026-10-09/delivery/evidence/P01'))) / 'signed-leaf-result.json'
NOW = '2026-10-09T12:01:00Z'  # Trusted fixture clock, never selected by a message.
require = leaf.require


def hashes():
    paths = []
    for directory in ('contracts/v1', 'sdk/python', 'sdk/typescript', 'tests/leaf'):
        paths += [p for p in (ROOT / directory).rglob('*') if p.is_file()
                  and not {'__pycache__', 'node_modules', 'dist'} & set(p.parts) and p.suffix != '.pyc']
    paths += [ROOT / 'tests/contracts/vectors' / n for n in ('valid-examples.json', 'payload-examples.json')]
    paths += [ROOT / 'hub/requirements.lock']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def mirror_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for d in ('contracts/v1', 'sdk/python') for p in sorted((root / d).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def build_hashes():
    source = ROOT / 'sdk/typescript'
    names = ['package.json', 'package-lock.json', 'tsconfig.json']
    names += [p.relative_to(source).as_posix() for p in sorted((source / 'src').rglob('*.ts'))]
    pairs = {n: {'repository': hashlib.sha256((source / n).read_bytes()).hexdigest(),
                 'buildSource': hashlib.sha256((TS.parent.parent / n).read_bytes()).hexdigest()} for n in names}
    return {'sources': pairs, 'allSourcesMatch': all(p['repository'] == p['buildSource'] for p in pairs.values()),
            'compiled': {p.relative_to(TS.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(TS.parent.rglob('*.js'))}}


class SDK:
    def __init__(self, language, mirror):
        self.command = [PYTHON, '-m', 'agentmux_contracts'] if language == 'python' else [NODE, str(TS)]
        self.env = dict(os.environ, PYTHONPATH=str(mirror / 'sdk/python'), AGENTMUX_SCHEMA_DIR=str(mirror / 'contracts/v1/schemas'))

    async def call(self, request):
        process = await asyncio.create_subprocess_exec(*self.command, cwd=ROOT, env=self.env,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(leaf.encode(request) + b'\n'), 20)
        except BaseException:
            if process.returncode is None:
                process.kill(); await process.wait()
            raise
        require(process.returncode == 0 and not stderr, 'SDK subprocess failed; diagnostics suppressed')
        return json.loads(stdout)

    async def accepted(self, request):
        response = await self.call(request)
        require(response.get('ok') is True, 'SDK rejected expected valid fixture request')
        return response['result']


class Contracts:
    def __init__(self, mirror):
        self.py, self.ts = SDK('python', mirror), SDK('typescript', mirror)
        self.examples = json.loads((ROOT / 'tests/contracts/vectors/valid-examples.json').read_text())
        self.payloads = json.loads((ROOT / 'tests/contracts/vectors/payload-examples.json').read_text())
        self.seeds = {hub: secrets.token_bytes(32) for hub in ('hub-origin', 'hub-executor')}
        # This explicit map stands in for pre-enrolled fixture trust, not message-provided key discovery.
        self.keys = {(hub, 'ingress-key-one', 1): SigningKey(seed).verify_key.encode().hex() for hub, seed in self.seeds.items()}

    async def envelope(self, name, source, destination, operation, payload=None):
        value = copy.deepcopy(self.examples['message-envelope'])
        entry = self.payloads[name]
        value.update(contractId=name, kind=entry['kind'], sourceHubId=source, destinationHubId=destination,
                     destinationServiceId=entry['destinationServiceId'], messageId='msg-' + operation, correlationId=operation,
                     payload=copy.deepcopy(payload or entry['payload']))
        value['operation'].update(operationId=operation, grantRef={'id': 'actor-grant', 'ownerHubId': 'hub-origin', 'revision': 1})
        value['operation']['caller']['authenticatedIdentityRef']['ownerHubId'] = source
        value['operation']['effectiveActorRef']['ownerHubId'] = source
        return await self.sign(value)

    async def sign(self, value):
        source = value['sourceHubId']; signer = self.py if source == 'hub-origin' else self.ts
        value['operation']['payloadDigest'] = (await signer.accepted({'op': 'canonical', 'value': value['payload']}))['sha256']
        attestation = value['ingressAttestation']; claims = attestation['claims']
        for name in ('messageId', 'kind', 'contractId', 'contractMajor', 'sourceHubId', 'sourceInstanceId', 'sentAt', 'correlationId', 'operation'):
            claims[name] = copy.deepcopy(value[name])
        claims.update(issuerHubId=source, audience={'hubId': value['destinationHubId'], 'serviceId': value['destinationServiceId']})
        for name in ('signingKeyRef', 'authenticatedTransportRef'):
            claims[name]['ownerHubId'] = source
        attestation['signature'] = await signer.accepted({'op': 'sign', 'claims': claims, 'seedHex': self.seeds[source].hex()})
        return value

    async def verify(self, raw, source, destination, service):
        verifier = self.ts if destination == 'hub-executor' else self.py
        # Strict decoding occurs in the receiving SDK before verification.
        try:
            text = raw.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            return None
        parsed = await verifier.call({'op': 'parse', 'raw': text})
        if not parsed.get('ok'):
            return None
        value = parsed['result']
        try:
            claims = value['ingressAttestation']['claims']; key = claims['signingKeyRef']
            if claims['issuerHubId'] != source or key['ownerHubId'] != source or value['sourceHubId'] != source:
                return None
            public = self.keys[(source, key['id'], key['revision'])]
        except (KeyError, TypeError):
            return None
        answer = await verifier.call({'op': 'verifyEnvelope', 'envelope': value, 'publicKeyHex': public,
                    'expectedAudience': {'hubId': destination, 'serviceId': service}, 'now': NOW})
        if not answer.get('ok'):
            return None
        # Static fixture owner policy is additional to signature/schema checks.
        operation = answer['result']['operation']
        if operation['scope'] != self.examples['message-envelope']['operation']['scope']:
            return None
        if operation['grantRef'] != {'id': 'actor-grant', 'ownerHubId': 'hub-origin', 'revision': 1}:
            return None
        return value


def decision_matches_offer(envelope, offer):
    """Bind a signed acceptance decision to the origin's reserved work."""
    payload, reserved = envelope['payload'], offer['payload']
    return (envelope['contractId'] == 'delegation-decision'
            and envelope['sourceHubId'] == reserved['executorHubId']
            and envelope['destinationHubId'] == reserved['originHubId']
            and payload['decision'] == 'accepted_reserved'
            and all(payload[key] == reserved[key] for key in
                    ('taskId', 'delegationId', 'attemptId')))


def result_matches_offer(envelope, offer):
    """Owner admission binds a valid signed report to its reserved work."""
    payload, reserved = envelope['payload'], offer['payload']
    return (envelope['contractId'] == 'execution-report'
            and envelope['sourceHubId'] == reserved['executorHubId']
            and envelope['destinationHubId'] == reserved['originHubId']
            and payload['status'] == 'completion_reported'
            and all(payload[key] == reserved[key] for key in
                    ('executorHubId', 'taskId', 'delegationId', 'attemptId', 'repositoryRevision')))


async def transfer(client, subject, subscription, value):
    raw = value if isinstance(value, bytes) else leaf.encode(value)
    await client.publish(subject, raw); await client.flush()
    received = (await subscription.next_msg(timeout=3)).data
    require(received == raw, 'leaf changed signed wire bytes')
    return received


async def exercise(directory, contracts, cases):
    a, b = leaf.Broker(directory, 'ORIGIN'), None
    def passed(name):
        cases.append({'name': name, 'status': 'passed'})
    try:
        b = leaf.Broker(directory, 'RECEIVER', a)
        await a.start(); await b.start()
        oa, ob = await a.connect('owner'), await b.connect('owner')
        ja, jb = oa.jetstream(domain='ORIGIN'), ob.jetstream(domain='RECEIVER')
        for js in (ja, jb):
            await js.add_stream(config=StreamConfig(name='LEDGER', subjects=['private.task.one'], storage=StorageType.FILE))
        ca, cb = await a.connect('bridge'), await b.connect('bridge')
        commands = await cb.subscribe(leaf.COMMAND); await cb.flush(); await leaf.link_ready(ca, commands)
        offer = await contracts.envelope('delegation-offer', 'hub-origin', 'hub-executor', 'offer-one')
        before = (await jb.stream_info('LEDGER')).state.messages
        bad = []
        bad.append(('malformed', b'{broken'))
        bad.append(('invalid-utf8', b'{"invalid":"\xff"}'))
        unknown = copy.deepcopy(offer); unknown['contractId'] = 'unknown-contract'; bad.append(('unknown-contract', await contracts.sign(unknown)))
        audience = copy.deepcopy(offer); audience['destinationHubId'] = 'other-hub'; bad.append(('wrong-audience', await contracts.sign(audience)))
        tampered = copy.deepcopy(offer); tampered['payload']['repositoryRevision'] = 'tampered'; bad.append(('tampered-payload', tampered))
        expired = copy.deepcopy(offer); expired['ingressAttestation']['claims']['expiresAt'] = '2026-10-09T12:00:30Z'; bad.append(('expired', await contracts.sign(expired)))
        for label, invalid in bad:
            raw = await transfer(ca, leaf.COMMAND, commands, invalid)
            require(await contracts.verify(raw, 'hub-origin', 'hub-executor', 'delegation-owner') is None, 'invalid offer admitted: ' + label)
            require((await jb.stream_info('LEDGER')).state.messages == before, 'invalid offer mutated owner ledger')
            passed('deny_' + label + '_before_owner_mutation')
        raw = await transfer(ca, leaf.COMMAND, commands, offer)
        verified = await contracts.verify(raw, 'hub-origin', 'hub-executor', 'delegation-owner')
        require(verified is not None, 'valid signed offer rejected')
        require(verified['payload'] == contracts.payloads['delegation-offer']['payload'], 'offer outside fixed fixture task/input grant')
        origin = {'status': 'reserved', 'acceptance': 'unknown', 'operationId': 'offer-one', 'digest': offer['operation']['payloadDigest']}
        await leaf.append(ja, origin, 0)
        receiver = {'status': 'accepted_reserved', 'offer': verified, 'executions': 0}
        await leaf.append(jb, receiver, 0)
        passed('python_signed_offer_typescript_verified_before_durable_acceptance')
        decision_payload = copy.deepcopy(contracts.payloads['delegation-decision']['payload'])
        decision_payload['decisionRecordRef']['ownerHubId'] = 'hub-executor'
        decision = await contracts.envelope('delegation-decision', 'hub-executor', 'hub-origin', 'decision-one', decision_payload)
        receiver['decision'] = decision
        await leaf.append(jb, receiver, 1)
        # Persisted decision precedes publication; no origin subscription means this acknowledgement is lost.
        await cb.publish(leaf.EVENT, leaf.encode(decision)); await cb.flush()
        require((await leaf.latest(ja))[0] == origin, 'lost signed decision changed origin')
        await a.stop()
        input_bytes = b'Approved read-only signed leaf input.\n'
        fixture = directory / 'input.txt'; fixture.write_bytes(input_bytes)
        scope = {'scope': {'project': 'one', 'action': 'read-sha256', 'resource': 'input.txt'}}
        output_digest = leaf.execute_read_only(scope, fixture)
        report_payload = copy.deepcopy(contracts.payloads['execution-report']['payload'])
        report_payload['reportRecordRef']['ownerHubId'] = 'hub-executor'
        report_payload['artifacts'] = [{'artifactId': 'fixture-input', 'ownerHubId': 'hub-executor',
            'storeRef': {'id': 'fixture-input', 'ownerHubId': 'hub-executor', 'revision': 1}, 'version': 'v1',
            'digest': 'sha256:' + output_digest, 'bytes': len(input_bytes), 'mediaType': 'text/plain'}]
        result = await contracts.envelope('execution-report', 'hub-executor', 'hub-origin', 'report-one', report_payload)
        receiver.update(status='completion_reported', executions=1, result=result)
        await leaf.append(jb, receiver, 2)
        require(fixture.read_bytes() == input_bytes, 'offline read mutated input')
        await b.stop(); await b.start()
        ob = await b.connect('owner'); jb = ob.jetstream(domain='RECEIVER')
        retained, revision = await leaf.latest(jb)
        require(retained == receiver, 'restart lost signed decision or result')
        await a.start(); oa = await a.connect('owner'); ja = oa.jetstream(domain='ORIGIN')
        require((await leaf.latest(ja))[0] == origin, 'outage released reservation')
        passed('signed_decision_loss_offline_read_and_separate_restart_recovery')
        ca, cb = await a.connect('bridge'), await b.connect('bridge')
        commands, events = await cb.subscribe(leaf.COMMAND), await ca.subscribe(leaf.EVENT)
        await cb.flush(); await ca.flush(); await leaf.link_ready(ca, commands)
        for changed in (False, True):
            replay = copy.deepcopy(offer)
            if changed:
                replay['payload']['repositoryRevision'] = 'changed-replay'
                replay = await contracts.sign(replay)
            incoming = await contracts.verify(await transfer(ca, leaf.COMMAND, commands, replay), 'hub-origin', 'hub-executor', 'delegation-owner')
            require(incoming is not None, 'signed replay failed envelope checks')
            matched = incoming['operation']['operationId'] == retained['offer']['operation']['operationId'] and incoming['operation']['payloadDigest'] == retained['offer']['operation']['payloadDigest']
            require(matched is not changed, 'durable replay identity/digest check failed')
            require((await leaf.latest(jb)) == (retained, revision), 'replay changed receiver ledger')
            if matched:
                decision_raw = await transfer(cb, leaf.EVENT, events, retained['decision'])
                admitted = await contracts.verify(decision_raw, 'hub-executor', 'hub-origin', 'task-owner')
                require(admitted and decision_matches_offer(admitted, retained['offer']), 'signed acceptance reconciliation failed')
                before_decision = await leaf.latest(ja)
                for field in ('taskId', 'delegationId', 'attemptId'):
                    mismatch = copy.deepcopy(retained['decision'])
                    mismatch['payload'][field] = 'wrong-value'
                    if field == 'delegationId':
                        mismatch['operation']['delegationRef']['id'] = 'wrong-value'
                    else:
                        mismatch['operation'][field] = 'wrong-value'
                    mismatch = await contracts.sign(mismatch)
                    raw = await transfer(cb, leaf.EVENT, events, mismatch)
                    admitted = await contracts.verify(raw, 'hub-executor', 'hub-origin', 'task-owner')
                    require(admitted is not None, 'SDK rejection masked decision owner binding check: ' + field)
                    require(not decision_matches_offer(admitted, retained['offer']), 'owner accepted mismatched decision: ' + field)
                    require(await leaf.latest(ja) == before_decision, 'mismatched decision mutated origin ledger')
                    passed('owner_rejects_signed_decision_' + field + '_mismatch_before_mutation')
        passed('signed_replay_reconciles_lost_decision_and_rejects_changed_digest_without_execution')
        rejected_result = copy.deepcopy(retained['result'])
        rejected_result['payload']['artifacts'][0]['digest'] = 'sha256:' + '0' * 64
        before_origin = await leaf.latest(ja)
        invalid_raw = await transfer(cb, leaf.EVENT, events, rejected_result)
        require(await contracts.verify(invalid_raw, 'hub-executor', 'hub-origin', 'task-owner') is None, 'tampered signed result admitted')
        require(await leaf.latest(ja) == before_origin, 'invalid result mutated origin ledger')
        passed('python_rejects_tampered_result_before_origin_mutation')
        # Each mismatch remains a valid signed envelope. Align the operation
        # context where needed so SDK admission cannot mask owner binding defects.
        for field in ('executorHubId', 'taskId', 'delegationId', 'attemptId', 'repositoryRevision'):
            mismatch = copy.deepcopy(retained['result'])
            mismatch['payload'][field] = 'wrong-value'
            if field in ('taskId', 'attemptId'):
                mismatch['operation'][field] = 'wrong-value'
            elif field == 'delegationId':
                mismatch['operation']['delegationRef']['id'] = 'wrong-value'
            mismatch = await contracts.sign(mismatch)
            raw = await transfer(cb, leaf.EVENT, events, mismatch)
            admitted = await contracts.verify(raw, 'hub-executor', 'hub-origin', 'task-owner')
            require(admitted is not None, 'SDK rejection masked owner binding check: ' + field)
            require(not result_matches_offer(admitted, retained['offer']), 'owner accepted mismatched result: ' + field)
            require(await leaf.latest(ja) == before_origin, 'mismatched result mutated origin ledger')
            passed('owner_rejects_signed_result_' + field + '_mismatch_before_mutation')
        raw = await transfer(cb, leaf.EVENT, events, retained['result'])
        admitted = await contracts.verify(raw, 'hub-executor', 'hub-origin', 'task-owner')
        require(admitted is not None, 'typescript signed result failed Python verification')
        require(result_matches_offer(admitted, retained['offer']), 'result does not match reserved offer')
        require((await leaf.latest(ja))[0]['status'] == 'reserved', 'completion event accepted task')
        artifact = admitted['payload']['artifacts'][0]
        require(artifact['digest'] == 'sha256:' + hashlib.sha256(input_bytes).hexdigest() and artifact['bytes'] == len(input_bytes), 'artifact evidence mismatch')
        origin.update(status='accepted', acceptance='accepted', resultDigest=artifact['digest'], acceptedBy='hub-origin')
        await leaf.append(ja, origin, 1)
        require((await leaf.latest(jb))[0]['status'] == 'completion_reported', 'origin rewrote receiver state')
        passed('typescript_signed_report_python_verified_then_origin_explicitly_accepts')
    finally:
        await a.stop()
        if b is not None:
            await b.stop()


async def main():
    started, before, cases = time.monotonic(), hashes(), []
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'sourceHashes': before, 'cases': cases,
        'command': 'python tests/leaf/signed_run.py', 'platform': platform.platform(), 'trustedFixtureClock': NOW,
        'limits': ['Static pre-enrolled fixture keys and scope, not production enrollment, OIDC, dynamic grants, TLS or a plugin runtime.',
                  'Real Ed25519/JCS SDK admission and NATS leaf bytes; owner policy and acceptance remain explicit fixture code.',
                  'Graceful local broker restarts with independent single-node stores, not R3 or final bilateral release acceptance.']}
    try:
        require(importlib.metadata.version('nats-py') == '2.16.0', 'unexpected NATS Python version')
        report['runtimeVersions'] = {'harnessPython': platform.python_version(), 'natsPy': importlib.metadata.version('nats-py'),
            'keyDerivationPyNaCl': importlib.metadata.version('PyNaCl'),
            'sdkPython': subprocess.check_output([PYTHON, '--version'], text=True).strip(),
            'node': subprocess.check_output([NODE, '--version'], text=True).strip()}
        report['brokerVersion'] = subprocess.check_output([str(leaf.SERVER), '--version'], text=True).strip()
        require(report['brokerVersion'].endswith('2.15.0'), 'unexpected NATS server version')
        report['brokerSha256'] = hashlib.sha256(leaf.SERVER.read_bytes()).hexdigest()
        report['sourceCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        build = build_hashes(); require(build['allSourcesMatch'] and TS.is_file(), 'TypeScript build source mismatch')
        report['typescriptBuild'] = build
        with tempfile.TemporaryDirectory(prefix='agentmux-signed-leaf-') as directory:
            root = Path(directory); mirror = root / 'inputs'
            for part in ('contracts/v1', 'sdk/python'):
                shutil.copytree(ROOT / part, mirror / part, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            copied = mirror_hashes(mirror)
            require(copied == mirror_hashes(ROOT), 'native mirror differs from repository')
            contracts = Contracts(mirror)
            report['trust'] = {'keyFingerprints': {hub: hashlib.sha256(bytes.fromhex(key)).hexdigest() for (hub, _, _), key in contracts.keys.items()},
                               'expectedAudiences': ['hub-executor/delegation-owner', 'hub-origin/task-owner']}
            await exercise(root, contracts, cases)
            require(copied == mirror_hashes(mirror) == mirror_hashes(ROOT), 'native source changed during run')
            report['sourceMirror'] = {'inputSha256': copied, 'matchesRepositoryBeforeAndAfter': True, 'unchangedDuringRun': True}
        require(before == hashes() and build == build_hashes(), 'source or compiled build changed during run')
        report.update(exitCode=0, sourceUnchangedDuringRun=True, buildUnchangedDuringRun=True, cleanupComplete=not root.exists())
    except Exception as error:
        report.update(exitCode=1, failureType=type(error).__name__)
        if isinstance(error, AssertionError):
            report['failure'] = str(error)
    report['durationSeconds'] = round(time.monotonic() - started, 3)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'exitCode': report['exitCode'], 'passedCases': len(cases), 'failure': report.get('failure', report.get('failureType'))}))
    return report['exitCode']


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
