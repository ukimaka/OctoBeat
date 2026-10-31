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

"""Проверка, загрузка и установка обновлений с GitHub Releases.

Используются только ``requests``, ``QThread`` и стандартная библиотека.
"""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from version import __version__

RELEASES_API = "https://api.github.com/repos/ukimaka/OctoBeat/releases/latest"
REQUEST_TIMEOUT = 15
CHUNK_SIZE = 64 * 1024


def _parse_version(text):
    """Превращает ``v1.0.1`` в ``(1, 0, 1)``; хвосты после цифр отбрасываются."""
    cleaned = str(text or "").strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


class UpdateChecker(QThread):
    """Запрашивает последний релиз и сравнивает его версию с текущей."""

    update_available = pyqtSignal(str, str)   # версия, ссылка на файл
    no_update = pyqtSignal()

    def run(self):
        try:
            response = requests.get(
                RELEASES_API,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            self.no_update.emit()
            return

        tag = str(data.get("tag_name") or "")
        if not tag or _parse_version(tag) <= _parse_version(__version__):
            self.no_update.emit()
            return

        url = self._download_url(data)
        if not url:
            self.no_update.emit()
            return

        self.update_available.emit(tag.lstrip("vV"), url)

    @staticmethod
    def _download_url(data):
        """Выбирает файл релиза под текущую платформу."""
        assets = [a for a in (data.get("assets") or []) if a.get("browser_download_url")]
        if not assets:
            return ""

        wanted = ".exe" if sys.platform.startswith("win") else ".appimage"
        for asset in assets:
            if str(asset.get("name") or "").lower().endswith(wanted):
                return asset["browser_download_url"]
        return assets[0]["browser_download_url"]


class UpdateDownloader(QThread):
    """Скачивает файл обновления во временную папку."""

    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._url = url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            with requests.get(
                self._url, stream=True, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                dest = Path(tempfile.gettempdir()) / self._filename(response)
                total = int(response.headers.get("Content-Length") or 0)
                received = 0

                with open(dest, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if self._cancelled:
                            break
                        if not chunk:
                            continue
                        handle.write(chunk)
                        received += len(chunk)
                        if total > 0:
                            self.progress.emit(
                                min(100, int(received * 100 / total))
                            )

                if self._cancelled:
                    try:
                        dest.unlink()
                    except OSError:
                        pass
                    self.error.emit("")
                    return

                self.progress.emit(100)
                self.finished.emit(str(dest))
        except Exception as exc:
            self.error.emit(str(exc))

    def _filename(self, response):
        """Имя файла из Content-Disposition или из URL."""
        disposition = response.headers.get("Content-Disposition") or ""
        for part in disposition.split(";"):
            part = part.strip()
            if part.lower().startswith("filename="):
                return part.split("=", 1)[1].strip().strip('"')
        name = Path(unquote(urlparse(self._url).path)).name
        return name or "octobeat_update"


def apply_update(filepath):
    """Устанавливает скачанный файл и перезапускает приложение."""
    path = Path(filepath)
    if not path.is_file():
        return False

    suffix = path.suffix.lower()
    if suffix == ".appimage":
        return _apply_appimage(path)
    if suffix == ".exe":
        return _apply_windows(path)
    return False


def _apply_appimage(path):
    """chmod +x и запуск новой версии через os.execv."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    current = Path(sys.argv[0]).resolve()
    target = path
    if current != path and current.suffix.lower() == ".appimage":
        # Подменяем текущий AppImage, чтобы ярлык указывал на новую версию.
        try:
            backup = current.with_suffix(current.suffix + ".old")
            if backup.exists():
                backup.unlink()
            current.rename(backup)
            path.rename(current)
            target = current
        except OSError:
            target = path

    os.execv(str(target), [str(target)])
    return True


def _apply_windows(path):
    """Перезаписывает .exe после выхода приложения через временный .bat."""
    target = Path(sys.executable)
    batch = Path(tempfile.gettempdir()) / "octobeat_update.bat"
    script = (
        "@echo off\r\n"
        "timeout /t 2 /nobreak > nul\r\n"
        f'copy /Y "{path}" "{target}" > nul\r\n'
        f'start "" "{target}"\r\n'
        'del "%~f0"\r\n'
    )
    batch.write_text(script, encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", str(batch)],
        creationflags=0x00000008,  # DETACHED_PROCESS
        close_fds=True,
    )
    sys.exit(0)
