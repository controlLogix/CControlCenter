"""The capability plugin contract (FEDERATION.md 9.1).

A plugin owns: envelope types it receives (`handles`), its own tables (`tables`, names
must start with p_<name>_), verbs (which become CLI verbs, hub-socket verbs and MCP
tools from one definition), and a dashboard panel. It never touches the connection:
it publishes through ctx.publish / ctx.stage, which run the guard pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class Param:
    type: str = "string"            # string | integer | boolean | array
    required: bool = False
    help: str = ""
    positional: bool = False        # CLI: taken from the bare words after the verb


@dataclass
class Verb:
    fn: Callable[..., Awaitable[Any]]   # async fn(ctx, args: dict, caller: str)
    help: str
    params: dict[str, Param] = field(default_factory=dict)
    operator_only: bool = False


class Plugin:
    name = ""
    handles: tuple[str, ...] = ()       # envelope types routed to on_envelope
    tables: list[str] = []

    async def start(self, ctx):
        pass

    async def on_connect(self, ctx):
        """Each (re)connect: bind consumers, start watchers."""

    async def on_tick(self, ctx):
        pass

    async def on_envelope(self, ctx, env, decision):
        pass

    async def on_local_event(self, ctx, kind, data):
        pass

    async def on_revoke(self, ctx, peer):
        """Another peer pulled its kill switch with --revoke."""

    def verbs(self) -> dict[str, Verb]:
        return {}

    def panel(self, ctx) -> dict | None:
        """Called on the db thread. {"title", "columns", "rows", "actions": [{"verb", "label", "arg"}]}"""
        return None
