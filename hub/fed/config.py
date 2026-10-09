"""federation.toml: connection, opt-in repos and per-peer trust (docs/FEDERATION.md section 6).

Read with tomllib; written back by the `fed share|unshare|trust` verbs with a small
writer that only has to handle this file's shape (tables of scalars and string lists).
"""
from __future__ import annotations

import json
import os
import tomllib

TRUST_LEVELS = ("auto", "flag", "approve", "deny")
DEFAULT_PLUGINS = ["messages", "work", "board", "knowledge", "code"]
DEFAULTS = {
    "enabled": False, "url": "", "creds": "", "ca": "", "peer": "", "plugins": DEFAULT_PLUGINS,
    "capture": True, "notify_findings": True, "code_remote": "origin", "primary": True,
    "presence_every_s": 20,
}


def path_for(hubdir: str) -> str:
    return os.path.join(hubdir, "federation.toml")


def load(hubdir: str) -> dict:
    p = path_for(hubdir)
    try:
        with open(p, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raw = {}
    fed = {**DEFAULTS, **raw.get("federation", {})}
    return {"federation": fed, "repos": dict(raw.get("repos", {})), "peers": dict(raw.get("peers", {}))}


def _val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    return json.dumps(str(v))


def _key(k):
    return k if k.replace("_", "").isalnum() else json.dumps(k)


def dump(cfg: dict) -> str:
    out = ["# agentmux federation - docs/FEDERATION.md section 6. Edited by `agentmux hub fed share|trust`.", "",
           "[federation]"]
    for k, v in cfg["federation"].items():
        if k in DEFAULTS and DEFAULTS[k] == v and k not in ("enabled", "url", "creds", "ca", "peer"):
            continue
        out.append(f"{k} = {_val(v)}")
    for section in ("repos", "peers"):
        for name, table in sorted(cfg.get(section, {}).items()):
            out += ["", f"[{section}.{_key(name)}]"]
            for k, v in table.items():
                out.append(f"{k} = {_val(v)}")
    return "\n".join(out) + "\n"


def save(hubdir: str, cfg: dict):
    p = path_for(hubdir)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(dump(cfg))
    os.replace(tmp, p)
