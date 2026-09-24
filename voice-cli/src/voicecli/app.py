"""Wires mic → transcriber → (stdout JSONL, log, overlay, tray, typing into the target window, HTTP/SSE)."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time

from . import __version__, audio, autostart, inject, logs
from .audio import InputDevice, MicStream, list_inputs, resolve_device
from .config import MODES, Config, asset, frozen, log_dir
from .engine import Transcriber
from .server import Api

log = logging.getLogger(__name__)
events_log = logging.getLogger("voicecli.events")

# Saying one of these on its own presses Enter instead of typing the words.
SUBMIT_PHRASES = {"send", "send it", "submit", "press enter", "enter", "go ahead"}

WATCH_EVERY_S = 2.0  # mic watchdog period
STALL_S = 3.0  # no audio for this long means the mic is gone
RETRY_S = 10.0  # after a failed or fallback reconnect, wait this long before trying again


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


class App:
    def __init__(self, cfg: Config, overlay: bool = True, verbose: bool = False, console: bool = True):
        self.cfg = cfg
        self.use_overlay = overlay
        self.verbose = verbose
        self.console = console
        self.overlay = None
        self.tray = None
        self.transcriber: Transcriber | None = None
        self.state = "loading"
        self.device: InputDevice | None = None
        self.target: inject.Window | None = None  # None = follow focus
        self._out_lock = threading.Lock()
        self._deliver_lock = threading.Lock()
        self._mic_lock = threading.Lock()
        self._done = threading.Event()
        self._retry_at = 0.0
        self._mic_name = ""
        self.api = Api(cfg.port, self)

    # -- event fan-out ------------------------------------------------------

    def emit(self, ev: dict) -> None:
        if ev["type"] == "state":
            self.state = ev["state"]
        elif ev["type"] == "device":
            self._mic_name = ev["device"]["name"]
        if self.console and (ev["type"] != "level" or self.verbose):
            with self._out_lock:
                try:
                    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                except (OSError, ValueError, AttributeError):
                    pass
        if ev["type"] not in logs.UNLOGGED:
            events_log.info(json.dumps(logs.redact(ev, self.cfg.log_transcripts), ensure_ascii=False))
        self.api.publish(ev)
        if self.overlay is not None:
            self.overlay.events.put(ev)
        if self.tray is not None and ev["type"] in ("state", "device"):
            self.tray.set_tooltip(self._tooltip())
        if ev["type"] == "final":
            self._deliver(ev["text"])

    def _tooltip(self) -> str:
        return f"Voice CLI – {self.state.replace('_', ' ')} · {self._mic_name or 'no mic'}"

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
                self.emit({"type": "typed", "action": "skipped", "window": win.title, "process": win.process,
                           "reason": reason})
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
                self.emit({"type": "typed", "action": "enter" if submit else "typed", "window": win.title,
                           "process": win.process})
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

    # -- controls (overlay, tray, hotkeys and HTTP all come through here) ----

    def status(self) -> dict:
        return {"state": self.state, "mode": self.cfg.mode, "ptt_key": self.cfg.ptt_key,
                "device": self.device.to_dict() if self.device else None,
                "target": self.target.to_dict() if self.target else None,
                "model": self.cfg.model, "type_text": self.cfg.type_text, "auto_enter": self.cfg.auto_enter}

    def devices(self) -> list[dict]:
        with self._mic_lock:  # not while the watchdog is re-initialising PortAudio
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
        if self.transcriber is None:
            raise ValueError("still starting up")
        with self._mic_lock:
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

    def autostart_available(self) -> bool:
        """Only the installed exe registers itself; a source checkout has no stable command."""
        return frozen()

    def autostart_enabled(self) -> bool:
        return autostart.enabled()

    def set_autostart(self, on: bool) -> None:
        autostart.set_enabled(on)
        self.emit({"type": "option", "key": "start_with_windows", "value": on})

    def open_logs(self) -> None:
        log_dir().mkdir(parents=True, exist_ok=True)
        os.startfile(log_dir())

    def show(self) -> None:
        if self.overlay is not None:
            self.overlay.request("show")

    def toggle_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.request("toggle")

    def _on_ptt(self, down: bool) -> None:
        if self.transcriber:
            self.transcriber.set_held(down)

    # -- microphone ---------------------------------------------------------

    def _pick_device(self) -> tuple[InputDevice, bool]:
        """The chosen mic, or the Windows default while the chosen one is missing (fallback=True)."""
        try:
            return resolve_device(self.cfg.device), False
        except ValueError:
            if not self.cfg.device:
                raise
            return resolve_device(None), True

    def _on_preferred(self) -> bool:
        mic = self.transcriber.mic if self.transcriber else None
        if mic is None:
            return False
        return not self.cfg.device or audio.matches(mic.device.name, self.cfg.device)

    def _watch_mic(self) -> None:
        """Reconnect when the mic stops delivering audio (unplugged, headset switched off), and
        move back to the chosen mic once Windows lists it again."""
        while not self._done.wait(WATCH_EVERY_S):
            try:
                self._check_mic()
            except Exception:
                log.exception("mic watchdog")

    def _check_mic(self) -> None:
        mic = self.transcriber.mic if self.transcriber else None
        if mic is not None and mic.stalled(STALL_S):
            log.warning("mic %r stopped delivering audio", mic.device.name)
            self._notify(f"Lost {mic.device.name}. Reconnecting…", warning=True)
            self._reconnect(announce=True)
        elif time.monotonic() >= self._retry_at and (
                mic is None or (not self._on_preferred() and audio.present(self.cfg.device))):
            self._reconnect()

    def _reconnect(self, announce: bool = False) -> None:
        with self._mic_lock:
            tr = self.transcriber
            was_fallback = not self._on_preferred()
            tr.detach_mic()
            audio.refresh()
            try:
                dev, fallback = self._pick_device()
                mic = MicStream(dev)
                tr.set_mic(mic)
            except (OSError, ValueError) as e:
                self.device = None
                self._retry_at = time.monotonic() + RETRY_S
                self.emit({"type": "error", "message": f"{e}. Waiting for a microphone…"})
                return
            self.device = mic.device
            if fallback:
                self._retry_at = time.monotonic() + RETRY_S
                self._notify(f"{self.cfg.device} not found; using {mic.device.name} for now.", warning=True)
            elif was_fallback or announce:
                self._notify(f"Microphone ready: {mic.device.name}")

    def _notify(self, message: str, warning: bool = False) -> None:
        self.emit({"type": "hint", "message": message})
        if self.tray is not None:
            self.tray.notify("Voice CLI", message, warning=warning)

    # -- tray ---------------------------------------------------------------

    def _tray_menu(self):
        from .tray import SEPARATOR, MenuItem

        hidden = self.overlay is not None and self.overlay.hidden
        return [
            MenuItem("Show overlay" if hidden else "Hide overlay", self.toggle_overlay),
            MenuItem("Start with Windows", lambda: self.set_autostart(not self.autostart_enabled()),
                     checked=self.autostart_available() and self.autostart_enabled(),
                     enabled=self.autostart_available()),
            MenuItem("Open log folder", self.open_logs),
            SEPARATOR,
            MenuItem(f"Voice CLI {__version__}", enabled=False),
            MenuItem("Quit Voice CLI", self.quit),
        ]

    def _start_tray(self) -> None:
        from .tray import Tray

        tray = Tray(asset("voicecli.ico"), "Voice CLI – starting", on_click=self.show, menu=self._tray_menu)
        if tray.start():
            self.tray = tray
        else:
            log.warning("no tray icon; use %s to show the overlay", self.cfg.show_hotkey)

    # -- lifecycle ----------------------------------------------------------

    def run(self, instance=None) -> int:
        startup_problem = None
        try:
            self.device, fallback = self._pick_device()
            if fallback:
                startup_problem = f"{self.cfg.device} not found; using {self.device.name} for now."
        except ValueError as e:
            self.device, startup_problem = None, f"{e}. Plug one in and it will be picked up."

        if self.use_overlay:
            from .overlay import Overlay
            self.overlay = Overlay(self, position=(self.cfg.overlay_x, self.cfg.overlay_y))
            self._start_tray()

        try:
            self.api.start()
        except OSError as e:
            log.warning("API port %s unavailable (%s); continuing without it", self.cfg.port, e)

        if instance is not None:
            instance.listen({"show": self.show, "quit": self.quit})

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
        threading.Thread(target=self._boot, args=(startup_problem,), name="boot", daemon=True).start()

        try:
            if self.overlay is not None:
                self.overlay.run()
            else:
                self._done.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self._done.set()
            ptt.stop()
            hotkeys.stop()
            if self.transcriber:
                self.transcriber.stop()
            self.api.stop()
            if self.tray is not None:
                self.tray.stop()
        log.info("voicecli stopped")
        return 0

    def _boot(self, startup_problem: str | None) -> None:
        try:
            self.transcriber = Transcriber(self.emit, model=self.cfg.model,
                                           partial_model=self.cfg.partial_model, language=self.cfg.language,
                                           mode=self.cfg.mode, silence_ms=self.cfg.silence_ms,
                                           allow_download=self.cfg.allow_download)
            self.transcriber.start()
        except Exception as e:  # surface startup failures in the overlay, not just the log
            log.exception("could not start the transcriber")
            self.emit({"type": "error", "message": f"startup failed: {e}"})
            self._notify(f"Voice CLI could not start: {e}", warning=True)
            return
        if self.device is not None:
            mic = MicStream(self.device)
            try:
                self.transcriber.set_mic(mic)
                self.device = mic.device
            except OSError as e:
                # Keep running: the watchdog retries, and another mic can be picked from the menu or API.
                self.emit({"type": "error", "message": f"{e}. Right-click to choose another mic."})
        if startup_problem:
            self._notify(startup_problem, warning=True)
        threading.Thread(target=self._watch_mic, name="mic-watchdog", daemon=True).start()

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
