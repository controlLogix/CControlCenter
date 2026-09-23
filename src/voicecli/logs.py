"""Logging: a size-capped rotating file under %LOCALAPPDATA%\\voicecli\\logs, crash hooks,
and redaction so spoken text stays out of the log unless the user opts in."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import log_dir

LOG_NAME = "voicecli.log"
MAX_BYTES = 1_000_000
BACKUPS = 5
# Events too chatty to be worth a log line.
UNLOGGED = {"level", "partial"}

log = logging.getLogger("voicecli")


def log_file() -> Path:
    return log_dir() / LOG_NAME


def setup(console: bool) -> Path:
    """Log to the rotating file, and to stderr when there is a console."""
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)  # one line per transcription otherwise
    if console:
        err = logging.StreamHandler(sys.stderr)
        err.setLevel(logging.WARNING)
        err.setFormatter(logging.Formatter("voicecli: %(message)s"))
        root.addHandler(err)
    return path


def redact(ev: dict, keep_text: bool) -> dict:
    """The event with spoken text and window titles (which name documents, videos, chats)
    replaced by their length, unless `keep_text`."""
    if keep_text:
        return ev
    out = dict(ev)
    for key in ("text", "window"):
        if isinstance(ev.get(key), str):
            out[key] = f"<{len(ev[key])} chars>"
    if isinstance(ev.get("target"), dict):
        out["target"] = {k: v for k, v in ev["target"].items() if k != "title"}
    return out


def install_crash_hooks(show_dialog: bool) -> None:
    """Log every uncaught exception; a fatal one on the main thread also gets a dialog
    when there is no console to print it to."""

    def main_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return sys.__excepthook__(exc_type, exc, tb)
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))
        if show_dialog:
            error_dialog(f"Voice CLI stopped because of an unexpected error:\n\n{exc}\n\nDetails: {log_file()}")

    def thread_hook(args: threading.ExceptHookArgs):
        if args.exc_type is SystemExit:
            return
        log.error("uncaught exception in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def error_dialog(message: str) -> None:
    MB_ICONERROR, MB_SETFOREGROUND = 0x10, 0x10000
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Voice CLI", MB_ICONERROR | MB_SETFOREGROUND)
    except (AttributeError, OSError):
        pass
