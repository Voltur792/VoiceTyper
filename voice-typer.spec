# -*- mode: python ; coding: utf-8 -*-

# PyInstaller spec for the standalone Voice Typer app.
# Build from the repo root:  pyinstaller voice-typer.spec --noconfirm
# → dist\VoiceTyper.exe (onefile; models are NOT bundled — put them in
#   models\ next to the exe or download them from the app's window).

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

here = os.path.abspath(SPECPATH)
icon = os.path.join(here, "app", "icon.ico")

# vosk loads libvosk.dll (and its mingw deps) via ctypes at runtime —
# PyInstaller can't see that, so collect the whole package's binaries.
vosk_binaries = collect_dynamic_libs("vosk")
# sounddevice ships the PortAudio library as data.
sounddevice_data = collect_data_files("sounddevice")

a = Analysis(
    ["app/main.py"],
    pathex=[here],
    binaries=vosk_binaries,
    datas=[(os.path.join(here, "app", "icon.png"), ".")] + sounddevice_data,
    hiddenimports=[
        "pystray", "PIL", "sounddevice", "vosk", "faster_whisper",
        "websockets", "requests", "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VoiceTyper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon if os.path.exists(icon) else None,
)
