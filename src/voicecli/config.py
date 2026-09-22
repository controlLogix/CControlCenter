"""Persistent user settings, stored as JSON under %APPDATA%\\voicecli."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

MODES = ("ptt", "open")


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "voicecli"


def config_path() -> Path:
    return config_dir() / "config.json"


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

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        if cfg.mode not in MODES:
            cfg.mode = "ptt"
        return cfg

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
