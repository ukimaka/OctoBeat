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

import os
import signal
import sys
import threading
import time

from PyQt5.QtCore import (
    QLibraryInfo,
    QLocale,
    QSettings,
    Qt,
    QTimer,
    QTranslator,
)
from PyQt5.QtGui import QPixmapCache
from PyQt5.QtWidgets import QApplication

import db
from main_window import MainWindow
from musicbrainz_client import init_musicbrainz
from paths import migrate_old_data
from qt_diagnostics import (
    background_left_running,
    install_diagnostics,
    log_warning,
    note,
    shutdown_diagnostics,
    wait_for_background,
)
from styles import ensure_preset_themes, load_theme
from ui_common import install_tooltip_delay

_interrupted = False


def _install_signal_handlers(app, window):
    """Делает Ctrl+C завершающим приложение, а не вечным ожиданием.

    Qt-цикл не возвращает управление Python без вызова Python-кода,
    поэтому лёгкий таймер регулярно даёт интерпретатору обработать
    SIGINT. Если штатное закрытие зависло на фоновом потоке, отдельный
    watchdog завершает процесс через os._exit() с записью в лог.
    """
    global _interrupted

    ticker = QTimer(app)
    ticker.timeout.connect(lambda: None)
    ticker.start(200)

    def _force_exit():
        time.sleep(6.0)
        try:
            note("signal watchdog: forcing process exit")
            log_warning(
                "signal watchdog: shutdown did not finish in 6s; "
                "forcing process exit"
            )
        finally:
            os._exit(130)

    def _request_shutdown():
        # Закрываем модальные диалоги (YouTube, прогресс и т.п.), затем
        # главное окно: его closeEvent делает ограниченное ожидание.
        for widget in QApplication.topLevelWidgets():
            if widget is window:
                continue
            try:
                widget.close()
            except RuntimeError:
                pass
        try:
            quit_application = getattr(window, "quit_application", None)
            if callable(quit_application):
                quit_application()
            else:
                window.close()
        except RuntimeError:
            pass
        app.quit()

    def _handler(signum, _frame):
        global _interrupted
        if _interrupted:
            return
        _interrupted = True
        note(f"signal {signum} received; requesting shutdown")
        log_warning(f"signal {signum} received; requesting shutdown")
        threading.Thread(
            target=_force_exit,
            name="signal-watchdog",
            daemon=True,
        ).start()
        QTimer.singleShot(0, _request_shutdown)

    signal.signal(signal.SIGINT, _handler)
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass
    return ticker


def main():
    global _interrupted
    install_diagnostics()
    migrate_old_data()
    # Масштаб читаем ДО создания QApplication: QT_SCALE_FACTOR применяется
    # Qt только на старте и масштабирует весь интерфейс — шрифты, иконки,
    # отступы и размеры окон, а не только текст.
    settings = QSettings("MusicPlayer", "MusicPlayer")
    try:
        zoom = int(settings.value("zoom", 100))
    except (TypeError, ValueError):
        zoom = 100

    # Qt5 умеет увеличивать интерфейс через QT_SCALE_FACTOR, но значения
    # меньше 1 (например, 0.75) официально не поддерживаются: backing store
    # получает меньше физических пикселей, чем логических, из-за чего часть
    # виджетов обрезается/исчезает. Поэтому 75% больше не применяем как
    # глобальный scale factor — сбрасываем сохранённое значение на 100%.
    if zoom < 100:
        zoom = 100
        settings.setValue("zoom", zoom)
        settings.sync()
    if zoom != 100:
        os.environ["QT_SCALE_FACTOR"] = str(zoom / 100.0)

    # Дробный масштаб (125%, 150%) не округляем до целого: иначе Qt может
    # внезапно переключиться на 100% или 200% и сломать компоновку.
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    # Включаем High-DPI до создания QApplication. Вместе с UseHighDpiPixmaps
    # это заставляет Qt пересчитывать логические размеры и растр иконок
    # согласованно при системном масштабе.
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    # Заставляет QIcon учитывать devicePixelRatio и возвращать физически
    # крупные pixmap'ы. Без этого Qt рисует иконку 22px как 22 физических
    # пикселя и растягивает её до 33 — отсюда замыливание при 150%.
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # MusicBrainz блокирует запросы без корректного User-Agent.
    init_musicbrainz()

    db.init_db()   # создаёт таблицы, если их нет

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    install_tooltip_delay(app, 1000)
    # Ограничиваем глобальный кэш обложек: 8 МБ достаточно для списков,
    # но не позволяет Qt держать десятки мегабайт растров «на всякий случай».
    QPixmapCache.setCacheLimit(8 * 1024)
    ensure_preset_themes()
    load_theme(settings.value("theme", "dark"), app)

    # Локализуем встроенные элементы Qt (Undo/Redo/Copy/Paste и т.п.).
    lang = settings.value("language", "en")
    if lang == "ru":
        translator = QTranslator(app)
        translations_path = QLibraryInfo.location(
            QLibraryInfo.TranslationsPath
        )
        if translator.load("qtbase_ru", translations_path):
            app.installTranslator(translator)

    window = MainWindow()
    window.show()
    signal_ticker = _install_signal_handlers(app, window)
    try:
        exit_code = app.exec_()
    except KeyboardInterrupt:
        _interrupted = True
        note("KeyboardInterrupt during event loop")
        log_warning("KeyboardInterrupt during event loop; shutting down")
        exit_code = 130
    if _interrupted and not exit_code:
        exit_code = 130

    # closeEvent уже ждал потоки, но при Ctrl+C окно могло не закрыться
    # (например, из-за модального диалога). Повторное ожидание ограничено
    # по времени и не даёт приложению зависнуть навсегда. При обычном
    # закрытии даём только короткий второй шанс уже отвязанным потокам.
    wait_for_background(timeout=None if _interrupted else 2.0)
    left_running = background_left_running()
    shutdown_diagnostics()
    if left_running:
        log_warning(
            "process exit: background threads still running after bounded "
            "wait; using os._exit to avoid QThread abort"
        )
        os._exit(exit_code or 130)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
