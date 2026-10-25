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

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication

from main_window import MainWindow
from styles import DARK_THEME
import db


def main():
    # Масштаб читаем ДО создания QApplication: QT_SCALE_FACTOR применяется
    # Qt только на старте и масштабирует весь интерфейс — шрифты, иконки,
    # отступы и размеры окон, а не только текст.
    settings = QSettings("MusicPlayer", "MusicPlayer")
    try:
        zoom = int(settings.value("zoom", 100))
    except (TypeError, ValueError):
        zoom = 100
    if zoom != 100:
        os.environ["QT_SCALE_FACTOR"] = str(zoom / 100.0)

    # Заставляет QIcon учитывать devicePixelRatio и возвращать физически
    # крупные pixmap'ы. Без этого Qt рисует иконку 22px как 22 физических
    # пикселя и растягивает её до 33 — отсюда замыливание при 150%.
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    db.init_db()   # создаёт таблицы, если их нет

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
