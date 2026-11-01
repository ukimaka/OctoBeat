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

"""Дисковый JSON-кэш метаданных MusicBrainz/YouTube."""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from metadata_normalize import normalize_artist_name, normalize_track_query

CACHE_DIR = Path.home() / ".cache" / "music_player"
CACHE_FILE = CACHE_DIR / "metadata_cache.json"

CACHE_TTL = 30 * 24 * 60 * 60          # успешный ответ — 30 дней
NEGATIVE_CACHE_TTL = 60 * 60           # заглушка/ошибка — 1 час


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


def _cache_get(key: str) -> dict[str, Any] | None:
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
