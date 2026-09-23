"""Windows plumbing: single instance, start-with-Windows, log redaction and rotation."""

import logging
import subprocess
import sys
import threading
import time
import winreg

import pytest

from voicecli import autostart, logs, singleton
from voicecli.audio import matches


@pytest.fixture
def names(monkeypatch):
    # Private names, so a real running voicecli doesn't interfere (and isn't disturbed).
    monkeypatch.setattr(singleton, "PREFIX", "Local\\VoiceCLI.pytest.")
    monkeypatch.setattr(singleton, "MUTEX", "Local\\VoiceCLI.pytest.Instance")


def test_second_instance_is_refused_and_can_signal_the_first(names):
    first = singleton.acquire()
    assert first is not None
    try:
        assert singleton.acquire() is None
        shown, quit_ = threading.Event(), threading.Event()
        first.listen({"show": shown.set, "quit": quit_.set})
        assert singleton.signal("show") and shown.wait(2)
        assert singleton.signal("quit") and quit_.wait(2)
    finally:
        first.release()
    again = singleton.acquire()
    assert again is not None
    again.release()


def test_signal_without_an_instance(names):
    assert singleton.signal("show") is False
    assert singleton.wait_gone(0.1) is True


def test_wait_gone_waits_for_the_process_to_exit(names):
    """--quit (used by the installer) must not return while the old exe is still loaded."""
    code = ("import time, voicecli.singleton as s; s.PREFIX = 'Local\\\\VoiceCLI.pytest.'; "
            "s.MUTEX = s.PREFIX + 'Instance'; i = s.acquire(); print('ready', flush=True); "
            "time.sleep(1.0); i.stop_listening(); time.sleep(1.0)")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    t0 = time.monotonic()
    assert singleton.wait_gone(10)
    assert time.monotonic() - t0 >= 1.8  # not at stop_listening, only once the process exits
    child.wait(5)


def test_autostart_round_trip():
    name = "VoiceCLI-pytest"
    try:
        autostart.set_enabled(True, name=name, cmd='"C:\\nowhere\\VoiceCLI.exe" --startup')
        assert autostart.enabled(name)
        # Task Manager's "Disable" flag wins over the Run value...
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, autostart.APPROVED_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, bytes([3] + [0] * 11))
        assert not autostart.enabled(name)
        # ...and turning it on from the app clears that flag.
        autostart.set_enabled(True, name=name, cmd='"C:\\nowhere\\VoiceCLI.exe" --startup')
        assert autostart.enabled(name)
    finally:
        autostart.set_enabled(False, name=name)
    assert not autostart.enabled(name)


def test_redaction_keeps_text_out_of_the_log_by_default():
    ev = {"type": "final", "text": "my password is hunter2", "audio_s": 1.0}
    assert logs.redact(ev, keep_text=False) == {"type": "final", "text": "<22 chars>", "audio_s": 1.0}
    assert logs.redact(ev, keep_text=True) is ev
    assert logs.redact({"type": "state", "state": "ready"}, keep_text=False) == {"type": "state", "state": "ready"}
    typed = {"type": "typed", "action": "typed", "window": "Q3 layoffs.docx - Word", "process": "WINWORD.EXE"}
    assert logs.redact(typed, keep_text=False)["window"] == "<22 chars>"
    assert logs.redact(typed, keep_text=False)["process"] == "WINWORD.EXE"
    target = {"type": "target", "target": {"hwnd": 5, "title": "Inbox - secret", "process": "outlook.exe"}}
    assert logs.redact(target, keep_text=False)["target"] == {"hwnd": 5, "process": "outlook.exe"}


def test_log_file_rotates(monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2000)
    root = logging.getLogger()
    before = list(root.handlers)
    path = logs.setup(console=False)
    try:
        for i in range(200):
            logging.getLogger("voicecli.test").info("line %d %s", i, "x" * 50)
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
    files = list(path.parent.glob("voicecli.log*"))
    assert 1 < len(files) <= logs.BACKUPS + 1
    assert all(f.stat().st_size <= 2200 for f in files)


@pytest.mark.parametrize("name,spec,expected", [
    ("Microphone (HyperX Cloud Alpha Wireless)", "hyperx", True),
    ("Microphone (HyperX Cloud Alpha ", "Microphone (HyperX Cloud Alpha Wireless)", True),  # MME cuts names
    ("Analogue 1 + 2 (2- Focusrite USB Audio)", "Microphone (HyperX Cloud Alpha Wireless)", False),
    ("", "hyperx", False),
])
def test_device_name_matching(name, spec, expected):
    assert matches(name, spec) is expected
