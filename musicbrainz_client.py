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

Пайплайн получения метаданных:

1. нормализуем artist/title (убираем YouTube-мусор);
2. ищем запись в MusicBrainz (strict search отсеивает каверы);
3. тянем обложку из Cover Art Archive (release → release-group);
4. если MusicBrainz ничего не дал — используем YouTube (yt-dlp);
5. если и там пусто — возвращаем имя файла и заглушку обложки.

Все сетевые операции обёрнуты в try/except: плеер не должен падать без
интернета. Результаты успешных запросов сохраняются в
``~/.cache/music_player/metadata_cache.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests

try:
    import musicbrainzngs
except ImportError:  # pragma: no cover — зависимость может отсутствовать
    musicbrainzngs = None


# ---------------------------------------------------------------------------
#  Константы
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "music_player"
CACHE_FILE = CACHE_DIR / "metadata_cache.json"
COVER_DIR = CACHE_DIR / "musicbrainz_covers"
YOUTUBE_COVER_DIR = CACHE_DIR / "youtube_covers"

CACHE_TTL = 30 * 24 * 60 * 60          # успешный ответ — 30 дней
NEGATIVE_CACHE_TTL = 60 * 60           # заглушка/ошибка — 1 час
SEARCH_LIMIT = 5
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
#  Кэш
# ---------------------------------------------------------------------------

_cache_lock = threading.RLock()
_cache_loaded = False
_cache: dict[str, dict[str, Any]] = {}


def _load_cache_locked() -> None:
    """Лениво загружает JSON-кэш. Повреждённый файл просто игнорируется."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True

    try:
        if not CACHE_FILE.is_file():
            return
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[musicbrainz] cache read failed: {exc}")
        return

    if not isinstance(raw, dict):
        return

    entries = raw.get("entries")
    if not isinstance(entries, dict):
        # Поддерживаем и старый/плоский формат.
        entries = raw

    _cache = {
        str(key): value
        for key, value in entries.items()
        if isinstance(value, dict)
    }


def _save_cache_locked() -> None:
    """Атомарно пишет кэш на диск (temp file + os.replace)."""
    tmp_name = ""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".metadata_cache.",
            suffix=".json",
            dir=str(CACHE_DIR),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "entries": _cache},
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, CACHE_FILE)
    except Exception as exc:
        print(f"[musicbrainz] cache write failed: {exc}")
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _cache_key(artist: str, title: str) -> str:
    return f"{(artist or '').strip().casefold()}|{(title or '').strip().casefold()}"


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    with _cache_lock:
        _load_cache_locked()
        entry = _cache.get(key)
        if not isinstance(entry, dict):
            return None

        try:
            expires_at = float(entry.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0

        data = entry.get("data")
        if expires_at <= time.time() or not isinstance(data, dict):
            _cache.pop(key, None)
            return None

        # Возвращаем копию, чтобы вызывающий код не менял кэш случайно.
        return dict(data)


def _cache_set(key: str, data: dict[str, Any], ttl: int = CACHE_TTL) -> None:
    with _cache_lock:
        _load_cache_locked()
        entry = {
            "expires_at": time.time() + max(1, int(ttl)),
            "data": dict(data),
        }
        _cache[key] = entry

        # Дублируем запись под ключом из финальных artist/title. После
        # переименования файла UI ищет кэш именно по имени файла, а оно
        # может отличаться от исходного запроса (например, после выноса
        # "feat." из названия в артиста).
        try:
            alias_key = _cache_key(
                normalize_artist_name(str(data.get("artist") or "")),
                normalize_track_query(str(data.get("title") or "")),
            )
        except Exception:
            alias_key = ""
        if alias_key and alias_key != key:
            _cache[alias_key] = entry

        _save_cache_locked()


def clear_cache() -> None:
    """Полностью очищает локальный кэш метаданных."""
    with _cache_lock:
        _cache.clear()
        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
        except OSError as exc:
            print(f"[musicbrainz] cache clear failed: {exc}")


# ---------------------------------------------------------------------------
#  Нормализация запросов
# ---------------------------------------------------------------------------

# Мусорные слова YouTube. Используются только внутри скобок или в конце
# строки, чтобы не испортить нормальные названия вроде «Video Games».
_NOISE_KEYWORDS = (
    r"official\s*(?:music\s*)?video"
    r"|official\s*audio"
    r"|official\s*lyric\s*video"
    r"|official\s*clip"
    r"|official"
    r"|lyric\s*video|lyrics?|color\s*coded(?:\s*lyrics?)?"
    r"|visuali[sz]er"
    r"|music\s*video|video\s*clip|clip\s*officiel"
    r"|m\s*/\s*v|\bmv\b"
    r"|audio"
    r"|(?:\d{3,4}p|\b4k\b|\b8k\b|\b2k\b|\buhd\b|\bhd\b|\bhq\b|\bhdr\b)"
    r"|explicit"
    r"|remaster(?:ed)?(?:\s*\d{4})?"
    r"|prod\.?\s*by|\bprod\b"
    r"|премьера|клип|официальн\w*|аудио|видео"
)

_NOISE_RE = re.compile(_NOISE_KEYWORDS, re.IGNORECASE)
_BRACKET_RE = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_FULLWIDTH_BRACKET_RE = re.compile(r"【([^】]*)】")
_EMPTY_BRACKET_RE = re.compile(r"[\(\[]\s*[\)\]]")
_TRAILING_NOISE_RE = re.compile(
    r"(?:\s*[-–—|·•]\s*)?\s*(?:" + _NOISE_KEYWORDS + r")\s*$",
    re.IGNORECASE,
)
_LEADING_NOISE_RE = re.compile(
    r"^\s*(?:" + _NOISE_KEYWORDS + r")\s*(?:[-–—|·•:]\s*)?",
    re.IGNORECASE,
)
_AUDIO_EXT_RE = re.compile(
    r"\.(?:mp3|flac|m4a|ogg|opus|wav|aac|webm|mp4|mkv)$",
    re.IGNORECASE,
)


def _is_bracket_noise(inner: str) -> bool:
    inner = (inner or "").strip()
    if not inner:
        return True
    if _NOISE_RE.search(inner):
        return True
    # Отдельные короткие маркеры: (Video), [Audio], (MV), [4K] и т.п.
    return bool(re.fullmatch(
        r"video|audio|m\s*/\s*v|mv|hd|hq|uhd|hdr|4k|8k|2k|\d{3,4}p",
        inner,
        re.IGNORECASE,
    ))


def normalize_track_query(raw_title: str) -> str:
    """Очищает название трека от YouTube-мусора перед поиском.

    Примеры:
        ``Artist - Song (Official Video) [4K]`` → ``Artist - Song``
        ``【MV】Artist - Song (Lyrics)``          → ``Artist - Song``
        ``Artist - Song | Official Audio``       → ``Artist - Song``
    """
    text = str(raw_title or "").strip()
    if not text:
        return ""

    text = _AUDIO_EXT_RE.sub("", text)

    # Скобочные группы с мусором: (Official Video), [Lyrics], (4K), 【MV】.
    text = _BRACKET_RE.sub(
        lambda match: " " if _is_bracket_noise(match.group(1)) else match.group(0),
        text,
    )
    text = _FULLWIDTH_BRACKET_RE.sub(
        lambda match: " " if _is_bracket_noise(match.group(1)) else match.group(0),
        text,
    )

    # Части через «|»: выкидываем сегменты, состоящие только из мусора.
    parts = re.split(r"\s*[|｜]\s*", text)
    kept = []
    for part in parts:
        value = part.strip()
        if not value:
            continue
        if _NOISE_RE.fullmatch(value.strip(" -–—·•")):
            continue
        kept.append(value)
    if kept:
        text = " - ".join(kept)

    # Мусор в начале и в конце без скобок:
    # «Artist - Song Official Video», «Artist - Song - Audio».
    previous = None
    while previous != text:
        previous = text
        text = _LEADING_NOISE_RE.sub("", text)
        candidate = _TRAILING_NOISE_RE.sub("", text).strip(" -–—|·•:,")
        if candidate:
            text = candidate

    text = _EMPTY_BRACKET_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—|·•:,")
    return text


def normalize_artist_name(raw_artist: str) -> str:
    """Чистит имя исполнителя от служебных приписок YouTube."""
    artist = str(raw_artist or "").strip()
    if not artist:
        return ""

    artist = re.sub(r"\s*[-–—]\s*Topic\s*$", "", artist, flags=re.IGNORECASE)
    if len(artist) > 4 and artist.lower().endswith("vevo"):
        artist = artist[:-4]
    artist = re.sub(
        r"^\s*(?:official|music|topic)\s*[-–—:]\s*",
        "",
        artist,
        flags=re.IGNORECASE,
    )
    artist = re.sub(r"\s+", " ", artist).strip(" -–—|·•:,")

    if artist.casefold() in {"", "unknown", "unknown artist", "n/a", "none", "-"}:
        return ""
    return artist


_BRACKETED_FEAT_RE = re.compile(
    r"\s*[\(\[]\s*(?:feat(?:uring)?|ft)\.?\s+([^\)\]]+?)\s*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_FEAT_RE = re.compile(
    r"\s+\b(?:feat(?:uring)?|ft)\.\s+(.+?)(?=\s*[\(\[]|$)"
    r"|\s+\bfeaturing\s+(.+?)(?=\s*[\(\[]|$)",
    re.IGNORECASE,
)


def split_featured_artists(title: str) -> tuple[str, str]:
    """Убирает ``feat.``/``ft.`` из названия и возвращает (title, featured).

    Пример:
        ``"Get Lucky ft. Pharrell Williams"``
        → ``("Get Lucky", "Pharrell Williams")``

    Поддерживаются варианты ``ft.``, ``feat.``, ``featuring`` и записи
    в скобках: ``(feat. X)``, ``[ft. X]``.
    """
    text = str(title or "").strip()
    if not text:
        return "", ""

    featured: list[str] = []

    def _remove_bracketed(match: re.Match[str]) -> str:
        value = match.group(1).strip(" -–—")
        if value:
            featured.append(value)
        return " "

    cleaned = _BRACKETED_FEAT_RE.sub(_remove_bracketed, text)

    match = _TRAILING_FEAT_RE.search(cleaned)
    if match:
        value = (match.group(1) or match.group(2) or "").strip(" -–—")
        if value:
            featured.append(value)
        cleaned = cleaned[:match.start()] + cleaned[match.end():]

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|·•:,")
    if not cleaned:
        return text, ""

    unique: list[str] = []
    seen: set[str] = set()
    for value in featured:
        key = value.casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    return cleaned, ", ".join(unique)


def clean_featured_title(title: str) -> str:
    """Короткий вариант :func:`split_featured_artists` — только название."""
    return split_featured_artists(title)[0]


def _merge_featured_artist(artist: str, featured: str) -> str:
    """Добавляет feat-исполнителя к артисту, если его там ещё нет."""
    if not featured:
        return artist
    if featured.casefold() in str(artist or "").casefold():
        return artist
    if artist:
        return f"{artist} feat. {featured}"
    return featured


def metadata_needs_refresh(artist: str, title: str) -> bool:
    """True, если теги пустые или содержат YouTube-мусор."""
    if not str(title or "").strip():
        return True
    if not normalize_artist_name(artist):
        return True
    return normalize_track_query(title).casefold() != str(title).strip().casefold()


# ---------------------------------------------------------------------------
#  MusicBrainz: поиск
# ---------------------------------------------------------------------------

def _fold(value: str) -> str:
    """Нормализация для сравнения: регистр, пунктуация, пробелы."""
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _titles_match(left: str, right: str) -> bool:
    a, b = _fold(left), _fold(right)
    if not a or not b:
        return False
    if a == b:
        return True

    # «feat.» / «ft.» часто есть только в одном варианте названия.
    a_base = re.split(r"\b(?:feat|ft)\b", a, maxsplit=1)[0].strip()
    b_base = re.split(r"\b(?:feat|ft)\b", b, maxsplit=1)[0].strip()
    if a_base and a_base == b_base:
        return True

    import difflib

    return difflib.SequenceMatcher(None, a_base or a, b_base or b).ratio() >= 0.9


def _artists_match(left: str, right: str) -> bool:
    a, b = _fold(left), _fold(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True

    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return False
    return len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens)) >= 0.5


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


def _pick_release(releases: list[Any]) -> Optional[dict[str, Any]]:
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
) -> Optional[dict[str, Any]]:
    best: Optional[dict[str, Any]] = None
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
) -> Optional[dict[str, Any]]:
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


def search_musicbrainz(artist: str, title: str) -> Optional[dict[str, Any]]:
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


def _download_image(url: str) -> Optional[bytes]:
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
    release_id: Optional[str],
    release_group_id: Optional[str] = None,
) -> Optional[bytes]:
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
) -> Optional[str]:
    ext = _detect_image_ext(data)
    if not ext:
        return None

    target_dir = COVER_DIR if source == "musicbrainz" else YOUTUBE_COVER_DIR
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    target = target_dir / f"{digest}{ext}"

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
        os.replace(tmp_name, target)
        return str(target)
    except Exception as exc:
        print(f"[cover-art] cannot save cover: {exc}")
        return None


def _copy_cover_file_to_cache(
    source_path: str,
    cache_key: str,
) -> Optional[str]:
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


def _youtube_first_result(query: str) -> Optional[dict[str, Any]]:
    """Один результат поиска YouTube через yt-dlp (без скачивания файла)."""
    if not query:
        return None

    exe = shutil.which("yt-dlp")
    if exe is None:
        return None

    cmd = [
        exe,
        "--no-warnings",
        "--flat-playlist",
        "--dump-json",
        f"ytsearch1:{query}",
    ]

    # Cookies из настроек YouTube-загрузчика (если PyQt/QSettings доступны).
    try:
        from youtube_worker import _find_cookies_file

        cookies_path = _find_cookies_file()
        if cookies_path is not None:
            cmd += ["--cookies", str(cookies_path)]
    except Exception:
        pass

    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        print(f"[youtube] search failed: {exc}")
        return None

    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            return entry
    return None


def _youtube_cover(
    artist: str,
    title: str,
    thumbnail_path: Optional[str],
    cache_key: str,
    video: Optional[dict[str, Any]] = None,
) -> Optional[str]:
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
    file_path: Optional[str] = None,
    youtube_thumbnail_path: Optional[str] = None,
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
#  Публичный пайплайн
# ---------------------------------------------------------------------------

def _default_result(
    artist: str,
    title: str,
    file_path: Optional[str] = None,
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
    file_path: Optional[str] = None,
    youtube_thumbnail_path: Optional[str] = None,
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
    mb_result: Optional[dict[str, Any]] = None
    try:
        mb_result = search_musicbrainz(clean_artist, clean_title)
    except Exception as exc:  # страховка на случай неожиданных ошибок
        print(f"[musicbrainz] unexpected search error: {exc}")

    if mb_result is not None:
        cover_data: Optional[bytes] = None
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


def _cached_entry_for_path(file_path: str) -> Optional[dict[str, Any]]:
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


def get_cached_cover_for_path(file_path: str) -> Optional[str]:
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


def get_cached_source_for_path(file_path: str) -> Optional[str]:
    """Источник метаданных для UI: musicbrainz / youtube / fallback."""
    cached = _cached_entry_for_path(file_path)
    if not cached:
        return None
    source = str(cached.get("source") or "").casefold()
    if source in ("musicbrainz", "youtube", "fallback"):
        return source
    return None
