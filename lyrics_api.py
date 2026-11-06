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

"""Загрузка текстов песен через LRCLIB.

Поиск идёт только по паре «исполнитель + название». Результат LRCLIB
содержит метаданные трека, поэтому каждое совпадение дополнительно
проверяется: исполнитель и название должны совпадать с тегами файла, а
длительность — с длительностью в базе. Случайный текст другой песни
отбрасывается, даже если провайдер вернул его первым.

Код не зависит от UI: сетевые запросы и запись в БД вынесены в
``LyricsWorker`` (QThread), чтобы не блокировать главный поток.
"""

import difflib
import re

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from metadata_normalize import _fold, _titles_match
from qt_diagnostics import note, track_thread
import playback_trace

import db

# LRCLIB: /search возвращает список версий с метаданными (artistName,
# trackName, duration), что позволяет проверить каждое совпадение.
# /get оставлен как быстрый точный запрос без длительности.
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_TIMEOUT = 10  # секунд

# Допуск по длительности: 5 секунд или 3% (что больше). LRCLIB хранит
# длительность с точностью до долей секунды, а в БД она округлена.
_DURATION_ABS_TOLERANCE = 5.0
_DURATION_REL_TOLERANCE = 0.03

# Заглушки вместо реального исполнителя: искать по ним бессмысленно и
# опасно — любой трек с таким же названием может «совпасть».
_UNKNOWN_ARTISTS = {
    "unknown", "unknown artist", "unknown artists", "n a", "none",
    "неизвестный исполнитель", "неизвестен",
}


def _has_real_artist(artist):
    folded = _fold(artist)
    return bool(folded) and folded not in _UNKNOWN_ARTISTS


def _as_seconds(value):
    """Приводит длительность из API/БД к float; None, если это не число."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _durations_match(expected, candidate):
    """Сравнивает длительность трека и найденной версии.

    Если одна из длительностей неизвестна, проверку пропускаем: лучше
    показать текст, чем оставить трек без него из-за пустого поля в БД.
    """
    expected = _as_seconds(expected)
    candidate = _as_seconds(candidate)
    if expected is None or candidate is None:
        return True
    tolerance = max(
        _DURATION_ABS_TOLERANCE, expected * _DURATION_REL_TOLERANCE
    )
    return abs(expected - candidate) <= tolerance


def _artist_variants(value):
    """Варианты имени исполнителя: полное и отдельные участники."""
    raw = str(value or "")
    # Отбрасываем «feat. X»: основной исполнитель должен совпасть.
    raw = re.split(
        r"\b(?:feat|ft|featuring)\b", raw, maxsplit=1, flags=re.IGNORECASE
    )[0]

    variants = set()

    def add_folded(text):
        folded = _fold(text)
        if not folded:
            return
        variants.add(folded)
        # Артикли в начале не меняют исполнителя: «The Beatles» = «Beatles».
        variants.add(re.sub(r"^the\s+", "", folded))

    add_folded(raw)
    # «Simon and Garfunkel» = «Simon & Garfunkel»: убираем союз целиком,
    # но не разбиваем имя на отдельных участников — иначе «Florence and
    # the Machine» ложно совпадёт с «Florence».
    add_folded(re.sub(r"\band\b", " ", raw, flags=re.IGNORECASE))

    for part in re.split(r"\s*(?:;|,|/|&|\+)\s*", raw):
        add_folded(part)
    return variants


def _artists_match_strict(expected, candidate):
    """Строгое сравнение исполнителей для текстов песен.

    В отличие от поиска обложек, здесь нельзя принимать частичное
    совпадение вроде «Muse» → «Muse Tribute»: лучше не найти текст, чем
    показать текст другой группы. Совпадают только полностью одинаковые
    имена (с поправкой на регистр/пунктуацию), варианты ``feat.`` и
    перечисления исполнителей через ``;``/``,``/``&``.
    """
    left = _artist_variants(expected)
    right = _artist_variants(candidate)
    if not left or not right:
        return False
    if left & right:
        return True

    # Небольшие различия в написании (дефисы, диакритика, транслит)
    # допускаем только при очень высоком сходстве.
    for a in left:
        for b in right:
            if difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
                return True
    return False


def _record_matches(record, artist, title, duration):
    """Проверяет, что запись LRCLIB относится именно к нашему треку."""
    if not isinstance(record, dict):
        return False
    rec_artist = record.get("artistName") or ""
    rec_title = record.get("trackName") or ""
    # Оба поля обязательны: запись без исполнителя/названия нельзя
    # подтвердить, а значит и показывать её нельзя.
    if not _fold(rec_artist) or not _fold(rec_title):
        return False
    if not _artists_match_strict(artist, rec_artist):
        return False
    if not _titles_match(title, rec_title):
        return False
    return _durations_match(duration, record.get("duration"))


def _record_has_lyrics(record):
    return bool(
        (record.get("syncedLyrics") or "").strip()
        or (record.get("plainLyrics") or "").strip()
    )


def _record_score(record, duration):
    """Чем больше, тем лучше: синхронный текст, затем близость длительности."""
    synced = bool((record.get("syncedLyrics") or "").strip())
    expected = _as_seconds(duration)
    candidate = _as_seconds(record.get("duration"))
    if expected is not None and candidate is not None:
        diff = abs(expected - candidate)
    else:
        diff = 999.0
    return (1 if synced else 0, -diff)


def _pick_best(records, artist, title, duration):
    """Выбирает лучшую подтверждённую запись из ответа /search."""
    best = None
    best_score = None
    for record in records:
        if not _record_matches(record, artist, title, duration):
            continue
        if not _record_has_lyrics(record):
            continue
        score = _record_score(record, duration)
        if best is None or score > best_score:
            best = record
            best_score = score
    return best


def _request_json(url, params):
    """GET-запрос к LRCLIB.

    Возвращает ``(status, payload)``, где status:
    ``"ok"`` — 200 и валидный JSON, ``"empty"`` — 404 (совпадений нет),
    ``"error"`` — сеть/HTTP/JSON. Ошибку и «ничего не найдено» важно
    различать: во втором случае имеет смысл точный запрос, в первом — нет
    (иначе LRCLIB быстро отвечает 429).
    """
    try:
        response = requests.get(url, params=params, timeout=LRCLIB_TIMEOUT)
    except requests.RequestException as e:
        print(f"[lyrics] LRCLIB request failed: {e}")
        return "error", None

    if response.status_code == 404:
        return "empty", None
    if response.status_code == 429:
        print("[lyrics] LRCLIB rate limit reached")
        return "error", None
    if response.status_code != 200:
        print(
            f"[lyrics] LRCLIB returned HTTP {response.status_code} "
            f"for {params}"
        )
        return "error", None
    try:
        return "ok", response.json()
    except ValueError as e:  # сюда же попадает битый JSON
        print(f"[lyrics] LRCLIB returned invalid JSON: {e}")
        return "error", None


def _fetch_lrclib(artist, title, duration):
    """Ищет текст в LRCLIB и возвращает ``{"synced", "plain"}`` или None.

    Запросов не больше двух, и в каждом обязательно передаются и
    исполнитель, и название:

    1. ``/search`` — список версий с метаданными, из которого выбирается
       версия, прошедшая проверку исполнителя/названия/длительности;
    2. ``/get`` — точный запрос по паре artist + title, если поиск ничего
       не дал. Его результат проверяется теми же правилами.

    Запись без подтверждённого исполнителя и названия не принимается.
    """
    if not _has_real_artist(artist) or not (title or "").strip():
        # Без обоих параметров поиск неизбежно даёт случайные совпадения.
        return None

    status, payload = _request_json(
        LRCLIB_SEARCH_URL,
        {"artist_name": artist, "track_name": title},
    )
    record = None
    if status == "ok":
        records = payload if isinstance(payload, list) else [payload]
        record = _pick_best(records, artist, title, duration)

    # Точный запрос — только если поиск отработал, но ничего не подтвердил.
    # При сетевой ошибке/429 второй запрос только усугубит лимит.
    if record is None and status != "error":
        status, payload = _request_json(
            LRCLIB_GET_URL,
            {"artist_name": artist, "track_name": title},
        )
        if status == "ok" and isinstance(payload, dict):
            if _record_matches(payload, artist, title, duration):
                record = payload

    if record is None:
        return None

    synced = (record.get("syncedLyrics") or "").strip()
    plain = (record.get("plainLyrics") or "").strip()
    if not synced and not plain:
        return None
    return {
        "synced": synced if synced else None,
        "plain": plain if plain and not synced else None,
    }


def fetch_lyrics(artist, title, duration):
    """Ищет текст песни по исполнителю, названию и длительности.

    ``duration`` — длительность в целых секундах (может быть None). Оба
    параметра ``artist`` и ``title`` обязательны: поиск только по названию
    часто возвращает текст другой песни.

    Возвращает ``{"synced": ..., "plain": ...}`` или ``None``, если текста
    нет. Ровно одно из полей заполнено: ``synced`` — LRC с таймкодами,
    ``plain`` — обычный текст без таймкодов.
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not _has_real_artist(artist) or not title:
        return None

    return _fetch_lrclib(artist, title, duration)


class LyricsWorker(QThread):
    """Фоново грузит текст (LRCLIB) и сохраняет его в БД.

    ``loaded(track_id, synced, plain)`` — текст найден (или провайдеры
    ответили «нет текста», но это не кешируется как окончательный результат);
    ``failed(track_id, error)`` — запрос сорвался (текст не сохраняем, чтобы
    попробовать снова при следующем воспроизведении).
    """

    loaded = pyqtSignal(int, str, str)
    failed = pyqtSignal(int, str)

    def __init__(self, track_id, artist, title, duration, parent=None):
        super().__init__(parent)
        track_thread(self, "lyrics")
        self.track_id = track_id
        self.artist = artist
        self.title = title
        self.duration = duration
        self._cancelled = False

    def cancel(self):
        """Просит воркер не сохранять/не отдавать результат.

        Сетевой вызов внутри ``run()`` прервать нельзя, но это безопасно:
        он выполняется в отдельном потоке, а после возврата результат просто
        игнорируется. Главный поток при этом не блокируется.
        """
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        if self._cancelled or self.isInterruptionRequested():
            playback_trace.log("lyrics.fetch.cancelled", track=self.track_id)
            return
        note(f"lyrics fetch start track={self.track_id}")
        playback_trace.log("lyrics.fetch.start", track=self.track_id, artist=self.artist, title=self.title, duration=self.duration)
        try:
            playback_trace.log("lyrics.fetch.request", track=self.track_id)
            result = fetch_lyrics(self.artist, self.title, self.duration)
            playback_trace.log("lyrics.fetch.response", track=self.track_id, found=bool(result), synced_len=len((result or {}).get("synced") or ""), plain_len=len((result or {}).get("plain") or ""))
        except Exception as e:  # noqa: BLE001 — воркер не должен ронять поток
            if not self._cancelled:
                playback_trace.log("lyrics.fetch.failed", track=self.track_id, error=str(e))
                self.failed.emit(self.track_id, str(e))
            return

        if self._cancelled or self.isInterruptionRequested():
            playback_trace.log("lyrics.fetch.cancelled", track=self.track_id)
            return

        if result is None:
            playback_trace.log("lyrics.fetch.none", track=self.track_id)
            # Источники иногда молча возвращают None и при сетевом сбое, и
            # когда текста действительно нет. Не пишем это в БД как
            # окончательный ответ: иначе «пусто» закешируется навсегда.
            # Загрузку повторим при следующем запуске приложения.
            self.loaded.emit(self.track_id, "", "")
            return

        synced = result.get("synced") or ""
        plain = result.get("plain") or ""
        playback_trace.log("lyrics.fetch.saving", track=self.track_id, synced_len=len(synced), plain_len=len(plain))
        self._save(synced, plain)
        note(f"lyrics fetch done track={self.track_id}")
        playback_trace.log("lyrics.fetch.done", track=self.track_id)
        self.loaded.emit(self.track_id, synced, plain)

    def _save(self, synced, plain):
        if self._cancelled or self.isInterruptionRequested():
            playback_trace.log("lyrics.fetch.cancelled", track=self.track_id)
            return
        try:
            # Пользователь мог сохранить свой текст, пока шёл запрос:
            # ручные правки неприкосновенны.
            if db.is_track_lyrics_manual(self.track_id):
                playback_trace.log(
                    "lyrics.fetch.skip_manual", track=self.track_id
                )
                return
            db.update_track_lyrics(self.track_id, synced, plain)
        except Exception as e:  # noqa: BLE001
            print(f"[lyrics] save failed for track {self.track_id}: {e}")
