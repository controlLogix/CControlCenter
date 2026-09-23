"""Start with Windows: the per-user Run key entry (the same one the installer writes).

Task Manager's Startup tab disables an entry without deleting it, by writing a flag under
Explorer\\StartupApproved\\Run, so both keys decide whether voicecli starts at logon."""

from __future__ import annotations

import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
NAME = "VoiceCLI"
ENABLED_FLAG = bytes([2] + [0] * 11)  # first byte 2 = enabled, 3 = disabled by the user


def command() -> str:
    return f'"{sys.executable}" --startup'


def _read(key: str, name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def enabled(name: str = NAME) -> bool:
    if not _read(RUN_KEY, name):
        return False
    approved = _read(APPROVED_KEY, name)
    return not (isinstance(approved, bytes) and approved[:1] == b"\x03")


def set_enabled(on: bool, name: str = NAME, cmd: str | None = None) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd or command())
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
    # Clear a Task Manager "disabled" flag so turning it on here really turns it on.
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
        try:
            if on:
                winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, ENABLED_FLAG)
            else:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass
