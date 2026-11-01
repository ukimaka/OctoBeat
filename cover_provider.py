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

"""Cover Art Archive, YouTube-превью и дисковый кэш обложек."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import requests

try:
    import musicbrainzngs
except ImportError:  # pragma: no cover — зависимость может отсутствовать
    musicbrainzngs = None

from metadata_cache import _cache_get, _cache_key
from metadata_normalize import (
    _merge_featured_artist,
    normalize_artist_name,
    normalize_track_query,
    split_featured_artists,
)
from paths import CACHE_DIR
from path_utils import safe_replace
from ytdlp_support import format_error, search_videos

COVER_DIR = CACHE_DIR / "musicbrainz_covers"
YOUTUBE_COVER_DIR = CACHE_DIR / "youtube_covers"

REQUEST_TIMEOUT = 15
MAX_IMAGE_BYTES = 20 * 1024 * 1024

_HTTP_USER_AGENT = "OctoBeat/1.0 (+https://github.com/ukimaka/OctoBeat)"


# ---------------------------------------------------------------------------
#  Инициализация MusicBrainz
# ---------------------------------------------------------------------------

def init_musicbrainz() -> bool:
    """Настраивает User-Agent. Без него MusicBrainz блокирует запросы."""
    if musicbrainzngs is None:
        print(
            "[musicbrainz] musicbrainzngs не установлен — "
            "работает только YouTube-fallback"
        )
        return False

    try:
        musicbrainzngs.set_useragent(
            "OctoBeat",
            "1.0",
            "https://github.com/ukimaka/OctoBeat",
        )
        return True
    except Exception as exc:  # pragma: no cover — защитный путь
        print(f"[musicbrainz] set_useragent failed: {exc}")
        return False


# Настраиваем сразу при импорте: main.py импортирует модуль до старта UI.
_MUSICBRAINZ_READY = init_musicbrainz()


# ---------------------------------------------------------------------------
#  Cover Art Archive
# ---------------------------------------------------------------------------

def _pick_image_url(
    image_list: dict[str, Any],
    front_only: bool = False,
) -> str:
    if not isinstance(image_list, dict):
        return ""

    images = image_list.get("images") or []
    if not isinstance(images, list):
        return ""

    fronts = [
        image for image in images
        if isinstance(image, dict) and image.get("front") and not image.get("back")
    ]
    if front_only:
        candidates = fronts
    else:
        candidates = fronts or [
            image for image in images if isinstance(image, dict)
        ]

    for image in candidates:
        thumbnails = image.get("thumbnails")
        if isinstance(thumbnails, dict):
            for size in ("1200", "large", "500", "250", "small"):
                url = thumbnails.get(size)
                if url:
                    return str(url)
        url = image.get("image")
        if url:
            return str(url)
    return ""


def _detect_image_ext(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def _download_image(url: str) -> bytes | None:
    if not url:
        return None

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": _HTTP_USER_AGENT},
        )
        response.raise_for_status()
        data = response.content
    except Exception as exc:
        print(f"[cover-art] download failed {url!r}: {exc}")
        return None

    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if not _detect_image_ext(data):
        return None
    return data


def get_cover_art(
    release_id: str | None,
    release_group_id: str | None = None,
) -> bytes | None:
    """Возвращает байты передней обложки из Cover Art Archive.

    Приоритет:
    1. front-обложка конкретного релиза;
    2. front-обложка release-group (обложка альбома) — обязательный шаг,
       если у релиза обложки нет или она не скачалась;
    3. прочие изображения релиза/release-group;
    4. только после этого вызывающий код уходит на YouTube.

    Любая сетевая ошибка приводит к ``None``, а не к исключению.
    """
    if musicbrainzngs is None or not _MUSICBRAINZ_READY:
        return None

    release_front = ""
    release_any = ""
    group_front = ""
    group_any = ""

    if release_id:
        try:
            image_list = musicbrainzngs.get_image_list(release_id)
            release_front = _pick_image_url(image_list, front_only=True)
            release_any = release_front or _pick_image_url(image_list)
        except Exception as exc:
            print(f"[cover-art] release/{release_id}: {exc}")

    # Есть нормальная передняя обложка релиза — используем её.
    if release_front:
        data = _download_image(release_front)
        if data:
            return data
        print(f"[cover-art] release front download failed: {release_id}")

    # У релиза обложки нет (или скачать не удалось) — обязательно
    # пробуем обложку release-group, то есть альбома целиком.
    if release_group_id:
        try:
            image_list = musicbrainzngs.get_release_group_image_list(
                release_group_id
            )
            group_front = _pick_image_url(image_list, front_only=True)
            group_any = group_front or _pick_image_url(image_list)
            if group_front:
                print(
                    f"[cover-art] release-group cover: {release_group_id}"
                )
        except Exception as exc:
            print(f"[cover-art] release-group/{release_group_id}: {exc}")

    if group_front:
        data = _download_image(group_front)
        if data:
            return data
        print(
            f"[cover-art] release-group front download failed: "
            f"{release_group_id}"
        )

    # Последняя попытка в CAA: не-front изображения (back, booklet и т.п.).
    for image_url in (release_any, group_any):
        if not image_url or image_url in (release_front, group_front):
            continue
        data = _download_image(image_url)
        if data:
            return data

    return None


# ---------------------------------------------------------------------------
#  Кэширование обложек на диск
# ---------------------------------------------------------------------------

def _save_cover_bytes(
    data: bytes,
    cache_key: str,
    source: str = "musicbrainz",
) -> str | None:
    ext = _detect_image_ext(data)
    if not ext:
        return None

    target_dir = COVER_DIR if source == "musicbrainz" else YOUTUBE_COVER_DIR
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    target = target_dir / f"{digest}{ext}"
    tmp_name = ""

    try:
        if target.is_file() and target.stat().st_size == len(data):
            return str(target)

        target_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            suffix=ext,
            dir=str(target_dir),
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        safe_replace(tmp_name, target)
        return str(target)
    except Exception as exc:
        if tmp_name:
            try:
                os.remove(tmp_name)
            except OSError:
                pass
        print(f"[cover-art] cannot save cover: {exc}")
        return None


def _copy_cover_file_to_cache(
    source_path: str,
    cache_key: str,
) -> str | None:
    try:
        path = Path(source_path)
        if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            return None
        data = path.read_bytes()
    except OSError as exc:
        print(f"[cover-art] cannot read local thumbnail: {exc}")
        return None
    return _save_cover_bytes(data, cache_key, source="youtube")


# ---------------------------------------------------------------------------
#  YouTube fallback
# ---------------------------------------------------------------------------

def _pick_thumbnail(entry: dict[str, Any]) -> str:
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list):
        best_url = ""
        best_width = -1
        for thumb in thumbnails:
            if not isinstance(thumb, dict) or not thumb.get("url"):
                continue
            width = int(thumb.get("width") or 0)
            if width > best_width:
                best_width = width
                best_url = str(thumb["url"])
        if best_url:
            return best_url
    return str(entry.get("thumbnail") or "")


def _youtube_first_result(query: str) -> dict[str, Any] | None:
    """Один результат поиска YouTube через python-yt-dlp.

    Cover lookup is best-effort: any yt-dlp failure is logged and converted
    to ``None`` so metadata lookup can continue without crashing the worker.
    """
    if not query:
        return None

    # Cookies из настроек YouTube-загрузчика (если PyQt/QSettings доступны).
    cookies_path = None
    try:
        from youtube_worker import _find_cookies_file

        cookies_path = _find_cookies_file()
    except Exception:
        pass

    try:
        entries = search_videos(query, limit=1, cookies_path=cookies_path)
    except Exception as exc:
        print(f"[youtube] search failed: {format_error(exc)}")
        return None
    return entries[0] if entries else None


def _youtube_cover(
    artist: str,
    title: str,
    thumbnail_path: str | None,
    cache_key: str,
    video: dict[str, Any] | None = None,
) -> str | None:
    # 1. Уже скачанное yt-dlp превью рядом с mp3.
    if thumbnail_path:
        saved = _copy_cover_file_to_cache(thumbnail_path, cache_key)
        if saved:
            return saved

    # 2. Превью из результата поиска YouTube.
    if video is None:
        query = " ".join(part for part in (artist, title) if part).strip()
        video = _youtube_first_result(query)
    if not video:
        return None

    url = _pick_thumbnail(video)
    if not url:
        video_id = str(video.get("id") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
    if not url:
        return None

    data = _download_image(url)
    if not data:
        return None
    return _save_cover_bytes(data, cache_key, source="youtube")


def _youtube_fallback(
    artist: str,
    title: str,
    file_path: str | None = None,
    youtube_thumbnail_path: str | None = None,
    cover_only: bool = False,
) -> dict[str, Any]:
    """Запасной источник: YouTube-поиск + превью. Никогда не бросает."""
    stem = Path(file_path).stem if file_path else ""
    clean_title = normalize_track_query(title) or normalize_track_query(stem)
    clean_artist = normalize_artist_name(artist)

    if not clean_title or not clean_artist:
        from metadata import clean_youtube_title

        parsed_artist, parsed_title = clean_youtube_title(title or stem)
        if parsed_artist != "Unknown Artist":
            if not clean_artist:
                clean_artist = normalize_artist_name(parsed_artist)
            if parsed_title:
                clean_title = normalize_track_query(parsed_title)
        elif parsed_title and not clean_title:
            clean_title = normalize_track_query(parsed_title)

    clean_title = clean_title or stem or "Unknown"
    # YouTube-названия часто содержат "ft. ..." — выносим это в артиста.
    clean_title, featured = split_featured_artists(clean_title)
    clean_artist = _merge_featured_artist(clean_artist, featured)
    cache_key = _cache_key(clean_artist, clean_title)

    result: dict[str, Any] = {
        "title": clean_title,
        "artist": clean_artist or "Unknown Artist",
        "album": None,
        "date": None,
        "cover_path": None,
        "cover_url": None,
        "cover_source": None,
        "is_default_cover": True,
        "source": "youtube",
        "file_path": str(file_path) if file_path else None,
        "file_name": Path(file_path).name if file_path else None,
    }

    # Сначала используем уже скачанное превью — это бесплатно и без сети.
    cover_path = None
    if youtube_thumbnail_path:
        cover_path = _youtube_cover(
            clean_artist,
            clean_title,
            youtube_thumbnail_path,
            cache_key,
        )
        if cover_path:
            result["cover_path"] = cover_path
            result["cover_source"] = "youtube"
            result["is_default_cover"] = False

    if cover_only and cover_path:
        return result
    if not cover_only and cover_path and clean_artist and clean_title:
        return result

    query = " ".join(part for part in (clean_artist, clean_title) if part).strip()
    video = _youtube_first_result(query)
    if not video:
        return result

    raw_video_title = str(video.get("title") or "").strip()
    if raw_video_title:
        from metadata import clean_youtube_title

        yt_artist, yt_title = clean_youtube_title(raw_video_title)
        yt_featured = ""
        if yt_title:
            clean_title = normalize_track_query(yt_title) or clean_title
            clean_title, yt_featured = split_featured_artists(clean_title)
        if not clean_artist and yt_artist != "Unknown Artist":
            clean_artist = normalize_artist_name(yt_artist)

        uploader = video.get("uploader") or video.get("channel") or ""
        if not clean_artist:
            clean_artist = normalize_artist_name(str(uploader))
        clean_artist = _merge_featured_artist(clean_artist, yt_featured)

        result["title"] = clean_title
        result["artist"] = clean_artist or "Unknown Artist"

    if not result["cover_path"]:
        cover_path = _youtube_cover(
            clean_artist,
            clean_title,
            youtube_thumbnail_path,
            cache_key,
            video=video,
        )
        if cover_path:
            result["cover_path"] = cover_path
            result["cover_source"] = "youtube"
            result["is_default_cover"] = False

    return result


# ---------------------------------------------------------------------------
#  Кэш метаданных по пути к файлу
# ---------------------------------------------------------------------------

def _cached_entry_for_path(file_path: str) -> dict[str, Any] | None:
    """Ищет запись кэша по имени аудиофайла (без сетевых запросов)."""
    try:
        from metadata import clean_youtube_title

        stem = Path(file_path).stem
        artist, title = clean_youtube_title(stem)
        clean_artist = (
            normalize_artist_name(artist)
            if artist != "Unknown Artist"
            else ""
        )
        clean_title = normalize_track_query(title)
        if not clean_title:
            return None
        return _cache_get(_cache_key(clean_artist, clean_title))
    except Exception as exc:
        print(f"[musicbrainz] cached metadata lookup failed: {exc}")
        return None


def get_cached_cover_for_path(file_path: str) -> str | None:
    """Возвращает обложку из локального кэша по имени аудиофайла.

    Используется UI при отрисовке библиотеки: сеть здесь не трогаем,
    иначе прокрутка списка треков будет «залипать».
    """
    cached = _cached_entry_for_path(file_path)
    if not cached:
        return None

    cover_path = cached.get("cover_path")
    if cover_path and Path(str(cover_path)).is_file():
        return str(cover_path)
    return None


def get_cached_source_for_path(file_path: str) -> str | None:
    """Источник метаданных для UI: musicbrainz / youtube / fallback."""
    cached = _cached_entry_for_path(file_path)
    if not cached:
        return None
    source = str(cached.get("source") or "").casefold()
    if source in ("musicbrainz", "youtube", "fallback"):
        return source
    return None
