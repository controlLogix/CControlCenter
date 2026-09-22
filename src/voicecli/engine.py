"""Streaming speech-to-text: faster-whisper over microphone audio, in two modes.

- open mic: an energy VAD finds speech; the phrase ends after `silence_ms` of silence.
- push-to-talk: everything captured while the key is held is one phrase; release ends it.

While a phrase is in progress it is re-transcribed about every `partial_every`
seconds (by the smaller `partial_model`) and emitted as a `partial` event. The
finished phrase is transcribed once more by the main model and emitted as `final`.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from typing import Callable

import numpy as np

from .audio import TARGET_RATE, MicStream

Emit = Callable[[dict], None]

# Whisper's typical output for near-silent or noisy clips.
HALLUCINATIONS = {
    "", "you", "thank you", "thanks for watching", "thank you for watching",
    "bye", "okay", "so", "the end", "subtitles by the amara.org community",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_noise(text: str) -> bool:
    return re.sub(r"[^a-z' ]", "", text.lower()).strip() in HALLUCINATIONS


class Transcriber:
    def __init__(
        self,
        emit: Emit,
        model: str = "small.en",
        partial_model: str | None = "base.en",
        language: str | None = None,
        mode: str = "open",
        silence_ms: int = 700,
        partial_every: float = 0.4,
        max_utterance_s: float = 60.0,
        cpu_threads: int = 8,
    ):
        from faster_whisper import WhisperModel  # heavy import, deferred

        self.emit = emit
        self.language = language or ("en" if model.endswith(".en") else None)
        self.silence_ms = silence_ms
        self.partial_every = partial_every
        self.max_samples = int(max_utterance_s * TARGET_RATE)
        emit({"type": "state", "state": "loading", "model": model})
        t0 = time.perf_counter()
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
        # A smaller model keeps live partials snappy; the final pass uses the main model.
        if partial_model and partial_model != model:
            self.partial_model = WhisperModel(partial_model, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
        else:
            self.partial_model = self.model
        emit({"type": "state", "state": "ready", "model": model, "load_s": round(time.perf_counter() - t0, 2)})

        self.mode = mode
        self.listening = True  # open mic: paused when False
        self.held = False  # push-to-talk: key currently held
        self._mic: MicStream | None = None
        self._mic_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- control ---------------------------------------------------------

    def set_mic(self, mic: MicStream) -> None:
        """Switch to `mic`. If it fails to open, the previous mic is restored and the error re-raised."""
        with self._mic_lock:
            previous = self._mic
            if previous is not None:
                previous.stop()
            try:
                mic.start()
            except OSError:
                if previous is not None:
                    previous.start()
                raise
            self._mic = mic
        self.emit({"type": "device", "device": mic.device.to_dict()})

    def idle_state(self) -> str:
        if self.mode == "ptt":
            return "ptt_idle"
        return "listening" if self.listening else "paused"

    def set_listening(self, on: bool) -> None:
        self.listening = on
        self.emit({"type": "state", "state": self.idle_state()})

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.held = False
        self.emit({"type": "state", "state": self.idle_state()})

    def set_held(self, down: bool) -> None:
        """Push-to-talk key changed. Ignored in open-mic mode."""
        if self.mode != "ptt":
            return
        self.held = down
        if down:
            self.emit({"type": "state", "state": "recording"})

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="transcriber", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._mic_lock:
            if self._mic is not None:
                self._mic.stop()

    # -- inference -------------------------------------------------------

    def transcribe(self, audio: np.ndarray, final: bool) -> str:
        model = self.model if final else self.partial_model
        segments, _ = model.transcribe(
            audio,
            language=self.language,
            beam_size=3 if final else 1,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
            temperature=0.0,
        )
        return _clean(" ".join(s.text for s in segments))

    # -- loop ------------------------------------------------------------

    def _run(self) -> None:
        block = int(TARGET_RATE * 0.03)
        preroll: deque[np.ndarray] = deque(maxlen=10)  # ~300 ms before onset / key press
        noise_floor = 0.003
        utter: list[np.ndarray] = []
        utter_samples = 0
        in_speech = False
        speech_samples = 0
        silence_samples = 0
        release_tail = 0  # ptt: frames still to capture after the key comes up
        last_partial = 0.0
        last_level_emit = 0.0
        silence_limit = int(self.silence_ms / 1000 * TARGET_RATE)
        pending = np.zeros(0, dtype=np.float32)
        quiet_since = time.monotonic()
        warned_quiet = False

        self.emit({"type": "state", "state": self.idle_state()})
        while not self._stop.is_set():
            with self._mic_lock:
                mic = self._mic
            if mic is None:
                time.sleep(0.05)
                continue
            try:
                chunk = mic.blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            pending = np.concatenate([pending, chunk])
            while len(pending) >= block:
                frame, pending = pending[:block], pending[block:]
                rms = float(np.sqrt(np.mean(frame * frame)))
                now = time.monotonic()
                if now - last_level_emit > 0.1:
                    last_level_emit = now
                    self.emit({"type": "level", "rms": round(rms, 6), "floor": round(noise_floor, 6)})

                # A digital-zero signal means a muted or disconnected mic; real mics always hiss.
                if rms > 1e-6:
                    quiet_since, warned_quiet = now, False
                elif not warned_quiet and now - quiet_since > 5:
                    warned_quiet = True
                    self.emit({"type": "hint", "message": "Mic is sending pure silence. Is it muted, or is it the wrong input?"})

                voiced = rms > max(noise_floor * 3.0, 0.004)

                def begin():
                    nonlocal in_speech, utter, utter_samples, speech_samples, silence_samples, last_partial
                    in_speech = True
                    utter = list(preroll)
                    utter_samples = sum(len(f) for f in utter)
                    speech_samples = silence_samples = 0
                    last_partial = now
                    self.emit({"type": "speech_start"})

                def end():
                    nonlocal in_speech, utter
                    self._finish(np.concatenate(utter), speech_samples)
                    utter, in_speech = [], False
                    preroll.clear()
                    self.emit({"type": "state", "state": self.idle_state()})

                if not in_speech:
                    # Track the background level only while nobody is talking.
                    noise_floor = 0.95 * noise_floor + 0.05 * min(rms, noise_floor * 4)
                    preroll.append(frame)
                    if self.mode == "ptt":
                        if self.held:
                            begin()
                            release_tail = 7  # keep ~200 ms after release
                    elif self.listening and voiced:
                        begin()
                    continue

                utter.append(frame)
                utter_samples += len(frame)
                if voiced:
                    speech_samples += block
                    silence_samples = 0
                else:
                    silence_samples += block

                if self.mode == "ptt":
                    if not self.held:
                        release_tail -= 1
                        if release_tail <= 0:
                            end()
                            continue
                    elif utter_samples >= self.max_samples:
                        end()
                        continue
                else:
                    if not self.listening:  # paused mid-phrase: drop it
                        utter, in_speech = [], False
                        continue
                    if silence_samples >= silence_limit or utter_samples >= self.max_samples:
                        end()
                        continue

                if now - last_partial >= self.partial_every and mic.blocks.qsize() < 5 and speech_samples:
                    text = self.transcribe(np.concatenate(utter), final=False)
                    last_partial = time.monotonic()
                    if text and not _is_noise(text):
                        self.emit({"type": "partial", "text": text})

    def _finish(self, audio: np.ndarray, speech_samples: int) -> None:
        if speech_samples < int(0.2 * TARGET_RATE):
            self.emit({"type": "discard", "reason": "too short"})
            return
        t0 = time.perf_counter()
        text = self.transcribe(audio, final=True)
        if not text or _is_noise(text):
            self.emit({"type": "discard", "reason": "noise", "text": text})
            return
        self.emit({
            "type": "final",
            "text": text,
            "audio_s": round(len(audio) / TARGET_RATE, 2),
            "latency_s": round(time.perf_counter() - t0, 2),
        })
