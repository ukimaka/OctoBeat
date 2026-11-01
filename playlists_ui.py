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

"""Вкладка «Плейлисты»: сетка обложек + страница внутри плейлиста."""

import random
import shutil
from pathlib import Path

from PyQt5.QtCore import QRectF, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import db
import metadata
from delegates import TrackDelegate
from dialogs import (
    BulkAddDialog,
    CustomConfirmDialog,
    CustomInputDialog,
    PlaylistCoverDelegate,
    colored_icon,
    colored_pixmap,
)
from musicbrainz_client import get_cached_source_for_path
from pixmap_utils import draw_centered, draw_cover, pixmap_size
from translations import tr
from ui_common import get_open_file_name

from playlist_widgets import (
    _PlaylistGridView,
    PlaylistTracksWidget,
    _CoverWidget,
    _DetailPage,
    _DescriptionEdit,
    _average_color,
    _theme_is_dark,
    _icon_color,
    _lang,
    _blend,
)

PLAYLIST_COVERS_DIR = Path.home() / ".local" / "share" / "music_player" / "playlist_covers"


class PlaylistsPage(QWidget):
    """Две страницы: сетка плейлистов и внутренняя страница плейлиста."""

    play_playlist = pyqtSignal(int)             # playlist_id
    play_track = pyqtSignal(int, int, list)     # playlist_id, track_id, ordered ids
    playlist_deleted = pyqtSignal(int)          # playlist_id
    settings_requested = pyqtSignal()           # открыть настройки приложения
    delete_track_requested = pyqtSignal(int)     # delete track from DB

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_playlist_id = None
        self.current_playlist_name = ""
        self._current_track_id = None
        # Направление сортировки для страницы плейлиста. При первом клике
        # по новому полю берём его "естественное" направление, повторный
        # клик по тому же полю переключает asc/desc.
        self._sort_index = 0
        self._sort_ascending = False

        self.stack = QStackedWidget(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.stack)

        self.stack.addWidget(self._build_grid_page())
        self.stack.addWidget(self._build_detail_page())

        self.reload()

    # ------------------------------------------------------------------
    #  Страница 1: сетка плейлистов
    # ------------------------------------------------------------------
    def _build_grid_page(self):
        page = QWidget()

        lang = _lang()

        self.create_button = QPushButton()
        self.create_button.setIcon(colored_icon("create-playlist.svg"))
        self.create_button.setIconSize(QSize(22, 22))
        self.create_button.setFlat(True)
        self.create_button.setToolTip(tr("Create playlist", lang))
        self.create_button.clicked.connect(self._on_create_playlist)

        self.random_button = self._icon_button(
            "random.svg", tr("Random Playlist", lang)
        )
        self.random_button.clicked.connect(self._on_random_playlist)

        # Шестерёнки здесь больше нет: настройки открываются основной
        # вкладкой Settings в главном окне.
        self.grid_count_label = QLabel(
            tr("Your playlists ({n})", lang).format(n=0)
        )

        top = QHBoxLayout()
        top.addWidget(self.create_button)
        top.addStretch()
        top.addWidget(self.random_button)
        top.addSpacing(8)
        top.addWidget(self.grid_count_label)

        self.grid_model = QStandardItemModel(self)
        self.grid_view = _PlaylistGridView()
        self.grid_view.setModel(self.grid_model)
        self.grid_view.setViewMode(QListView.IconMode)
        self.grid_view.setResizeMode(QListView.Adjust)
        self.grid_view.setMovement(QListView.Free)
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setSpacing(8)
        self.grid_view.setMouseTracking(True)
        self.grid_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid_view.setItemDelegate(PlaylistCoverDelegate(self.grid_view))

        self.grid_view.play_clicked.connect(self._on_play_playlist)
        self.grid_view.item_clicked.connect(self._on_grid_item_clicked)
        self.grid_view.context_menu_requested.connect(
            self._on_grid_context_menu
        )
        self.grid_view.positions_changed.connect(self.reload)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(top)
        layout.addWidget(self.grid_view)
        return page

    def _build_detail_page(self):
        lang = _lang()
        page = _DetailPage()
        page.setObjectName("playlistDetail")
        self.detail_page = page

        # --- Левая часть шапки: кнопка «назад» + обложка ---
        self.back_button = QPushButton()
        self.back_button.setIcon(colored_icon("back.svg", _icon_color()))
        self.back_button.setIconSize(QSize(22, 22))
        self.back_button.setFlat(True)
        self.back_button.setToolTip(tr("Back to playlists", lang))
        self.back_button.clicked.connect(self._go_back)

        self.cover_widget = _CoverWidget()
        self.cover_widget.setFixedSize(140, 140)
        self.cover_widget.clicked.connect(self._on_cover_clicked)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.back_button, 0, Qt.AlignLeft)
        left.addWidget(self.cover_widget, 0, Qt.AlignLeft)
        left.addStretch()

        # --- Правая часть шапки: название, «+», описание ---
        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-size: 32px; font-weight: bold;")

        self.add_tracks_button = QPushButton("+")
        self.add_tracks_button.setMinimumSize(28, 28)
        self.add_tracks_button.setMaximumSize(36, 36)
        self.add_tracks_button.setCursor(Qt.PointingHandCursor)
        self.add_tracks_button.setToolTip(tr("Add Tracks", lang))
        self.add_tracks_button.setStyleSheet(
            "QPushButton {"
            " font-size: 22px; font-weight: 600; border: none;"
            " border-radius: 16px; background: transparent; padding: 0;"
            "}"
            "QPushButton:hover { background: palette(highlight); }"
        )
        self.add_tracks_button.clicked.connect(self._on_bulk_add)

        self.description_edit = _DescriptionEdit()
        self.description_edit.setObjectName("playlistDescription")
        self.description_edit.setPlaceholderText(
            tr("Add a description...", lang)
        )
        self.description_edit.setMinimumHeight(60)
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self.description_edit.setFrameStyle(0)
        self.description_edit.editing_finished.connect(self._on_description_changed)

        self.delete_button = self._icon_button(
            "trash.svg", tr("Delete", lang)
        )
        self.delete_button.clicked.connect(self._on_delete_playlist)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(10)
        name_row.addWidget(self.name_label)
        name_row.addWidget(self.add_tracks_button, 0, Qt.AlignVCenter)
        name_row.addStretch(1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addLayout(name_row)
        right.addWidget(self.description_edit)
        right.addStretch(1)

        top = QHBoxLayout()
        top.addLayout(left, 0)
        top.addSpacing(16)
        top.addLayout(right, 1)
        top.addWidget(self.delete_button, 0, Qt.AlignTop)

        # --- Строка поиска и сортировки ---
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            tr("Search in playlist...", lang)
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_icon_action = self.search_edit.addAction(
            colored_icon("search.svg", _icon_color()), QLineEdit.LeadingPosition
        )
        self.search_edit.textChanged.connect(self._on_search_changed)

        self.filter_icon_label = QLabel()
        self.filter_icon_label.setPixmap(
            colored_pixmap("filter.svg", 20, _icon_color())
        )
        self.filter_icon_label.setStyleSheet(
            "background: transparent; border: none; padding: 0; margin: 0;"
        )

        self.sort_combo = QComboBox()
        self.sort_combo.addItem(tr("By order (drag)", lang), 0)
        self.sort_combo.addItem(tr("By title", lang), 1)
        self.sort_combo.addItem(tr("By artist", lang), 2)
        self.sort_combo.addItem(tr("By duration", lang), 3)
        self.sort_combo.addItem(tr("By date added", lang), 4)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self.sort_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sort_combo.setMinimumWidth(150)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.filter_icon_label)
        filter_row.addWidget(self.sort_combo)

        self.tracks_count_label = QLabel(
            tr("Tracks in playlist ({n})", lang).format(n=0)
        )

        # --- Список треков ---
        self.tracks_list = PlaylistTracksWidget()
        self.track_delegate = TrackDelegate(self.tracks_list, controller=self)
        self.track_delegate.delete_requested.connect(
            self.delete_track_requested.emit
        )
        settings = QSettings("MusicPlayer", "MusicPlayer")
        self.track_delegate.set_show_metadata_badges(
            bool(settings.value("show_metadata_source_badges", False, type=bool))
        )
        self.tracks_list.setItemDelegate(self.track_delegate)
        self.tracks_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tracks_list.setMouseTracking(True)
        self.tracks_list.viewport().setMouseTracking(True)
        self.tracks_list.setAttribute(Qt.WA_Hover, True)
        self.tracks_list.itemDoubleClicked.connect(self._on_track_double_click)
        self.tracks_list.play_requested.connect(self._on_track_play)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(top)
        layout.addLayout(filter_row)
        layout.addWidget(self.tracks_count_label)
        layout.addWidget(self.tracks_list, 1)
        return page

    def reload(self):
        self._refresh_grid()

    def _refresh_grid(self):
        self.grid_model.clear()
        for row in db.get_all_playlists():
            cover_path = row["cover_path"]
            if not cover_path:
                first_track = db.get_first_track_in_playlist(row["id"])
                if first_track is not None:
                    cover_path = metadata.extract_cover(
                        first_track["file_path"], first_track["id"]
                    )
            item = QStandardItem()
            item.setEditable(False)
            item.setFlags(
                Qt.ItemIsSelectable | Qt.ItemIsEnabled
                | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
            )
            item.setData({
                "id": row["id"],
                "name": row["name"],
                "cover_path": cover_path,
                "is_pinned": row["is_pinned"],
            }, Qt.UserRole)
            self.grid_model.appendRow(item)
        self.grid_count_label.setText(
            tr("Your playlists ({n})", _lang()).format(
                n=self.grid_model.rowCount()
            )
        )

    def _go_back(self):
        self.stack.setCurrentIndex(0)
        self.current_playlist_id = None
        self.current_playlist_name = ""
        self._refresh_grid()

    def refresh_tracks(self):
        self._refresh_tracks()
        self.track_delegate.set_current_playing(self._current_track_id)

    def set_current_track(self, track_id):
        """Помечает играющий трек в списке (маркер + фон в делегате)."""
        self._current_track_id = track_id
        self.track_delegate.set_current_playing(track_id)
        self.tracks_list.viewport().update()

    def set_current_playing(self, track_id):
        """Обратная совместимость: тот же смысл, что и set_current_track."""
        self.set_current_track(track_id)

    def _on_create_playlist(self):
        dialog = CustomInputDialog(
            tr("Create Playlist", _lang()),
            tr("Enter playlist name:", _lang()),
            self,
        )
        if dialog.exec_() and dialog.text().strip():
            name = dialog.text().strip()
            playlist_id = db.create_playlist(name)
            if playlist_id:
                self.reload()
                self.open_playlist(playlist_id)

    def _on_random_playlist(self):
        playlist_id = db.get_random_playlist()
        if playlist_id:
            self.open_playlist(playlist_id)

    def _on_grid_item_clicked(self, index):
        data = index.data(Qt.UserRole) or {}
        pid = data.get("id")
        if pid is None:
            return
        self.open_playlist(pid)

    def open_playlist(self, playlist_id):
        """Открывает страницу плейлиста по id (в т.ч. клик из профиля)."""
        row = db.get_playlist_by_id(playlist_id)
        if row is None:
            return
        self.current_playlist_id = playlist_id
        self.current_playlist_name = row["name"] or ""
        self.name_label.setText(self.current_playlist_name)

        cover_path = row["cover_path"]
        if not cover_path:
            first_track = db.get_first_track_in_playlist(playlist_id)
            if first_track is not None:
                cover_path = metadata.extract_cover(
                    first_track["file_path"], first_track["id"]
                )
        self.cover_widget.set_cover(cover_path)
        self.detail_page.set_cover_color(
            _average_color(QPixmap(cover_path)) if cover_path else None
        )

        self.description_edit.blockSignals(True)
        self.description_edit.setPlainText((row["description"] if row else "") or "")
        self.description_edit.blockSignals(False)

        self.search_edit.clear()
        self._refresh_tracks()
        self.stack.setCurrentIndex(1)

    def _on_description_changed(self, text):
        if self.current_playlist_id is None:
            return
        db.update_playlist_description(self.current_playlist_id, text)

    def _on_play_playlist(self, index):
        data = index.data(Qt.UserRole) or {}
        pid = data.get("id")
        if pid is not None:
            self.play_playlist.emit(pid)

    def _on_grid_context_menu(self, global_pos, index):
        data = index.data(Qt.UserRole) or {}
        pid = data.get("id")
        if pid is None:
            return
        menu = QMenu(self)
        play_act = menu.addAction(tr("Play", _lang()))
        edit_act = menu.addAction(tr("Rename", _lang()))
        del_act = menu.addAction(tr("Delete", _lang()))
        act = menu.exec_(global_pos)
        if act == play_act:
            self.play_playlist.emit(pid)
        elif act == edit_act:
            self._rename_playlist(pid)
        elif act == del_act:
            self._delete_playlist(pid)

    def _rename_playlist(self, playlist_id):
        row = db.get_playlist_by_id(playlist_id)
        if row is None:
            return
        dialog = CustomInputDialog(
            tr("Rename Playlist", _lang()),
            tr("New name:", _lang()),
            self,
            row["name"],
        )
        if dialog.exec_() and dialog.text().strip():
            db.rename_playlist(playlist_id, dialog.text().strip())
            self.reload()

    def _delete_playlist(self, playlist_id):
        dialog = CustomConfirmDialog(
            tr("Delete Playlist", _lang()),
            tr("Delete this playlist?", _lang()),
            self,
        )
        if dialog.exec_():
            db.delete_playlist(playlist_id)
            self.playlist_deleted.emit(playlist_id)
            if self.current_playlist_id == playlist_id:
                self._on_back()
            self.reload()

    def _on_back(self):
        self.current_playlist_id = None
        self.stack.setCurrentIndex(0)

    def _on_cover_clicked(self):
        path, _ = get_open_file_name(
            self,
            tr("Choose Cover Image", _lang()),
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        import db
        ext = Path(path).suffix
        PLAYLIST_COVERS_DIR.mkdir(parents=True, exist_ok=True)
        dest = PLAYLIST_COVERS_DIR / f"{self.current_playlist_id}{ext}"
        for old in PLAYLIST_COVERS_DIR.glob(f"{self.current_playlist_id}.*"):
            if old != dest:
                old.unlink()
        shutil.copy2(path, dest)
        db.update_playlist_cover(self.current_playlist_id, str(dest))
        self.cover_widget.set_cover(str(dest))
        self.detail_page.set_cover_color(
            _average_color(QPixmap(str(dest))) if dest else None
        )
        self._refresh_grid()

    def _on_bulk_add(self):
        pid = self.current_playlist_id
        if pid is None:
            return

        dialog = BulkAddDialog(self)
        if not dialog.exec_():
            return

        selected = dialog.selected_track_ids()
        if not selected:
            return

        existing = {row["id"] for row in db.get_tracks_in_playlist(pid)}
        added = 0
        for track_id in selected:
            if track_id in existing:
                continue
            if db.add_track_to_playlist(pid, track_id):
                existing.add(track_id)
                added += 1

        if added:
            self._refresh_tracks()
            self._refresh_grid()
        else:
            CustomConfirmDialog.information(
                self,
                tr("Nothing added", _lang()),
                tr("All tracks are already in the playlist.", _lang()),
            )

    def _on_delete_playlist(self):
        pid = self.current_playlist_id
        if pid is None:
            return
        lang = _lang()
        if not CustomConfirmDialog.question(
            self,
            tr("Delete playlist", lang),
            tr("Delete playlist '{name}'?", lang).format(
                name=self.current_playlist_name
            ),
        ):
            return
        db.delete_playlist(pid)
        self._go_back()
        self.playlist_deleted.emit(pid)

    def _refresh_tracks(self):
        self.tracks_list.clear()
        if self.current_playlist_id is None:
            return
        lang = _lang()
        search = self.search_edit.text().strip().lower()

        rows = db.get_tracks_in_playlist(self.current_playlist_id)

        if search:
            rows = [
                r for r in rows
                if search in (r["title"] or "").lower()
                or search in (r["artist"] or "").lower()
            ]

        if self._sort_index:
            reverse = not self._sort_ascending
            if self._sort_index == 1:  # title
                rows.sort(key=lambda r: (r["title"] or "").lower(), reverse=reverse)
            elif self._sort_index == 2:  # artist
                rows.sort(key=lambda r: (r["artist"] or "").lower(), reverse=reverse)
            elif self._sort_index == 3:  # duration
                rows.sort(key=lambda r: r["duration"] or 0, reverse=reverse)
            elif self._sort_index == 4:  # date added
                rows.sort(key=lambda r: r["added_at"] or "", reverse=reverse)

        for index, row in enumerate(rows, start=1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, {
                "id": row["id"],
                "path": row["file_path"],
                "title": row["title"] or "Unknown Title",
                "artist": row["artist"] or "Unknown Artist",
                "duration": row["duration"],
                "cover_path": metadata.extract_cover(
                    row["file_path"], row["id"]
                ),
                "metadata_source": get_cached_source_for_path(
                    row["file_path"]
                ),
                "index": index,
            })
            self.tracks_list.addItem(item)

        if not rows:
            self.tracks_list.addItem(
                QListWidgetItem(tr("Nothing added", lang))
            )
            self.tracks_list.item(0).setFlags(Qt.NoItemFlags)

        self._update_track_count(len(rows))

    def _update_track_count(self, count):
        self.tracks_count_label.setText(
            tr("Tracks in playlist ({n})", _lang()).format(n=count)
        )

    def _on_search_changed(self, _):
        self._refresh_tracks()

    def _on_sort_changed(self, idx):
        if idx == self._sort_index:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_index = idx
            self._sort_ascending = False
        self._refresh_tracks()

    def _on_filter_changed(self, _):
        self._refresh_tracks()

    def _on_track_play(self, item):
        row = item.data(Qt.UserRole)
        if not row:
            return
        track_id = row["id"]
        playlist_id = self.current_playlist_id
        all_ids = [
            self.tracks_list.item(i).data(Qt.UserRole)["id"]
            for i in range(self.tracks_list.count())
            if self.tracks_list.item(i).data(Qt.UserRole)
        ]
        self.play_track.emit(playlist_id, track_id, all_ids)

    def _on_track_double_click(self, item):
        self._on_track_play(item)

    def _icon_button(self, icon_name, tooltip):
        btn = QPushButton()
        btn.setIcon(colored_icon(icon_name, _icon_color()))
        btn.setIconSize(QSize(20, 20))
        btn.setFlat(True)
        btn.setToolTip(tooltip)
        return btn
