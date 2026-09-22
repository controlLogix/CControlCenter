"""Win32 plumbing: typing into windows, finding and focusing windows, global hotkeys
and a held push-to-talk key."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

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
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short


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


MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # shift, ctrl, alt, lwin, rwin


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def wait_modifiers_released(timeout: float = 2.0) -> None:
    """Typing while Ctrl/Alt/Win is physically held would turn letters into shortcuts."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and any(key_down(vk) for vk in MODIFIER_VKS):
        time.sleep(0.02)


# -- windows --------------------------------------------------------------------

@dataclass
class Window:
    hwnd: int
    title: str
    cls: str
    pid: int
    process: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @property
    def label(self) -> str:
        title = self.title if len(self.title) <= 60 else self.title[:57] + "…"
        return f"{title}  —  {self.process}" if self.process else title


# Shell surfaces: typing there does nothing useful except make Windows ding.
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland"}


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_info(hwnd: int) -> Window:
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return Window(int(hwnd or 0), title.value, cls.value, pid.value, _process_name(pid.value))


def foreground() -> Window:
    return window_info(user32.GetForegroundWindow())


def foreground_title() -> str:
    return foreground().title


def is_alive(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def typeable(win: Window) -> tuple[bool, str]:
    if not win.hwnd:
        return False, "no window has focus"
    if win.pid == os.getpid():
        return False, "the overlay has focus. Click into your CLI first"
    if win.cls in SHELL_CLASSES:
        return False, "the desktop/taskbar has focus. Click into your CLI first"
    return True, ""


def _cloaked(hwnd: int) -> bool:
    val = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val))  # DWMWA_CLOAKED
    return val.value != 0


def list_windows() -> list[Window]:
    """Top-level app windows, the same set Alt+Tab shows."""
    found: list[Window] = []
    me = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80 or _cloaked(hwnd):  # WS_EX_TOOLWINDOW
            return True
        w = window_info(hwnd)
        if w.title and w.pid != me and w.cls not in SHELL_CLASSES:
            found.append(w)
        return True

    user32.EnumWindows(cb, 0)
    return found


def focus(hwnd: int, timeout: float = 0.6) -> bool:
    """Bring `hwnd` to the foreground. Windows only lets the foreground thread do that,
    so borrow its input queue with AttachThreadInput."""
    if not is_alive(hwnd):
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    me = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    attached = fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


# -- key names ------------------------------------------------------------------

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
KEY_VK = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "pause": 0x13, "capslock": 0x14,
    "scrolllock": 0x91, "insert": 0x2D, "apps": 0x5D, "menu": 0x5D,
    "ctrl": 0x11, "lctrl": 0xA2, "rctrl": 0xA3, "alt": 0x12, "lalt": 0xA4, "ralt": 0xA5,
    "shift": 0x10, "lshift": 0xA0, "rshift": 0xA1, "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "mouse4": 0x05, "mouse5": 0x06,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}
KEY_LABEL = {"rctrl": "Right Ctrl", "lctrl": "Left Ctrl", "ralt": "Right Alt", "lalt": "Left Alt",
             "rshift": "Right Shift", "lshift": "Left Shift", "mouse4": "Mouse 4", "mouse5": "Mouse 5",
             "capslock": "Caps Lock", "scrolllock": "Scroll Lock"}


def _vk(name: str) -> int:
    if name in KEY_VK:
        return KEY_VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    raise ValueError(f"unknown key {name!r}")


def key_label(spec: str) -> str:
    return "+".join(KEY_LABEL.get(p, p.capitalize()) for p in spec.lower().replace(" ", "").split("+"))


def parse_hotkey(spec: str) -> tuple[int, int]:
    mods, vk = MOD_NOREPEAT, None
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MOD:
            mods |= MOD[part]
        else:
            vk = _vk(part)
    if vk is None:
        raise ValueError(f"hotkey {spec!r} has no main key")
    return mods, vk


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class HotkeyListener:
    """RegisterHotKey for several combos on one thread with its own message loop."""

    def __init__(self, bindings: dict[str, Callable[[], None]]):
        self.bindings = [(spec, parse_hotkey(spec), cb) for spec, cb in bindings.items() if spec]
        self.errors: list[str] = []
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self) -> list[str]:
        threading.Thread(target=self._run, name="hotkeys", daemon=True).start()
        self._ready.wait(2)
        return self.errors

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        registered = {}
        for i, (spec, (mods, vk), cb) in enumerate(self.bindings, start=1):
            if user32.RegisterHotKey(None, i, mods, vk):
                registered[i] = cb
            else:
                self.errors.append(f"could not register {spec} (already in use?)")
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in registered:
                registered[msg.wParam]()
        for i in registered:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class HoldKey:
    """Polls a key (or combo such as ctrl+win) and reports press/release, for push-to-talk.
    Polling GetAsyncKeyState needs no hook and never swallows the key."""

    def __init__(self, spec: str, on_change: Callable[[bool], None], poll_s: float = 0.015):
        self.spec = spec
        self.vks = [_vk(p) for p in spec.lower().replace(" ", "").split("+")]
        self.on_change = on_change
        self.poll_s = poll_s
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="ptt", daemon=True).start()

    def _run(self) -> None:
        held = False
        while not self._stop.is_set():
            now = all(key_down(vk) for vk in self.vks)
            if now != held:
                held = now
                self.on_change(held)
            time.sleep(self.poll_s)

    def stop(self) -> None:
        self._stop.set()
