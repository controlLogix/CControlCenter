"""Protocol names: parts, session names, addresses. See docs/PROTOCOL.md section 2.

Every part is [a-z0-9_]. The hyphen is ONLY the separator, which is what lets any
session name be split back into (repo, role, agent) without asking the registry,
and what lets every address become a NATS subject token without escaping.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PART_RE = re.compile(r"^[a-z0-9_]+$")
LIMITS = {"repo": 32, "role": 24, "agent": 32, "team": 32, "node": 32, "group": 32}


class NameError_(ValueError):
    """A name that is not a valid protocol part. Carries the suggested form."""

    def __init__(self, kind: str, given: str, suggestion: str | None):
        self.kind, self.given, self.suggestion = kind, given, suggestion
        hint = f" (suggested: {suggestion!r})" if suggestion else ""
        super().__init__(f"invalid {kind} {given!r}: parts are [a-z0-9_], hyphen is reserved{hint}")


def normalize(s: str, kind: str = "agent") -> str:
    """NFKD, drop marks, lowercase, runs of non-[a-z0-9] -> '_', trim, truncate."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[: LIMITS.get(kind, 32)].rstrip("_")


def check_part(s: str, kind: str, accept_normalized: bool = False) -> str:
    """Return s if it is already a valid part. Otherwise refuse, suggesting the
    normalized form - or return that form when the caller explicitly accepts it.
    Suggestive, never silent: a human always sees the name that will be used."""
    limit = LIMITS.get(kind, 32)
    if isinstance(s, str) and PART_RE.match(s) and len(s) <= limit:
        return s
    sug = normalize(s or "", kind) or None
    if accept_normalized and sug:
        return sug
    raise NameError_(kind, s, sug)


def session_name(repo: str, role: str, agent: str) -> str:
    return f"{check_part(repo, 'repo')}-{check_part(role, 'role')}-{check_part(agent, 'agent')}"


def split_session(name: str) -> tuple[str, str, str]:
    parts = name.split("-")
    if len(parts) != 3 or not all(PART_RE.match(p) for p in parts):
        raise ValueError(f"not a protocol session name: {name!r}")
    return parts[0], parts[1], parts[2]


@dataclass(frozen=True)
class Address:
    kind: str            # agent | role | team | virtual
    scope: str           # repo, 'group:<g>', 'team:<repo>/<team>', '*', or '' for virtual
    name: str            # agent session / role / team / virtual name

    def __str__(self) -> str:
        if self.kind == "agent":
            return f"agent:{self.name}"
        if self.kind == "virtual":
            return f"virtual:{self.name}"
        return f"{self.kind}:{self.scope}/{self.name}"


def parse_address(a: str) -> Address:
    """agent:<repo>/<role>/<agent> | agent:<session> | role:<scope>/<role> |
    team:<repo>/<team> | virtual:<name>. Scope for a role is <repo>, group:<g>,
    team:<repo>/<team>, or '*'."""
    if ":" not in a:
        raise ValueError(f"address needs a kind prefix (agent:/role:/team:/virtual:): {a!r}")
    kind, rest = a.split(":", 1)
    if kind == "agent":
        bits = rest.split("/")
        if len(bits) == 3:
            return Address("agent", "", session_name(*bits))
        split_session(rest)
        return Address("agent", "", rest)
    if kind == "virtual":
        return Address("virtual", "", check_part(rest, "agent"))
    if kind == "team":
        repo, team = rest.split("/", 1)
        return Address("team", check_part(repo, "repo"), check_part(team, "team"))
    if kind == "role":
        scope, role = rest.rsplit("/", 1)
        check_part(role, "role")
        if scope == "*":
            pass
        elif scope.startswith("group:"):
            check_part(scope[6:], "group")
        elif scope.startswith("team:"):
            r, t = scope[5:].split("/", 1)
            check_part(r, "repo"), check_part(t, "team")
        else:
            check_part(scope, "repo")
        return Address("role", scope, role)
    raise ValueError(f"unknown address kind {kind!r}")


def nats_subject(addr: Address, node: str) -> str:
    """The subject this address maps to once a NATS bridge exists (PROTOCOL.md 11)."""
    if addr.kind == "agent":
        # Node-agnostic: a sender cannot know which node hosts the recipient. Every hub
        # subscribes to am.agent.> and only the one that has the agent ingests it.
        r, ro, ag = split_session(addr.name)
        return f"am.agent.{r}.{ro}.{ag}"
    if addr.kind == "role":
        scope = addr.scope.replace("group:", "g_").replace("team:", "t_").replace("/", ".").replace("*", "all")
        return f"am.work.{scope}.{addr.name}"
    if addr.kind == "team":
        return f"am.team.{addr.scope}.{addr.name}"
    return f"am.{node}.virtual.{addr.name}"
