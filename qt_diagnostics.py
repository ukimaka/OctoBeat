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

"""Диагностика фатальных Qt-сообщений и фоновых потоков.

Qt при ``QThread: Destroyed while thread is still running`` вызывает
``qFatal`` и abort. Обычный Python ``except`` здесь не срабатывает, поэтому
ставим Qt message handler, faulthandler и ведём кольцевой буфер последних
действий. Всё пишется в отдельный ``qt-fatal.log`` в каталог данных.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

from PyQt5.QtCore import (
    QThread,
    QThreadPool,
    QtFatalMsg,
    qInstallMessageHandler,
)

from paths import DATA_DIR

LOG_PATH: Path = DATA_DIR / "qt-fatal.log"
_ACTION_LIMIT = 120
_actions: deque[str] = deque(maxlen=_ACTION_LIMIT)
_lock = threading.RLock()
_threads: dict[int, tuple[QThread, str]] = {}
_pools: dict[int, tuple[QThreadPool, str]] = {}
_workers: dict[int, tuple[QThread, object]] = {}
_previous_handler = None
_faulthandler_file = None
_installed = False


def _thread_name() -> str:
    """Имя текущего QThread для строки лога."""
    if threading.current_thread() is threading.main_thread():
        return "main"
    try:
        name = QThread.currentThread().objectName()
        if name:
            return name
    except Exception:
        pass
    return f"py-{threading.get_ident()}"


def note(action: str) -> None:
    """Запоминает последнее действие (для отчёта при qFatal)."""
    stamp = time.strftime("%H:%M:%S")
    line = f"{stamp} [{_thread_name()}] {action}"
    with _lock:
        _actions.append(line)


def track_thread(thread, name: str):
    """Задаёт имя и держит сильную ссылку, пока QThread работает.

    Это не даёт Python GC уничтожить C++ QThread, если объект был создан
    локально в функции и потерял обычную ссылку.
    """
    if thread is None:
        return thread
    try:
        thread.setObjectName(name)
        with _lock:
            _prune_finished_threads()
            _threads[id(thread)] = (thread, name)
    except RuntimeError:
        pass
    return thread


def track_pool(pool, name: str):
    """Задаёт имя QThreadPool и держит ссылку для диагностики."""
    if pool is None:
        return pool
    try:
        pool.setObjectName(name)
        with _lock:
            _pools[id(pool)] = (pool, name)
    except RuntimeError:
        pass
    return pool


def untrack_pool(pool) -> None:
    """Убирает пул из реестра после полного ожидания."""
    if pool is None:
        return
    with _lock:
        _pools.pop(id(pool), None)


def hold_worker(thread, worker, name=None):
    """Держит объект-воркер живым, пока его QThread не завершится.

    ``moveToThread()`` не передаёт Qt владение QObject: если атрибут
    воркера обнулить, а локальную ссылку потерять, Python может собрать
    wrapper, пока нативный ``run()`` ещё работает. Реестр удерживает
    пару «поток → воркер» до фактического ``finished``.
    """
    if thread is None or worker is None:
        return worker
    try:
        if name:
            worker.setObjectName(name)
    except (RuntimeError, TypeError):
        pass
    with _lock:
        _workers[id(thread)] = (thread, worker)
    return worker


def _prune_finished_threads() -> None:
    """Убирает из реестра уже завершённые QThread (вызывается под lock)."""
    for key, (thread, _name) in list(_threads.items()):
        try:
            if not thread.isRunning():
                del _threads[key]
        except RuntimeError:
            del _threads[key]
    for key, (thread, _worker) in list(_workers.items()):
        try:
            if thread.isFinished():
                del _workers[key]
        except RuntimeError:
            del _workers[key]


def _worker_label(thread) -> str:
    """Имя воркера, привязанного к потоку (для fatal-отчёта)."""
    entry = _workers.get(id(thread))
    if entry is None:
        return ""
    worker = entry[1]
    try:
        name = worker.objectName()
        if name:
            return f" worker='{name}'"
        return f" worker={worker.metaObject().className()}"
    except RuntimeError:
        return " worker=(C++ deleted)"


def alive_background_summary() -> list[str]:
    """Список живых QThread/QThreadPool для фатального отчёта."""
    lines = []
    with _lock:
        for thread, name in list(_threads.values()):
            try:
                lines.append(
                    f"  QThread '{name}' "
                    f"class={thread.metaObject().className()} "
                    f"running={thread.isRunning()} "
                    f"finished={thread.isFinished()}"
                    f"{_worker_label(thread)}"
                )
            except RuntimeError:
                lines.append(
                    f"  QThread '{name}' (C++ deleted)"
                    f"{_worker_label(thread)}"
                )
        for pool, name in list(_pools.values()):
            try:
                lines.append(
                    f"  QThreadPool '{name}' "
                    f"active={pool.activeThreadCount()} "
                    f"max={pool.maxThreadCount()}"
                )
            except RuntimeError:
                lines.append(f"  QThreadPool '{name}' (C++ deleted)")
    return lines


def _write(text: str) -> None:
    """Атомарно дописывает текст в отдельный лог."""
    with _lock:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(text)
                if not text.endswith("\n"):
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            try:
                sys.stderr.write(f"[diagnostics] cannot write log: {exc}\n")
            except Exception:
                pass


def log_warning(message: str) -> None:
    """Пишет предупреждение о долгом ожидании в тот же лог."""
    _write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [WARN] {message}\n")


def _fatal_report(message: str, context) -> str:
    lines = [
        "",
        "=" * 78,
        f"QT FATAL: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"thread: {_thread_name()}",
        f"message: {message}",
    ]
    if context is not None:
        try:
            lines.append(
                f"context: {context.file}:{context.line} {context.function}"
            )
        except Exception:
            pass
    lines.append("alive background objects:")
    lines.extend(alive_background_summary() or ["  (none)"])
    lines.append("last actions:")
    with _lock:
        actions = list(_actions)
    lines.extend(f"  {line}" for line in actions)
    lines.append("python stack:")
    lines.extend(traceback.format_stack(limit=40))
    lines.append("=" * 78)
    return "\n".join(lines) + "\n"


def _message_handler(mode, context, message):
    """Qt message handler: расширенный отчёт только для фатальных сообщений."""
    fatal = (
        mode == QtFatalMsg
        or "Destroyed while thread is still running" in str(message)
    )
    if fatal:
        try:
            _write(_fatal_report(str(message), context))
            if _faulthandler_file is not None:
                try:
                    faulthandler.dump_traceback(
                        file=_faulthandler_file, all_threads=True
                    )
                    _faulthandler_file.flush()
                except Exception:
                    pass
        except Exception as exc:
            try:
                sys.stderr.write(f"[diagnostics] fatal report failed: {exc}\n")
            except Exception:
                pass
    if _previous_handler is not None:
        try:
            _previous_handler(mode, context, message)
            return
        except Exception:
            pass
    try:
        sys.stderr.write(str(message) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    """Логирует необработанное Python-исключение и вызывает старый hook."""
    try:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        _write(
            f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"UNCAUGHT EXCEPTION [{_thread_name()}]\n{text}\n"
        )
    except Exception:
        pass
    if _old_excepthook is not None:
        _old_excepthook(exc_type, exc, tb)


_old_excepthook = None


def install_diagnostics() -> Path:
    """Включает faulthandler, Qt handler и sys.excepthook. Идемпотентно."""
    global _installed, _previous_handler, _old_excepthook
    global _faulthandler_file
    if _installed:
        return LOG_PATH
    _installed = True
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _faulthandler_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_faulthandler_file, all_threads=True)
    except Exception as exc:
        try:
            sys.stderr.write(f"[diagnostics] faulthandler disabled: {exc}\n")
        except Exception:
            pass
    try:
        _previous_handler = qInstallMessageHandler(_message_handler)
    except Exception as exc:
        try:
            sys.stderr.write(f"[diagnostics] Qt handler disabled: {exc}\n")
        except Exception:
            pass
    _old_excepthook = sys.excepthook
    sys.excepthook = _excepthook
    note(f"diagnostics enabled, log={LOG_PATH}")
    return LOG_PATH


_EXIT_WAIT_TIMEOUT = 10.0
_background_left_running = False


def background_left_running() -> bool:
    """True, если последний wait_for_background() не дождался потоков."""
    return _background_left_running


def wait_for_background(timeout: float | None = None) -> bool:
    """Дожидается QThread/QThreadPool, но не бесконечно.

    Возвращает True, если все фоновые задачи завершились. Если общий
    дедлайн истёк, пишет в лог список незавершённых объектов и
    возвращает False. Вызывающий код должен в этом случае завершить
    процесс через os._exit(), иначе Qt может аварийно завершиться при
    уничтожении работающего QThread.
    """
    global _background_left_running
    _background_left_running = False
    if timeout is None:
        timeout = _EXIT_WAIT_TIMEOUT
    deadline = time.monotonic() + max(0.0, float(timeout))

    with _lock:
        pools = list(_pools.values())
        threads = list(_threads.values())

    def remaining_ms() -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    for pool, name in pools:
        try:
            pool.clear()
            active = pool.activeThreadCount()
            if not active:
                continue
            if remaining_ms() <= 0:
                _background_left_running = True
                log_warning(
                    f"exit wait: QThreadPool {name} still active; "
                    f"deadline {timeout:.1f}s exceeded"
                )
                continue
            note(f"exit wait: QThreadPool {name} active={active}")
            log_warning(
                f"exit wait: QThreadPool {name} active={active}; "
                f"waiting up to {remaining_ms()} ms"
            )
            started = time.monotonic()
            done = pool.waitForDone(remaining_ms())
            elapsed = time.monotonic() - started
            note(
                f"exit wait: QThreadPool {name} done={done} "
                f"in {elapsed:.2f}s"
            )
            log_warning(
                f"exit wait: QThreadPool {name} finished={done} "
                f"in {elapsed:.2f}s"
            )
            if not done:
                _background_left_running = True
                log_warning(
                    f"exit wait: QThreadPool {name} did not finish within "
                    f"{timeout:.1f}s; leaving it running"
                )
        except RuntimeError:
            pass

    for thread, name in threads:
        try:
            if not thread.isRunning():
                continue
            if remaining_ms() <= 0:
                _background_left_running = True
                log_warning(
                    f"exit wait: QThread {name} still running; "
                    f"deadline {timeout:.1f}s exceeded"
                )
                continue
            note(f"exit wait: QThread {name} running")
            log_warning(
                f"exit wait: QThread {name} still running; "
                f"waiting up to {remaining_ms()} ms"
            )
            started = time.monotonic()
            done = thread.wait(remaining_ms())
            elapsed = time.monotonic() - started
            note(
                f"exit wait: QThread {name} done={done} "
                f"in {elapsed:.2f}s"
            )
            log_warning(
                f"exit wait: QThread {name} finished={done} "
                f"in {elapsed:.2f}s"
            )
            if not done:
                _background_left_running = True
                log_warning(
                    f"exit wait: QThread {name} did not finish within "
                    f"{timeout:.1f}s; leaving it running"
                )
        except RuntimeError:
            pass

    with _lock:
        _prune_finished_threads()
    return not _background_left_running


def shutdown_diagnostics() -> None:
    """Сбрасывает faulthandler и очищает реестры после остановки потоков."""
    global _faulthandler_file
    note("diagnostics shutdown")
    with _lock:
        _threads.clear()
        _pools.clear()
        _workers.clear()
    if _faulthandler_file is not None:
        try:
            faulthandler.disable()
        except Exception:
            pass
        try:
            _faulthandler_file.flush()
            _faulthandler_file.close()
        except Exception:
            pass
        _faulthandler_file = None
