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

"""Фоновый воркер: скачивание аудио с YouTube через python-yt-dlp."""

import os
import re
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from PyQt5.QtCore import QObject, QSettings, pyqtSignal

from metadata import clean_youtube_title
from musicbrainz_client import get_track_metadata_with_fallback
from paths import MUSIC_DIR
from ytdlp_support import (
    DownloadCancelled,
    download_audio,
    format_error,
    search_videos,
)

# MUSIC_FOLDER is now read from settings.
MUSIC_FOLDER = MUSIC_DIR

# Небезопасные для файловой системы символы
_UNSAFE_FS_RE = re.compile(r'[\\/:*?"<>|]')

# ID видео в ссылках YouTube: ?v=ID, youtu.be/ID, /shorts/ID, /embed/ID
_VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/v/)([A-Za-z0-9_-]{11})"
)


def _image_mime(path):
    """MIME-тип обложки по расширению файла."""
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/jpeg"


def _find_cookies_file(extra_folder=None):
    """Ищет cookies.txt: сначала в настройках, затем в стандартных местах."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    cookies_path_str = settings.value("youtube_cookies", "")
    cookies_path = Path(cookies_path_str) if cookies_path_str else None
    if cookies_path and cookies_path.is_file():
        return cookies_path

    candidates = []
    if extra_folder is not None:
        candidates.append(Path(extra_folder) / "cookies.txt")
    candidates.append(MUSIC_FOLDER / "cookies.txt")
    candidates.append(Path(__file__).resolve().parent / "cookies.txt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class YoutubeWorker(QObject):
    """Качает аудио через yt-dlp. Живёт в отдельном QThread."""

    progress = pyqtSignal(int)      # 0..100
    finished = pyqtSignal(str)      # путь к скачанному mp3
    error = pyqtSignal(str)

    def __init__(self, query, target_folder=None):
        super().__init__()
        self.query = (query or "").strip()
        settings = QSettings("MusicPlayer", "MusicPlayer")
        default_dir = MUSIC_DIR
        self.target_folder = Path(settings.value("download_dir", str(default_dir)))
        self._stopped = False

    def run(self):
        """Run the download without ever letting yt-dlp kill the Qt thread."""
        try:
            self._run()
        except DownloadCancelled:
            return
        except Exception as exc:
            if not self._stopped:
                self.error.emit(
                    f"Ошибка загрузки YouTube:\n{format_error(exc)}"
                )

    def _run(self):
        if not self.query:
            self.error.emit("Пустой запрос")
            return

        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            return

        source = (
            self.query
            if self._looks_like_url(self.query)
            else f"ytsearch1:{self.query}"
        )
        cookies_path = _find_cookies_file(self.target_folder)

        final_path = download_audio(
            source,
            str(self.target_folder / "%(title)s.%(ext)s"),
            cookies_path=cookies_path,
            progress_callback=self._on_progress,
            cancel_check=lambda: self._stopped,
        )
        if self._stopped:
            return

        if not (final_path and Path(final_path).exists()):
            self.error.emit(
                "Загрузка прошла, но не удалось определить путь к файлу"
            )
            return

        # --- Метаданные: MusicBrainz → YouTube → имя файла ---
        raw_title = Path(final_path).stem
        fallback_artist, fallback_title = clean_youtube_title(raw_title)

        # yt-dlp мог скачать превью рядом с mp3 (--write-thumbnail).
        base_path = os.path.splitext(final_path)[0]
        img_path = None
        for ext in (".jpg", ".webp", ".png"):
            if os.path.exists(base_path + ext):
                img_path = base_path + ext
                break

        try:
            info = get_track_metadata_with_fallback(
                fallback_artist,
                fallback_title,
                file_path=final_path,
                youtube_thumbnail_path=img_path,
            )
        except Exception as e:
            print(f"[metadata] lookup failed, using filename: {e}")
            info = {
                "title": fallback_title,
                "artist": fallback_artist,
                "album": None,
                "cover_path": img_path,
                "source": "filename",
            }

        artist = info.get("artist") or fallback_artist
        clean_title = info.get("title") or fallback_title
        album = info.get("album")

        # --- Обложка: MusicBrainz/Cover Art Archive или превью YouTube ---
        cover_source = info.get("cover_path") or img_path
        embedded_ok = False
        if cover_source and os.path.exists(cover_source):
            try:
                try:
                    audio = ID3(final_path)
                except ID3NoHeaderError:
                    audio = ID3()

                mime = _image_mime(cover_source)
                with open(cover_source, "rb") as img:
                    audio.add(APIC(
                        encoding=3,
                        mime=mime,
                        type=3,
                        desc="Cover",
                        data=img.read(),
                    ))

                audio.save(final_path, v2_version=3)
                embedded_ok = True
                print(
                    f"[tags] Обложка вшита ({info.get('source', 'youtube')}): "
                    f"{mime}"
                )
            except Exception as e:
                print(f"[tags] Ошибка вшивания обложки: {e}")

        # Временное превью yt-dlp больше не нужно (кэш MusicBrainz не трогаем).
        if embedded_ok and img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass

        # --- Теги: MusicBrainz/YouTube либо очищенное имя файла ---
        if clean_title:
            try:
                try:
                    audio = EasyID3(final_path)
                except Exception:
                    audio = EasyID3()

                if artist and artist != "Unknown Artist":
                    audio["artist"] = artist
                audio["title"] = clean_title
                if album:
                    audio["album"] = album
                audio.save(final_path, v2_version=3)
                print(
                    f"[tags] Artist='{artist}', Title='{clean_title}', "
                    f"Album='{album}'"
                )
            except Exception as e:
                print(f"[tags] Cannot write tags: {e}")

        if artist and artist != "Unknown Artist" and clean_title:
            safe_name = _UNSAFE_FS_RE.sub("_", f"{artist} - {clean_title}").strip()
            suffix = Path(final_path).suffix or ".mp3"
            new_name = f"{safe_name}{suffix}"
            new_path = os.path.join(os.path.dirname(final_path), new_name)
            try:
                if os.path.abspath(final_path) != os.path.abspath(new_path):
                    if os.path.exists(new_path):
                        counter = 2
                        while os.path.exists(new_path):
                            new_name = f"{safe_name} ({counter}){suffix}"
                            new_path = os.path.join(
                                os.path.dirname(final_path), new_name
                            )
                            counter += 1
                    os.rename(final_path, new_path)
                    final_path = new_path
                    print(f"[rename] Renamed to {new_name}")
            except Exception as e:
                print(f"[rename] Failed to rename: {e}")

        self.progress.emit(100)
        self.finished.emit(final_path)

    def _on_progress(self, percent):
        if not self._stopped:
            self.progress.emit(max(0, min(100, int(percent))))

    def stop(self):
        """Ask yt-dlp to stop from its progress hook."""
        self._stopped = True

    @staticmethod
    def _looks_like_url(text):
        return text.startswith(("http://", "https://", "www."))


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
        if best is None:
            best = thumb
            continue
        width = thumb.get("width") or 0
        best_width = best.get("width") or 0
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

        cookies_path = _find_cookies_file()
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

        self.finished.emit(results)

    def stop(self):
        """Ask the search to stop; yt-dlp is interrupted on return."""
        self._stopped = True
