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

"""Поиск, импорт и удаление cookies.txt для yt-dlp.

Пользователь не выбирает браузер: приложение ищет готовый Netscape
cookies.txt в своём каталоге данных и в музыкальной папке. Импорт копирует
выбранный файл в каталог данных, откуда yt-dlp всегда его подхватит.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt5.QtCore import QSettings

from paths import DATA_DIR, MUSIC_DIR

COOKIES_NAME = "cookies.txt"
APP_COOKIES_FILE = DATA_DIR / COOKIES_NAME


def _download_dir() -> Path | None:
    """Папка загрузок из настроек, если она отличается от MUSIC_DIR."""
    try:
        value = QSettings("MusicPlayer", "MusicPlayer").value(
            "download_dir", str(MUSIC_DIR)
        )
        return Path(value) if value else None
    except Exception:
        return None


def cookie_candidates(extra_folder: Path | str | None = None) -> list[Path]:
    """Все известные места cookies.txt в порядке приоритета."""
    candidates: list[Path] = [APP_COOKIES_FILE, MUSIC_DIR / COOKIES_NAME]
    download_dir = _download_dir()
    if download_dir is not None:
        candidates.append(download_dir / COOKIES_NAME)
    if extra_folder is not None:
        candidates.append(Path(extra_folder) / COOKIES_NAME)

    unique: list[Path] = []
    seen = set()
    for path in candidates:
        try:
            key = path.expanduser().resolve()
        except OSError:
            key = path
        if key not in seen:
            seen.add(key)
            unique.append(path.expanduser())
    return unique


def find_cookies_file(extra_folder: Path | str | None = None) -> Path | None:
    """Возвращает первый существующий непустой cookies.txt или None."""
    for path in cookie_candidates(extra_folder):
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def import_cookies(source: Path | str) -> Path:
    """Копирует выбранный cookies.txt в каталог данных приложения."""
    source_path = Path(source).expanduser()
    if not source_path.is_file() or source_path.stat().st_size <= 0:
        raise OSError("cookies.txt is empty or missing")

    target = APP_COOKIES_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != target.resolve():
        shutil.copyfile(source_path, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def remove_cookies() -> list[Path]:
    """Удаляет cookies.txt из всех известных мест. Возвращает удалённые."""
    removed: list[Path] = []
    for path in cookie_candidates():
        try:
            if path.is_file():
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed
