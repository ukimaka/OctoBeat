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

"""Загрузка текстов песен через ``syncedlyrics`` и LRCLIB.

``syncedlyrics`` сама опрашивает несколько провайдеров (Musixmatch, LRCLIB,
NetEase, Megalobiz, Genius) и по умолчанию сначала ищет синхронизированный
текст, а если его нет — отдаёт обычный текст. Если библиотека ничего не
вернула, модуль делает прямой запрос к API LRCLIB. Код не зависит от UI:
сетевые запросы и запись в БД вынесены в ``LyricsWorker`` (QThread), чтобы
не блокировать главный поток.
"""

import inspect
import re

import requests
from PyQt5.QtCore import QThread, pyqtSignal

import db

try:
    import syncedlyrics
except ImportError:  # pragma: no cover — библиотека необязательна
    syncedlyrics = None
    print("[lyrics] syncedlyrics is not installed")

# Таймкод формата LRC: [mm:ss.xx], [mm:ss.xxx] или [mm:ss]. Шаблон совпадает
# с ``lyrics_manager._LRC_TIME_RE``, чтобы «синхронным» считалось ровно то,
# что умеет разобрать ``lyrics_manager.parse_lrc``.
_LRC_TIMECODE_RE = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]")

# Запасной источник синхронизированного текста.
LRCLIB_API_URL = "https://lrclib.net/api/get"
LRCLIB_TIMEOUT = 10  # секунд

# Старые версии syncedlyrics принимали ``allow_plain_format``; в новых (1.x)
# такого аргумента нет, но обычный текст там отдаётся и так (PREFER_SYNCED).
# Определяем поддержку один раз при импорте, чтобы не ловить TypeError.
_SEARCH_KWARGS = {}
if syncedlyrics is not None:
    try:
        _params = inspect.signature(syncedlyrics.search).parameters
        if "allow_plain_format" in _params:
            _SEARCH_KWARGS["allow_plain_format"] = True
    except (TypeError, ValueError):  # pragma: no cover — защитный путь
        _SEARCH_KWARGS = {}


def _fetch_lrclib_synced(artist, title):
    """Прямой запрос к LRCLIB; возвращает LRC или None.

    Любые сетевые ошибки и таймауты гасятся здесь: плеер не должен падать,
    если оба источника недоступны.
    """
    try:
        response = requests.get(
            LRCLIB_API_URL,
            params={
                "artist_name": artist or "",
                "track_name": title or "",
            },
            timeout=LRCLIB_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"[lyrics] LRCLIB request failed for '{artist} - {title}': {e}")
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except ValueError as e:  # сюда же попадает битый JSON
        print(f"[lyrics] LRCLIB returned invalid JSON: {e}")
        return None

    if not isinstance(payload, dict):
        return None

    synced = payload.get("syncedLyrics")
    if not isinstance(synced, str) or not synced.strip():
        return None
    return synced.strip()


def fetch_lyrics(artist, title, duration):
    """Ищет текст песни: сначала ``syncedlyrics``, затем LRCLIB.

    ``duration`` — длительность в целых секундах (может быть None); оставлен
    для совместимости с вызывающим кодом, в поисковом запросе не используется.

    Возвращает ``{"synced": ..., "plain": ...}`` или ``None``, если текста
    нет. Ровно одно из полей заполнено: ``synced`` — LRC с таймкодами,
    ``plain`` — обычный текст без таймкодов.
    """
    if not title:
        return None

    query = f"{artist} {title}".strip()
    result = None
    if syncedlyrics is not None:
        try:
            result = syncedlyrics.search(query, **_SEARCH_KWARGS)
        except Exception as e:  # noqa: BLE001 — сеть не должна ронять UI
            print(f"[lyrics] search failed for '{query}': {e}")

    if result and result.strip():
        # Строка с таймкодами — синхронизированный текст, иначе — обычный.
        if _LRC_TIMECODE_RE.search(result):
            return {"synced": result, "plain": None}
        return {"synced": None, "plain": result}

    # syncedlyrics ничего не вернул — пробуем прямой API LRCLIB.
    synced = _fetch_lrclib_synced(artist, title)
    if synced:
        return {"synced": synced, "plain": None}
    return None


class LyricsWorker(QThread):
    """Фоново грузит текст (syncedlyrics + LRCLIB) и сохраняет его в БД.

    ``loaded(track_id, synced, plain)`` — текст найден (или провайдеры
    ответили «нет текста», но это не кешируется как окончательный результат);
    ``failed(track_id, error)`` — запрос сорвался (текст не сохраняем, чтобы
    попробовать снова при следующем воспроизведении).
    """

    loaded = pyqtSignal(int, str, str)
    failed = pyqtSignal(int, str)

    def __init__(self, track_id, artist, title, duration, parent=None):
        super().__init__(parent)
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

    def run(self):
        try:
            result = fetch_lyrics(self.artist, self.title, self.duration)
        except Exception as e:  # noqa: BLE001 — воркер не должен ронять поток
            if not self._cancelled:
                self.failed.emit(self.track_id, str(e))
            return

        if self._cancelled:
            return

        if result is None:
            # Источники иногда молча возвращают None и при сетевом сбое, и
            # когда текста действительно нет. Не пишем это в БД как
            # окончательный ответ: иначе «пусто» закешируется навсегда.
            # Загрузку повторим при следующем запуске приложения.
            self.loaded.emit(self.track_id, "", "")
            return

        synced = result.get("synced") or ""
        plain = result.get("plain") or ""
        self._save(synced, plain)
        self.loaded.emit(self.track_id, synced, plain)

    def _save(self, synced, plain):
        if self._cancelled:
            return
        try:
            db.update_track_lyrics(self.track_id, synced, plain)
        except Exception as e:  # noqa: BLE001
            print(f"[lyrics] save failed for track {self.track_id}: {e}")
