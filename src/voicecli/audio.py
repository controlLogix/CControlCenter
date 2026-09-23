"""Microphone discovery and capture, resampled to 16 kHz mono float32."""

from __future__ import annotations

import ctypes
import queue
import time
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

TARGET_RATE = 16000
PREFERRED_HOSTAPI = "Windows WASAPI"


@dataclass
class InputDevice:
    index: int
    name: str
    hostapi: str
    rate: int
    channels: int
    is_default: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def list_inputs(all_apis: bool = False) -> list[InputDevice]:
    """Input devices. By default only the WASAPI view (one entry per physical mic)."""
    hostapis = sd.query_hostapis()
    default_in = sd.default.device[0]
    default_name = sd.query_devices(default_in)["name"] if default_in is not None and default_in >= 0 else ""
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        api = hostapis[d["hostapi"]]["name"]
        if not all_apis and api != PREFERRED_HOSTAPI:
            continue
        out.append(
            InputDevice(
                index=i,
                name=d["name"],
                hostapi=api,
                rate=int(d["default_samplerate"]),
                channels=int(d["max_input_channels"]),
                # MME truncates names to 31 chars, so compare by prefix.
                is_default=bool(default_name) and d["name"].startswith(default_name.rstrip()[:28]),
            )
        )
    if not out and not all_apis:
        return list_inputs(all_apis=True)
    return out


def refresh() -> None:
    """Re-scan audio devices. PortAudio lists them once when it starts, so a mic plugged in
    (or a headset switched on) later stays invisible until it is re-initialised. Close every
    open stream first."""
    sd._terminate()
    sd._initialize()


class _WAVEINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD),
                ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD)]


def system_input_names() -> list[str]:
    """Input names straight from Windows (MME, cut at 31 characters). Unlike PortAudio's list
    this is always current, and reading it does not disturb an open stream."""
    winmm = ctypes.WinDLL("winmm")
    names = []
    caps = _WAVEINCAPSW()
    for i in range(winmm.waveInGetNumDevs()):
        if winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def matches(name: str, spec: str) -> bool:
    """Does device `name` fit the user's `spec` (a name substring, possibly MME-truncated)?"""
    name, spec = name.lower().rstrip(), spec.lower()
    if not name or not spec:
        return False
    return spec in name or spec.startswith(name[:28]) or name.startswith(spec[:28])


def present(spec: str) -> bool:
    return any(matches(n, spec) for n in system_input_names())


def resolve_device(spec: str | int | None) -> InputDevice:
    """Match a device by index, or by case-insensitive name substring; None means the default."""
    devices = list_inputs()
    if not devices:
        raise ValueError("no microphone found")
    if spec is None or spec == "":
        return next((d for d in devices if d.is_default), devices[0])
    if isinstance(spec, int) or str(spec).isdigit():
        idx = int(spec)
        for d in list_inputs(all_apis=True):
            if d.index == idx:
                return d
        raise ValueError(f"no input device with index {idx}")
    needle = str(spec).lower()
    matches = [d for d in devices if needle in d.name.lower()] or [
        d for d in list_inputs(all_apis=True) if needle in d.name.lower()
    ]
    if not matches:
        raise ValueError(f"no input device matching {spec!r}")
    return matches[0]


FALLBACK_APIS = ("Windows WASAPI", "Windows DirectSound", "MME")


def _same_mic_other_apis(dev: InputDevice) -> list[InputDevice]:
    # MME cuts names at 31 characters, so match on a shared prefix.
    key = dev.name[:28].lower()
    others = [d for d in list_inputs(all_apis=True)
              if d.index != dev.index and d.hostapi in FALLBACK_APIS
              and (d.name.lower().startswith(key) or dev.name.lower().startswith(d.name.lower().rstrip()[:28]))]
    return sorted(others, key=lambda d: FALLBACK_APIS.index(d.hostapi))


def _resample(x: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate == TARGET_RATE:
        return x
    n_out = int(round(len(x) * TARGET_RATE / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    t_out = np.linspace(0, len(x) - 1, n_out)
    return np.interp(t_out, np.arange(len(x)), x).astype(np.float32)


class MicStream:
    """Captures from one device and puts 16 kHz mono float32 blocks on `self.blocks`."""

    def __init__(self, device: InputDevice, block_ms: int = 30):
        self.device = device
        self.blocks: queue.Queue[np.ndarray] = queue.Queue()
        self._block_ms = block_ms
        self._frames = int(device.rate * block_ms / 1000)
        self._stream: sd.InputStream | None = None
        self.last_block = 0.0  # time.monotonic() of the latest audio callback

    def _callback(self, indata, frames, time_info, status) -> None:
        self.last_block = time.monotonic()
        mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
        self.blocks.put(_resample(mono.astype(np.float32, copy=False), self.device.rate))

    def stalled(self, seconds: float) -> bool:
        """True if the open stream has delivered nothing for `seconds` (device gone)."""
        if self._stream is None:
            return False
        return not self._stream.active or time.monotonic() - self.last_block > seconds

    def _open(self, dev: InputDevice) -> sd.InputStream:
        self._frames = int(dev.rate * self._block_ms / 1000)
        stream = sd.InputStream(
            device=dev.index,
            samplerate=dev.rate,
            channels=min(dev.channels, 2),
            dtype="float32",
            blocksize=self._frames,
            callback=self._callback,
        )
        stream.start()
        return stream

    def start(self) -> None:
        """Open the device; if its host API refuses, retry the same mic through the others."""
        errors = []
        for dev in [self.device] + _same_mic_other_apis(self.device):
            try:
                self.last_block = time.monotonic()
                self._stream = self._open(dev)
                self.device = dev
                return
            except sd.PortAudioError as e:
                errors.append(f"{dev.hostapi}: {e}")
        raise OSError(f"could not open {self.device.name!r} — " + "; ".join(errors))

    def stop(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError:
                pass  # the device is already gone
