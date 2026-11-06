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

"""Утилиты для путей: нормализация, поиск инструментов и subprocess."""

import os
import shutil
import subprocess
import sys
import time

from paths import RESOURCE_DIR


def normalize_track_path(path):
    """Нормализует путь для хранения и поиска в БД.

    ``normcase`` убирает различия регистра и разделителей на Windows, а
    ``abspath`` избавляет от ``..`` и относительных путей. На Linux функция
    по-прежнему возвращает абсолютный путь без изменения регистра.
    """
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def paths_equal(first, second):
    """Сравнивает два пути с учётом правил текущей файловой системы."""
    return normalize_track_path(first) == normalize_track_path(second)


def unique_path(path, current_path=None, is_taken=None):
    """Возвращает свободный путь, добавляя `` (2)``, `` (3)`` и т.д.

    ``current_path`` — текущее имя файла. Если целевой путь совпадает с ним
    (например, меняется только регистр на Windows), конфликта нет.

    ``is_taken`` — необязательная функция для дополнительных проверок
    (например, занятости пути в базе данных).
    """
    if current_path is not None and paths_equal(path, current_path):
        return path

    def taken(candidate):
        if os.path.exists(candidate):
            return True
        return bool(is_taken and is_taken(candidate))

    if not taken(path):
        return path

    absolute = os.path.abspath(os.fspath(path))
    root, ext = os.path.splitext(absolute)
    counter = 2
    candidate = f"{root} ({counter}){ext}"
    while taken(candidate):
        counter += 1
        candidate = f"{root} ({counter}){ext}"
    return candidate


def find_tool(name):
    """Ищет исполняемый файл в папке bin приложения, рядом с ним, затем в PATH.

    ``<data>/bin`` — место, куда авто-установщик кладёт FFmpeg. Локальная
    копия важнее системной, иначе скачанная сборка может «проиграть»
    старой версии из PATH.

    ``RESOURCE_DIR`` — папка ресурсов (в PyInstaller это ``_MEIPASS``).
    ``shutil.which`` с явным ``path`` учитывает расширения Windows
    (``.exe``, ``.cmd``) и права на запуск на Unix.
    """
    try:
        from dependencies import local_tool_path

        local_binary = local_tool_path(name)
        if local_binary is not None:
            return str(local_binary)
    except Exception:
        pass

    local = shutil.which(name, path=str(RESOURCE_DIR))
    if local:
        return local
    return shutil.which(name)


def subprocess_env():
    """Окружение для фоновых процессов с принудительным UTF-8.

    Если FFmpeg скачан в ``<data>/bin``, эта папка добавляется в начало
    PATH: SomeDL и запускаемый им yt-dlp CLI найдут именно нашу сборку.
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    try:
        from dependencies import augment_environment

        augment_environment(env)
    except Exception:
        pass
    return env


def subprocess_creationflags():
    """Не показывает консольные окна при запуске дочерних процессов."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def safe_replace(src, dst, retries=3, delay=0.5):
    """Заменяет файл через ``os.replace`` с повторами при блокировке.

    На Windows антивирус или индексатор могут ненадолго удерживать файл
    после записи. После исчерпания попыток исключение пробрасывается.
    """
    for attempt in range(retries + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt >= retries:
                raise
            time.sleep(delay)
