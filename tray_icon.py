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

"""Системный трей OctoBeat: открыть окно или полностью выйти."""

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QSystemTrayIcon,
)

from paths import RESOURCE_DIR
from translations import tr
from ui_common import apply_menu_depth

APP_ICON_PATH = RESOURCE_DIR / "icons" / "OctoBeat.svg"


def application_icon() -> QIcon:
    """Иконка приложения из подготовленной папки icons/."""
    icon = QIcon(str(APP_ICON_PATH))
    if not icon.isNull():
        return icon
    app = QApplication.instance()
    if app is not None and not app.windowIcon().isNull():
        return app.windowIcon()
    return QIcon()


class TrayIcon(QObject):
    """QSystemTrayIcon с ленивым (и безопасным) поведением.

    Если трей в окружении недоступен, объект остаётся в режиме fallback:
    MainWindow тогда сворачивает окно в панель задач вместо скрытия.
    """

    open_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent_window, icons, parent=None):
        super().__init__(parent if parent is not None else parent_window)
        self.parent_window = parent_window
        self.icons = icons
        self.tray = None
        self._menu = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = application_icon()
        if icon.isNull():
            icon = parent_window.style().standardIcon(
                QStyle.SP_ComputerIcon
            )
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("OctoBeat")
        tray.setContextMenu(self._build_menu())
        tray.activated.connect(self._on_activated)
        tray.show()
        self.tray = tray

        # Скрытое окно не должно завершать приложение: выход только явный.
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)

    @property
    def available(self) -> bool:
        """Трей реально доступен и его иконка видима."""
        return bool(
            self.tray is not None
            and self.tray.isVisible()
            and QSystemTrayIcon.isSystemTrayAvailable()
        )

    def _build_menu(self):
        lang = self.parent_window.settings.value("language", "en")
        menu = QMenu()
        apply_menu_depth(menu)
        open_action = menu.addAction(
            self.icons.icon("expand.svg"), tr("Open", lang)
        )
        exit_action = menu.addAction(
            self.icons.icon("cancel.svg"), tr("Exit", lang)
        )
        open_action.triggered.connect(self.open_requested)
        exit_action.triggered.connect(self.quit_requested)
        self._menu = menu
        return menu

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            self.open_requested.emit()

    def refresh_menu(self):
        """Пересобирает меню после смены темы (цвета иконок)."""
        if self.tray is None:
            return
        old_menu = self._menu
        self.tray.setContextMenu(self._build_menu())
        if old_menu is not None:
            old_menu.deleteLater()

    def hide(self):
        if self.tray is not None:
            self.tray.hide()

    def show(self):
        if self.tray is not None:
            self.tray.show()
