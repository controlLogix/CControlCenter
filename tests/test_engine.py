"""The Transcriber's phrase logic, driven by synthetic audio and a fake model (no Whisper)."""

import queue
import threading
import time

import numpy as np
import pytest

from voicecli import engine
from voicecli.audio import TARGET_RATE, InputDevice
from voicecli.engine import Transcriber

BLOCK = int(TARGET_RATE * 0.03)


class FakeModel:
    def __init__(self, text="hello world", delay=0.0):
        self.text, self.delay, self.calls = text, delay, 0

    def transcribe(self, audio, **kw):
        self.calls += 1
        time.sleep(self.delay)
        return [type("Seg", (), {"text": self.text})()], None


class FakeMic:
    def __init__(self):
        self.device = InputDevice(-1, "fake", "test", TARGET_RATE, 1)
        self.blocks = queue.Queue()

    def start(self):
        pass

    def stop(self):
        pass

    def feed(self, seconds, amplitude):
        rng = np.random.default_rng(0)
        for _ in range(int(seconds / 0.03)):
            if amplitude > 0.01:  # "speech": a loud tone
                t = np.arange(BLOCK) / TARGET_RATE
                block = amplitude * np.sin(2 * np.pi * 220 * t)
            else:  # background hiss
                block = rng.normal(0, amplitude, BLOCK)
            self.blocks.put(block.astype(np.float32))

    def drain(self, timeout=5):
        end = time.monotonic() + timeout
        while self.blocks.qsize() and time.monotonic() < end:
            time.sleep(0.01)
        time.sleep(0.1)


@pytest.fixture
def rig(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(engine, "load_model", lambda *a, **kw: model)
    events = []
    got = threading.Condition()

    def emit(ev):
        with got:
            events.append(ev)
            got.notify_all()

    def wait_for(kind, count=1, timeout=5):
        with got:
            got.wait_for(lambda: sum(e["type"] == kind for e in events) >= count, timeout)
        return [e for e in events if e["type"] == kind]

    def make(mode):
        tr = Transcriber(emit, mode=mode, silence_ms=300)
        mic = FakeMic()
        tr.set_mic(mic)
        tr.start()
        return tr, mic

    yield make, model, events, wait_for


def test_push_to_talk_phrase(rig):
    make, model, events, wait_for = rig
    tr, mic = make("ptt")
    mic.feed(0.5, 0.001)
    mic.drain()
    tr.set_held(True)
    mic.feed(1.0, 0.2)
    mic.drain()
    tr.set_held(False)
    mic.feed(0.5, 0.001)
    finals = wait_for("final")
    tr.stop()
    assert [f["text"] for f in finals] == ["hello world"]
    assert 1.0 <= finals[0]["audio_s"] <= 1.8  # the held span (+ pre-roll and release tail), not the silence


def test_open_mic_phrase_ends_on_silence(rig):
    make, model, events, wait_for = rig
    tr, mic = make("open")
    mic.feed(1.0, 0.001)
    mic.feed(1.0, 0.2)
    mic.feed(1.0, 0.001)
    finals = wait_for("final")
    tr.stop()
    assert [f["text"] for f in finals] == ["hello world"]


def test_short_blip_is_discarded(rig):
    make, model, events, wait_for = rig
    tr, mic = make("open")
    mic.feed(1.0, 0.001)
    mic.feed(0.09, 0.2)
    mic.feed(1.0, 0.001)
    discards = wait_for("discard")
    tr.stop()
    assert discards[0]["reason"] == "too short"
    assert not [e for e in events if e["type"] == "final"]


def test_slow_final_does_not_stall_capture(rig):
    """While the main model is busy with one phrase, the next is still captured on time."""
    make, model, events, wait_for = rig
    model.delay = 1.0
    tr, mic = make("ptt")
    for _ in range(2):
        tr.set_held(True)
        mic.feed(0.6, 0.2)
        mic.drain()
        tr.set_held(False)
        mic.feed(0.4, 0.001)
        mic.drain()
    # Both phrases were cut before the first final finished.
    starts = [e for e in events if e["type"] == "speech_start"]
    assert len(starts) == 2
    finals = wait_for("final", count=2, timeout=6)
    tr.stop()
    assert len(finals) == 2
