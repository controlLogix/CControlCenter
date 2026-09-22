"""Wires mic → transcriber → (stdout JSONL, overlay, typing into the target window, HTTP/SSE)."""

from __future__ import annotations

import json
import re
import sys
import threading
import time

from . import inject
from .audio import MicStream, list_inputs, resolve_device
from .config import MODES, Config
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
        self.transcriber: Transcriber | None = None
        self.state = "loading"
        self.device = None
        self.target: inject.Window | None = None  # None = follow focus
        self._out_lock = threading.Lock()
        self._deliver_lock = threading.Lock()
        self._done = threading.Event()
        self.api = Api(cfg.port, self)

    # -- event fan-out ------------------------------------------------------

    def emit(self, ev: dict) -> None:
        if ev["type"] == "state":
            self.state = ev["state"]
        if sys.stdout is not None and (ev["type"] != "level" or self.verbose):
            with self._out_lock:
                try:
                    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                except (OSError, ValueError):
                    pass
        self.api.publish(ev)
        if self.overlay is not None:
            self.overlay.events.put(ev)
        if ev["type"] == "final":
            self._deliver(ev["text"])

    def _deliver(self, text: str) -> None:
        if not self.cfg.type_text:
            return
        with self._deliver_lock:
            submit = _normalized(text) in SUBMIT_PHRASES
            payload = "" if submit else text + ("" if self.cfg.auto_enter else " ")
            enter = submit or self.cfg.auto_enter
            inject.wait_modifiers_released()

            if self.target is not None:
                if not inject.is_alive(self.target.hwnd):
                    self.emit({"type": "error", "message": f"locked window is gone: {self.target.title}"})
                    self.set_target(None)
                    return
                win = self.target
            else:
                win = inject.foreground()
            ok, reason = inject.typeable(win)
            if not ok:
                self.emit({"type": "typed", "action": "skipped", "window": win.title, "reason": reason})
                return

            previous = inject.foreground()
            switched = previous.hwnd != win.hwnd
            if switched:
                if not inject.focus(win.hwnd):
                    self.emit({"type": "error", "message": f"could not bring '{win.title}' forward to type into it"})
                    return
                time.sleep(0.12)  # let the newly active window settle its keyboard focus
            try:
                if payload:
                    inject.type_text(payload)
                if enter:
                    inject.press_enter()
                self.emit({"type": "typed", "action": "enter" if submit else "typed", "window": win.title})
            except OSError as e:
                self.emit({"type": "error", "message": f"typing failed: {e}"})
            finally:
                if switched:
                    # SendInput only queues keystrokes; they go to whichever window is in front
                    # when they are processed. Give them time to drain, and only switch back if
                    # the target is still in front (otherwise the user already moved on).
                    time.sleep(0.25 + 0.004 * len(payload))
                    if inject.foreground().hwnd == win.hwnd and inject.typeable(previous)[0]:
                        inject.focus(previous.hwnd)

    # -- controls (overlay, hotkeys and HTTP all come through here) ----------

    def status(self) -> dict:
        return {"state": self.state, "mode": self.cfg.mode, "ptt_key": self.cfg.ptt_key,
                "device": self.device.to_dict() if self.device else None,
                "target": self.target.to_dict() if self.target else None,
                "model": self.cfg.model, "type_text": self.cfg.type_text, "auto_enter": self.cfg.auto_enter}

    def devices(self) -> list[dict]:
        return [d.to_dict() for d in list_inputs()]

    def windows(self) -> list[dict]:
        return [w.to_dict() for w in inject.list_windows()]

    def set_listening(self, on: bool) -> None:
        if self.transcriber:
            self.transcriber.set_listening(on)

    def toggle_listening(self) -> None:
        if self.transcriber and self.cfg.mode == "open":
            self.set_listening(not self.transcriber.listening)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.cfg.mode = mode
        self.cfg.save()
        if self.transcriber:
            self.transcriber.set_mode(mode)
        self.emit({"type": "mode", "mode": mode, "ptt_key": self.cfg.ptt_key})

    def set_device(self, spec: str) -> None:
        mic = MicStream(resolve_device(spec))
        self.transcriber.set_mic(mic)
        self.device = mic.device  # may differ from the request if a fallback host API was used
        self.cfg.device = mic.device.name
        self.cfg.save()

    def set_target(self, hwnd: int | None) -> None:
        if hwnd:
            win = inject.window_info(hwnd)
            ok, reason = inject.typeable(win)
            if not ok:
                raise ValueError(reason)
            self.target = win
        else:
            self.target = None
        self.emit({"type": "target", "target": self.target.to_dict() if self.target else None})

    def toggle_lock(self) -> None:
        """Hotkey: lock to the focused window, or unlock if already locked."""
        if self.target is not None:
            self.set_target(None)
            return
        try:
            self.set_target(inject.foreground().hwnd)
        except ValueError as e:
            self.emit({"type": "error", "message": f"can't lock: {e}"})

    def set_option(self, key: str, value: bool) -> None:
        setattr(self.cfg, key, value)
        self.cfg.save()
        self.emit({"type": "option", "key": key, "value": value})

    def show(self) -> None:
        if self.overlay is not None:
            self.overlay.request("show")

    def toggle_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.request("toggle")

    def _on_ptt(self, down: bool) -> None:
        if self.transcriber:
            self.transcriber.set_held(down)

    # -- lifecycle ----------------------------------------------------------

    def run(self) -> int:
        try:
            self.device = resolve_device(self.cfg.device)
        except ValueError as e:
            print(f"voicecli: {e}. Run `voicecli devices` to see what's available.", file=sys.stderr)
            return 2

        if self.use_overlay:
            from .overlay import Overlay
            self.overlay = Overlay(self, position=(self.cfg.overlay_x, self.cfg.overlay_y))

        try:
            self.api.start()
        except OSError as e:
            print(f"voicecli: API port {self.cfg.port} unavailable ({e}); continuing without it", file=sys.stderr)

        hotkeys = inject.HotkeyListener({
            self.cfg.hotkey: self.toggle_listening,
            self.cfg.lock_hotkey: self.toggle_lock,
            self.cfg.show_hotkey: self.toggle_overlay,
        })
        for err in hotkeys.start():
            self.emit({"type": "error", "message": f"hotkey: {err}"})
        ptt = inject.HoldKey(self.cfg.ptt_key, self._on_ptt)
        ptt.start()

        # Model loading takes a few seconds; do it off the UI thread.
        threading.Thread(target=self._boot, name="boot", daemon=True).start()

        try:
            if self.overlay is not None:
                self.overlay.run()
            else:
                self._done.wait()
        except KeyboardInterrupt:
            pass
        finally:
            ptt.stop()
            hotkeys.stop()
            if self.transcriber:
                self.transcriber.stop()
            self.api.stop()
        return 0

    def _boot(self) -> None:
        try:
            self.transcriber = Transcriber(self.emit, model=self.cfg.model,
                                           partial_model=self.cfg.partial_model, language=self.cfg.language,
                                           mode=self.cfg.mode, silence_ms=self.cfg.silence_ms)
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

    def save_position(self, x: int, y: int) -> None:
        self.cfg.overlay_x, self.cfg.overlay_y = x, y
        self.cfg.save()

    def save_opacity(self, value: float) -> None:
        self.cfg.opacity = value
        self.cfg.save()

    def quit(self) -> None:
        self._done.set()
        if self.overlay is not None:
            self.overlay.request("quit")
