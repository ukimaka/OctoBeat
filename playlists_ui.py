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
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
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

PLAYLIST_COVERS_DIR = Path.home() / ".local" / "share" / "music_player" / "playlist_covers"


def _theme_is_dark():
    """Текущая тема из QSettings (виджеты читают её при отрисовке)."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return settings.value("theme", "dark") != "light"


def _icon_color():
    """Цвет перекраски иконок под текущую тему."""
    return "#ffffff" if _theme_is_dark() else "#000000"


def _lang():
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return settings.value("language", "en")


def _blend(color_a, color_b, factor):
    """Смешивает два цвета: factor — доля color_b в результате."""
    factor = max(0.0, min(1.0, factor))
    return QColor(
        round(color_a.red() * (1 - factor) + color_b.red() * factor),
        round(color_a.green() * (1 - factor) + color_b.green() * factor),
        round(color_a.blue() * (1 - factor) + color_b.blue() * factor),
    )



class _PlaylistGridView(QListView):
    """QListView, различающий клик по кнопке Play и клик по плитке."""

    play_clicked = pyqtSignal(object)   # QModelIndex
    item_clicked = pyqtSignal(object)   # QModelIndex
    context_menu_requested = pyqtSignal(object, object)  # QPoint, QModelIndex
    positions_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                delegate = self.itemDelegate()
                rect = self.visualRect(index)
                if (isinstance(delegate, PlaylistCoverDelegate)
                        and delegate.play_rect(rect).contains(event.pos())):
                    self.play_clicked.emit(index)
                else:
                    self.item_clicked.emit(index)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            self.context_menu_requested.emit(event.globalPos(), index)
            event.accept()
            return
        super().contextMenuEvent(event)

    def dragMoveEvent(self, event):
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dropEvent(self, event):
        # Получаем индексы
        source_index = self.currentIndex()
        target_index = self.indexAt(event.pos())

        if not source_index.isValid():
            event.ignore()
            return

        # Если дропнули в пустоту (ниже всех плиток) — ставим в конец
        if target_index.isValid():
            target_row = target_index.row()
        else:
            target_row = self.model().rowCount() - 1

        source_row = source_index.row()

        if source_row == target_row:
            event.ignore()
            return

        # Вручную двигаем строку в QStandardItemModel
        item = self.model().takeRow(source_row)[0]
        self.model().insertRow(target_row, item)

        event.acceptProposedAction()

        # Сохраняем новый порядок в БД
        new_order_ids = []
        for row in range(self.model().rowCount()):
            data = self.model().index(row, 0).data(Qt.UserRole) or {}
            pid = data.get("id")
            if pid is not None:
                new_order_ids.append(pid)

        if new_order_ids:
            db.update_all_playlists_positions(new_order_ids)
            self.positions_changed.emit()


class PlaylistTracksWidget(QListWidget):
    """Список треков плейлиста с реакцией на клик по иконке Play слева."""

    play_requested = pyqtSignal(object)  # QListWidgetItem

    def mouseReleaseEvent(self, event):
        """Одиночный клик по иконке Play слева запускает трек."""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and TrackDelegate.is_play_click(
                event.pos(), self.visualItemRect(item)
            ):
                self.play_requested.emit(item)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        # CHANGED: view сам отслеживает наведение на иконку мусорки.
        super().mouseMoveEvent(event)
        index = self.indexAt(event.pos())
        delegate = self.itemDelegate()

        if index.isValid() and hasattr(delegate, "get_trash_rect_for_index"):
            trash_rect = delegate.get_trash_rect_for_index(self, index)

            old_index = delegate.hovered_trash_index
            old_rect = delegate.hovered_trash_rect

            if trash_rect and trash_rect.contains(event.pos()):
                delegate.hovered_trash_index = index
                delegate.hovered_trash_rect = trash_rect
            else:
                delegate.hovered_trash_index = None
                delegate.hovered_trash_rect = None

            if (
                old_index != delegate.hovered_trash_index
                or old_rect != delegate.hovered_trash_rect
            ):
                self.viewport().update()
        else:
            if (
                hasattr(delegate, "hovered_trash_index")
                and delegate.hovered_trash_index is not None
            ):
                delegate.hovered_trash_index = None
                delegate.hovered_trash_rect = None
                self.viewport().update()


class _CoverWidget(QWidget):
    """Большая обложка плейлиста с hover-оверлеем «Choose photo»."""

    clicked = pyqtSignal()

    COVER_SIZE = 140
    RADIUS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        # Обложка может немного сжиматься в узком окне, но не раздувается
        # больше своего обычного размера.
        self.setMinimumSize(110, 110)
        self.setMaximumSize(self.COVER_SIZE, self.COVER_SIZE)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self._cover_path = None
        self._hover = False
        self._note_cache = {}
        # Карандаш рисуется поверх тёмного hover-оверлея — всегда белый.
        self._pencil = colored_pixmap("pencil.svg", 20, "#ffffff")

    def sizeHint(self):
        return QSize(self.COVER_SIZE, self.COVER_SIZE)

    def set_cover(self, path):
        self._cover_path = path
        self.update()

    def _note_pixmap(self, color):
        """Нота-заглушка, перекрашенная и кэшированная по цвету."""
        note = self._note_cache.get(color)
        if note is None:
            note = colored_pixmap("music-note.svg", 56, color)
            self._note_cache[color] = note
        return note

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self.rect()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)

        pixmap = QPixmap(self._cover_path) if self._cover_path else QPixmap()
        if not draw_cover(painter, QRectF(rect), pixmap):
            dark = _theme_is_dark()
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if dark:
                gradient.setColorAt(0.0, QColor("#2e2e2e"))
                gradient.setColorAt(1.0, QColor("#1e1e1e"))
            else:
                gradient.setColorAt(0.0, QColor("#fbfbfb"))
                gradient.setColorAt(1.0, QColor("#e6e6e6"))
            painter.fillRect(rect, gradient)
            note = self._note_pixmap("#888888" if dark else "#000000")
            draw_centered(painter, QRectF(rect), note)

        if self._hover:
            painter.fillRect(rect, QColor(0, 0, 0, 140))

            font = QFont(painter.font())
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))

            text = tr("Choose photo", _lang())
            tw = QFontMetrics(font).horizontalAdvance(text)
            gap = 8
            pencil_size = pixmap_size(self._pencil)
            total = pencil_size.width() + gap + tw
            start_x = rect.x() + (rect.width() - total) // 2
            cy = rect.y() + rect.height() // 2

            painter.drawPixmap(
                start_x, cy - pencil_size.height() // 2, self._pencil
            )
            painter.drawText(
                start_x + pencil_size.width() + gap,
                cy - 10, tw, 20,
                Qt.AlignLeft | Qt.AlignVCenter, text,
            )

        painter.end()


def _average_color(pixmap):
    """Средний цвет обложки: масштабируем QPixmap до 1x1 и берём пиксель."""
    if pixmap is None or pixmap.isNull():
        # None → _DetailPage сам подставит фон текущей темы.
        return None
    tiny = pixmap.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return tiny.toImage().pixelColor(0, 0)


class _DetailPage(QWidget):
    """Контейнер страницы 2: вертикальный градиент от цвета обложки к фону."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        # None → верхний цвет градиента равен фону текущей темы.
        self._top_color = None

    def set_cover_color(self, color):
        if color is not None and color.isValid():
            self._top_color = color
        else:
            self._top_color = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        dark = _theme_is_dark()
        bottom = QColor("#121212") if dark else QColor("#ffffff")

        if self._top_color is not None:
            top = QColor(self._top_color)
            if not dark:
                # В светлой теме приглушаем цвет обложки, уводя его в белый.
                top = _blend(top, QColor("#ffffff"), 0.6)
        else:
            top = bottom

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, top)
        if dark:
            gradient.setColorAt(0.3, bottom)
        else:
            gradient.setColorAt(0.45, QColor("#fafafa"))
        gradient.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), gradient)


class _DescriptionEdit(QTextEdit):
    """QTextEdit, сохраняющий текст при потере фокуса."""

    editing_finished = pyqtSignal(str)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editing_finished.emit(self.toPlainText())


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
        self.grid_view.play_clicked.connect(self._on_grid_play_clicked)
        self.grid_view.item_clicked.connect(self._on_grid_item_clicked)
        self.grid_view.context_menu_requested.connect(self._on_grid_context_menu)
        self.grid_view.positions_changed.connect(self._refresh_grid)

        layout = QVBoxLayout(page)
        layout.addLayout(top)
        layout.addWidget(self.grid_view)
        return page

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

    def _on_grid_play_clicked(self, index):
        data = index.data(Qt.UserRole) or {}
        pid = data.get("id")
        if pid is not None:
            self.play_playlist.emit(pid)

    def _on_random_playlist(self):
        """Играет случайный непустой плейлист из БД."""
        candidates = [
            p for p in db.get_all_playlists()
            if db.get_tracks_in_playlist(p["id"])
        ]
        if not candidates:
            return
        chosen = random.choice(candidates)
        self.play_playlist.emit(chosen["id"])

    def _on_grid_context_menu(self, global_pos, index):
        data = index.data(Qt.UserRole) or {}
        pid = data.get("id")
        if pid is None:
            return
        name = data.get("name") or ""
        is_pinned = bool(data.get("is_pinned"))

        menu = QMenu(self)

        icon_color = _icon_color()

        lang = _lang()

        pin_action = QAction(
            tr("Unpin" if is_pinned else "Pin", lang), menu
        )
        pin_action.setIcon(colored_icon("pin.svg", icon_color))
        pin_action.triggered.connect(
            lambda checked=False, p=pid, v=not is_pinned:
                self._on_grid_toggle_pin(p, v)
        )
        menu.addAction(pin_action)

        queue_action = QAction(tr("Add to queue", lang), menu)
        queue_action.setIcon(colored_icon("queue.svg", icon_color))
        queue_action.triggered.connect(
            lambda checked=False, p=pid: self.play_playlist.emit(p)
        )
        menu.addAction(queue_action)

        copy_action = QAction(tr("Add to another playlist", lang), menu)
        copy_action.setIcon(colored_icon("add-to-playlist.svg", icon_color))
        copy_action.triggered.connect(
            lambda checked=False, p=pid: self._on_copy_to_playlist(p)
        )
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction(tr("Delete", lang), menu)
        delete_action.setIcon(colored_icon("trash.svg", "#e05a5a"))
        delete_action.setData("danger")
        delete_action.triggered.connect(
            lambda checked=False, p=pid, n=name:
                self._on_grid_delete_playlist(p, n)
        )
        menu.addAction(delete_action)

        menu.exec_(global_pos)

    def _on_copy_to_playlist(self, source_playlist_id):
        """Копирует все треки плейлиста в другой выбранный плейлист."""
        lang = _lang()
        targets = [
            p for p in db.get_all_playlists() if p["id"] != source_playlist_id
        ]
        if not targets:
            CustomConfirmDialog.information(
                self, tr("Nothing to choose", lang),
                tr("No other playlists.", lang),
            )
            return

        names = [p["name"] for p in targets]
        name, ok = QInputDialog.getItem(
            self, tr("Add to another playlist", lang),
            tr("Choose playlist:", lang), names, 0, False,
        )
        if not ok or not name:
            return

        target = targets[names.index(name)]
        existing = {row["id"] for row in db.get_tracks_in_playlist(target["id"])}
        added = 0
        for row in db.get_tracks_in_playlist(source_playlist_id):
            if row["id"] in existing:
                continue
            db.add_track_to_playlist(target["id"], row["id"])
            added += 1

        self._refresh_grid()
        if self.current_playlist_id == target["id"]:
            self.refresh_tracks()

        if added == 0:
            CustomConfirmDialog.information(
                self, tr("Nothing added", lang),
                tr("All tracks are already in the playlist.", lang),
            )
        else:
            CustomConfirmDialog.information(
                self, tr("Playlist updated", lang),
                tr("Tracks added: {n}", lang).format(n=added),
            )

    def _on_grid_toggle_pin(self, playlist_id, is_pinned):
        db.set_playlist_pinned(playlist_id, is_pinned)
        self._refresh_grid()

    def _on_grid_delete_playlist(self, playlist_id, name):
        lang = _lang()
        if not CustomConfirmDialog.question(
            self,
            tr("Delete playlist", lang),
            tr("Delete playlist '{name}'?", lang).format(name=name),
        ):
            return
        db.delete_playlist(playlist_id)
        if self.current_playlist_id == playlist_id:
            self.current_playlist_id = None
            self.current_playlist_name = ""
        self._refresh_grid()
        self.playlist_deleted.emit(playlist_id)

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

    def _on_create_playlist(self):
        lang = _lang()
        name, ok = CustomInputDialog.get_text(
            self,
            tr("New playlist", lang),
            tr("Playlist name:", lang),
        )
        if not ok or not name.strip():
            return
        if db.create_playlist(name.strip()) is None:
            CustomConfirmDialog.information(
                self,
                tr("Already exists", lang),
                tr("Playlist '{name}' already exists.", lang).format(
                    name=name.strip()
                ),
            )
            return
        self._refresh_grid()

    # ------------------------------------------------------------------
    #  Страница 2: внутри плейлиста
    # ------------------------------------------------------------------
    def _build_detail_page(self):
        lang = _lang()
        page = _DetailPage()
        page.setObjectName("playlistDetail")
        self.detail_page = page

        self.cover_widget = _CoverWidget()
        self.cover_widget.clicked.connect(self._on_choose_cover)

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
            "QPushButton:hover { background: rgba(81, 81, 171, 0.35); }"
        )
        self.add_tracks_button.clicked.connect(self._on_bulk_add)

        self.description_edit = _DescriptionEdit()
        self.description_edit.setObjectName("playlistDescription")
        self.description_edit.setPlaceholderText(
            tr("Add a description...", lang)
        )
        self.description_edit.setMinimumHeight(44)
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        self.description_edit.setFrameStyle(0)
        self.description_edit.editing_finished.connect(self._on_description_changed)

        self.back_button = self._icon_button(
            "back.svg", tr("Back", lang)
        )
        self.delete_button = self._icon_button(
            "trash.svg", tr("Delete", lang)
        )

        self.back_button.clicked.connect(self._go_back)
        self.delete_button.clicked.connect(self._on_delete_playlist)

        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addStretch()
        buttons.addWidget(self.delete_button)

        right = QVBoxLayout()
        right.addLayout(buttons)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(10)
        name_row.addWidget(self.name_label)
        name_row.addWidget(self.add_tracks_button, 0, Qt.AlignVCenter)
        name_row.addStretch(1)
        right.addLayout(name_row)
        right.addWidget(self.description_edit)
        right.addStretch()

        header = QHBoxLayout()
        header.addWidget(self.cover_widget, 0, Qt.AlignTop)
        header.addSpacing(16)
        header.addLayout(right, 1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            tr("Search in playlist...", lang)
        )
        self.search_icon_action = self.search_edit.addAction(
            colored_icon("search.svg", _icon_color()), QLineEdit.LeadingPosition
        )
        self.search_edit.textChanged.connect(self._refresh_tracks)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            tr("Date added", lang),
            tr("Title", lang),
            tr("Artist", lang),
            tr("Duration", lang),
        ])
        # activated срабатывает и при повторном выборе текущего пункта —
        # именно это нужно для переключения asc/desc.
        self.sort_combo.activated.connect(self._on_sort_activated)
        self.sort_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sort_combo.setMinimumWidth(150)
        self._update_sort_indicator()

        self.filter_icon_label = QLabel()
        self.filter_icon_label.setPixmap(
            colored_pixmap("filter.svg", 20, _icon_color())
        )
        self.filter_icon_label.setStyleSheet(
            "background: transparent; border: none; padding: 0; margin: 0;"
        )

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.filter_icon_label)
        filter_row.addWidget(self.sort_combo)

        self.tracks_count_label = QLabel(
            tr("Tracks in playlist ({n})", lang).format(n=0)
        )

        self.tracks_list = PlaylistTracksWidget()
        self.track_delegate = TrackDelegate(self.tracks_list, controller=self)
        self.track_delegate.delete_requested.connect(self.delete_track_requested.emit)
        # Применяем текущую настройку бейджей источников метаданных
        settings = QSettings("MusicPlayer", "MusicPlayer")
        self.track_delegate.set_show_metadata_badges(
            bool(settings.value("show_metadata_source_badges", False, type=bool))
        )
        self.tracks_list.setItemDelegate(self.track_delegate)
        # Мультиселект: Ctrl+A / shift-клик / «Select all» из контекстного меню.
        # Двойной клик и контекстное меню работают по координатам мыши,
        # так что клик по строке для плеера не ломает логику выбора.
        self.tracks_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Отслеживание мыши — иначе делегат не получает State_MouseOver (ховер).
        self.tracks_list.setMouseTracking(True)
        self.tracks_list.viewport().setMouseTracking(True)
        self.tracks_list.setAttribute(Qt.WA_Hover, True)
        self.tracks_list.itemDoubleClicked.connect(self._on_track_double_clicked)
        self.tracks_list.play_requested.connect(self._on_track_double_clicked)

        layout = QVBoxLayout(page)
        layout.addLayout(header)
        layout.addWidget(self.tracks_count_label)
        layout.addLayout(filter_row)
        layout.addWidget(self.tracks_list)

        # Даем списку треков весь оставшийся вертикальный простор
        layout.setStretchFactor(self.tracks_list, 1)

        return page

    def _icon_button(self, icon_name, tooltip):
        btn = QPushButton()
        btn.setIcon(colored_icon(icon_name))
        btn.setIconSize(QSize(22, 22))
        btn.setFlat(True)
        btn.setToolTip(tooltip)
        return btn

    def _go_back(self):
        self.stack.setCurrentIndex(0)
        self.current_playlist_id = None
        self.current_playlist_name = ""
        self._refresh_grid()

    def _on_choose_cover(self):
        if self.current_playlist_id is None:
            return
        lang = _lang()
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose photo", lang), str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return

        try:
            PLAYLIST_COVERS_DIR.mkdir(parents=True, exist_ok=True)
            ext = Path(path).suffix.lower() or ".jpg"
            dest = PLAYLIST_COVERS_DIR / f"{self.current_playlist_id}{ext}"
            for old in PLAYLIST_COVERS_DIR.glob(f"{self.current_playlist_id}.*"):
                if old != dest:
                    old.unlink(missing_ok=True)
            shutil.copyfile(path, dest)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Не удалось сохранить обложку:\n{e}")
            return

        db.update_playlist_cover(self.current_playlist_id, str(dest))
        self.cover_widget.set_cover(str(dest))
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
        pid = self.current_playlist_id
        if pid is None:
            self._update_tracks_count()
            return

        rows = db.get_tracks_in_playlist(pid)

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
        reverse = not self._sort_ascending
        if idx == 0:
            rows = sorted(rows, key=lambda r: r["added_at"] or "", reverse=reverse)
        elif idx == 1:
            rows = sorted(
                rows, key=lambda r: (r["title"] or "").lower(), reverse=reverse
            )
        elif idx == 2:
            rows = sorted(
                rows, key=lambda r: (r["artist"] or "").lower(), reverse=reverse
            )
        elif idx == 3:
            rows = sorted(
                rows, key=lambda r: r["duration"] or 0, reverse=reverse
            )

        for i, row in enumerate(rows):
            path = row["file_path"]
            item = QListWidgetItem()
            source = get_cached_source_for_path(path)
            item.setData(Qt.UserRole, {
                "id": row["id"],
                "path": path,
                "title": row["title"] or "Unknown Title",
                "artist": row["artist"] or "Unknown Artist",
                "duration": row["duration"],
                "cover_path": metadata.extract_cover(path, row["id"]),
                "metadata_source": source,
                "index": i + 1,
            })
            self.tracks_list.addItem(item)
        self._update_tracks_count()

    def _on_sort_activated(self, index):
        """Переключает направление сортировки при каждом клике."""
        if index < 0:
            return
        if index == self._sort_index:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_index = index
            # Дате и длительности логичнее начинать с убывания, а
            # названию/артисту — с возрастания.
            self._sort_ascending = index in (1, 2)
        self._update_sort_indicator()
        self._refresh_tracks()

    def _update_sort_indicator(self):
        """Рисует ↑/↓ у выбранного пункта, не трогая остальные."""
        arrow = "↑" if self._sort_ascending else "↓"
        for i in range(self.sort_combo.count()):
            text = self.sort_combo.itemText(i).strip(" ↑↓")
            if i == self.sort_combo.currentIndex():
                text = f"{text} {arrow}"
            self.sort_combo.setItemText(i, text)

    def _update_tracks_count(self):
        self.tracks_count_label.setText(
            tr("Tracks in playlist ({n})", _lang()).format(
                n=self.tracks_list.count()
            )
        )

    def _on_track_double_clicked(self, item):
        if self.current_playlist_id is None:
            return
        data = item.data(Qt.UserRole) or {}
        path = data.get("path")
        if path and not Path(path).exists():
            QMessageBox.warning(self, "File missing", f"Файл не найден:\n{path}")
            return
        ids = []
        for i in range(self.tracks_list.count()):
            row_item = self.tracks_list.item(i)
            if row_item is None:
                continue
            row_data = row_item.data(Qt.UserRole) or {}
            ids.append(row_data.get("id"))
        self.play_track.emit(self.current_playlist_id, data.get("id"), ids)

    # ------------------------------------------------------------------
    #  Публичный API для MainWindow
    # ------------------------------------------------------------------
    def _apply_icon_theme(self):
        """Перекрашивает иконки страницы под текущую тему."""
        color = _icon_color()
        self.create_button.setIcon(colored_icon("create-playlist.svg", color))
        self.random_button.setIcon(colored_icon("random.svg", color))
        self.back_button.setIcon(colored_icon("back.svg", color))
        self.delete_button.setIcon(colored_icon("trash.svg", color))
        if self.search_icon_action is not None:
            self.search_icon_action.setIcon(colored_icon("search.svg", color))
        self.filter_icon_label.setPixmap(colored_pixmap("filter.svg", 20, color))

    def reload(self):
        self._apply_icon_theme()
        self._refresh_grid()
        self._refresh_tracks()
        # Градиент и большая обложка читают тему при отрисовке — форсируем repaint.
        self.detail_page.update()
        self.cover_widget.update()

    def refresh_tracks(self):
        self._refresh_tracks()
        self.track_delegate.set_current_playing(self._current_track_id)

    def set_current_track(self, track_id):
        """Помечает играющий трек в списке (маркер + фон в делегате)."""
        self._current_track_id = track_id
        self.track_delegate.set_current_playing(track_id)
        self.tracks_list.viewport().update()

    # Обратная совместимость: тот же смысл, что и set_current_track.
    def set_current_playing(self, track_id):
        self.set_current_track(track_id)
