"""Circle administration that needs a NATS connection (deploy/nats/circle.sh calls this).

  python -m hub.fed.admin provision --url U --creds admin.creds [--ca ca.pem] [--replicas N]
  python -m hub.fed.admin push --url U --creds sys.creds [--ca ca.pem] --jwt account.jwt

provision is idempotent: it creates what is missing and updates what differs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from hub.fed import conn


async def provision(url, creds, ca, replicas=1):
    nats = conn.nats_mod()
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig, DiscardPolicy
    from nats.js.errors import NotFoundError
    nc = await conn.connect(url, creds, ca, "agentmux-admin")
    js = nc.jetstream()
    made = []
    for name, (subjects, retention, max_age) in conn.STREAMS.items():
        cfg = StreamConfig(name=name, subjects=subjects,
                           retention=RetentionPolicy.WORK_QUEUE if retention == "workqueue" else RetentionPolicy.LIMITS,
                           storage=StorageType.FILE, max_age=max_age, num_replicas=replicas,
                           duplicate_window=conn.DUPE_WINDOW_S, discard=DiscardPolicy.OLD)
        try:
            await js.stream_info(name)
            await js.update_stream(cfg)
            made.append(f"stream {name} (updated)")
        except NotFoundError:
            await js.add_stream(cfg)
            made.append(f"stream {name} (created)")
    for bucket, (history, ttl) in conn.BUCKETS.items():
        try:
            await js.key_value(bucket)
            made.append(f"kv {bucket} (exists)")
        except Exception:
            from nats.js.api import KeyValueConfig
            await js.create_key_value(KeyValueConfig(bucket=bucket, history=history, ttl=ttl or None,
                                                     replicas=replicas, storage=StorageType.FILE))
            made.append(f"kv {bucket} (created)")
    await conn.close(nc)
    del nats
    return made


async def push(url, creds, ca, jwt_path):
    """What `nsc push` does: send the account JWT to $SYS.REQ.CLAIMS.UPDATE as the system
    user. Done here so TLS with our own CA works the same as for the hubs."""
    with open(jwt_path) as f:
        jwt = f.read().strip()
    nc = await conn.connect(url, creds, ca, "agentmux-admin-push")
    r = await nc.request("$SYS.REQ.CLAIMS.UPDATE", jwt.encode(), timeout=5)
    await conn.close(nc)
    data = json.loads(r.data or b"{}")
    if data.get("error"):
        raise SystemExit(f"push refused: {data['error']}")
    return data


def main(argv):
    ap = argparse.ArgumentParser(prog="hub.fed.admin")
    ap.add_argument("verb", choices=["provision", "push"])
    ap.add_argument("--url", required=True)
    ap.add_argument("--creds", required=True)
    ap.add_argument("--ca")
    ap.add_argument("--replicas", type=int, default=1)
    ap.add_argument("--jwt")
    a = ap.parse_args(argv)
    if a.verb == "provision":
        for line in asyncio.run(provision(a.url, a.creds, a.ca, a.replicas)):
            print(line)
    else:
        print(json.dumps(asyncio.run(push(a.url, a.creds, a.ca, a.jwt))))


if __name__ == "__main__":
    main(sys.argv[1:])
