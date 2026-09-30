"""Terminal transports. See docs/TRANSPORT.md.

A Transport moves bytes to and from a terminal and reports what state the terminal
itself is in (normal, copy-mode, dead). It knows nothing about any agent CLI - that is
profiles.py - and nothing about messages - that is deliver.py.

Only TmuxTransport exists. The interface is what another backend (Orca, ConPTY, a
headless SDK agent) would implement.
"""
from __future__ import annotations

import os
import re
import subprocess
from abc import ABC, abstractmethod

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")

# Abstract key vocabulary (TRANSPORT.md 4). A transport maps each to its own name;
# anything outside this set is refused rather than typed as literal text, which is
# what tmux does with an unknown key name (it typed "Dowm" once).
KEYS = {"Enter", "Escape", "Tab", "BTab", "Space", "BSpace", "Up", "Down", "Left", "Right",
        "Home", "End", "PageUp", "PageDown", "C-c", "C-u", "C-d"}


def strip_ansi(s: str) -> str:
    return ANSI.sub("", s)


class Transport(ABC):
    name = "abstract"

    @abstractmethod
    def list(self) -> list[str]: ...
    @abstractmethod
    def alive(self, session: str) -> bool: ...
    @abstractmethod
    def handle(self, session: str) -> tuple[str, int] | None: ...     # (pane id, pane pid)
    @abstractmethod
    def mode(self, handle: str) -> str: ...                            # normal | copy | dead
    @abstractmethod
    def capture(self, handle: str) -> str: ...                         # visible screen, ANSI stripped
    @abstractmethod
    def send_text(self, handle: str, text: str) -> None: ...          # literal, no submit
    @abstractmethod
    def send_buffer(self, handle: str, text: str) -> None: ...        # large text, bracketed paste
    @abstractmethod
    def send_key(self, handle: str, key: str) -> None: ...
    @abstractmethod
    def leave_mode(self, handle: str) -> None: ...
    @abstractmethod
    def output_mark(self, session: str) -> int | None: ...             # monotonic output counter
    @abstractmethod
    def kill(self, session: str) -> None: ...


class TmuxError(RuntimeError):
    pass


class TmuxTransport(Transport):
    name = "tmux"

    def __init__(self, socket: str | None = None, logdir: str | None = None):
        self.socket = socket or os.environ.get("AGENTMUX_SOCKET", "agentmux")
        self.logdir = logdir

    def _tm(self, *args, input_=None, check=True) -> str:
        r = subprocess.run(["tmux", "-L", self.socket, *args], input=input_, capture_output=True,
                           stdin=None if input_ is not None else subprocess.DEVNULL, timeout=10)
        if check and r.returncode != 0:
            raise TmuxError(r.stderr.decode(errors="replace").strip() or f"tmux {args[0]} failed")
        return r.stdout.decode(errors="replace")

    def list(self):
        try:
            out = self._tm("list-sessions", "-F", "#{session_name}")
        except TmuxError:
            return []
        return [l for l in out.splitlines() if l]

    def alive(self, session):
        r = subprocess.run(["tmux", "-L", self.socket, "has-session", "-t", f"={session}"],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        if r.returncode != 0:
            return False
        h = self.handle(session)
        return bool(h) and self.mode(h[0]) != "dead"

    def handle(self, session):
        try:
            out = self._tm("list-panes", "-t", f"={session}", "-F", "#{pane_id} #{pane_pid}")
        except TmuxError:
            return None
        first = out.split("\n", 1)[0].split()
        return (first[0], int(first[1])) if len(first) == 2 else None

    def mode(self, handle):
        try:
            out = self._tm("display-message", "-p", "-t", handle, "#{pane_dead} #{pane_in_mode}").split()
        except TmuxError:
            return "dead"
        if not out or out[0] == "1":
            return "dead"
        return "copy" if len(out) > 1 and out[1] == "1" else "normal"

    def capture(self, handle):
        return strip_ansi(self._tm("capture-pane", "-p", "-J", "-t", handle))

    def send_text(self, handle, text):
        if "\n" in text or "\r" in text:
            raise ValueError("send_text is single-line; use send_buffer for multi-line text")
        self._tm("send-keys", "-t", handle, "-l", "--", text)

    def send_buffer(self, handle, text):
        # load-buffer from stdin: no argv size limit (D04: >16 KB became a bare Enter),
        # no shell parsing of ; or \ . paste-buffer -p wraps it in bracketed paste
        # only if the application asked for it; -d deletes the named buffer after.
        name = f"hub-{os.getpid()}-{abs(hash(handle)) % 100000}"
        self._tm("load-buffer", "-b", name, "-", input_=text.encode())
        self._tm("paste-buffer", "-p", "-d", "-b", name, "-t", handle)

    def send_key(self, handle, key):
        if key not in KEYS and not re.fullmatch(r"[!-~]", key):
            raise ValueError(f"not an abstract key: {key!r}")
        self._tm("send-keys", "-t", handle, key)

    def leave_mode(self, handle):
        self._tm("send-keys", "-t", handle, "-X", "cancel", check=False)

    def output_mark(self, session):
        # The pipe-pane log grows exactly when the pane prints. This is the liveness
        # signal R-LIVE-1 requires - NOT #{session_activity}, which went hours stale
        # on panes that were demonstrably working and got them killed (C4).
        if not self.logdir:
            return None
        try:
            return os.stat(os.path.join(self.logdir, f"{session}.log")).st_size
        except OSError:
            return None

    def kill(self, session):
        self._tm("kill-session", "-t", f"={session}", check=False)


class FakeTransport(Transport):
    """In-memory transport for offline tests. Screens are scripted per session."""
    name = "fake"

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.sent: list[tuple[str, str, str]] = []   # (session, kind, payload)

    def add(self, session, screen="› ", mode="normal", pid=1000):
        self.sessions[session] = {"screen": screen, "mode": mode, "pid": pid, "out": 0, "on_submit": None}

    def _s(self, handle):
        return self.sessions[handle]

    def list(self):
        return sorted(self.sessions)

    def alive(self, session):
        return session in self.sessions and self.sessions[session]["mode"] != "dead"

    def handle(self, session):
        s = self.sessions.get(session)
        return (session, s["pid"]) if s else None

    def mode(self, handle):
        return self.sessions.get(handle, {"mode": "dead"})["mode"]

    def capture(self, handle):
        return self._s(handle)["screen"]

    def send_text(self, handle, text):
        self.sent.append((handle, "text", text))
        s = self._s(handle)
        if s["mode"] == "copy":
            return                                     # copy-mode swallows keys (D02)
        s["screen"] = s["screen"].rstrip("\n") + text

    def send_buffer(self, handle, text):
        self.sent.append((handle, "buffer", text))
        self._s(handle)["screen"] += f"[Pasted Content {len(text)} chars]"

    def send_key(self, handle, key):
        self.sent.append((handle, "key", key))
        s = self._s(handle)
        if key == "Enter" and s["mode"] == "normal":
            cb = s.get("on_submit")
            s["screen"] = cb(s["screen"]) if cb else "working… (esc to interrupt)\n› "
            s["out"] += 1

    def leave_mode(self, handle):
        self.sent.append((handle, "key", "cancel-mode"))
        if self._s(handle)["mode"] == "copy":
            self._s(handle)["mode"] = "normal"

    def output_mark(self, session):
        s = self.sessions.get(session)
        return s["out"] if s else None

    def kill(self, session):
        self.sessions.pop(session, None)
