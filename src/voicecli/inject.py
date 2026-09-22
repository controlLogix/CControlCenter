"""Win32 plumbing: type text into the focused window and listen for a global hotkey."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput was blocked (is the target window elevated?)")


def type_text(text: str) -> None:
    """Type `text` as Unicode key events; UTF-16 surrogate pairs cover characters beyond the BMP."""
    units = text.encode("utf-16-le")
    inputs: list[INPUT] = []
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i:i + 2], "little")
        inputs.append(_key(scan=code, flags=KEYEVENTF_UNICODE))
        inputs.append(_key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    for i in range(0, len(inputs), 200):  # keep batches small so slow terminals keep up
        _send(inputs[i:i + 200])


def press_enter() -> None:
    _send([_key(vk=VK_RETURN), _key(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)])


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


# -- global hotkey ------------------------------------------------------------

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
NAMED_VK = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "pause": 0x13,
            **{f"f{n}": 0x6F + n for n in range(1, 13)}}
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def parse_hotkey(spec: str) -> tuple[int, int]:
    mods, vk = MOD_NOREPEAT, None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MOD:
            mods |= MOD[part]
        elif part in NAMED_VK:
            vk = NAMED_VK[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"unknown key {part!r} in hotkey {spec!r}")
    if vk is None:
        raise ValueError(f"hotkey {spec!r} has no main key")
    return mods, vk


class HotkeyListener:
    """RegisterHotKey on a dedicated thread with its own message loop."""

    def __init__(self, spec: str, on_press: Callable[[], None]):
        self.mods, self.vk = parse_hotkey(spec)
        self.spec = spec
        self.on_press = on_press
        self._thread_id = 0
        self.error: str | None = None
        self._ready = threading.Event()

    def start(self) -> bool:
        threading.Thread(target=self._run, name="hotkey", daemon=True).start()
        self._ready.wait(2)
        return self.error is None

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.mods, self.vk):
            self.error = f"could not register {self.spec} (already in use?)"
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.on_press()
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
