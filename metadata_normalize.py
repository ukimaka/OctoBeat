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

"""Нормализация названий треков, исполнителей и сравнение метаданных."""

import re


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
#  Сравнение названий и исполнителей
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
