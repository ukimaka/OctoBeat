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

"""Вкладка библиотеки: тулбар, поиск, сортировка, дерево и Next in queue."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

import db
import metadata
from delegates import TrackDelegate
from dialogs import CustomConfirmDialog, CustomInputDialog
from library_tree import LibraryTreeWidget
from next_track_island import NextTrackIsland
from translations import tr


class LibraryTab(QWidget):
    """Изолированная вкладка библиотеки.

    Наружу сообщает только о намерениях пользователя сигналами; загрузку
    данных, поиск, сортировку и сохранение состояния дерева делает сама.
    """

    play_requested = pyqtSignal(object)  # QTreeWidgetItem с треком
    random_play_requested = pyqtSignal()
    import_requested = pyqtSignal()
    csv_import_requested = pyqtSignal()
    rescan_requested = pyqtSignal()
    youtube_requested = pyqtSignal()
    library_changed = pyqtSignal()
    # Контекстное меню обрабатывает MainWindow (там же меню плейлистов).
    context_menu_requested = pyqtSignal(object)  # QPoint

    def __init__(self, settings, icons, event_filter=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icons = icons

        # Свёрнутые папки: по умолчанию все раскрыты, храним только свёрнутые.
        self._saved_collapsed_folders = self._load_saved_collapsed_folders()
        self._folders_initialized = False
        self.sort_ascending = False
        self._next_track_id = None

        lang = self.settings.value("language", "en")

        self.tracks_list = LibraryTreeWidget()
        self.tracks_list.setHeaderHidden(True)
        self.tracks_list.setColumnCount(1)
        self.track_delegate = TrackDelegate(self.tracks_list)
        self.tracks_list.setItemDelegate(self.track_delegate)
        # Полностью отключаем системное выделение: никаких рамок/фонов при клике.
        # Двойной клик и контекстное меню работают по координатам мыши.
        self.tracks_list.setSelectionMode(QAbstractItemView.NoSelection)
        # Программное выделение (нужно для Drag & Drop) заставляет оформление
        # рисовать синюю рамку фокуса вокруг элемента. Фокус дереву не нужен:
        # навигация стрелками не критична, а перетаскивание работает и без него.
        self.tracks_list.setFocusPolicy(Qt.NoFocus)
        # Отслеживание мыши — иначе делегат не получает State_MouseOver (ховер).
        self.tracks_list.setMouseTracking(True)
        self.tracks_list.viewport().setMouseTracking(True)
        self.tracks_list.setAttribute(Qt.WA_Hover, True)
        self.tracks_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Разворот папок обрабатываем сами (двойной клик по папке)
        self.tracks_list.setExpandsOnDoubleClick(False)
        # Высота строк разная: треки выше, папки ниже
        self.tracks_list.setUniformRowHeights(False)
        # Drag & Drop: перетаскивание треков в папки (сохранение в БД — след. шаг)
        self.tracks_list.setDragEnabled(True)
        self.tracks_list.setAcceptDrops(True)
        self.tracks_list.setDropIndicatorShown(True)
        self.tracks_list.setDragDropMode(QAbstractItemView.InternalMove)

        # Нота (add-music) по своей природе узкая (её глиф занимает ~78% ширины
        # viewBox), поэтому даём ей чуть больший размер, чтобы не проигрывать по
        # визуальной массе остальным иконкам тулбара. Кубик (random) выровнен
        # обрезкой viewBox до границ глифа.
        self.import_button = self._icon_button(
            "add-music.svg", tr("Import files", lang), size=24,
            event_filter=event_filter,
        )
        self.new_folder_button = self._icon_button(
            "add-folder.svg", tr("New folder", lang),
            event_filter=event_filter,
        )
        self.youtube_button = self._icon_button(
            "download.svg", tr("Download music", lang),
            event_filter=event_filter,
        )
        self.rescan_button = self._icon_button(
            "update-track-info.svg", tr("Update track info", lang),
            event_filter=event_filter,
        )
        self.random_play_button = self._icon_button(
            "random.svg", tr("Play Random", lang),
            event_filter=event_filter,
        )
        self.tracks_count_label = QLabel(
            f"{tr('Library', lang)} (0 {tr('tracks', lang)})"
        )
        self.next_island = NextTrackIsland(self.settings, self.icons)

        top = QHBoxLayout()
        top.addWidget(self.import_button)
        top.addWidget(self.new_folder_button)
        top.addWidget(self.youtube_button)
        top.addWidget(self.rescan_button)
        top.addWidget(self.random_play_button)
        top.addStretch()
        top.addWidget(self.next_island, 0, Qt.AlignVCenter)
        top.addSpacing(12)
        top.addWidget(self.tracks_count_label)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            tr("Search by title or artist...", lang)
        )
        self.search_icon_action = self.search_edit.addAction(
            self.icons.icon("search.svg"), QLineEdit.LeadingPosition
        )

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            tr("Date added", lang),
            tr("Title", lang),
            tr("Artist", lang),
            tr("Duration", lang),
        ])

        self.filter_icon_label = QLabel()
        self.filter_icon_label.setPixmap(self.icons.pixmap("filter.svg", 20))
        self.filter_icon_label.setStyleSheet(
            "background: transparent; border: none; padding: 0; margin: 0;"
        )

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.filter_icon_label)
        filter_row.addWidget(self.sort_combo)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(filter_row)
        layout.addWidget(self.tracks_list)

        # Сигналы наружу
        self.import_button.clicked.connect(
            lambda: self.import_requested.emit()
        )
        self.new_folder_button.clicked.connect(self._on_create_folder)
        self.youtube_button.clicked.connect(
            lambda: self.youtube_requested.emit()
        )
        self.rescan_button.clicked.connect(
            lambda: self.rescan_requested.emit()
        )
        self.random_play_button.clicked.connect(
            lambda: self.random_play_requested.emit()
        )

        # Внутренние связи библиотеки
        self.search_edit.textChanged.connect(self.reload)
        self.sort_combo.currentIndexChanged.connect(self.reload)
        self.sort_combo.activated.connect(self._on_sort_toggled)
        self.tracks_list.itemDoubleClicked.connect(
            self._on_item_double_clicked
        )
        self.tracks_list.play_requested.connect(self._on_play_requested)
        self.tracks_list.library_changed.connect(
            self._on_tree_library_changed
        )
        self.tracks_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tracks_list.customContextMenuRequested.connect(
            self.context_menu_requested.emit
        )

    # ------------------------------------------------------------------
    #  Данные дерева
    # ------------------------------------------------------------------
    def reload(self):
        """Перечитывает БД, применяет поиск/сортировку и перестраивает дерево."""
        folders = db.get_all_folders()
        rows = db.get_all_tracks()

        text = self.search_edit.text().strip().lower()
        if text:
            def matches(row):
                title = (row["title"] or "").lower()
                artist = (row["artist"] or "").lower()
                if title or artist:
                    return text in title or text in artist
                return text in (row["file_path"] or "").lower()

            rows = [row for row in rows if matches(row)]

        idx = self.sort_combo.currentIndex()
        if idx == 0:
            rows = sorted(
                rows, key=lambda r: r["id"],
                reverse=not self.sort_ascending,
            )
        elif idx == 1:
            rows = sorted(
                rows, key=lambda r: (r["title"] or "").lower(),
                reverse=not self.sort_ascending,
            )
        elif idx == 2:
            rows = sorted(
                rows, key=lambda r: (r["artist"] or "").lower(),
                reverse=not self.sort_ascending,
            )
        elif idx == 3:
            rows = sorted(
                rows, key=lambda r: r["duration"] or 0,
                reverse=not self.sort_ascending,
            )

        # Раскладываем треки: сгруппировать по папкам, остальные — в корень
        by_folder = {}
        root_rows = []
        for row in rows:
            fid = row["folder_id"]
            if fid is None:
                root_rows.append(row)
            else:
                by_folder.setdefault(fid, []).append(row)

        # Свёрнутые папки: при первом построении — из QSettings, дальше — из
        # текущего состояния дерева, чтобы пере-фильтровка не сбрасывала раскрытие.
        first_build = not self._folders_initialized
        collapsed = (
            self._saved_collapsed_folders if first_build
            else self.collapsed_folder_ids()
        )

        self.tracks_list.setUpdatesEnabled(False)
        self.tracks_list.clear()
        track_index = 0
        for folder in folders:
            folder_item = self._make_folder_item(folder)
            for row in by_folder.get(folder["id"], []):
                track_index += 1
                folder_item.addChild(self._make_track_item(row, track_index))
            self.tracks_list.addTopLevelItem(folder_item)
            folder_item.setExpanded(folder["id"] not in collapsed)
        for row in root_rows:
            track_index += 1
            self.tracks_list.addTopLevelItem(
                self._make_track_item(row, track_index)
            )
        self.tracks_list.setUpdatesEnabled(True)

        self._folders_initialized = True
        self.update_track_count()

    def _make_track_item(self, row, index=None):
        item = QTreeWidgetItem()
        item.setData(0, Qt.UserRole, {
            "id": row["id"],
            "path": row["file_path"],
            "title": row["title"] or "Unknown Title",
            "artist": row["artist"] or "Unknown Artist",
            "duration": row["duration"],
            "cover_path": metadata.extract_cover(row["file_path"], row["id"]),
            "index": index,
        })
        # Треки можно таскать, но нельзя принимать drop (не станут контейнером)
        item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        )
        return item

    def _make_folder_item(self, folder):
        item = QTreeWidgetItem()
        item.setData(0, Qt.UserRole, {
            "is_folder": True,
            "id": folder["id"],
            "name": folder["name"],
        })
        # Папка принимает drop, но сама не таскается
        item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled
        )
        return item

    @staticmethod
    def _user_data(item):
        """Достаёт Qt.UserRole у QTreeWidgetItem."""
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    @staticmethod
    def _item_id(item):
        data = LibraryTab._user_data(item)
        if isinstance(data, dict):
            return data.get("id")
        return data

    @staticmethod
    def _path_of(item):
        data = LibraryTab._user_data(item)
        if isinstance(data, dict):
            return data.get("path")
        return item.data(0, Qt.UserRole + 1)

    def library_ids(self):
        """id всех треков в визуальном порядке (папки пропускаем)."""
        ids = []
        iterator = QTreeWidgetItemIterator(self.tracks_list)
        while iterator.value():
            data = self._user_data(iterator.value()) or {}
            if not data.get("is_folder") and data.get("id") is not None:
                ids.append(data["id"])
            iterator += 1
        return ids

    def find_track_item(self, track_id):
        iterator = QTreeWidgetItemIterator(self.tracks_list)
        while iterator.value():
            item = iterator.value()
            data = self._user_data(item) or {}
            if not data.get("is_folder") and data.get("id") == track_id:
                return item
            iterator += 1
        return None

    def current_item(self):
        return self.tracks_list.currentItem()

    def select_track(self, track_id):
        item = self.find_track_item(track_id)
        if item is not None:
            self.tracks_list.setCurrentItem(item)
        return item

    def collapsed_folder_ids(self):
        """id свёрнутых папок в текущем дереве."""
        ids = set()
        for i in range(self.tracks_list.topLevelItemCount()):
            item = self.tracks_list.topLevelItem(i)
            if item is None:
                continue
            data = self._user_data(item) or {}
            if data.get("is_folder") and not item.isExpanded():
                ids.add(data.get("id"))
        return ids

    def _load_saved_collapsed_folders(self):
        """Свёрнутые папки из QSettings (0/1 значение нормализуем в set[int])."""
        value = self.settings.value("collapsed_folders", [])
        if value is None:
            return set()
        if not isinstance(value, (list, tuple)):
            value = [value]
        result = set()
        for entry in value:
            try:
                result.add(int(entry))
            except (TypeError, ValueError):
                continue
        return result

    def save_state(self):
        """Сохраняет свёрнутые папки для следующего запуска."""
        self.settings.setValue(
            "collapsed_folders", sorted(self.collapsed_folder_ids())
        )

    def update_track_count(self):
        count = len(self.library_ids())
        lang = self.settings.value("language", "en")
        self.tracks_count_label.setText(
            f"{tr('Library', lang)} ({count} {tr('tracks', lang)})"
        )

    # ------------------------------------------------------------------
    #  Взаимодействие
    # ------------------------------------------------------------------
    def _on_item_double_clicked(self, item, column=0):
        data = self._user_data(item) or {}
        if data.get("is_folder"):
            item.setExpanded(not item.isExpanded())
            return
        self.play_requested.emit(item)

    def _on_play_requested(self, item):
        data = self._user_data(item) or {}
        if data.get("is_folder"):
            return
        self.play_requested.emit(item)

    def _on_tree_library_changed(self):
        self.update_track_count()
        self.library_changed.emit()

    def _on_create_folder(self):
        lang = self.settings.value("language", "en")
        parent = self.window()
        name, ok = CustomInputDialog.get_text(
            parent, tr("New folder", lang), tr("Folder name:", lang)
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        if db.create_folder(name) is None:
            CustomConfirmDialog.information(
                parent, tr("New folder", lang),
                tr("A folder with this name already exists.", lang),
            )
            return
        self.reload()
        self.library_changed.emit()

    def _on_sort_toggled(self, index):
        self.sort_ascending = not self.sort_ascending
        arrow = "↑" if self.sort_ascending else "↓"

        # 1. Очищаем ВСЕ пункты от старых стрелок
        for i in range(self.sort_combo.count()):
            text = self.sort_combo.itemText(i).strip(" ↑↓")
            self.sort_combo.setItemText(i, text)

        # 2. Добавляем стрелку к выбранному
        current_text = self.sort_combo.itemText(index).strip(" ↑↓")
        self.sort_combo.setItemText(index, f"{current_text} {arrow}")

    def focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    # ------------------------------------------------------------------
    #  Тема и «Next in queue»
    # ------------------------------------------------------------------
    def apply_theme(self):
        """Перекрашивает иконки тулбара и обновляет островок Next in queue."""
        self.import_button.setIcon(self.icons.icon("add-music.svg"))
        self.new_folder_button.setIcon(self.icons.icon("add-folder.svg"))
        self.youtube_button.setIcon(self.icons.icon("download.svg"))
        self.rescan_button.setIcon(
            self.icons.icon("update-track-info.svg")
        )
        self.random_play_button.setIcon(self.icons.icon("random.svg"))
        if self.search_icon_action is not None:
            self.search_icon_action.setIcon(self.icons.icon("search.svg"))
        self.filter_icon_label.setPixmap(self.icons.pixmap("filter.svg", 20))
        self.next_island.apply_theme()
        self._refresh_next_track()

    def set_current_track(self, track_id):
        """Обновляет маркер играющего трека и раскрывает его папку."""
        delegate = self.tracks_list.itemDelegate()
        if hasattr(delegate, "set_current_playing"):
            delegate.set_current_playing(track_id)
        self.tracks_list.clearSelection()       # Сбрасываем системное выделение
        self.tracks_list.viewport().update()    # Заставляем перерисовать всё

        item = self.find_track_item(track_id)
        if item is not None:
            parent = item.parent()
            if parent is not None:
                parent.setExpanded(True)

    def set_next_track(self, track_id, title=""):
        """Показывает следующий трек; id = -1 (пустая очередь) скрывает островок."""
        if track_id is None or track_id < 0:
            self._next_track_id = None
            self.next_island.clear()
            return
        self._next_track_id = track_id
        self._refresh_next_track(title)

    def _refresh_next_track(self, title=""):
        """Перечитывает данные следующего трека (также при смене темы)."""
        track_id = self._next_track_id
        if track_id is None:
            self.next_island.clear()
            return

        row = db.get_track_by_id(track_id)
        if row is None:
            self.next_island.clear()
            return

        lang = self.settings.value("language", "en")
        track_title = row["title"] or title or "—"
        artist = row["artist"] or tr("(unknown)", lang)
        cover_path = metadata.extract_cover(row["file_path"], track_id)
        self.next_island.set_track(track_title, artist, cover_path)

    def _icon_button(self, icon_name, tooltip, size=22, event_filter=None):
        """Плоская кнопка-иконка (фон и hover задаются темой)."""
        return self.icons.icon_button(
            icon_name, tooltip, size=size, event_filter=event_filter
        )
