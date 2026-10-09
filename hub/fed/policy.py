"""Who we share with, and how much we trust what comes back (docs/FEDERATION.md 6).

Repo identity (F6): rid = "r" + sha256(normalized origin URL)[:12]. Two people who
call the same repo `falcon` and `falcon_fork` compute the same rid, so addresses and
board keys line up without anyone agreeing on a local name.
"""
from __future__ import annotations

import hashlib

from hub import names
from hub.fed.config import TRUST_LEVELS

PRIVILEGED_CAPS = {"privileged", "plc_write", "codesys_runtime", "profinet", "pcm_write"}


def normalize_remote(url: str) -> str:
    """Same rule as hub/server.py normalize_remote (repo_add stores this form as an alias)."""
    u = url.strip()
    for pre in ("https://", "http://", "ssh://", "git://", "file://"):
        if u.startswith(pre):
            u = u[len(pre):]
    u = u.split("@", 1)[-1].replace(":", "/").rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.rstrip("/").lower()


def rid_for_remote(remote: str) -> str:
    return "r" + hashlib.sha256(normalize_remote(remote).encode()).hexdigest()[:12]


class Policy:
    def __init__(self, cfg: dict, remotes: dict[str, str]):
        """cfg: config.load(); remotes: local repo -> normalized remote (from repo_aliases)."""
        self.cfg = cfg
        self.me = cfg["federation"].get("peer", "")
        self._rid: dict[str, str] = {}
        self._local: dict[str, str] = {}
        for repo, table in cfg.get("repos", {}).items():
            remote = table.get("remote") or remotes.get(repo)
            if not remote:
                continue            # opted in but no remote: cannot be matched (reported by `fed status`)
            rid = rid_for_remote(remote)
            self._rid[repo] = rid
            self._local[rid] = repo

    # -- repos ------------------------------------------------------------------------
    def shared(self) -> dict[str, str]:
        return dict(self._rid)

    def unmatched(self) -> list[str]:
        return [r for r in self.cfg.get("repos", {}) if r not in self._rid]

    def rid_of(self, repo: str) -> str | None:
        return self._rid.get(repo)

    def local_of(self, rid: str) -> str | None:
        return self._local.get(rid)

    def repo_peers(self, repo: str) -> list[str]:
        return list(self.cfg["repos"].get(repo, {}).get("peers", ["*"]))

    def may_send(self, repo: str, peer: str) -> bool:
        """Scope filter: is this repo shared with this peer ('*' = the whole circle)?"""
        if repo not in self._rid:
            return False
        ps = self.repo_peers(repo)
        return "*" in ps or peer in ps

    def may_receive(self, rid: str, peer: str) -> bool:
        repo = self._local.get(rid)
        return bool(repo) and self.may_send(repo, peer)

    def board_prefix(self, repo: str) -> str:
        return str(self.cfg["repos"].get(repo, {}).get("board_prefix", "SH")).upper()

    # -- peers ------------------------------------------------------------------------
    def trust(self, peer: str) -> str:
        peers = self.cfg.get("peers", {})
        t = (peers.get(peer) or peers.get("*") or {}).get("trust", "approve")
        return t if t in TRUST_LEVELS else "approve"

    def known_peer(self, peer: str) -> bool:
        try:
            names.check_part(peer, "peer")
        except Exception:
            return False
        return True
