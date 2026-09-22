"""Shows the overlay with scripted events (no mic, no typing) for visual checks."""
import sys
from voicecli.overlay import Overlay

o = Overlay(float(sys.argv[1]) if len(sys.argv) > 1 else 0.92, lambda: [], lambda n: None, lambda: None,
            options={"type_text": True, "auto_enter": False}, hotkey="ctrl+alt+space")
dev = {"name": "Microphone (HyperX Cloud Alpha Wireless)"}
script = [
    (100, {"type": "device", "device": dev}), (150, {"type": "state", "state": "listening"}),
    (400, {"type": "final", "text": "List all the files in the current directory and show me the git status."}),
    (450, {"type": "typed", "action": "typed", "window": "Windows PowerShell — claude"}),
    (600, {"type": "speech_start"}), (650, {"type": "level", "rms": 0.05}),
    (700, {"type": "partial", "text": "now refactor the audio module so it falls back to"}),
    (int(sys.argv[2]) if len(sys.argv) > 2 else 6000, "quit"),
]
for ms, ev in script:
    o.root.after(ms, o.root.destroy if ev == "quit" else (lambda e=ev: o.events.put(e)))
o.run()
