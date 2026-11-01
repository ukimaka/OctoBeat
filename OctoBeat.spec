# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OctoBeat (onedir build)."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve()
APP_NAME = "OctoBeat"

# icons/ and themes/ are looked up through paths.RESOURCE_DIR, which points
# at sys._MEIPASS (the _internal directory in a PyInstaller 6 onedir build).
datas = [
    (str(PROJECT_ROOT / "icons"), "icons"),
    (str(PROJECT_ROOT / "themes"), "themes"),
]

# Ship the project and third-party notices with the application.
for notice in ("LICENSE", "THIRD_PARTY_LICENSES.md"):
    path = PROJECT_ROOT / notice
    if path.is_file():
        datas.append((str(path), "."))

binaries = []
hiddenimports = [
    # Both bindings are imported lazily, so list them explicitly.
    "vlc",
    "yt_dlp",
]


def _find_windows_vlc():
    """Locate the 64-bit VLC installation used to bundle the runtime."""
    candidates = []
    explicit = os.environ.get("OCTOBEAT_VLC_DIR")
    if explicit:
        candidates.append(Path(explicit))
    for env_name in ("ProgramW6432", "ProgramFiles"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "VideoLAN" / "VLC")
    # ProgramFiles(x86) is intentionally not used: the Windows build
    # requires 64-bit VLC to match 64-bit Python.
    candidates.append(Path(r"C:\Program Files\VideoLAN\VLC"))

    for candidate in candidates:
        if (
            (candidate / "libvlc.dll").is_file()
            and (candidate / "libvlccore.dll").is_file()
        ):
            return candidate
    return None


if sys.platform == "win32":
    vlc_root = _find_windows_vlc()
    if vlc_root is None:
        raise SystemExit(
            "OctoBeat.spec: 64-bit VLC was not found. Install VLC or set "
            "OCTOBEAT_VLC_DIR to the VLC installation directory."
        )

    plugins_dir = vlc_root / "plugins"
    if not plugins_dir.is_dir():
        raise SystemExit(
            f"OctoBeat.spec: VLC plugins directory not found: {plugins_dir}"
        )

    # Copy all top-level VLC DLLs. Besides libvlc.dll and libvlccore.dll,
    # libvlccore depends on the MinGW runtime DLLs shipped by VLC.
    # Destination "vlc" matches vlc_backend._find_vlc_paths(
    # RESOURCE_DIR / "vlc").
    bundled_dlls = sorted(
        path for path in vlc_root.glob("*.dll") if path.is_file()
    )
    for dll in bundled_dlls:
        binaries.append((str(dll), "vlc"))

    for required in ("libvlc.dll", "libvlccore.dll"):
        if not (vlc_root / required).is_file():
            raise SystemExit(
                f"OctoBeat.spec: missing required VLC library: {required}"
            )

    # VLC's plugin tree contains codecs, demuxers, audio outputs, etc.
    # Keep this a 2-tuple (source, destination): PyInstaller expands the
    # directory recursively. Tree() returns 3-tuples, which Analysis()
    # rejects because it expects (source, destination) pairs.
    datas.append((str(plugins_dir), "vlc/plugins"))

    # Keep the VLC license texts next to the bundled runtime when present.
    for license_name in ("COPYING", "COPYING.LIB"):
        license_path = vlc_root / license_name
        if license_path.is_file():
            datas.append((str(license_path), "vlc"))


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# python-vlc uses ctypes, so PyInstaller may auto-collect the host libvlc
# without its plugin tree. On Linux/macOS OctoBeat deliberately uses the
# system VLC installation; keeping only the bare libraries would make
# libVLC look for plugins next to the frozen binary and fail. On Windows the
# runtime is bundled explicitly under vlc/ above, so drop duplicate copies at
# the bundle root.
def _vlc_library_name(destination):
    return Path(destination).name.lower().startswith(
        ("libvlc.", "libvlccore.")
    )


if sys.platform == "win32":
    a.binaries = [
        entry
        for entry in a.binaries
        if not (
            _vlc_library_name(entry[0])
            and not entry[0].replace("\\", "/").startswith("vlc/")
        )
    ]
else:
    a.binaries = [
        entry for entry in a.binaries if not _vlc_library_name(entry[0])
    ]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
