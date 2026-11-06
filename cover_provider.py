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

"""Локальные обложки и бейдж источника метаданных.

Сетевых запросов здесь больше нет: SomeDL сам вшивает обложку 544x544 в
аудиофайл. Модуль оставлен как тонкий слой для UI, который умеет отличать
читаемые Qt форматы и определять, что теги трека записаны SomeDL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _displayable_cover_path(value: Any) -> str | None:
    """Путь к обложке, которую гарантированно декодирует Qt."""
    if not value:
        return None
    try:
        path = Path(str(value))
    except (TypeError, ValueError):
        return None
    if path.suffix.casefold() not in (".jpg", ".jpeg", ".png", ".gif"):
        return None
    return str(path) if path.is_file() else None


def get_cached_source_for_path(file_path: str) -> str | None:
    """Источник метаданных для debug-бейджа в списках треков.

    SomeDL пишет MusicBrainz/YouTube/Genius/Deezer-поля прямо в теги
    (например, ``MusicBrainz Artist Id`` и ``WOAS``), поэтому отдельный
    кэш больше не нужен. Файл без тегов остаётся «fallback».
    """
    if not file_path:
        return None
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(file_path, easy=True)
    except Exception:
        return None
    if audio is None or not audio.tags:
        return None

    tags = audio.tags
    markers = (
        "musicbrainz_artistid",
        "musicbrainz_albumid",
        "musicbrainz_trackid",
    )
    if any(tags.get(key) for key in markers):
        return "somedl"
    # SomeDL всегда сохраняет ссылку на источник (WOAS/mp4 ©cmt).
    if tags.get("website") or tags.get("comment"):
        return "somedl"
    if tags.get("album") and tags.get("artist") and tags.get("title"):
        return "somedl"
    return None
