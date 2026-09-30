"""NATS bridge: hub <-> hub over NATS (TM-218, docs/PROTOCOL.md section 11).

Stdlib only - a minimal client for the core NATS text protocol (INFO, CONNECT, SUB,
UNSUB, PUB, MSG, PING/PONG). No JetStream: the delivery guarantee stays with the hubs
themselves (at-least-once + idempotent ingest), and NATS carries three flows:

  am.agent.<repo>.<role>.<agent>   a direct message for an agent on some other hub.
                                   Every hub subscribes to am.agent.>; only the one
                                   that has the agent ingests it (idem key nats:<id>).
  am.work.<scope>.<role>           a federated role item. Each hub subscribes ONLY for
                                   the role subjects its live agents can serve, in a
                                   queue group named after the subject - NATS gives
                                   each message to exactly one member of a queue
                                   group, which makes "first claim wins" hold across
                                   nodes: one hub gets the item, then one local agent
                                   claims it.
  am.result.<node>                 a finished federated item, back to its origin hub.

Everything published comes from nats_outbox, written in the same transaction as the
state change it announces; a row is marked sent only after the PUB is flushed.
"""
from __future__ import annotations

import asyncio
import json
import time

from . import names


class NatsClient:
    def __init__(self, url: str, name: str):
        hp = url.split("://", 1)[-1]
        self.host, _, port = hp.rpartition(":")
        self.port = int(port or 4222)
        self.name = name
        self.reader = self.writer = None
        self.sids: dict[int, tuple[str, str | None]] = {}
        self._next_sid = 1
        self.handlers = {}

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host or "127.0.0.1", self.port)
        info = await self.reader.readline()
        if not info.startswith(b"INFO"):
            raise ConnectionError(f"not a NATS server: {info[:60]!r}")
        opts = {"verbose": False, "pedantic": False, "name": self.name, "lang": "python-stdlib", "version": "1"}
        self.writer.write(f"CONNECT {json.dumps(opts)}\r\nPING\r\n".encode())
        await self.writer.drain()
        # re-establish subscriptions after a reconnect
        for sid, (subj, queue) in list(self.sids.items()):
            self._send_sub(sid, subj, queue)
        await self.writer.drain()

    def _send_sub(self, sid, subj, queue):
        self.writer.write(f"SUB {subj} {queue + ' ' if queue else ''}{sid}\r\n".encode())

    async def sub(self, subject, handler, queue=None):
        sid = self._next_sid
        self._next_sid += 1
        self.sids[sid] = (subject, queue)
        self.handlers[sid] = handler
        self._send_sub(sid, subject, queue)
        await self.writer.drain()
        return sid

    async def unsub(self, sid):
        self.sids.pop(sid, None)
        self.handlers.pop(sid, None)
        self.writer.write(f"UNSUB {sid}\r\n".encode())
        await self.writer.drain()

    async def pub(self, subject, payload: bytes):
        self.writer.write(f"PUB {subject} {len(payload)}\r\n".encode() + payload + b"\r\n")

    async def flush(self):
        await self.writer.drain()

    async def read_loop(self):
        while True:
            line = await self.reader.readline()
            if not line:
                raise ConnectionError("NATS connection closed")
            if line.startswith(b"MSG "):
                parts = line.decode().split()
                subj, sid, size = parts[1], int(parts[2]), int(parts[-1])
                data = await self.reader.readexactly(size + 2)
                h = self.handlers.get(sid)
                if h:
                    await h(subj, data[:-2])
            elif line.startswith(b"PING"):
                self.writer.write(b"PONG\r\n")
                await self.writer.drain()
            elif line.startswith(b"-ERR"):
                raise ConnectionError(line.decode().strip())

    def close(self):
        if self.writer:
            self.writer.close()


class Bridge:
    """Runs inside the hub. `hub` provides .store, .db(), .cfg, .stop and log()."""

    def __init__(self, hub, url, node, log):
        self.hub, self.url, self.node, self.log = hub, url, node, log
        self.nc = None
        self.role_subs: dict[str, int] = {}
        self.connected = False
        self.stats = {"published": 0, "ingested_messages": 0, "ingested_work": 0, "results": 0}

    async def run(self):
        backoff = 1
        while not self.hub.stop.is_set():
            self.nc = NatsClient(self.url, f"agentmux-hub-{self.node}")
            self.role_subs = {}
            try:
                await self.nc.connect()
                await self.nc.sub("am.agent.>", self.on_agent)
                await self.nc.sub(f"am.result.{self.node}", self.on_result)
                self.connected, backoff = True, 1
                self.log("nats connected", self.url, "node", self.node)
                reader = asyncio.create_task(self.nc.read_loop())
                while not self.hub.stop.is_set() and not reader.done():
                    await self.sync_role_subs()
                    await self.drain_outbox()
                    await asyncio.sleep(0.5)
                if reader.done():
                    reader.result()                # surface the connection error
                reader.cancel()
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as e:
                self.log("nats unavailable:", type(e).__name__, e, f"- retrying in {backoff}s")
            finally:
                self.connected = False
                self.nc.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def drain_outbox(self):
        rows = await self.hub.db(self.hub.store.outbox_pending)
        if not rows:
            return
        for r in rows:
            await self.nc.pub(r["subject"], r["payload"].encode())
        await self.nc.flush()
        await self.hub.db(self.hub.store.outbox_sent, [r["seq"] for r in rows])
        self.stats["published"] += len(rows)

    async def sync_role_subs(self):
        """Queue-subscribe to exactly the role subjects our live agents can serve."""
        want = set()
        for ag in await self.hub.db(self.hub.store.agents, True):
            for t in await self.hub.db(self.hub.store.eligible_targets, ag["session"]):
                if t.startswith("role:"):
                    want.add(names.nats_subject(names.parse_address(t), self.node))
        for subj in want - set(self.role_subs):
            self.role_subs[subj] = await self.nc.sub(subj, self.on_work, queue=subj.replace(".", "_"))
        for subj in set(self.role_subs) - want:
            await self.nc.unsub(self.role_subs.pop(subj))

    async def on_agent(self, subj, data):
        env = _load(data)
        if env and env.get("origin") != self.node:
            r = await self.hub.db(self.hub.store.ingest_message, env)
            if r and not r.get("duplicate"):
                self.stats["ingested_messages"] += 1

    async def on_work(self, subj, data):
        env = _load(data)
        if env:
            try:
                w = await self.hub.db(self.hub.store.ingest_work, env)
                self.stats["ingested_work"] += 1
                self.log("federated work", env.get("origin"), "->", w["id"])
            except Exception as e:
                self.log("federated work refused:", e)

    async def on_result(self, subj, data):
        env = _load(data)
        w = await self.hub.db(self.hub.store.ingest_result, env) if env else None
        if w:
            self.stats["results"] += 1
            await self.hub._notify_work_owner(w, f"nats:{env.get('node')}:{env.get('by')}")


def _load(data):
    try:
        return json.loads(data)
    except ValueError:
        return None
