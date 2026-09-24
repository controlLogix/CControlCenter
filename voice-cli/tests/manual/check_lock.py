"""Locks delivery to a window by title and delivers a phrase while another window has focus.

    uv run python tests/check_lock.py "VOICE TARGET" "phrase"
"""
import sys
from voicecli import inject
from voicecli.app import App
from voicecli.config import Config

title, phrase = sys.argv[1], sys.argv[2]
cfg = Config(auto_enter=True)
app = App(cfg, overlay=False)
match = next(w for w in inject.list_windows() if w.title == title)
before = inject.foreground()
app.set_target(match.hwnd)
app._deliver(phrase)
after = inject.foreground()
print("focus before:", before.title, "| after:", after.title, "| restored:", before.hwnd == after.hwnd)
