"""Disposable two-broker leaf transport and reservation recovery qualification."""
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import nats
from nats.js.api import StreamConfig, StorageType

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SERVER = Path(os.environ.get('AGENTMUX_LEAF_SERVER', str(Path.home() / '.cache/agentmux-governance/tools/nats-server')))
REPORT = ROOT / 'docs/planning/2026-10-09/delivery/evidence/P01/leaf-result.json'
COMMAND = 'fixture.project.one.command'
EVENT = 'fixture.project.one.event'


def require(value, message):
    if not value:
        raise AssertionError(message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def hashes():
    files = [p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py', '.md')]
    files += [ROOT / 'hub/requirements.lock']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Broker:
    def __init__(self, root, name, remote=None):
        self.root = root / name
        self.root.mkdir(mode=0o700)
        self.name, self.port, self.leafport = name, port(), port()
        self.users = {key: secrets.token_hex(32) for key in ('owner', 'bridge', 'outsider', 'leaf', 'probe')}
        self.process = self.log = None
        self.clients = []
        self.errors = []
        pub, sub = (COMMAND, EVENT) if remote is None else (EVENT, COMMAND)
        account = name + '_LINK'
        accounts = {
            name + '_OWNER': {'jetstream': 'enabled', 'users': [{'user': 'owner', 'password': self.users['owner']}]},
            name + '_OTHER': {'users': [{'user': 'outsider', 'password': self.users['outsider']}]},
            account: {'users': [
                {'user': 'bridge', 'password': self.users['bridge'], 'permissions': {'publish': [pub], 'subscribe': [sub]}},
                # Test-only unrestricted local probe distinguishes leaf filtering
                # from the ordinary bridge client's own subject restrictions.
                {'user': 'probe', 'password': self.users['probe']},
                {'user': 'leaf', 'password': self.users['leaf'], 'permissions': {'publish': [EVENT], 'subscribe': [COMMAND]}}
            ]}
        }
        leaf = {'listen': f'127.0.0.1:{self.leafport}'} if remote is None else {
            'reconnect': 1, 'remotes': [{'url': f'nats-leaf://leaf:{remote.users["leaf"]}@127.0.0.1:{remote.leafport}',
                                      'account': account}]}
        config = {'server_name': name, 'host': '127.0.0.1', 'port': self.port,
                  'jetstream': {'domain': name, 'store_dir': str(self.root / 'store')},
                  'accounts': accounts, 'leafnodes': leaf}
        self.config = self.root / 'server.conf'
        self.config.write_text(json.dumps(config), encoding='utf-8')
        self.config.chmod(0o600)

    async def start(self):
        self.log = (self.root / 'server.log').open('ab')
        self.process = subprocess.Popen([str(SERVER), '-c', str(self.config)], stdout=self.log, stderr=self.log)
        for _ in range(150):
            require(self.process.poll() is None, 'broker failed readiness; private local diagnostics retained only during run')
            try:
                reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
                ready = await asyncio.wait_for(reader.readline(), 1)
                writer.close()
                await writer.wait_closed()
                if ready.startswith(b'INFO '):
                    return
            except (OSError, TimeoutError):
                pass
            await asyncio.sleep(.02)
        raise AssertionError('broker readiness timeout')

    async def connect(self, user):
        async def error(err):
            # Keep only a classified code; raw transport errors can contain secrets.
            self.errors.append('permission_denied' if 'permissions violation' in str(err).lower() else type(err).__name__)
        client = await nats.connect(f'nats://127.0.0.1:{self.port}', user=user, password=self.users[user],
                                    allow_reconnect=False, connect_timeout=2, error_cb=error)
        self.clients.append(client)
        return client

    async def stop(self):
        for client in self.clients:
            await client.close()
        self.clients.clear()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()


async def append(js, value, previous):
    ack = await js.publish('private.task.one', encode(value), headers={'Nats-Expected-Last-Subject-Sequence': str(previous)})
    return ack.seq


async def latest(js):
    msg = await js.get_last_msg('LEDGER', 'private.task.one')
    return json.loads(msg.data), msg.seq


async def exchange(sender, subject, subscription, value):
    # Retrying a read-only transport probe deals with leaf interest propagation.
    # Business offers are sent once after this probe establishes the link.
    await sender.publish(subject, encode(value))
    await sender.flush()
    return json.loads((await subscription.next_msg(timeout=3)).data)


async def link_ready(sender, subscription):
    for _ in range(30):
        await sender.publish(COMMAND, encode({'probe': True}))
        await sender.flush()
        try:
            require(json.loads((await subscription.next_msg(timeout=.15)).data) == {'probe': True}, 'unexpected probe')
            return
        except nats.errors.TimeoutError:
            await asyncio.sleep(.05)
    raise AssertionError('scoped leaf failed to connect')


async def forbidden(broker, client, subject, subscribe=False):
    before = len(broker.errors)
    if subscribe:
        subscription = await client.subscribe(subject)
    else:
        await client.publish(subject, b'forbidden')
    await client.flush()
    for _ in range(30):
        if len(broker.errors) > before:
            break
        await asyncio.sleep(.01)
    require('permission_denied' in broker.errors[before:], 'broker failed to report permission denial')
    if subscribe:
        await subscription.unsubscribe()


def execute_read_only(offer, fixture):
    require(offer['scope'] == {'project': 'one', 'action': 'read-sha256', 'resource': 'input.txt'}, 'offline operation outside granted scope')
    return hashlib.sha256(fixture.read_bytes()).hexdigest()


async def exercise(directory, cases):
    a = Broker(directory, 'ORIGIN')
    b = Broker(directory, 'RECEIVER', a)
    def passed(name, **details):
        cases.append({'name': name, 'status': 'passed', **details})
    try:
        await a.start(); await b.start()
        owner_a, owner_b = await a.connect('owner'), await b.connect('owner')
        ja, jb = owner_a.jetstream(domain='ORIGIN'), owner_b.jetstream(domain='RECEIVER')
        for js in (ja, jb):
            await js.add_stream(config=StreamConfig(name='LEDGER', subjects=['private.task.one'], storage=StorageType.FILE))
        ca, cb = await a.connect('bridge'), await b.connect('bridge')
        commands = await cb.subscribe(COMMAND)
        await cb.flush()
        await link_ready(ca, commands)
        passed('authenticated_leaf_transfers_scoped_command')
        probe_a, probe_b = await a.connect('probe'), await b.connect('probe')
        blocked_event = await probe_a.subscribe('fixture.project.other.event')
        allowed_event = await probe_a.subscribe(EVENT)
        blocked_command = await probe_b.subscribe('fixture.project.other.command')
        await probe_a.flush(); await probe_b.flush()
        # The local probe may publish these subjects, but the leaf credentials may not carry them.
        await probe_b.publish('fixture.project.other.event', b'not-exportable')
        await probe_a.publish('fixture.project.other.command', b'not-importable')
        await probe_b.flush(); await probe_a.flush()
        require(await exchange(cb, EVENT, allowed_event, {'control': True}) == {'control': True}, 'event direction control failed')
        for denied in (blocked_event, blocked_command):
            try:
                await denied.next_msg(timeout=.25)
            except nats.errors.TimeoutError:
                pass
            else:
                raise AssertionError('leaf credentials carried unrelated subject')
        await probe_a.close(); await probe_b.close()
        passed('leaf_credentials_filter_both_directions_independently_of_client_permissions')
        await forbidden(b, cb, 'fixture.project.other.command')
        await forbidden(b, cb, 'private.task.one')
        await forbidden(b, cb, '$JS.ORIGIN.API.STREAM.INFO.LEDGER')
        await forbidden(b, cb, 'fixture.origin.accept')
        await forbidden(b, cb, 'private.>', subscribe=True)
        passed('receiver_bridge_cannot_publish_outside_scope_or_access_owner_storage')
        outsider = await b.connect('outsider')
        hidden = await outsider.subscribe(COMMAND)
        await outsider.flush()
        require(await exchange(ca, COMMAND, commands, {'visible': True}) == {'visible': True}, 'positive control failed')
        try:
            await hidden.next_msg(timeout=.25)
        except nats.errors.TimeoutError:
            pass
        else:
            raise AssertionError('unrelated account received linked command')
        passed('unrelated_account_isolated_with_positive_delivery_control')
        fixture = directory / 'input.txt'
        fixture.write_bytes(b'Non-destructive Agentmux leaf fixture.\n')
        original = fixture.read_bytes()
        offer = {'operationId': 'offer-one', 'reservationId': 'reservation-one', 'taskId': 'task-one',
                 'originHubId': 'ORIGIN', 'executorHubId': 'RECEIVER',
                 'scope': {'project': 'one', 'action': 'read-sha256', 'resource': 'input.txt'}}
        offer_digest = digest(offer)
        origin = {'status': 'reserved', 'acceptance': 'unknown', 'offer': offer, 'digest': offer_digest}
        await append(ja, origin, 0)
        received = await exchange(ca, COMMAND, commands, offer)
        require(received == offer, 'offer changed in transit')
        receiver = {'status': 'accepted', 'offer': received, 'digest': digest(received), 'executions': 0, 'result': None}
        await append(jb, receiver, 0)
        # No origin event subscription: the actual acceptance event is lost.
        await cb.publish(EVENT, encode({'status': 'accepted', 'operationId': offer['operationId'], 'digest': offer_digest}))
        await cb.flush()
        require((await latest(ja))[0]['acceptance'] == 'unknown', 'lost acknowledgement became acceptance')
        passed('receiver_acceptance_durable_before_lost_ack_origin_remains_unknown')
        await a.stop()
        require(a.process.poll() is not None and b.process.poll() is None, 'broker outage not established')
        saved, revision = await latest(jb)
        require(saved['status'] == 'accepted', 'receiver reservation lost')
        for field, bad in [('action', 'write'), ('project', 'other'), ('resource', '../outside')]:
            changed = json.loads(json.dumps(offer)); changed['scope'][field] = bad
            try:
                execute_read_only(changed, fixture)
            except AssertionError:
                pass
            else:
                raise AssertionError('offline scope guard accepted unauthorized operation')
        saved.update(status='completion_reported', executions=1, result=execute_read_only(offer, fixture))
        await append(jb, saved, revision)
        require(fixture.read_bytes() == original, 'fixture input changed')
        passed('offline_receiver_retains_reservation_and_completes_only_read_only_scope')
        await b.stop(); await b.start()
        owner_b = await b.connect('owner'); jb = owner_b.jetstream(domain='RECEIVER')
        retained, _ = await latest(jb)
        require(retained == saved, 'receiver restart lost retained result')
        passed('receiver_restart_retains_independent_ledger_and_result')
        await a.start()
        owner_a = await a.connect('owner'); ja = owner_a.jetstream(domain='ORIGIN')
        recovered, origin_revision = await latest(ja)
        require(recovered == origin, 'origin reservation changed during disconnection')
        require(recovered != retained, 'independent ledgers unexpectedly shared')
        passed('origin_restart_retains_reservation_and_ledgers_are_distinct')
        ca, cb = await a.connect('bridge'), await b.connect('bridge')
        commands, events = await cb.subscribe(COMMAND), await ca.subscribe(EVENT)
        await cb.flush(); await ca.flush()
        await link_ready(ca, commands)
        for requested_digest, expected in [(offer_digest, 'accepted'), ('0' * 64, 'digest_conflict'), (offer_digest, 'accepted')]:
            query = {'operationId': offer['operationId'], 'digest': requested_digest}
            incoming = await exchange(ca, COMMAND, commands, query)
            authoritative, _ = await latest(jb)
            require(incoming['operationId'] == authoritative['offer']['operationId'], 'lookup identity mismatch')
            answer = {'status': 'accepted' if incoming['digest'] == authoritative['digest'] else 'digest_conflict',
                      'operationId': incoming['operationId'], 'digest': incoming['digest']}
            observed = await exchange(cb, EVENT, events, answer)
            require(observed['status'] == expected, 'acceptance reconciliation failed')
        require((await latest(jb))[0]['executions'] == 1, 'reconciliation executed duplicate work')
        passed('leaf_reconciliation_resolves_lost_acceptance_and_rejects_changed_digest_without_reexecution')
        # Retrying the original offer is distinct from a status lookup. Compare
        # actual offer bytes, not a caller-supplied digest, before returning history.
        for offered, expected in [(offer, 'accepted'), ({**offer, 'executorHubId': 'another-hub'}, 'digest_conflict')]:
            incoming = await exchange(ca, COMMAND, commands, offered)
            authoritative, old_revision = await latest(jb)
            answer = {'status': 'accepted' if digest(incoming) == authoritative['digest'] else 'digest_conflict'}
            observed = await exchange(cb, EVENT, events, answer)
            require(observed['status'] == expected, 'offer replay binding failed')
            require((await latest(jb)) == (authoritative, old_revision), 'replayed offer changed durable execution')
        passed('actual_offer_replay_recomputes_digest_and_preserves_single_execution')
        result = await exchange(cb, EVENT, events, {'status': 'completion_reported', 'operationId': offer['operationId'],
                                                   'digest': retained['digest'], 'result': retained['result']})
        require((await latest(ja))[0]['status'] == 'reserved', 'receiver completion accepted origin task')
        require(result['digest'] == offer_digest and result['result'] == hashlib.sha256(original).hexdigest(), 'result evidence mismatch')
        recovered.update(status='accepted', acceptance='accepted', result=result['result'], acceptedBy='ORIGIN')
        await append(ja, recovered, origin_revision)
        require((await latest(jb))[0]['status'] == 'completion_reported', 'origin acceptance rewrote receiver ledger')
        require((await latest(ja))[0]['acceptedBy'] == 'ORIGIN', 'origin acceptance missing')
        passed('retained_result_crosses_reconnected_leaf_and_only_origin_owner_accepts')
        require(fixture.read_bytes() == original, 'input changed after recovery')
        return {'domains': ['ORIGIN', 'RECEIVER'], 'executions': 1, 'inputUnchanged': True,
                'originState': 'accepted', 'receiverState': 'completion_reported'}
    finally:
        await a.stop(); await b.stop()


async def main():
    before, cases, started = hashes(), [], time.monotonic()
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'sourceHashes': before, 'cases': cases,
              'command': 'python tests/leaf/run.py', 'environment': {'platform': platform.platform(), 'python': platform.python_version()},
              'limitations': ['Local WSL loopback fixture; not production federation, TLS, enrollment, OIDC, dynamic grants or final bilateral release proof.',
                              'A narrow fixture protocol models reservation and acceptance; no production SDK, ingress signature or full contract compatibility is claimed.',
                              'Single-node independent stores and graceful process restarts; no R3, power-loss, network adversary or host-failure durability claim.',
                              'Static broker account permissions are real; offline scope checks and origin acceptance are explicit fixture logic.']}
    try:
        require(SERVER.is_file(), 'required nats-server missing; no skips')
        version = subprocess.check_output([str(SERVER), '--version'], text=True).strip()
        require(version.endswith('2.15.0'), 'unexpected broker version')
        require(importlib.metadata.version('nats-py') == '2.16.0', 'unexpected nats-py version')
        report.update(sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      sourceBinding='Checkout base commit plus exact fixture and dependency-lock hashes; no legacy application import.',
                      brokerVersion=version, brokerSha256=hashlib.sha256(SERVER.read_bytes()).hexdigest(), natsPyVersion='2.16.0')
        with tempfile.TemporaryDirectory(prefix='agentmux-leaf-') as directory:
            report['outcome'] = await exercise(Path(directory), cases)
        report['cleanupComplete'] = not Path(directory).exists()
        require(before == hashes(), 'fixture source changed during run')
        report.update(exitCode=0, sourceUnchangedDuringRun=True)
    except Exception as exc:
        report.update(exitCode=1, failureType=type(exc).__name__)
        # Assertion messages are fixture constants; broker exceptions may carry credentials.
        if isinstance(exc, AssertionError):
            report['failure'] = str(exc)
    report['durationSeconds'] = round(time.monotonic() - started, 3)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'exitCode': report['exitCode'], 'passedCases': len(cases), 'failure': report.get('failure', report.get('failureType'))}))
    return report['exitCode']


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
