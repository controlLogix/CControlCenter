"""Independent Python JetStream fixture client, not a production owner service."""
import asyncio
import json
import os
import sys
from urllib.parse import urlparse

import nats
from nats.js.errors import APIError, NotFoundError


async def perform(request):
    if urlparse(os.environ['AMX_STORAGE_URL']).hostname not in ('127.0.0.1', 'localhost', '::1'):
        return {'error': 'nonlocal_broker'}
    nc = await nats.connect(os.environ['AMX_STORAGE_URL'], token=os.environ['AMX_STORAGE_TOKEN'],
                            allow_reconnect=False, connect_timeout=2)
    js = nc.jetstream(timeout=3)
    try:
        op = request['op']
        if op == 'inspect':
            info = await js.stream_info(request['stream'])
            return {'messages': info.state.messages, 'lastSequence': info.state.last_seq,
                    'firstSequence': info.state.first_seq}
        if op == 'publish':
            headers = dict(request.get('headers', {}))
            headers['Nats-Expected-Last-Subject-Sequence'] = str(request['expectedSequence'])
            if request.get('msgId'):
                headers['Nats-Msg-Id'] = request['msgId']
            ack = await js.publish(request['subject'], json.dumps(request['record'], separators=(',', ':')).encode(), headers=headers)
            return {'sequence': ack.seq, 'duplicate': bool(ack.duplicate)}
        if op == 'read':
            msg = await js.get_msg(request['stream'], subject=request['subject'], direct=False)
            return {'record': json.loads(msg.data), 'sequence': msg.seq}
        if op == 'reconcile':
            info = await js.stream_info(request['stream'])
            if info.state.first_seq > 1 or info.state.num_deleted or info.state.last_seq > 10000:
                return {'error': 'history_gap'}
            # Read authoritative retained history; a last-record-only lookup loses old outcomes.
            sequence = 1
            while sequence <= info.state.last_seq:
                msg = await js.get_msg(request['stream'], seq=sequence, subject=request['subject'], next=True)
                if msg.seq > info.state.last_seq:
                    break
                record = json.loads(msg.data)
                operation = record.get('operation', {})
                if operation.get('operationId') == request['operationId']:
                    if operation.get('payloadDigest') != request['payloadDigest']:
                        return {'error': 'operation_conflict'}
                    return {'record': record, 'sequence': msg.seq, 'replayed': True}
                sequence = msg.seq + 1
            return {'error': 'not_found'}
        return {'error': 'unknown_operation'}
    finally:
        await nc.close()


async def main():
    try:
        request = json.loads(sys.stdin.readline())
        result = await perform(request)
        response = {'ok': False, **result} if 'error' in result else {'ok': True, 'result': result}
    except NotFoundError:
        response = {'ok': False, 'error': 'not_found'}
    except APIError as exc:
        response = {'ok': False, 'error': 'publish_rejected', 'apiCode': exc.err_code}
    except Exception:
        response = {'ok': False, 'error': 'client_failure'}
    print(json.dumps(response))


if __name__ == '__main__':
    asyncio.run(main())
