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
