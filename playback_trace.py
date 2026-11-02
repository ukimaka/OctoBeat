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

"""Временная трассировка первого воспроизведения после старта.

Включается переменной окружения ``OCTOBEAT_TRACE_FIRST_PLAY=1``. Каждая
строка пишется в ``first-play-trace.log`` в каталоге данных приложения и
дублируется через ``qt_diagnostics.note()``. Путь к файлу можно переопределить
переменной ``OCTOBEAT_TRACE_FIRST_PLAY_LOG``.

Трассировка охватывает только первый трек после запуска: она начинается перед
первым ``play()`` и выключается при завершении трека, crossfade или переходе
на следующий трек. Это диагностический модуль: он ничего не меняет в логике
плеера и не должен оставаться в релизе.
"""

from __future__ import annotations

import os
import platform
import sys
import threading
import time
from pathlib import Path

from paths import DATA_DIR
from qt_diagnostics import _thread_name, note

ENV_FLAG = "OCTOBEAT_TRACE_FIRST_PLAY"
ENV_LOG = "OCTOBEAT_TRACE_FIRST_PLAY_LOG"


def _flag_enabled() -> bool:
    value = os.environ.get(ENV_FLAG, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


_ENABLED = _flag_enabled()
_LOG_PATH = Path(
    os.environ.get(ENV_LOG) or (DATA_DIR / "first-play-trace.log")
)
_LOCK = threading.RLock()
_started_at = None
_finished = False
_track_id = None


def enabled() -> bool:
    return _ENABLED


def active() -> bool:
    return _ENABLED and _started_at is not None and not _finished


def track_id():
    return _track_id


def _format_value(value) -> str:
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if not value:
            return "''"
        if any(ch.isspace() for ch in value) or "=" in value:
            return repr(value)
        return value
    return str(value)


def _write(line: str) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    except OSError as exc:
        try:
            sys.stderr.write(f"[first-play-trace] cannot write log: {exc}\n")
        except Exception:
            pass


def _row_value(row, key):
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def begin(track_id=None, path=None, row=None, source="") -> bool:
    """Начинает трассировку один раз за запуск приложения."""
    global _started_at, _track_id
    if not _ENABLED or _started_at is not None or _finished:
        return False
    with _LOCK:
        if _started_at is not None or _finished:
            return False
        _started_at = time.monotonic()
        _track_id = track_id
        _write(
            f"=== first-play trace begin {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            f"platform={sys.platform}\n"
            f"platform_detail={platform.platform()}\n"
            f"python={platform.python_version()}\n"
            f"session_type={os.environ.get('XDG_SESSION_TYPE')}\n"
            f"desktop={os.environ.get('XDG_CURRENT_DESKTOP')}\n"
            f"pulse_server={os.environ.get('PULSE_SERVER')}\n"
            f"pipewire_remote={os.environ.get('PIPEWIRE_REMOTE')}\n"
            f"log_path={_LOG_PATH}\n"
        )
    log(
        "trace.begin",
        track=track_id,
        path=path,
        source=source,
    )
    if row is not None:
        log(
            "track.meta",
            track=track_id,
            title=_row_value(row, "title"),
            artist=_row_value(row, "artist"),
            duration=_row_value(row, "duration"),
            loudness=_row_value(row, "loudness"),
            file_path=_row_value(row, "file_path"),
        )
    return True


def log(name: str, /, **fields) -> None:
    """Пишет одну строку в файл трассировки и в ring buffer note()."""
    if not active():
        return
    now = time.time()
    stamp = time.strftime("%H:%M:%S", time.localtime(now))
    elapsed_ms = (time.monotonic() - _started_at) * 1000.0
    parts = [
        f"{stamp}.{int(now * 1000) % 1000:03d}",
        f"+{elapsed_ms:9.1f}ms",
        f"[{_thread_name()}]",
        name,
    ]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    line = " ".join(parts)
    with _LOCK:
        _write(line)
    note(line)


def end(reason="") -> None:
    """Завершает трассировку первого трека; повторный вызов игнорируется."""
    global _finished
    if not _ENABLED or _started_at is None or _finished:
        return
    log("trace.end", reason=reason)
    with _LOCK:
        _finished = True
        _write(
            f"=== first-play trace end "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} reason={reason} ===\n"
        )
