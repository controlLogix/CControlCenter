"""Persistent user settings (JSON under %APPDATA%\\voicecli) and the app's other locations."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import typing
from dataclasses import asdict, dataclass, fields
from pathlib import Path

MODES = ("ptt", "open")

log = logging.getLogger(__name__)
_save_lock = threading.Lock()


def config_dir() -> Path:
    """Roaming settings (config.json, api-token)."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "voicecli"


def data_dir() -> Path:
    """Machine-local data (logs)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "voicecli"


def log_dir() -> Path:
    return data_dir() / "logs"


def config_path() -> Path:
    return config_dir() / "config.json"


def frozen() -> bool:
    """True when running as the packaged VoiceCLI.exe."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Install directory of VoiceCLI.exe, or the repository root when run from source."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base / "assets" / name


def models_dir() -> Path:
    """Models shipped with the app (<install dir>\\models\\<name>\\model.bin)."""
    return app_dir() / "models"


# Numeric settings outside these ranges fall back to the default.
RANGES = {"opacity": (0.2, 1.0), "silence_ms": (100, 5000), "port": (1024, 65535)}


@dataclass
class Config:
    device: str | None = None  # input device name (matched as a substring), None = system default
    model: str = "small.en"  # final transcript
    partial_model: str | None = "base.en"  # live preview; null reuses `model`
    language: str | None = None  # None lets multilingual models auto-detect
    mode: str = "ptt"  # "ptt" = hold ptt_key to talk, "open" = always listening
    ptt_key: str = "rctrl"  # held key (or combo) for push-to-talk
    opacity: float = 1.0  # opaque by default; right-click > Opacity to change
    auto_enter: bool = False  # press Enter after each typed utterance
    type_text: bool = True  # type final text into the target window
    silence_ms: int = 700  # trailing silence that ends an utterance (open mic)
    port: int = 47821  # local HTTP/SSE API
    hotkey: str = "ctrl+alt+space"  # open mic: pause/resume
    lock_hotkey: str = "ctrl+alt+l"  # lock output to the focused window (press again to unlock)
    show_hotkey: str = "ctrl+alt+v"  # show/hide the overlay
    overlay_x: int | None = None
    overlay_y: int | None = None
    log_transcripts: bool = False  # write spoken text and window titles to the log (off: only their length)
    allow_download: bool = False  # fetch models that are not installed from Hugging Face

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as e:
            log.warning("config %s unreadable (%s); using defaults", path, e)
            return cls()
        if not isinstance(data, dict):
            log.warning("config %s is not a JSON object; using defaults", path)
            return cls()
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Keep valid values; a missing, ill-typed or out-of-range one gets its default."""
        hints = typing.get_type_hints(cls)
        values = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = _coerce(data[f.name], hints[f.name])
            lo_hi = RANGES.get(f.name)
            if value is _INVALID or (lo_hi and value is not None and not lo_hi[0] <= value <= lo_hi[1]):
                log.warning("config: ignoring %s=%r (using %r)", f.name, data[f.name], f.default)
                continue
            values[f.name] = value
        cfg = cls(**values)
        if cfg.mode not in MODES:
            log.warning("config: unknown mode %r, using 'ptt'", cfg.mode)
            cfg.mode = "ptt"
        return cfg

    def save(self) -> None:
        """Write atomically: a crash mid-save leaves the previous file intact."""
        path = config_path()
        with _save_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            os.replace(tmp, path)


_INVALID = object()


def _coerce(value, hint):
    """`value` if it fits the annotation `hint` (int also fits float), else _INVALID."""
    for t in typing.get_args(hint) or (hint,):
        if t is type(None) and value is None:
            return None
        if isinstance(value, bool):
            if t is bool:
                return value
            continue
        if t is int and isinstance(value, int):
            return value
        if t is float and isinstance(value, (int, float)):
            return float(value)
        if t is str and isinstance(value, str):
            return value
    return _INVALID

