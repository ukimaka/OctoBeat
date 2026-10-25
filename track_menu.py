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

"""Построение контекстного меню трека.

Меню только создаёт пункты и сообщает о намерениях пользователя сигналами.
Никаких изменений в БД или плеере здесь нет.
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QAction, QMenu

from translations import tr


class TrackContextMenu(QMenu):
    """Общее меню трека для библиотеки и плейлиста."""

    add_to_playlist_requested = pyqtSignal(int, int)  # playlist_id, track_id
    add_to_queue_requested = pyqtSignal(int)          # track_id
    favorite_requested = pyqtSignal(int)              # track_id
    edit_metadata_requested = pyqtSignal(int)         # track_id
    remove_requested = pyqtSignal(int, str)           # track_id, scope

    def __init__(
        self,
        parent,
        settings,
        icons,
        track_id,
        playlists,
        scope,
        source_list,
    ):
        super().__init__(parent)
        if scope not in ("library", "playlist"):
            raise ValueError("scope must be 'library' or 'playlist'")
        self.settings = settings
        self.icons = icons
        self.track_id = track_id
        self.scope = scope
        self.source_list = source_list
        self._build(playlists or [])

    def _build(self, playlists):
        lang = self.settings.value("language", "en")

        add_menu = QMenu(tr("Add to playlist", lang), self)
        add_menu.setIcon(self.icons.icon("add-to-playlist.svg"))
        self.addMenu(add_menu)
        if not playlists:
            empty = QAction(tr("(no playlists)", lang), add_menu)
            empty.setEnabled(False)
            add_menu.addAction(empty)
        else:
            for playlist in playlists:
                action = QAction(playlist["name"], add_menu)
                action.triggered.connect(
                    lambda checked=False, pid=playlist["id"],
                    tid=self.track_id:
                    self.add_to_playlist_requested.emit(pid, tid)
                )
                add_menu.addAction(action)

        queue_action = QAction(tr("Add to queue", lang), self)
        queue_action.setIcon(self.icons.icon("queue.svg"))
        queue_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.add_to_queue_requested.emit(tid)
        )
        self.addAction(queue_action)

        favorite_action = QAction(tr("Set as Favorite", lang), self)
        favorite_action.setIcon(self.icons.icon("favorite.svg"))
        favorite_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.favorite_requested.emit(tid)
        )
        self.addAction(favorite_action)

        fix_action = QAction(tr("Change title && author", lang), self)
        fix_action.setIcon(self.icons.icon("pencil.svg"))
        fix_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.edit_metadata_requested.emit(tid)
        )
        self.addAction(fix_action)

        if self.scope == "library":
            # QAction не умеет красить текст (HTML не рендерится), поэтому
            # пункт делаем узнаваемым красной иконкой мусорки.
            remove_action = QAction(tr("Remove from library", lang), self)
            remove_action.setIcon(
                self.icons.icon("trash.svg", color="#e05a4a")
            )
        else:
            remove_action = QAction(
                tr("Remove from this playlist", lang), self
            )
            remove_action.setIcon(self.icons.icon("trash.svg"))
        remove_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.remove_requested.emit(tid, self.scope)
        )
        self.addAction(remove_action)

    def exec_at(self, pos):
        """Показывает меню в глобальной позиции, рассчитанной по source_list."""
        if self.source_list is not None:
            pos = self.source_list.mapToGlobal(pos)
        return self.exec_(pos)
