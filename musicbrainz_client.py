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

"""MusicBrainz + Cover Art Archive с кэшем и YouTube-fallback.

Публичный фасад пайплайна метаданных. Кэш вынесен в ``metadata_cache``,
нормализация — в ``metadata_normalize``, обложки и YouTube — в
``cover_provider``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cover_provider import (
    COVER_DIR,
    MAX_IMAGE_BYTES,
    REQUEST_TIMEOUT,
    YOUTUBE_COVER_DIR,
    _MUSICBRAINZ_READY,
    _copy_cover_file_to_cache,
    _detect_image_ext,
    _download_image,
    _pick_image_url,
    _pick_thumbnail,
    _save_cover_bytes,
    _youtube_cover,
    _youtube_fallback,
    _youtube_first_result,
    get_cached_cover_for_path,
    get_cached_source_for_path,
    get_cover_art,
    init_musicbrainz,
    musicbrainzngs,
)
from metadata_cache import (
    CACHE_DIR,
    CACHE_FILE,
    CACHE_TTL,
    NEGATIVE_CACHE_TTL,
    _cache_get,
    _cache_key,
    _cache_set,
    clear_cache,
)
from metadata_normalize import (
    _artists_match,
    _fold,
    _merge_featured_artist,
    _titles_match,
    clean_featured_title,
    metadata_needs_refresh,
    normalize_artist_name,
    normalize_track_query,
    split_featured_artists,
)

SEARCH_LIMIT = 5


# ---------------------------------------------------------------------------
#  MusicBrainz: поиск
# ---------------------------------------------------------------------------

def _artist_credit(recording: dict[str, Any]) -> str:
    credits = recording.get("artist-credit") or []
    if not isinstance(credits, list):
        return ""

    parts: list[str] = []
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        name = credit.get("name")
        if not name:
            artist = credit.get("artist")
            if isinstance(artist, dict):
                name = artist.get("name")
        if name:
            parts.append(str(name))
        joinphrase = credit.get("joinphrase")
        if joinphrase:
            parts.append(str(joinphrase))
    return "".join(parts).strip()


def _pick_release(releases: list[Any]) -> dict[str, Any] | None:
    """Выбирает наиболее информативный релиз (альбом, official, с датой)."""
    valid = [release for release in releases if isinstance(release, dict)]
    if not valid:
        return None

    def score(release: dict[str, Any]) -> int:
        result = 0
        release_group = release.get("release-group")
        if isinstance(release_group, dict):
            result += 10
            group_type = str(
                release_group.get("type")
                or release_group.get("primary-type")
                or ""
            ).casefold()
            if group_type == "album":
                result += 6
        if str(release.get("status") or "").casefold() == "official":
            result += 5
        if release.get("date"):
            result += 2
        if release.get("id"):
            result += 1
        return result

    return max(valid, key=score)


def _recording_to_metadata(
    recording: dict[str, Any],
    fallback_artist: str,
    fallback_title: str,
) -> dict[str, Any]:
    releases = recording.get("release-list") or []
    if not isinstance(releases, list):
        releases = []

    release = _pick_release(releases)
    release_group: dict[str, Any] = {}
    if isinstance(release, dict):
        group = release.get("release-group")
        if isinstance(group, dict):
            release_group = group

    title = normalize_track_query(recording.get("title") or "") or fallback_title
    title, featured = split_featured_artists(title)
    artist = _artist_credit(recording) or fallback_artist
    artist = _merge_featured_artist(artist, featured)
    album = None
    date = None
    if isinstance(release, dict):
        album = release.get("title")
        date = release.get("date")
    if not album:
        album = release_group.get("title")
    if not date:
        date = release_group.get("first-release-date")

    recording_id = recording.get("id")
    return {
        "title": title,
        "artist": artist,
        "album": album,
        "date": date,
        "release_id": release.get("id") if isinstance(release, dict) else None,
        "release_group_id": release_group.get("id"),
        "recording_id": recording_id,
        "musicbrainz_url": (
            f"https://musicbrainz.org/recording/{recording_id}"
            if recording_id
            else None
        ),
        "cover_path": None,
        "cover_url": None,
        "cover_source": None,
        "is_default_cover": True,
        "source": "musicbrainz",
    }


def _choose_recording(
    recordings: list[Any],
    artist: str,
    title: str,
    require_artist: bool = True,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1

    for recording in recordings:
        if not isinstance(recording, dict):
            continue
        if str(recording.get("video") or "").casefold() == "true":
            continue

        rec_title = recording.get("title") or ""
        rec_artist = _artist_credit(recording)
        if not _titles_match(title, rec_title):
            continue
        if require_artist and artist and not _artists_match(artist, rec_artist):
            continue

        score = 100
        if _fold(title) == _fold(normalize_track_query(rec_title)):
            score += 20
        if artist and _artists_match(artist, rec_artist):
            score += 30
        if recording.get("release-list"):
            score += 5
        try:
            score += int(float(recording.get("ext:score") or 0)) // 100
        except (TypeError, ValueError):
            pass

        if score > best_score:
            best_score = score
            best = recording

    return best


def _musicbrainz_search(
    artist: str,
    title: str,
    require_artist: bool,
) -> dict[str, Any] | None:
    if not _MUSICBRAINZ_READY or musicbrainzngs is None:
        return None

    kwargs: dict[str, Any] = {
        "recording": title,
        "strict": True,
        "limit": SEARCH_LIMIT,
    }
    if artist:
        kwargs["artist"] = artist

    response = musicbrainzngs.search_recordings(**kwargs)
    recordings = response.get("recording-list") or []
    if not isinstance(recordings, list):
        return None

    recording = _choose_recording(
        recordings,
        artist=artist,
        title=title,
        require_artist=require_artist,
    )
    if recording is None:
        return None
    return _recording_to_metadata(recording, artist, title)


def search_musicbrainz(artist: str, title: str) -> dict[str, Any] | None:
    """Ищет трек в MusicBrainz и возвращает нормализованные метаданные.

    ``strict=True`` заставляет MusicBrainz искать точные совпадения, что
    заметно снижает шанс получить кавер вместо оригинала. Если поиск с
    исполнителем ничего не дал, делается одна попытка только по названию.
    """
    clean_artist = normalize_artist_name(artist)
    clean_title = normalize_track_query(title)
    if not clean_title:
        return None

    try:
        result = _musicbrainz_search(
            clean_artist,
            clean_title,
            require_artist=bool(clean_artist),
        )
        if result is not None:
            return result
    except Exception as exc:
        print(
            f"[musicbrainz] search failed for "
            f"{clean_artist!r} / {clean_title!r}: {exc}"
        )
        return None

    # Иногда исполнитель в тегах написан иначе (транслитерация, feat. и т.п.).
    if clean_artist:
        try:
            return _musicbrainz_search(
                "",
                clean_title,
                require_artist=False,
            )
        except Exception as exc:
            print(f"[musicbrainz] title-only search failed: {exc}")

    return None




# ---------------------------------------------------------------------------
#  Публичный пайплайн
# ---------------------------------------------------------------------------

def _default_result(
    artist: str,
    title: str,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Заглушка: имя файла/трек, «Unknown Artist» и стандартная обложка UI."""
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

    return {
        "title": clean_title or stem or "Unknown",
        "artist": clean_artist or "Unknown Artist",
        "album": None,
        "date": None,
        "cover_path": None,
        "cover_url": None,
        "cover_source": None,
        "is_default_cover": True,
        "source": "fallback",
        "file_path": str(file_path) if file_path else None,
        "file_name": Path(file_path).name if file_path else None,
    }


def _validate_cached_result(data: dict[str, Any]) -> dict[str, Any]:
    """Проверяет, что файл обложки из кэша ещё существует."""
    result = dict(data)
    cover_path = result.get("cover_path")
    if cover_path and not Path(str(cover_path)).is_file():
        result["cover_path"] = None
        result["cover_source"] = None
        result["is_default_cover"] = True
    return result


def get_track_metadata_with_fallback(
    artist: str,
    title: str,
    file_path: str | None = None,
    youtube_thumbnail_path: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Главная точка входа: MusicBrainz → YouTube → имя файла.

    Возвращает словарь с ключами ``title``, ``artist``, ``album``,
    ``cover_path``, ``source`` и служебными полями. Функция никогда не
    выбрасывает сетевые исключения — при любой ошибке возвращается
    YouTube-fallback или заглушка.
    """
    raw_title = title or (Path(file_path).stem if file_path else "")
    clean_title = normalize_track_query(raw_title)
    clean_artist = normalize_artist_name(artist)

    if not clean_title or not clean_artist:
        from metadata import clean_youtube_title

        parsed_artist, parsed_title = clean_youtube_title(raw_title)
        if parsed_artist != "Unknown Artist":
            if not clean_artist:
                clean_artist = normalize_artist_name(parsed_artist)
            if parsed_title:
                clean_title = normalize_track_query(parsed_title)
        elif parsed_title and not clean_title:
            clean_title = normalize_track_query(parsed_title)

    if not clean_title and file_path:
        clean_title = normalize_track_query(Path(file_path).stem)

    cache_key = _cache_key(clean_artist, clean_title)

    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return _validate_cached_result(cached)

    # --- 1. MusicBrainz -----------------------------------------------------
    mb_result: dict[str, Any] | None = None
    try:
        mb_result = search_musicbrainz(clean_artist, clean_title)
    except Exception as exc:  # страховка на случай неожиданных ошибок
        print(f"[musicbrainz] unexpected search error: {exc}")

    if mb_result is not None:
        cover_data: bytes | None = None
        try:
            cover_data = get_cover_art(
                mb_result.get("release_id"),
                mb_result.get("release_group_id"),
            )
        except Exception as exc:
            print(f"[musicbrainz] unexpected cover error: {exc}")

        if cover_data:
            cover_path = _save_cover_bytes(
                cover_data,
                cache_key,
                source="musicbrainz",
            )
            if cover_path:
                mb_result["cover_path"] = cover_path
                mb_result["cover_source"] = "musicbrainz"
                mb_result["is_default_cover"] = False

        if mb_result.get("cover_path"):
            _cache_set(cache_key, mb_result, CACHE_TTL)
            return mb_result

        # Метаданные нашлись, а обложки у релиза нет — добираем её
        # из YouTube, но метаданные MusicBrainz сохраняем.
        try:
            yt_result = _youtube_fallback(
                clean_artist,
                clean_title,
                file_path=file_path,
                youtube_thumbnail_path=youtube_thumbnail_path,
                cover_only=True,
            )
        except Exception as exc:
            print(f"[youtube] cover-only fallback failed: {exc}")
            yt_result = None

        if yt_result and yt_result.get("cover_path"):
            mb_result["cover_path"] = yt_result["cover_path"]
            mb_result["cover_source"] = "youtube"
            mb_result["is_default_cover"] = False

        _cache_set(
            cache_key,
            mb_result,
            CACHE_TTL if mb_result.get("cover_path") else NEGATIVE_CACHE_TTL,
        )
        return mb_result

    # --- 2. YouTube fallback ------------------------------------------------
    try:
        yt_result = _youtube_fallback(
            clean_artist,
            clean_title,
            file_path=file_path,
            youtube_thumbnail_path=youtube_thumbnail_path,
        )
    except Exception as exc:
        print(f"[youtube] fallback failed: {exc}")
        yt_result = None

    if yt_result and (
        yt_result.get("cover_path")
        or yt_result.get("title")
        or yt_result.get("artist") != "Unknown Artist"
    ):
        _cache_set(
            cache_key,
            yt_result,
            CACHE_TTL if yt_result.get("cover_path") else NEGATIVE_CACHE_TTL,
        )
        return yt_result

    # --- 3. Заглушка --------------------------------------------------------
    default = _default_result(clean_artist, clean_title, file_path=file_path)
    _cache_set(cache_key, default, NEGATIVE_CACHE_TTL)
    return default
