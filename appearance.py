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

"""Применение темы и перекраска иконок во всех вкладках."""

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from styles import DARK_THEME, LIGHT_THEME


class AppearanceManager(QObject):
    """Единая точка применения UI-настроек.

    Порядок обновления сохранён как в прежнем ``MainWindow``: сначала
    перестраивается библиотека, затем обновляются остальные вкладки,
    аватарка и иконки.
    """

    avatar_update_requested = pyqtSignal()

    def __init__(
        self,
        settings,
        icons,
        library_tab,
        playlists_page,
        player_bar,
        lyrics_panel,
        settings_page,
        profile_page,
        friends_page,
        media_player,
        player_state_changed,
        parent_window=None,
        parent=None,
    ):
        super().__init__(parent if parent is not None else parent_window)
        self.settings = settings
        self.icons = icons
        self.library_tab = library_tab
        self.playlists_page = playlists_page
        self.player_bar = player_bar
        self.lyrics_panel = lyrics_panel
        self.settings_page = settings_page
        self.profile_page = profile_page
        self.friends_page = friends_page
        self.media_player = media_player
        self.player_state_changed = player_state_changed
        self.parent_window = parent_window
        self.is_dark_theme = True

    def apply_ui_settings(self):
        """Применяет тему из настроек.

        Масштаб интерфейса сюда не входит: он задаётся через
        ``QT_SCALE_FACTOR`` в ``main.py`` до создания ``QApplication`` и
        вступает в силу только после перезапуска приложения.
        """
        app = QApplication.instance()
        if app is None:
            return

        theme = self.settings.value("theme", "dark")
        self.is_dark_theme = (theme != "light")
        self.icons.set_dark(self.is_dark_theme)
        if self.parent_window is not None:
            self.parent_window.is_dark_theme = self.is_dark_theme

        app.setStyleSheet(LIGHT_THEME if theme == "light" else DARK_THEME)

        # Тема сменилась — перерисовываем списки и перекрашиваем иконки,
        # иначе делегаты/иконки остаются в цветах прежней темы.
        self.library_tab.reload()
        self.apply_icons()

    def apply_icons(self):
        """Обновляет иконки и данные во всех вкладках после смены темы."""
        # PlaylistsPage перекрашивает иконки внутри reload().
        self.playlists_page.reload()

        # ProfilePage перекрашивает иконки внутри reload_stats().
        self.profile_page.reload_stats()

        # Аватарка в углу вкладок.
        self.avatar_update_requested.emit()

        # FriendsPage перекрашивает поиск и строки друзей.
        self.friends_page.refresh_icons()

        # Панель библиотеки (тулбар, поиск, фильтр, Next in queue)
        self.library_tab.apply_theme()

        # Нижняя панель плеера и панель текста.
        self.player_bar.apply_theme()
        self.lyrics_panel.apply_theme()
        self.player_state_changed(self.media_player.state())

        # Настройки перекрашивают навигацию и описания.
        self.settings_page.apply_theme()
