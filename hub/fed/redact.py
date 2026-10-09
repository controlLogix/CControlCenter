"""Outbound secret filter (docs/FEDERATION.md 7.1, assumption A12).

scrub(payload) walks every string in a JSON-able payload. BLOCK patterns refuse the
whole publish (a private key or an nkey seed in a message is never intended); REDACT
patterns are replaced in place by [REDACTED:<kind>]. The caller gets the list of kinds
found, never the values - that list is what goes into the audit log.
"""
from __future__ import annotations

import re

BLOCK = [
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("nkey_seed", re.compile(r"\bS[UAONCX][A-Z2-7]{56}\b")),
    ("nats_creds", re.compile(r"-----BEGIN NATS USER JWT-----")),
]

REDACT = [
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("azure_conn", re.compile(r"(?i)\b(?:AccountKey|SharedAccessKey)=[A-Za-z0-9+/=]{20,}")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}")),
    # KEY=value / key: value where the key names a secret. Keeps the key, drops the value.
    ("assignment", re.compile(
        r"(?im)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CLIENT_SECRET)[A-Z0-9_]*)"
        r"(\s*[=:]\s*)(['\"]?)([^\s'\"]{6,})\3")),
]


class Blocked(Exception):
    def __init__(self, kinds):
        super().__init__("refused to publish: payload contains " + ", ".join(sorted(set(kinds))))
        self.kinds = kinds


def scrub_text(s: str, found: list) -> str:
    for kind, rx in BLOCK:
        if rx.search(s):
            raise Blocked([kind])
    for kind, rx in REDACT:
        if kind == "assignment":
            def sub(m):
                found.append(kind)
                return f"{m.group(1)}{m.group(2)}[REDACTED:{kind}]"
            s = rx.sub(sub, s)
        else:
            n = len(rx.findall(s))
            if n:
                found.extend([kind] * n)
                s = rx.sub(f"[REDACTED:{kind}]", s)
    return s


def scrub(obj, found=None):
    """Returns (clean_copy, kinds_found). Raises Blocked."""
    if found is None:
        found = []
    if isinstance(obj, str):
        return scrub_text(obj, found), found
    if isinstance(obj, dict):
        return {k: scrub(v, found)[0] for k, v in obj.items()}, found
    if isinstance(obj, list):
        return [scrub(v, found)[0] for v in obj], found
    return obj, found
