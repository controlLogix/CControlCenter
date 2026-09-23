"""One instance per Windows session: a named mutex, plus named events a second launch
(or the installer) uses to ask the running instance to show itself or quit."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForMultipleObjects.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD)
kernel32.WaitForMultipleObjects.restype = wintypes.DWORD

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF

# "Local\" scopes the names to this logon session, so each signed-in user has their own.
PREFIX = "Local\\VoiceCLI."
MUTEX = PREFIX + "Instance"
SIGNALS = ("show", "quit")


def _event_name(signal: str) -> str:
    return PREFIX + signal.capitalize()


class Instance:
    """Holds the mutex while voicecli runs; call `listen` to act on show/quit signals."""

    def __init__(self, mutex: int):
        self._mutex = mutex
        self._events = {s: kernel32.CreateEventW(None, False, False, _event_name(s)) for s in SIGNALS}
        self._stop = kernel32.CreateEventW(None, True, False, None)
        self._thread: threading.Thread | None = None

    def listen(self, handlers: dict[str, Callable[[], None]]) -> None:
        signals = [s for s in SIGNALS if s in handlers and self._events[s]]
        handles = (wintypes.HANDLE * (len(signals) + 1))(self._stop, *(self._events[s] for s in signals))

        def run():
            while True:
                i = kernel32.WaitForMultipleObjects(len(handles), handles, False, INFINITE)
                if i == WAIT_OBJECT_0 or not WAIT_OBJECT_0 < i <= len(signals):
                    return
                handlers[signals[i - 1]]()

        self._thread = threading.Thread(target=run, name="instance-signals", daemon=True)
        self._thread.start()

    def stop_listening(self) -> None:
        """Stop answering show/quit, but keep the mutex. Windows releases it only when the process
        has fully exited, which is what `wait_gone` (and so the installer) must wait for: until
        then the exe and its DLLs are still locked."""
        if self._stop:
            kernel32.SetEvent(self._stop)
        if self._thread is not None:
            self._thread.join(1)
            self._thread = None
        for handle in (*self._events.values(), self._stop):
            if handle:
                kernel32.CloseHandle(handle)
        self._events, self._stop = {}, None

    def release(self) -> None:
        self.stop_listening()
        if self._mutex:
            kernel32.ReleaseMutex(self._mutex)
            kernel32.CloseHandle(self._mutex)
            self._mutex = 0


def acquire() -> Instance | None:
    """The Instance if this is the first voicecli in the session, else None."""
    handle = kernel32.CreateMutexW(None, True, MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return Instance(handle)


def signal(name: str) -> bool:
    """Ask the running instance to `show` or `quit`. False if none is listening."""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, _event_name(name))
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def wait_gone(timeout_s: float) -> bool:
    """Wait for the running instance to exit. True once no instance holds the mutex (a running
    voicecli holds it until its process is gone)."""
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX)
    if not handle:
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout_s * 1000))
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            kernel32.ReleaseMutex(handle)
            return True
        return False
    finally:
        kernel32.CloseHandle(handle)
