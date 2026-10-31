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
import sys

from PyQt5.QtCore import QLibraryInfo, QLocale, QSettings, Qt, QTranslator
from PyQt5.QtWidgets import QApplication

import db
from main_window import MainWindow
from musicbrainz_client import init_musicbrainz
from styles import ensure_preset_themes, load_theme


def main():
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
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
