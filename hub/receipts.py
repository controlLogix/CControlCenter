"""Receipts from each CLI's own session log (TM-213, R-QUEUE-1, failure class C15).

"Submitted" means the doorbell left the input box. It does not mean the model saw it:
grok holds submitted input in an internal queue (median 502 s, p95 1500 s from courier
`sent` to user turn in the 2026-09 analysis, one hold of 25 minutes). The only proof a
CLI received a line is that line appearing as a user turn in the CLI's own log.

Every doorbell names its recipient ("... for calc-worker-codex_2303 ..."), so matching
needs no heuristics: a user turn containing "[hub]" and a session name IS the receipt
for that session's most recent bell.

The scanner tails files incrementally (by inode + offset), and starts every file that
already exists at EOF - history is not re-read, only what arrives while the hub runs.
Formats, as established by analysis/comms-2026-09/extract_receipts.py:
  codex   <CODEX_HOME>/sessions/**/rollout-*.jsonl  event_msg / item_completed / UserMessage
  claude  <config>/projects/*/*.jsonl               type=user message.content, or attachment queued_command
  grok    ~/.grok/sessions/*/*/updates.jsonl        params.update.sessionUpdate = user_message_chunk
"""
from __future__ import annotations

import glob
import json
import os
import re

BELL_RE = re.compile(r"\[hub\].*?\bfor ([a-z0-9_]+-[a-z0-9_]+-[a-z0-9_]+)\b")


def default_roots(home=None):
    home = home or os.path.expanduser("~")
    ammux = os.environ.get("AGENTMUX_HOME") or os.path.join(home, ".agentmux")
    codex = os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
    return {
        "codex": [os.path.join(codex, "sessions", "**", "*.jsonl")],
        "claude": [os.path.join(ammux, "claude-config", "*", "projects", "*", "*.jsonl"),
                   os.path.join(home, ".claude-wsl", "projects", "*", "*.jsonl")],
        "grok": [os.path.join(home, ".grok", "sessions", "*", "*", "updates.jsonl")],
    }


def _texts(content):
    if isinstance(content, str):
        return [content]
    out = []
    for c in content or []:
        if isinstance(c, dict) and isinstance(c.get("text"), str):
            out.append(c["text"])
    return out


def user_texts(cli, obj):
    """The user-turn text(s) in one parsed log line, or []."""
    if cli == "codex":
        p = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        if obj.get("type") == "event_msg" and p.get("type") == "item_completed":
            item = p.get("item") or {}
            if item.get("type") == "UserMessage":
                return _texts(item.get("content"))
        if obj.get("type") == "event_msg" and p.get("type") == "user_message":
            return _texts(p.get("message"))
        if obj.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
            return _texts(p.get("content"))
        return []
    if cli == "claude":
        if obj.get("isSidechain"):
            return []
        if obj.get("type") == "user":
            return _texts((obj.get("message") or {}).get("content"))
        if obj.get("type") == "attachment":
            a = obj.get("attachment") or {}
            if a.get("type") == "queued_command":
                return _texts(a.get("prompt"))
        return []
    if cli == "grok":
        u = ((obj.get("params") or {}).get("update")) or {}
        if u.get("sessionUpdate") == "user_message_chunk":
            c = u.get("content") or {}
            return [c["text"]] if isinstance(c, dict) and isinstance(c.get("text"), str) else []
        return []
    return []


class ReceiptScanner:
    def __init__(self, roots=None):
        self.roots = roots or default_roots()
        self.pos: dict[str, tuple[int, int]] = {}
        self.carry: dict[str, str] = {}      # grok chunks can split a bell line
        self.primed = False

    def _files(self):
        for cli, pats in self.roots.items():
            for pat in pats:
                for f in glob.glob(pat, recursive=True):
                    yield cli, f

    def prime(self):
        """Start every existing file at EOF: only what arrives from now on is a receipt."""
        for _cli, f in self._files():
            try:
                st = os.stat(f)
                self.pos[f] = (st.st_ino, st.st_size)
            except OSError:
                pass
        self.primed = True

    def scan(self):
        """[(session, cli, ref)] for every bell user-turn appended since the last scan."""
        if not self.primed:
            self.prime()
            return []
        out = []
        for cli, f in self._files():
            try:
                st = os.stat(f)
            except OSError:
                continue
            ino, off = self.pos.get(f, (st.st_ino, 0))
            if ino != st.st_ino or st.st_size < off:
                off = 0                                   # replaced or truncated: reread
            if st.st_size == off:
                self.pos[f] = (st.st_ino, off)
                continue
            try:
                with open(f, "rb") as fh:
                    fh.seek(off)
                    data = fh.read()
            except OSError:
                continue
            nl = data.rfind(b"\n")
            if nl < 0:
                continue                                  # partial line: wait for the rest
            chunk, off = data[:nl + 1], off + nl + 1
            self.pos[f] = (st.st_ino, off)
            for i, line in enumerate(chunk.splitlines()):
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for t in user_texts(cli, obj):
                    if cli == "grok":
                        t = self.carry.get(f, "") + t
                        self.carry[f] = t[-400:]
                    for m in BELL_RE.finditer(t):
                        out.append((m.group(1), cli, f"{f}@{off}"))
                        if cli == "grok":
                            self.carry[f] = ""
        return out
