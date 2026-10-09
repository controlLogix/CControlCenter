"""A bounded wire-format check, not an Agentmux Python SDK."""
import asyncio
import json
import os
import nats


async def main():
    nc = await nats.connect(os.environ['AMX_SPIKE_URL'], token=os.environ['AMX_SPIKE_TOKEN'],
                            connect_timeout=2, allow_reconnect=False)
    try:
        payload = os.environ['AMX_SPIKE_PAYLOAD'].encode()
        reply = await nc.request(os.environ['AMX_SPIKE_SUBJECT'], payload, timeout=2)
        assert json.loads(reply.data) == {'request': json.loads(payload), 'server': 'python'}
        print(json.dumps({'client': 'python', 'ok': True}))
    finally:
        await nc.close()


if __name__ == '__main__':
    asyncio.run(main())
