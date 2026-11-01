# OctoBeat - музыкальный плеер
# Copyright (C) 2026 ukimaka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Централизованные пути приложения (Windows, macOS, Linux).

Пути данных и кэша берутся у Qt (``QStandardPaths``), поэтому на каждой
платформе приложение использует положенные ей каталоги. Каталоги данных и
кэша создаются при импорте модуля.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QStandardPaths

APP_NAME = "OctoBeat"

# QStandardPaths читает имя приложения из QCoreApplication. paths.py может
# импортироваться раньше создания QApplication (например, из db.py), поэтому
# задаём имя сразу. Организацию не задаём: иначе Qt добавит лишний уровень
# в путь (``OctoBeat/OctoBeat``).
QCoreApplication.setApplicationName(APP_NAME)


def _writable_location(location, fallback):
    """Возвращает каталог Qt либо запасной путь, если Qt его не знает."""
    value = QStandardPaths.writableLocation(location)
    return Path(value) if value else fallback


def _fallback_data_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def _fallback_cache_dir():
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        return base / APP_NAME / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / APP_NAME


def _ensure_dir(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[paths] cannot create {directory}: {exc}")


DATA_DIR = _writable_location(
    QStandardPaths.AppDataLocation,
    _fallback_data_dir(),
)
CACHE_DIR = _writable_location(
    QStandardPaths.CacheLocation,
    _fallback_cache_dir(),
)
DB_FILE = DATA_DIR / "music.db"
MUSIC_DIR = _writable_location(
    QStandardPaths.MusicLocation,
    Path.home() / "Music",
)

if hasattr(sys, "_MEIPASS"):
    RESOURCE_DIR = Path(sys._MEIPASS)
else:
    RESOURCE_DIR = Path(__file__).parent

_ensure_dir(DATA_DIR)
_ensure_dir(CACHE_DIR)

# Старые места хранения данных (до перехода на QStandardPaths).
LEGACY_DATA_DIR = Path.home() / ".local" / "share" / "music_player"
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).resolve().parent
else:
    _APP_DIR = Path(__file__).resolve().parent
LEGACY_DB_FILE = _APP_DIR / "music.db"


def _copy_missing(source, target):
    """Копирует файлы, не перезаписывая уже существующие данные."""
    try:
        for root, _dirs, files in os.walk(source):
            relative = Path(root).relative_to(source)
            destination = target / relative
            destination.mkdir(parents=True, exist_ok=True)
            for name in files:
                src = Path(root) / name
                dst = destination / name
                if dst.exists():
                    continue
                try:
                    shutil.copy2(src, dst)
                except OSError as exc:
                    print(f"[paths] cannot migrate {src}: {exc}")
    except OSError as exc:
        print(f"[paths] cannot migrate {source}: {exc}")


def migrate_old_data():
    """Переносит данные из старых каталогов, не затирая новые файлы."""
    if LEGACY_DATA_DIR.is_dir():
        _copy_missing(LEGACY_DATA_DIR, DATA_DIR)

    # Раньше music.db лежала рядом с исходниками. Переносим её только при
    # отсутствии новой базы, вместе с WAL-файлами, чтобы не потерять данные.
    if LEGACY_DB_FILE.is_file() and not DB_FILE.exists():
        _ensure_dir(DATA_DIR)
        # WAL и SHM копируем первыми: основная база появится последней,
        # поэтому прерванная миграция повторится при следующем запуске.
        for suffix in ("-wal", "-shm", ""):
            source = Path(str(LEGACY_DB_FILE) + suffix)
            if source.is_file():
                try:
                    shutil.copy2(source, Path(str(DB_FILE) + suffix))
                except OSError as exc:
                    print(f"[paths] cannot migrate {source}: {exc}")
