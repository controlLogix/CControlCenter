"""Connecting to the federation cluster (docs/FEDERATION.md sections 3-5).

The one place that knows the stream and bucket layout, so the admin provisioner, the
runtime and the tests cannot disagree about it. nats-py is imported lazily: the core
hub stays stdlib-only and only federation needs the dependency (assumption A4).
"""
from __future__ import annotations

import os
import ssl

# name -> (subjects, retention, max_age_s). Section 5.
STREAMS = {
    "AM_MSG": (["am.msg.>"], "limits", 14 * 86400),
    "AM_WORK": (["am.work.>"], "workqueue", 30 * 86400),
    "AM_SHARE": (["am.know.>", "am.code.>"], "limits", 365 * 86400),
}
# name -> (history, ttl_s)
BUCKETS = {
    "am_board": (16, 0),
    "am_presence": (1, 90),
}
DUPE_WINDOW_S = 120


class MissingDependency(RuntimeError):
    pass


def nats_mod():
    try:
        import nats  # noqa: F401
        import nats.js.api  # noqa: F401
        return nats
    except ImportError as e:
        raise MissingDependency(
            "federation needs nats-py: run `agentmux hub fed setup` (creates .venv with hub/requirements.txt)") from e


def tls_context(ca: str | None):
    if not ca:
        return None
    ctx = ssl.create_default_context(cafile=os.path.expanduser(ca))
    return ctx


async def connect(url: str, creds: str | None, ca: str | None, name: str, reconnect=False, **cb):
    """reconnect=False for one-shot tools: nats-py otherwise retries a failing FIRST
    connect forever, which hid a TLS refusal behind a hang (2026-10-07)."""
    nats = nats_mod()
    opts = dict(servers=[url], name=name, max_reconnect_attempts=-1 if reconnect else 0, reconnect_time_wait=2,
                connect_timeout=5, allow_reconnect=reconnect, **cb)
    if creds:
        opts["user_credentials"] = os.path.expanduser(creds)
    ctx = tls_context(ca)
    if ctx is not None:
        opts["tls"] = ctx
        opts["tls_hostname"] = "localhost" if "127.0.0.1" in url or "localhost" in url else None
        if opts["tls_hostname"] is None:
            del opts["tls_hostname"]
    return await nats.connect(**opts)


async def close(nc):
    """Close, ignoring the TLS close_notify race nats-py hits on Python 3.14."""
    try:
        await nc.close()
    except Exception:  # noqa: BLE001 - a failed goodbye is not a failure
        pass
