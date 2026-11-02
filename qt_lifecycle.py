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

"""Безопасная работа с временем жизни Qt-объектов.

Два класса падений, которые здесь закрываются:

* обращение к уже удалённому ``QWidget``/``QProgressDialog`` из
  запоздавшего queued-сигнала;
* уничтожение ``QThread``, чей ``run()`` ещё выполняется (Qt завершает
  процесс сообщением ``QThread: Destroyed while thread is still running``).
"""

from PyQt5 import sip
from PyQt5.QtCore import QTimer

from qt_diagnostics import log_warning, note, track_thread

# Потоки, которые не успели остановиться за wait(). Держим ссылки до
# фактического завершения: родитель-виджет уже не должен их уничтожать.
_LINGERING_THREADS = set()


def widget_alive(widget) -> bool:
    """True, если Python-обёртка и C++-объект виджета ещё живы."""
    if widget is None:
        return False
    try:
        return not sip.isdeleted(widget)
    except (RuntimeError, TypeError):
        return False


def retire_thread(thread, wait_ms: int = 2000) -> bool:
    """Останавливает и освобождает QThread, не удаляя работающий поток.

    Возвращает ``True``, если поток завершился и запланирован к удалению.
    Если за ``wait_ms`` он не остановился, поток отвязывается от родителя
    и остаётся в модульном реестре до сигнала/опроса о завершении.
    """
    if thread is None:
        return True
    name = thread.objectName() or thread.metaObject().className()
    track_thread(thread, name)
    note(f"retire_thread: waiting for {name}")
    try:
        if thread.isRunning():
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass
            try:
                thread.quit()
            except RuntimeError:
                pass
            thread.wait(wait_ms)
        if thread.isRunning():
            try:
                thread.setParent(None)
            except (RuntimeError, TypeError):
                pass
            _LINGERING_THREADS.add(thread)
            log_warning(
                f"QThread {name} did not stop in {wait_ms} ms; "
                "detached and kept alive"
            )
            note(f"retire_thread: {name} still running, detached")
            _schedule_release(thread)
            return False
        note(f"retire_thread: {name} finished")
        thread.deleteLater()
        return True
    except RuntimeError:
        # C++-объект уже удалён обработчиком finished.
        return True


def _schedule_release(thread) -> None:
    """Ждёт фактического завершения отвязанного потока и удаляет его."""
    if thread not in _LINGERING_THREADS:
        return
    try:
        if thread.isRunning():
            QTimer.singleShot(
                250, lambda t=thread: _schedule_release(t)
            )
            return
    except RuntimeError:
        pass
    _LINGERING_THREADS.discard(thread)
    note(f"retire_thread: releasing {thread.objectName() or 'thread'}")
    try:
        thread.deleteLater()
    except RuntimeError:
        pass
