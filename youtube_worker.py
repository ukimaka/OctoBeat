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

"""Фоновый воркер: скачивание аудио с YouTube через SomeDL.

SomeDL сам скачивает трек, подтягивает метаданные (YouTube Music,
MusicBrainz, Genius, Deezer) и вшивает обложку 544x544 в аудиофайл.
Приложение только забирает готовый путь к файлу и добавляет его в БД.
"""

import os
import re
from pathlib import Path

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

import db
import metadata
import somedl_integration
from cookies_store import find_cookies_file
from paths import MUSIC_DIR
from qt_diagnostics import note
from ytdlp_support import (
    DownloadCancelled,
    current_download_mode,
    format_error,
    search_videos,
)

DOWNLOAD_MODE_MP3 = "mp3"
DOWNLOAD_MODE_NATIVE = "native"
DEFAULT_DOWNLOAD_MODE = DOWNLOAD_MODE_NATIVE
DOWNLOAD_MODES = (DOWNLOAD_MODE_NATIVE, DOWNLOAD_MODE_MP3)

# MUSIC_FOLDER is now read from settings.
MUSIC_FOLDER = MUSIC_DIR

# ID видео в ссылках YouTube: ?v=ID, youtu.be/ID, /shorts/ID, /embed/ID
_VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/v/)([A-Za-z0-9_-]{11})"
)


class YoutubeWorker(QObject):
    """Качает аудио через SomeDL. Живёт в отдельном QThread."""

    progress = pyqtSignal(int)      # 0..100
    finished = pyqtSignal(str)      # путь к скачанному файлу (mp3/m4a/…)
    error = pyqtSignal(str)

    def __init__(self, query, target_folder=None, download_mode=None):
        super().__init__()
        self.setObjectName("yt-download-worker")
        self.query = (query or "").strip()
        settings = QSettings("MusicPlayer", "MusicPlayer")
        default_dir = MUSIC_DIR
        if target_folder:
            self.target_folder = Path(target_folder)
        else:
            self.target_folder = Path(
                settings.value("download_dir", str(default_dir))
            )
        self.download_mode = (
            download_mode or current_download_mode()
        )
        self._stopped = False

    def run(self):
        """Run the download without ever letting yt-dlp kill the Qt thread."""
        try:
            self._run()
        except DownloadCancelled:
            return
        except Exception as exc:
            if not self._stopped:
                note(f"yt-download error: {exc}")
                self.error.emit(
                    f"Ошибка загрузки YouTube:\n{format_error(exc)}"
                )

    def _run(self):
        if not self.query:
            self.error.emit("Пустой запрос")
            return
        note(f"yt-download start: {self.query[:120]!r}")

        if not somedl_integration.somedl_available():
            self.error.emit(
                "SomeDL не установлен. Установите зависимость: pip install somedl"
            )
            return

        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            return

        cookies_path = find_cookies_file(self.target_folder)
        note(
            "yt-download cookies: "
            f"file={cookies_path or 'none'} "
            f"mode={self.download_mode}"
        )

        try:
            final_path = somedl_integration.download_track(
                self.query,
                self.target_folder,
                audio_format=(
                    "mp3"
                    if self.download_mode == DOWNLOAD_MODE_MP3
                    else "best"
                ),
                cookies_path=cookies_path,
                cancel_check=lambda: self._stopped,
            )
        except somedl_integration.SomedlCancelled:
            note("yt-download cancelled")
            return
        except Exception as exc:
            note(f"yt-download failed: {exc}")
            self.error.emit(f"Ошибка загрузки YouTube:\n{exc}")
            return
        if self._stopped:
            return

        if not (final_path and Path(final_path).exists()):
            self.error.emit(
                "Загрузка прошла, но не удалось определить путь к файлу"
            )
            return

        note(
            "yt-download finished: "
            f"{final_path} ({Path(final_path).suffix})"
        )

        # --- БД: читаем теги, которые вшил SomeDL ---
        # Без этого ImportFlow.sync_library() добавил бы строку только с
        # путём, и UI показал бы "Unknown Title" до следующего рескана.
        try:
            existing = db.get_track_by_path(final_path)
            track_id = (
                existing["id"] if existing is not None
                else db.add_track(final_path)
            )
            if track_id is not None:
                md = metadata.read_metadata(final_path)
                db.update_track_metadata(
                    track_id,
                    title=md["title"] or Path(final_path).stem,
                    artist=md["artist"] or "Unknown Artist",
                    album=md["album"],
                    duration=md["duration"],
                )
        except Exception as e:
            print(f"[youtube] DB metadata update failed for {final_path}: {e}")

        if self._stopped:
            return
        note(f"yt-download finished: {final_path}")
        self.progress.emit(100)
        self.finished.emit(final_path)

    def stop(self):
        """Ask the current somedl download to stop."""
        self._stopped = True


def _extract_video_id(value):
    """Достаёт ID видео из ссылки YouTube (или принимает готовый ID)."""
    if not value:
        return ""
    text = str(value).strip()
    match = _VIDEO_ID_RE.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return ""


def _pick_thumbnail(entry):
    """Выбирает превью ~320px шириной из списка thumbnails."""
    thumbs = entry.get("thumbnails")
    if not isinstance(thumbs, list):
        return ""

    best = None
    for thumb in thumbs:
        if not isinstance(thumb, dict) or not thumb.get("url"):
            continue
        width = thumb.get("width") or 0
        best_width = best.get("width") or 0 if best else 0
        if abs(width - 320) < abs(best_width - 320):
            best = thumb
    return best.get("url", "") if best else ""


def _entry_to_result(entry):
    """Преобразует запись yt-dlp в словарь результата поиска."""
    if not isinstance(entry, dict):
        return None
    raw_url = entry.get("webpage_url") or entry.get("url") or ""
    video_id = _extract_video_id(raw_url) or _extract_video_id(entry.get("id"))
    if str(raw_url).startswith("http"):
        url = raw_url
    elif video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
    else:
        url = str(raw_url)

    try:
        duration = int(entry["duration"]) if entry.get("duration") is not None else 0
    except (TypeError, ValueError):
        duration = 0

    uploader = (
        entry.get("uploader")
        or entry.get("channel")
        or entry.get("uploader_id")
        or ""
    )

    thumbnail = entry.get("thumbnail") or _pick_thumbnail(entry)
    if not thumbnail and video_id:
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

    return {
        "id": url,
        "video_id": video_id,
        "title": entry.get("title") or "Unknown",
        "uploader": uploader,
        "duration": duration,
        "thumbnail": thumbnail or "",
    }


class YoutubeSearchWorker(QObject):
    """Ищет видео на YouTube через yt-dlp — без скачивания."""

    finished = pyqtSignal(list)     # список словарей с метаданными
    error = pyqtSignal(str)

    RESULT_LIMIT = 5

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.setObjectName("yt-search-worker")
        self.query = (query or "").strip()
        self._stopped = False

    def run(self):
        """Run the search without ever letting yt-dlp kill the Qt thread."""
        try:
            self._run()
        except DownloadCancelled:
            return
        except Exception as exc:
            if not self._stopped:
                self.error.emit(
                    f"Ошибка поиска YouTube:\n{format_error(exc)}"
                )

    def _run(self):
        if not self.query:
            self.error.emit("Пустой запрос")
            return
        note(f"yt-search start: {self.query[:120]!r}")

        cookies_path = find_cookies_file()
        note(
            "yt-search cookies: "
            f"file={cookies_path or 'none'}"
        )
        entries = search_videos(
            self.query,
            limit=self.RESULT_LIMIT,
            cookies_path=cookies_path,
        )
        if self._stopped:
            return

        results = [
            result
            for entry in entries
            if (result := _entry_to_result(entry)) is not None
        ]
        if not results:
            self.error.emit("Ничего не найдено")
            return

        note(f"yt-search finished: {len(results)} results")
        self.finished.emit(results)

    def stop(self):
        """Ask the search to stop; yt-dlp is interrupted on return."""
        self._stopped = True
