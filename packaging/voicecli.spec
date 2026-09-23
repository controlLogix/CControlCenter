# PyInstaller spec for VoiceCLI.exe: a windowed (no console) one-folder build.
#   uv run pyinstaller packaging/voicecli.spec --noconfirm --clean --distpath dist --workpath build/pyinstaller
# One folder, not one file: it starts faster (nothing to unpack on each launch) and antivirus
# tools treat it more kindly. The Whisper models are added next to the exe by build.ps1.

import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "voicecli.ico")
init = open(os.path.join(ROOT, "src", "voicecli", "__init__.py"), encoding="utf-8").read()
VERSION = re.search(r'__version__ = "([^"]+)"', init).group(1)
nums = tuple(int(n) for n in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Voice CLI"),
            StringStruct("FileDescription", "Voice CLI – talk to any CLI"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "VoiceCLI"),
            StringStruct("OriginalFilename", "VoiceCLI.exe"),
            StringStruct("ProductName", "Voice CLI"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=collect_dynamic_libs("ctranslate2"),
    datas=collect_data_files("faster_whisper") + [(ICON, "assets")],
    # onnxruntime is only needed for faster-whisper's VAD filter, which voicecli does not use.
    excludes=["onnxruntime", "pytest", "PIL", "matplotlib", "IPython", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceCLI",
    console=False,
    icon=ICON,
    version=version_info,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VoiceCLI", upx=False)
