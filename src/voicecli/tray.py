"""Notification-area (tray) icon: a hidden window with its own message loop on a thread.

Left-click runs `on_click`; right-click shows the menu built by `menu()` at that moment,
so checkmarks always reflect the current state. The icon is re-added when Explorer
restarts (the "TaskbarCreated" broadcast)."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.RegisterClassW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPVOID)
user32.LoadIconW.restype = wintypes.HICON
user32.DestroyIcon.argtypes = (wintypes.HICON,)
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
user32.TrackPopupMenu.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID)
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = (wintypes.HMENU,)
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.restype = LRESULT
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WM_NULL, WM_DESTROY, WM_CLOSE, WM_CONTEXTMENU = 0x0000, 0x0002, 0x0010, 0x007B
WM_LBUTTONUP, WM_RBUTTONUP, WM_APP = 0x0202, 0x0205, 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None] | None = None
    checked: bool = False
    enabled: bool = True


SEPARATOR = None


class Tray:
    def __init__(self, icon: Path, tooltip: str, on_click: Callable[[], None],
                 menu: Callable[[], list[MenuItem | None]]):
        self.icon_path = icon
        self.tooltip = tooltip
        self.on_click = on_click
        self.menu = menu
        self.hwnd = None
        self._class = f"VoiceCLI.Tray.{id(self)}"
        self._hicon = None
        self._taskbar_created = -1
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    # -- public (any thread) -------------------------------------------------

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        return self.hwnd is not None

    def stop(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(2)

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text
        self._notify(NIM_MODIFY, NIF_TIP)

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        """Windows notification from the tray icon."""
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = message[:255]
        nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # -- tray thread ---------------------------------------------------------

    def _nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1, uFlags=flags,
                              uCallbackMessage=WM_TRAY, hIcon=self._hicon)
        nid.szTip = self.tooltip[:127]
        return nid

    def _notify(self, op: int, flags: int) -> bool:
        if not self.hwnd:
            return False
        return bool(shell32.Shell_NotifyIconW(op, ctypes.byref(self._nid(flags))))

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._proc)  # keep a reference: Windows calls it for the window's life
        wc = WNDCLASSW(lpfnWndProc=self._wndproc, hInstance=hinst, lpszClassName=self._class)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.error("tray: RegisterClassW failed (%s)", ctypes.get_last_error())
            self._ready.set()
            return
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        # A real (hidden) top-level window, not message-only, so it receives the TaskbarCreated broadcast.
        self.hwnd = user32.CreateWindowExW(0, self._class, "Voice CLI", 0, 0, 0, 0, 0, None, None, hinst, None)
        self._hicon = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, user32.GetSystemMetrics(SM_CXSMICON),
                                        user32.GetSystemMetrics(SM_CYSMICON), LR_LOADFROMFILE)
        self._owns_icon = bool(self._hicon)
        if not self._hicon:
            self._hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        if not self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP):
            log.warning("tray: could not add the notification icon")
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._owns_icon:
            user32.DestroyIcon(self._hicon)
        user32.UnregisterClassW(self._class, hinst)

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP:
                self._safe(self.on_click)
            elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            return 0
        if msg == self._taskbar_created:  # Explorer restarted: the icon is gone, add it again
            self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._notify(NIM_DELETE, 0)
            self.hwnd = None
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        hmenu = user32.CreatePopupMenu()
        actions = {}
        try:
            for i, item in enumerate(self.menu(), start=1):
                if item is SEPARATOR:
                    user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                    continue
                flags = MF_STRING | (MF_CHECKED if item.checked else 0) | (0 if item.enabled else MF_GRAYED)
                user32.AppendMenuW(hmenu, flags, i, item.label)
                if item.action:
                    actions[i] = item.action
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # Without this the menu doesn't close when the user clicks elsewhere.
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON,
                                        pt.x, pt.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(hmenu)
        if cmd in actions:
            self._safe(actions[cmd])

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:  # a failing menu action must not take down the tray thread
            log.exception("tray action failed")
