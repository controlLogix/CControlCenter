"""Feed WAV files through the real Transcriber via a fake mic, in real time.

    uv run python tests/sim_engine.py phrase1.wav phrase2.wav [--model small.en]
"""
import argparse, json, queue, threading, time, wave

import numpy as np

from voicecli.audio import TARGET_RATE, InputDevice
from voicecli.engine import Transcriber


class FakeMic:
    ptt = None  # Transcriber to press/release around each clip (push-to-talk test)

    def __init__(self, clips):
        self.device = InputDevice(-1, "fake", "file", TARGET_RATE, 1)
        self.blocks = queue.Queue()
        self.clips = clips

    def start(self):
        def feed():
            block = int(TARGET_RATE * 0.03)
            silence = np.random.normal(0, 0.001, TARGET_RATE * 2).astype(np.float32)
            for clip in [silence] + [c for x in self.clips for c in (x, silence)]:
                speech = clip is not silence
                if speech and self.ptt:
                    self.ptt.set_held(True)
                for i in range(0, len(clip), block):
                    self.blocks.put(clip[i:i + block])
                    time.sleep(0.03)
                if speech and self.ptt:
                    self.ptt.set_held(False)
        threading.Thread(target=feed, daemon=True).start()

    def stop(self):
        pass


def load(path):
    with wave.open(path) as w:
        assert w.getframerate() == TARGET_RATE and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


ap = argparse.ArgumentParser()
ap.add_argument("wavs", nargs="+")
ap.add_argument("--model", default="small.en")
ap.add_argument("--ptt", action="store_true", help="simulate holding push-to-talk during each clip")
a = ap.parse_args()
clips = [load(p) for p in a.wavs]
events = []
t0 = time.perf_counter()
def emit(ev):
    ev["t"] = round(time.perf_counter() - t0, 2)
    if ev["type"] != "level":
        print(json.dumps(ev), flush=True)
    events.append(ev)
tr = Transcriber(emit, model=a.model, mode="ptt" if a.ptt else "open")
mic = FakeMic(clips)
mic.ptt = tr if a.ptt else None
tr.set_mic(mic)
tr.start()
total = 2 + sum(len(c) / TARGET_RATE + 2 for c in clips)
time.sleep(total + 4)
finals = [e["text"] for e in events if e["type"] == "final"]
print("FINALS:", finals)
print("PARTIALS:", sum(e["type"] == "partial" for e in events))
