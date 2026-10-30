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

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QAction, QMenu

from translations import tr


class TrackContextMenu(QMenu):
    """Общее меню трека для библиотеки и плейлиста."""

    add_to_playlist_requested = pyqtSignal(int, int)  # playlist_id, track_id
    add_to_queue_requested = pyqtSignal(int)          # track_id
    favorite_requested = pyqtSignal(int)              # track_id
    edit_metadata_requested = pyqtSignal(int)         # track_id
    # CHANGED: запрос на смену обложки трека
    change_cover_requested = pyqtSignal(int)          # track_id
    # CHANGED: запрос на интерактивную обрезку аудио
    trim_audio_requested = pyqtSignal(int)            # track_id
    remove_requested = pyqtSignal(int, str)           # track_id, scope
    remove_selected_requested = pyqtSignal(str, object)  # scope, [track_id, ...]
    select_all_requested = pyqtSignal(str)              # scope: "library" | "playlist"

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
        self._selected_ids = self._collect_selected_ids()
        self._build(playlists or [])

    def _collect_selected_ids(self):
        """id всех выбранных треков в source_list (мультивыбор)."""
        ids = []
        if self.source_list is None:
            return ids
        for item in self.source_list.selectedItems():
            if hasattr(item, "data") and hasattr(item, "text"):
                try:
                    # QTreeWidgetItem требует (column, role), QListWidgetItem — только role.
                    data = item.data(0, Qt.UserRole)
                except TypeError:
                    # Fallback для QListWidgetItem
                    data = item.data(Qt.UserRole)
                if isinstance(data, dict):
                    track_id = data.get("id")
                    if track_id is not None and track_id not in ids:
                        ids.append(track_id)
        return ids

    def _valid_items_count(self):
        """CHANGED: число валидных элементов в source_list (треки/папки/строки)."""
        if self.source_list is None:
            return 0

        def has_track_data(item):
            try:
                data = item.data(0, Qt.UserRole)
            except TypeError:
                data = item.data(Qt.UserRole)
            return isinstance(data, dict) and data.get("id") is not None

        if hasattr(self.source_list, "topLevelItemCount"):
            total = 0
            for i in range(self.source_list.topLevelItemCount()):
                top = self.source_list.topLevelItem(i)
                if has_track_data(top):
                    total += 1
                total += sum(
                    1
                    for j in range(top.childCount())
                    if has_track_data(top.child(j))
                )
            return total

        if hasattr(self.source_list, "count"):
            return sum(
                1
                for i in range(self.source_list.count())
                if has_track_data(self.source_list.item(i))
            )

        model = self.source_list.model()
        return model.rowCount() if model is not None else 0

    def _toggle_select_all(self, checked=False):
        """CHANGED: прямой selectAll/clearSelection вместо сигнала."""
        if self.source_list is None:
            return
        total_items = self._valid_items_count()
        if total_items > 0 and len(self._selected_ids) >= total_items:
            self.source_list.clearSelection()
        else:
            self.source_list.selectAll()

    def _build(self, playlists):
        # CHANGED: setIconSize убран — выравнивание select-all правим в SVG.
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

        # CHANGED: объединяем редактирование трека в одно подменю "Edit Track"
        edit_menu = QMenu(tr("Edit Track", lang), self)
        edit_menu.setIcon(self.icons.icon("pencil.svg"))

        fix_action = QAction(tr("Change title && author", lang), edit_menu)
        fix_action.setIcon(self.icons.icon("pencil.svg"))
        fix_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.edit_metadata_requested.emit(tid)
        )
        edit_menu.addAction(fix_action)

        # CHANGED: пункт "Change cover" сразу после редактирования названия
        cover_action = QAction(tr("Change cover", lang), edit_menu)
        cover_action.setIcon(self.icons.icon("image.svg"))
        cover_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.change_cover_requested.emit(tid)
        )
        edit_menu.addAction(cover_action)

        # CHANGED: пункт "Trim audio" — интерактивный редактор обрезки
        trim_audio_action = QAction(tr("Trim audio", lang), edit_menu)
        trim_audio_action.setIcon(self.icons.icon("cut.svg"))
        trim_audio_action.triggered.connect(
            lambda checked=False, tid=self.track_id:
            self.trim_audio_requested.emit(tid)
        )
        edit_menu.addAction(trim_audio_action)

        # Подменю занимает место бывшего пункта "Change title & author".
        self.addMenu(edit_menu)

        # CHANGED: "Select all" / "Deselect all" перенесён выше корзины,
        # текст зависит от текущего выделения, клик управляет source_list.
        total_items = self._valid_items_count()
        all_selected = (
            total_items > 0 and len(self._selected_ids) >= total_items
        )
        select_all_text = (
            tr("Deselect all", lang) if all_selected else tr("Select all", lang)
        )
        select_all_action = QAction(select_all_text, self)
        select_all_action.setIcon(self.icons.icon("select-all.svg"))
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._toggle_select_all)
        self.addAction(select_all_action)

        if self.scope == "library":
            # QAction не умеет красить текст (HTML не рендерится), поэтому
            # пункт делаем узнаваемым красной иконкой мусорки.
            text = (
                tr("Remove selected tracks", lang)
                if len(self._selected_ids) > 1
                else tr("Remove from library", lang)
            )
            remove_action = QAction(text, self)
            remove_action.setIcon(self.icons.icon("trash.svg", color="#e05a4a"))
        else:
            text = (
                tr("Remove selected tracks", lang)
                if len(self._selected_ids) > 1
                else tr("Remove from this playlist", lang)
            )
            remove_action = QAction(text, self)
            remove_action.setIcon(self.icons.icon("trash.svg"))
        remove_action.triggered.connect(
            lambda checked=False: (
                self.remove_selected_requested.emit(
                    self.scope, list(self._selected_ids)
                )
                if len(self._selected_ids) > 1
                else self.remove_requested.emit(self.track_id, self.scope)
            )
        )
        self.addAction(remove_action)

    def exec_at(self, pos):
        """Показывает меню в глобальной позиции, рассчитанной по source_list."""
        if self.source_list is not None:
            pos = self.source_list.mapToGlobal(pos)
        return self.exec_(pos)
