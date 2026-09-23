"""Microphone recovery: what the watchdog does when the mic stalls, vanishes or comes back."""

import pytest

from voicecli import app as appmod
from voicecli.app import App
from voicecli.audio import InputDevice
from voicecli.config import Config

HEADSET = InputDevice(1, "Microphone (HyperX Cloud Alpha Wireless)", "Windows WASAPI", 48000, 1)
BUILTIN = InputDevice(2, "Microphone Array (Realtek Audio)", "Windows WASAPI", 48000, 2, is_default=True)


class FakeMic:
    def __init__(self, device):
        self.device = device
        self.is_stalled = False

    def stalled(self, seconds):
        return self.is_stalled


class FakeTranscriber:
    def __init__(self):
        self.mic = None

    def set_mic(self, mic):
        self.mic = mic

    def detach_mic(self):
        self.mic = None


@pytest.fixture
def world(monkeypatch):
    """Which mics Windows currently has; the app sees them through resolve_device/present."""
    attached = {HEADSET.name: HEADSET, BUILTIN.name: BUILTIN}

    def resolve(spec):
        if not attached:
            raise ValueError("no microphone found")
        if not spec:
            return next(d for d in attached.values() if d.is_default) if BUILTIN.name in attached else next(iter(attached.values()))
        for d in attached.values():
            if spec.lower() in d.name.lower():
                return d
        raise ValueError(f"no input device matching {spec!r}")

    monkeypatch.setattr(appmod, "resolve_device", resolve)
    monkeypatch.setattr(appmod, "MicStream", FakeMic)
    monkeypatch.setattr(appmod.audio, "refresh", lambda: None)
    monkeypatch.setattr(appmod.audio, "present", lambda spec: any(spec.lower() in n.lower() for n in attached))
    return attached


@pytest.fixture
def app(world):
    a = App(Config(device="hyperx"), overlay=False, console=False)
    a.events = []
    emit = a.emit
    a.emit = lambda ev: (a.events.append(ev), emit(ev))
    a.transcriber = FakeTranscriber()
    return a


def hints(app):
    return [e["message"] for e in app.events if e["type"] == "hint"]


def test_missing_mic_at_startup_falls_back_instead_of_exiting(app, world):
    del world[HEADSET.name]
    device, fallback = app._pick_device()
    assert device is BUILTIN and fallback


def test_stalled_mic_is_reopened(app):
    app.transcriber.mic = FakeMic(HEADSET)
    app.transcriber.mic.is_stalled = True
    app._check_mic()
    assert app.transcriber.mic.device is HEADSET and not app.transcriber.mic.is_stalled
    assert hints(app)[0].startswith("Lost Microphone (HyperX") and hints(app)[-1].startswith("Microphone ready")


def test_headset_off_then_on(app, world):
    app.transcriber.mic = FakeMic(HEADSET)
    del world[HEADSET.name]  # headset switched off: its stream stops
    app.transcriber.mic.is_stalled = True
    app._check_mic()
    assert app.transcriber.mic.device is BUILTIN  # meanwhile, the built-in mic
    app._check_mic()
    assert app.transcriber.mic.device is BUILTIN  # headset still off: stay put

    world[HEADSET.name] = HEADSET  # headset back on
    app._retry_at = 0
    app._check_mic()
    assert app.transcriber.mic.device is HEADSET
    assert hints(app)[-1] == f"Microphone ready: {HEADSET.name}"


def test_no_mic_at_all_waits_and_retries(app, world):
    world.clear()
    app._check_mic()
    assert app.transcriber.mic is None and app.device is None
    assert any(e["type"] == "error" and "no microphone" in e["message"] for e in app.events)
    app._check_mic()  # inside the retry window: no second attempt
    assert sum(e["type"] == "error" for e in app.events) == 1
    world[BUILTIN.name] = BUILTIN
    app._retry_at = 0
    app._check_mic()
    assert app.transcriber.mic.device is BUILTIN
