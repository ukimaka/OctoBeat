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

"""Аватарка в углу вкладок и меню профиля/настроек."""

from PyQt5.QtCore import QObject, QSize, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMenu, QPushButton, QSizePolicy

import db
from profile_ui import _round_avatar_pixmap
from translations import tr
from ui_common import apply_menu_depth


class AccountMenu(QObject):
    """Управляет глобальной аватаркой и локальным меню пользователя."""

    def __init__(
        self,
        parent_window,
        settings,
        tabs,
        profile_page,
        icons,
    ):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.settings = settings
        self.tabs = tabs
        self.profile_page = profile_page
        self.icons = icons

        self.avatar_button = self._build_avatar_button()

        # Смена аватарки в профиле сразу обновляет кнопку в углу вкладок.
        self.profile_page.avatar_changed.connect(
            lambda _path: self.update_avatar()
        )

    # ------------------------------------------------------------------
    #  Аватарка
    # ------------------------------------------------------------------
    def _build_avatar_button(self):
        """Маленькая круглая аватарка для правого верхнего угла вкладок."""
        self.avatar_button = QPushButton()
        self.avatar_button.setObjectName("globalAvatarButton")
        self.avatar_button.setFlat(True)
        self.avatar_button.setFixedSize(32, 32)
        self.avatar_button.setIconSize(QSize(32, 32))
        # Фиксированный размер не должен растягиваться layout'ом.
        self.avatar_button.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        self.avatar_button.setCursor(Qt.PointingHandCursor)
        self.avatar_button.setStyleSheet(
            "QPushButton#globalAvatarButton {"
            " border: none; background: transparent; border-radius: 16px;"
            " padding: 0px;"
            "}"
            "QPushButton#globalAvatarButton:hover {"
            " background: rgba(128, 128, 128, 0.2); }"
        )
        self.avatar_button.clicked.connect(self._show_profile)
        self.avatar_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.avatar_button.customContextMenuRequested.connect(
            self._show_avatar_context_menu
        )

        self.update_avatar()
        self.update_tooltip()
        return self.avatar_button

    def update_avatar(self) -> None:
        """Обновляет аватарку в углу вкладок по локальному профилю."""
        try:
            profile = db.get_profile()
        except Exception:  # noqa: BLE001 - панель не должна ронять окно
            profile = None
        path = profile["avatar_path"] if profile else None
        self.avatar_button.setIcon(QIcon(_round_avatar_pixmap(path, 32)))

    def update_tooltip(self) -> None:
        lang = self.settings.value("language", "en")
        self.avatar_button.setToolTip(tr("Profile", lang))

    # ------------------------------------------------------------------
    #  Клик и контекстное меню
    # ------------------------------------------------------------------
    def _show_profile(self) -> None:
        """ЛКМ по аватарке открывает профиль (как и раньше)."""
        self.show_user_page(self.profile_page)
        self.profile_page.reload_stats()

    def _show_avatar_context_menu(self, pos) -> None:
        """ПКМ по аватарке: смена аватарки и полный выход из приложения."""
        lang = self.settings.value("language", "en")
        menu = QMenu(self.parent_window)
        apply_menu_depth(menu)

        change_action = menu.addAction(
            self.icons.icon("image.svg"), tr("Change avatar", lang)
        )
        menu.addSeparator()
        exit_action = menu.addAction(
            self.icons.icon("cancel.svg"), tr("Exit", lang)
        )

        chosen = menu.exec_(self.avatar_button.mapToGlobal(pos))
        if chosen is change_action:
            self.profile_page.change_avatar()
        elif chosen is exit_action:
            self._quit_application()

    def _quit_application(self) -> None:
        quit_application = getattr(
            self.parent_window, "quit_application", None
        )
        if callable(quit_application):
            quit_application()
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ------------------------------------------------------------------
    #  Навигация
    # ------------------------------------------------------------------
    def show_user_page(self, page) -> None:
        """Показывает страницу, скрытую из tab bar.

        Виджет мог быть убран через ``removeTab`` — в этом случае возвращаем
        его в стек как невидимую вкладку, чтобы ``setCurrentWidget`` работал.
        """
        if self.tabs.indexOf(page) == -1:
            index = self.tabs.addTab(page, "")
            self.tabs.tabBar().setTabVisible(index, False)
        self.tabs.setCurrentWidget(page)
