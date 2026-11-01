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

"""Диалог массового добавления треков в плейлист."""

from PyQt5.QtCore import QSettings, QRectF, QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

import db
import metadata
from dialog_base import (
    _FramelessDialog,
    _dialog_lang,
    _mix_color,
    colored_pixmap,
)
from musicbrainz_client import get_cached_source_for_path
from pixmap_utils import draw_centered, draw_cover, draw_source_badge
from translations import tr


class _BulkTrackDelegate(QStyledItemDelegate):
    """Строка массового добавления: чекбокс, обложка, название и артист."""

    ROW_HEIGHT = 58
    COVER_SIZE = 40
    CHECK_SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self._check_mark = colored_pixmap("confirm.svg", 12, "#ffffff")
        self._note_cache = {}
        self._show_metadata_badges = False

    def _palette(self, option):
        """Цвета строки из палитры активной темы (акцент, текст, фон)."""
        pal = option.palette
        text = pal.color(QPalette.Text)
        window_text = pal.color(QPalette.WindowText)
        highlight = pal.color(QPalette.Highlight)

        subtext = QColor(window_text)
        subtext.setAlpha(150)
        checked_bg = QColor(highlight)
        checked_bg.setAlpha(28)
        hover = QColor(window_text)
        hover.setAlpha(15)
        check_border = QColor(window_text)
        check_border.setAlpha(90)
        # Иконку-заглушку приглушаем, чтобы не светилась ярче текста.
        note = _mix_color(text, pal.color(QPalette.Base), 0.45).name()
        return {
            "accent": highlight,
            "text": text,
            "subtext": subtext,
            "cover_bg": pal.color(QPalette.Base),
            "note": note,
            "hover": hover,
            "checked_bg": checked_bg,
            "check_border": check_border,
        }

    def _note_pixmap(self, color):
        """Иконка-нота, перекрашенная под тему (с кэшем по цвету)."""
        pixmap = self._note_cache.get(color)
        if pixmap is None:
            pixmap = colored_pixmap("music-note.svg", 20, color)
            self._note_cache[color] = pixmap
        return pixmap

    def set_show_metadata_badges(self, enabled: bool):
        """Включает/выключает отрисовку бейджей источников метаданных."""
        if self._show_metadata_badges != enabled:
            self._show_metadata_badges = enabled
            parent = self.parent()
            if parent is not None:
                parent.viewport().update()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        if painter is None:
            return

        data = index.data(Qt.UserRole) or {}
        checked = index.data(Qt.CheckStateRole) == Qt.Checked
        rect = option.rect
        palette = self._palette(option)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(rect, Qt.transparent)

        if checked:
            painter.fillRect(rect, palette["checked_bg"])
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, palette["hover"])

        # Кастомный чекбокс: Qt.ItemIsUserCheckable хранит состояние,
        # а рисуем его сами, чтобы строка выглядела единым целым.
        check_rect = QRectF(
            rect.x() + 12,
            rect.y() + (rect.height() - self.CHECK_SIZE) / 2,
            self.CHECK_SIZE,
            self.CHECK_SIZE,
        )
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(palette["accent"])
            painter.drawRoundedRect(check_rect, 4, 4)
            draw_centered(painter, check_rect, self._check_mark)
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(palette["check_border"], 1.2))
            painter.drawRoundedRect(check_rect, 4, 4)

        # Обложка трека.
        cover_rect = QRectF(
            rect.x() + 42,
            rect.y() + (rect.height() - self.COVER_SIZE) / 2,
            self.COVER_SIZE,
            self.COVER_SIZE,
        )
        clip = QPainterPath()
        clip.addRoundedRect(cover_rect, 5, 5)
        painter.save()
        painter.setClipPath(clip)
        cover_path = data.get("cover_path")
        pixmap = QPixmap(cover_path) if cover_path else QPixmap()
        if not draw_cover(painter, cover_rect, pixmap):
            painter.fillRect(cover_rect, palette["cover_bg"])
            draw_centered(painter, cover_rect, self._note_pixmap(palette["note"]))
        painter.restore()
        if self._show_metadata_badges:
            draw_source_badge(painter, cover_rect, data.get("metadata_source"), size=11)

        # Название и исполнитель.
        text_x = cover_rect.right() + 12
        text_width = max(20, int(rect.right() - text_x - 12))
        title_font = QFont(painter.font())
        title_font.setPixelSize(13)
        title_font.setBold(True)
        title = QFontMetrics(title_font).elidedText(
            data.get("title") or "Unknown Title",
            Qt.ElideRight,
            text_width,
        )
        painter.setFont(title_font)
        painter.setPen(palette["text"])
        painter.drawText(
            QRectF(text_x, rect.y() + 8, text_width, 19),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )

        artist_font = QFont(painter.font())
        artist_font.setPixelSize(11)
        artist_font.setBold(False)
        artist = QFontMetrics(artist_font).elidedText(
            data.get("artist") or "Unknown Artist",
            Qt.ElideRight,
            text_width,
        )
        painter.setFont(artist_font)
        painter.setPen(palette["subtext"])
        painter.drawText(
            QRectF(text_x, rect.y() + 28, text_width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            artist,
        )

        painter.restore()


class _BulkListWidget(QListWidget):
    """Список, в котором клик по любой точке строки переключает галочку."""

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and item.flags() & Qt.ItemIsUserCheckable:
                if item.checkState() == Qt.Checked:
                    item.setCheckState(Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class BulkAddDialog(_FramelessDialog):
    """Безрамочный диалог массового добавления треков в плейлист."""

    def __init__(self, parent=None):
        lang = _dialog_lang()
        super().__init__(parent, tr("Add Tracks", lang))

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 4, 20, 6)
        col.setSpacing(8)

        self.list = _BulkListWidget()
        self.list.setObjectName("cdBulkList")
        self._bulk_delegate = _BulkTrackDelegate(self.list)
        self.list.setItemDelegate(self._bulk_delegate)
        # Применяем текущую настройку бейджей
        settings = QSettings("MusicPlayer", "MusicPlayer")
        self._bulk_delegate.set_show_metadata_badges(
            bool(settings.value("show_metadata_source_badges", False, type=bool))
        )
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.setUniformItemSizes(True)

        for row in db.get_all_tracks():
            path = row["file_path"]
            cover_path = metadata.extract_cover(path, row["id"]) if path else None
            source = get_cached_source_for_path(path) if path else None
            item = QListWidgetItem()
            item.setData(Qt.UserRole, {
                "id": row["id"],
                "title": row["title"] or "Unknown Title",
                "artist": row["artist"] or "Unknown Artist",
                "cover_path": cover_path,
                "metadata_source": source,
            })
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)

        col.addWidget(self.list, 1)
        self.body.addWidget(content)

        self.cancel_button = self._make_button(
            "cdCancel", tr("Cancel", lang), "cancel.svg"
        )
        self.cancel_button.clicked.connect(self.reject)

        self.confirm_button = self._make_button(
            "cdConfirm", tr("OK", lang), "confirm.svg"
        )
        self.confirm_button.setDefault(True)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.accept)

        self._add_footer([self.cancel_button, self.confirm_button])
        self.list.itemChanged.connect(self._update_confirm_state)

        self.setMinimumSize(600, 540)
        self.resize(640, 620)
        self.list.setFocus()

    def selected_track_ids(self):
        """id отмеченных треков в порядке списка."""
        ids = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole) or {}
                if data.get("id") is not None:
                    ids.append(data["id"])
        return ids

    def _update_confirm_state(self, _item=None):
        self.confirm_button.setEnabled(bool(self.selected_track_ids()))
