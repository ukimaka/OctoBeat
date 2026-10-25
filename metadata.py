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

"""Чтение метаданных аудиофайлов: теги через mutagen + fallback на имя файла."""

import re
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile


COVERS_DIR = Path.home() / ".cache" / "music_player" / "covers"

# Ведущие мусорные группы в скобках: [MV], [Official Video], [VOCALOID RUS] ...
_PREFIX_BRACKETS_RE = re.compile(r"^(?:\[[^\]]*\]\s*)+")

# Ключевые слова-мусор внутри скобок
_NOISE_WORDS = (
    r"official|lyrics?|audio|video|visuali[sz]er|\bm/?v\b|prod\b|explicit"
)

# Замыкающие мусорные группы в скобках: (Official Video), [Lyrics], (Audio)
_NOISE_SUFFIX_RE = re.compile(
    r"(?:\s*[\(\[]\s*[^\)\]]*(?:" + _NOISE_WORDS + r")[^\)\]]*[\)\]])+\s*$",
    re.IGNORECASE,
)


def clean_youtube_title(raw_title):
    """Чистит название, полученное из YouTube, и выделяет (artist, clean_title).

    Убирает мусорные префиксы ([MV], [Official Video], ...) и суффиксы
    ((Official Video), [Lyrics], (Audio), ...), затем пробует разбить строку
    по разделителю. Если разделителя нет — artist будет "Unknown Artist"."""
    title = (raw_title or "").strip()

    # 1. Мусорные префиксы в начале строки
    title = _PREFIX_BRACKETS_RE.sub("", title)

    # 2. Мусорные суффиксы в конце строки
    title = _NOISE_SUFFIX_RE.sub("", title)
    title = title.strip()

    # 3. Разделители artist — title
    for sep in (" - ", " – ", " — ", " : ", ": "):
        if sep in title:
            artist, clean_title = title.split(sep, 1)
            artist = artist.strip()
            clean_title = clean_title.strip()
            if not artist or not clean_title:
                return "Unknown Artist", title
            return artist, clean_title

    # 4. Разделителя нет
    return "Unknown Artist", title


def _parse_filename(path):
    stem = Path(path).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()

    # Добавили двоеточие в список разделителей
    for sep in (" — ", " – ", " : ", ": "):
        if sep in stem:
            artist, title = stem.split(sep, 1)
            return title.strip(), artist.strip()

    return stem.strip(), None


def read_metadata(path):
    """Возвращает dict {title, artist, album, duration}.
    Всё, что не удалось достать — None. duration — целые секунды."""
    result: dict[str, Optional[str | int]] = {
        "title": None, "artist": None, "album": None, "duration": None,
    }
    # 1. Пробуем теги
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            if audio.tags:
                title = audio.get("title")
                artist = audio.get("artist")
                album = audio.get("album")
                if title:
                    result["title"] = title[0]
                if artist:
                    result["artist"] = artist[0]
                if album:
                    result["album"] = album[0]
            if audio.info and audio.info.length:
                result["duration"] = int(audio.info.length)
    except Exception as e:
        print(f"[metadata] tag read failed for {path}: {e}")

    # 2. Fallback — имя файла для title/artist
    if not result["title"] or not result["artist"]:
        fname_title, fname_artist = _parse_filename(path)
        if not result["title"]:
            result["title"] = fname_title
        if not result["artist"]:
            result["artist"] = fname_artist

    return result


def extract_cover(file_path, track_id):
    """Кэширует встроенную обложку трека в COVERS_DIR/{track_id}.jpg.
    Возвращает путь к файлу обложки или None, если обложки нет."""
    cover_file = COVERS_DIR / f"{track_id}.jpg"
    if cover_file.exists() and cover_file.stat().st_size > 0:
        return str(cover_file)

    try:
        audio = MutagenFile(file_path)
    except Exception as e:
        print(f"[metadata] cover read failed for {file_path}: {e}")
        return None

    if audio is None or audio.tags is None:
        return None

    data = None

    # 1. Для MP3 (ID3)
    if hasattr(audio.tags, 'getall'):
        for tag in audio.tags.getall('APIC'):
            data = tag.data
            break

    # 2. Для MP4/M4A
    if data is None and 'covr' in audio.tags:
        covr = audio.tags.get('covr')
        if covr:
            data = bytes(covr[0])

    if not data:
        return None

    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        cover_file.write_bytes(data)
        return str(cover_file)
    except Exception as e:
        print(f"[metadata] cover save failed for {file_path}: {e}")
        return None


def format_track(track, fallback_path=None, with_duration=True):
    """Строка для отображения в списке: 'Artist — Title [m:ss]'.
    with_duration=False — убрать хвост с длительностью."""
    title = track["title"]
    artist = track["artist"]
    dur = track["duration"]

    if title and artist:
        display = f"{artist} — {title}"
    elif title:
        display = title
    elif fallback_path:
        display = Path(fallback_path).name
    else:
        display = "(unknown)"

    if dur and with_duration:
        m, s = divmod(dur, 60)
        display += f"  [{m}:{s:02d}]"

    return display
