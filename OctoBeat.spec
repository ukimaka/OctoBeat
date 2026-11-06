# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: onedir-сборка OctoBeat.

onedir выбран вместо onefile: приложение стартует сразу, не распаковывая
сотни мегабайт Qt/VLC во временную папку при каждом запуске.

На Windows в сборку попадают libvlc.dll, libvlccore.dll и все плагины VLC.
VLC ищется в VLC_DIR (её выставляет GitHub Actions) или в стандартных путях
установки VideoLAN. На Linux/macOS системный VLC используется как раньше.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "themes"), "themes"),
    (str(ROOT / "icons"), "icons"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_LICENSES.md"), "."),
]
binaries = []
hiddenimports = []


def collect(package, required=True):
    """Добавляет пакет целиком: данные, бинарники и скрытые импорты."""
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as exc:
        if required:
            raise
        print(f"[spec] optional package skipped: {package} ({exc})")
        return
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)


# PyQt5 подтягивает Qt-плагины (platforms, styles, imageformats, sqldrivers).
collect("PyQt5")

# python-vlc: сам модуль vlc.py. libVLC добавляется отдельно ниже.
collect("vlc")

# Ленивые импорты: без collect_all эти пакеты теряются при анализе.
collect("yt_dlp")
collect("SomeDL")
# SomeDL использует ytmusicapi, который при импорте читает locales/*.mo.
# Без этих файлов frozen-сборка падает с "No translation file found".
collect("ytmusicapi")
collect("mutagen")
collect("pydub")
collect("numpy")

# Некоторые модули импортируются только по имени из данных/настроек.
hiddenimports += [
    "requests",
]

if sys.platform.startswith("linux"):
    hiddenimports += [
        "mpris_integration",
        "mpris_server",
    ]


def windows_vlc_assets():
    """Возвращает (datas, binaries) для libVLC из установленного VLC."""
    if not sys.platform.startswith("win"):
        return [], []

    candidates = []
    explicit = os.environ.get("VLC_DIR")
    if explicit:
        candidates.append(Path(explicit))
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(env_name)
        if program_files:
            candidates.append(Path(program_files) / "VideoLAN" / "VLC")

    for base in candidates:
        library = base / "libvlc.dll"
        core = base / "libvlccore.dll"
        plugins = base / "plugins"
        if not library.is_file() or not core.is_file():
            continue
        if not plugins.is_dir():
            continue

        print(f"[spec] bundling VLC from {base}")
        # Копируем все DLL из корня VLC: libvlc зависит не только от
        # libvlccore, но и от сопутствующих runtime-библиотек (libgcc,
        # libstdc++, libwinpthread и т.п.).
        vlc_binaries = [
            (str(dll), "vlc") for dll in sorted(base.glob("*.dll"))
        ]
        # vlc_backend ищет RESOURCE_DIR/vlc/libvlc.dll и .../plugins.
        return (
            [(str(plugins), "vlc/plugins")],
            vlc_binaries,
        )

    raise SystemExit(
        "VLC runtime not found. Install VLC or set VLC_DIR to the folder "
        "containing libvlc.dll, libvlccore.dll and plugins."
    )


vlc_datas, vlc_binaries = windows_vlc_assets()
datas.extend(vlc_datas)
binaries.extend(vlc_binaries)

icon_path = ROOT / "icons" / "icon.ico"

excludes = ["gi", "tkinter"]
if sys.platform.startswith("win"):
    # На Windows MPRIS (D-Bus) не используется и mpris_server не ставится.
    excludes += ["mpris_integration", "mpris_server"]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OctoBeat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OctoBeat",
)
