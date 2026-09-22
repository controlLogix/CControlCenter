"""Wires mic → transcriber → (stdout JSONL, overlay, focused-window typing, HTTP/SSE)."""

from __future__ import annotations

import json
import re
import sys
import threading

from . import inject
from .audio import MicStream, list_inputs, resolve_device
from .config import Config
from .engine import Transcriber
from .server import Api

# Saying one of these on its own presses Enter instead of typing the words.
SUBMIT_PHRASES = {"send", "send it", "submit", "press enter", "enter", "go ahead"}


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


class App:
    def __init__(self, cfg: Config, overlay: bool = True, verbose: bool = False):
        self.cfg = cfg
        self.use_overlay = overlay
        self.verbose = verbose
        self.overlay = None
        self.state = "loading"
        self.device = None
        self._out_lock = threading.Lock()
        self.api = Api(cfg.port, self.status, lambda: [d.to_dict() for d in list_inputs()],
                       self.set_listening, self.set_device)

    # -- event fan-out ------------------------------------------------------

    def emit(self, ev: dict) -> None:
        if ev["type"] == "state":
            self.state = ev["state"]
        if ev["type"] != "level" or self.verbose:
            with self._out_lock:
                sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        self.api.publish(ev)
        if self.overlay is not None:
            self.overlay.events.put(ev)
        if ev["type"] == "final":
            self._deliver(ev["text"])

    def _deliver(self, text: str) -> None:
        if not self.cfg.type_text:
            return
        window = inject.foreground_title()
        try:
            if _normalized(text) in SUBMIT_PHRASES:
                inject.press_enter()
                action = "enter"
            else:
                inject.type_text(text + ("" if self.cfg.auto_enter else " "))
                if self.cfg.auto_enter:
                    inject.press_enter()
                action = "typed"
            self.emit({"type": "typed", "action": action, "window": window})
        except OSError as e:
            self.emit({"type": "error", "message": f"typing failed: {e}"})

    # -- controls (overlay, hotkey and HTTP all come through here) ---------

    def status(self) -> dict:
        return {"state": self.state, "device": self.device.to_dict() if self.device else None,
                "model": self.cfg.model, "type_text": self.cfg.type_text, "auto_enter": self.cfg.auto_enter}

    def set_listening(self, on: bool) -> None:
        self.transcriber.set_listening(on)

    def toggle_listening(self) -> None:
        self.set_listening(not self.transcriber.listening)

    def set_device(self, spec: str) -> None:
        mic = MicStream(resolve_device(spec))
        self.transcriber.set_mic(mic)
        self.device = mic.device  # may differ from the request if a fallback host API was used
        self.cfg.device = mic.device.name
        self.cfg.save()

    def set_option(self, key: str, value: bool) -> None:
        setattr(self.cfg, key, value)
        self.cfg.save()
        self.emit({"type": "option", "key": key, "value": value})

    # -- lifecycle ----------------------------------------------------------

    def run(self) -> int:
        try:
            self.device = resolve_device(self.cfg.device)
        except ValueError as e:
            print(f"voicecli: {e}. Run `voicecli devices` to see what's available.", file=sys.stderr)
            return 2

        if self.use_overlay:
            from .overlay import Overlay
            self.overlay = Overlay(
                opacity=self.cfg.opacity,
                devices=lambda: [d.to_dict() for d in list_inputs()],
                on_device=self.set_device,
                on_toggle_listen=self.toggle_listening,
                options={"type_text": self.cfg.type_text, "auto_enter": self.cfg.auto_enter},
                on_option=self.set_option,
                on_move=self._save_position,
                on_opacity=self._save_opacity,
                on_quit=self._quit,
                position=(self.cfg.overlay_x, self.cfg.overlay_y),
                hotkey=self.cfg.hotkey,
            )

        try:
            self.api.start()
        except OSError as e:
            print(f"voicecli: API port {self.cfg.port} unavailable ({e}); continuing without it", file=sys.stderr)

        hotkey = inject.HotkeyListener(self.cfg.hotkey, self.toggle_listening)
        if not hotkey.start():
            self.emit({"type": "error", "message": f"hotkey: {hotkey.error}"})

        # Model loading takes a few seconds; do it off the UI thread.
        self._done = threading.Event()
        threading.Thread(target=self._boot, name="boot", daemon=True).start()

        try:
            if self.overlay is not None:
                self.overlay.run()
            else:
                self._done.wait()
        except KeyboardInterrupt:
            pass
        finally:
            hotkey.stop()
            if hasattr(self, "transcriber"):
                self.transcriber.stop()
            self.api.stop()
        return 0

    def _boot(self) -> None:
        try:
            self.transcriber = Transcriber(self.emit, model=self.cfg.model,
                                           partial_model=self.cfg.partial_model, language=self.cfg.language,
                                           silence_ms=self.cfg.silence_ms)
            self.transcriber.start()
        except Exception as e:  # surface startup failures in the overlay, not just stderr
            self.emit({"type": "error", "message": f"startup failed: {e}"})
            raise
        mic = MicStream(self.device)
        try:
            self.transcriber.set_mic(mic)
            self.device = mic.device
        except OSError as e:
            # Keep running so another mic can be picked from the overlay or the API.
            self.emit({"type": "error", "message": f"{e}. Right-click to choose another mic."})

    def _save_position(self, x: int, y: int) -> None:
        self.cfg.overlay_x, self.cfg.overlay_y = x, y
        self.cfg.save()

    def _save_opacity(self, value: float) -> None:
        self.cfg.opacity = value
        self.cfg.save()

    def _quit(self) -> None:
        self._done.set()
        if self.overlay is not None:
            self.overlay.root.destroy()
