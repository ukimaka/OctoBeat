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

"""Виджеты для вкладки Плейлисты: грид, треки, обложка, страница деталей."""

from __future__ import annotations

import os

from PyQt5.QtCore import QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QTextEdit,
    QWidget,
)

from dialog_base import colored_pixmap
from pixmap_utils import cached_cover, draw_centered, draw_cover, pixmap_size
from translations import tr
from styles import is_dark_theme
from PyQt5.QtCore import QSettings

_HOVER_DEBUG = os.environ.get("OCTOBEAT_HOVER_DEBUG") == "1"


def _theme_is_dark():
    """Текущая тема из QSettings (виджеты читают её при отрисовке)."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return is_dark_theme(settings.value("theme", "dark"))


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
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
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
                if (hasattr(delegate, 'play_rect')
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
        import db
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(20)
        # Все строки треков фиксированной высоты 60 px.
        self.setUniformItemSizes(True)
        # Кэш последнего hover: при 8K-мыши mouseMoveEvent приходит тысячи
        # раз в секунду, поэтому пересчитываем строку/иконку только при
        # переходе курсора между строками или зоной trash-иконки.
        self._last_hovered_index = None
        self._last_row_rect = None
        self._last_hovered_icon = False
        self._last_trash_rect = None

    def _repaint_hover_rows(self, *row_rects):
        """Перерисовывает только указанные строки, не весь viewport."""
        viewport = self.viewport()
        area = viewport.rect()
        seen = set()
        for row_rect in row_rects:
            if row_rect is None:
                continue
            rect = QRect(
                0, row_rect.y(), viewport.width(), row_rect.height()
            ).intersected(area)
            if rect.isEmpty():
                continue
            key = (rect.x(), rect.y(), rect.width(), rect.height())
            if key in seen:
                continue
            seen.add(key)
            if _HOVER_DEBUG:
                print(
                    f"[hover] {type(self).__name__} repaint "
                    f"y={rect.y()} h={rect.height()}"
                )
            viewport.update(rect)

    def mouseReleaseEvent(self, event):
        """Одиночный клик по иконке Play слева запускает трек."""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None:
                from delegates import TrackDelegate
                if TrackDelegate.is_play_click(
                    event.pos(), self.visualItemRect(item)
                ):
                    self.play_requested.emit(item)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        # Сбрасываем кэш и hover-иконку, иначе после повторного входа
        # курсора на ту же строку состояние может остаться устаревшим.
        old_row_rect = self._last_row_rect
        self._last_hovered_index = None
        self._last_row_rect = None
        self._last_hovered_icon = False
        self._last_trash_rect = None
        delegate = self.itemDelegate()
        if getattr(delegate, "hovered_trash_index", None) is not None:
            delegate.hovered_trash_index = None
            delegate.hovered_trash_rect = None
        self._repaint_hover_rows(old_row_rect)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.pos()
        index = self.indexAt(pos)
        delegate = self.itemDelegate()

        # QModelIndex() не равен None, поэтому для пустой области
        # используем None как единый ключ — иначе update() вызывался бы
        # на каждое движение мыши вне строк.
        index_key = index if index.isValid() else None
        row_rect = self.visualRect(index) if index.isValid() else None
        old_row_rect = self._last_row_rect
        row_changed = (
            index_key != self._last_hovered_index
            or row_rect != self._last_row_rect
        )
        if row_changed:
            self._last_hovered_index = index_key
            self._last_row_rect = row_rect
            if (
                index.isValid()
                and hasattr(delegate, "get_trash_rect_for_index")
            ):
                self._last_trash_rect = (
                    delegate.get_trash_rect_for_index(self, index)
                )
            else:
                self._last_trash_rect = None

        icon_hovered = bool(
            self._last_trash_rect
            and self._last_trash_rect.contains(pos)
        )
        if not row_changed and icon_hovered == self._last_hovered_icon:
            # Обычное движение внутри строки: никакой перерисовки.
            super().mouseMoveEvent(event)
            return

        self._last_hovered_icon = icon_hovered
        if hasattr(delegate, "hovered_trash_index"):
            if icon_hovered and index.isValid():
                delegate.hovered_trash_index = index
                delegate.hovered_trash_rect = self._last_trash_rect
            elif delegate.hovered_trash_index is not None:
                delegate.hovered_trash_index = None
                delegate.hovered_trash_rect = None

        if row_changed:
            self._repaint_hover_rows(old_row_rect, row_rect)
        else:
            self._repaint_hover_rows(row_rect)
        super().mouseMoveEvent(event)


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
        self.setSizePolicy(
            self.sizePolicy().Policy.Preferred,
            self.sizePolicy().Policy.Preferred
        )
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
            pal = self.palette()
            surface = pal.color(QPalette.Base)
            top = surface.lighter(118) if dark else surface.darker(104)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, surface)
            painter.fillRect(rect, gradient)
            muted = pal.color(QPalette.WindowText)
            muted.setAlpha(140)
            note = self._note_pixmap(muted.name())
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
        palette = self.palette()
        dark = _theme_is_dark()
        # Нижний цвет градиента — фон текущей темы (QPalette.Window),
        # поэтому страница автоматически подстраивается под любой .qss.
        bottom = palette.color(QPalette.Window)

        if self._top_color is not None:
            top = QColor(self._top_color)
            if not dark:
                # В светлой теме приглушаем цвет обложки, уводя его в фон.
                top = _blend(top, bottom, 0.6)
        else:
            top = QColor(bottom)

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, top)
        if dark:
            gradient.setColorAt(0.3, bottom)
        else:
            # Светлая тема: плавный переход обложка → фон без «жёсткого» стыка.
            gradient.setColorAt(0.45, _blend(top, bottom, 0.75))
        gradient.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), gradient)


class _DescriptionEdit(QTextEdit):
    """QTextEdit, сохраняющий текст при потере фокуса."""

    editing_finished = pyqtSignal(str)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editing_finished.emit(self.toPlainText())


class PlaylistCoverDelegate(QStyledItemDelegate):
    """Плитка плейлиста: квадратная обложка + название, кнопка Play при hover."""

    COVER_SIZE = 160
    COVER_RADIUS = 8
    TILE_WIDTH = 180
    TILE_HEIGHT = 210
    PLAY_BTN_SIZE = 44
    PLAY_MARGIN = 8

    def __init__(self, parent=None, is_dark_theme=None):
        super().__init__(parent)
        self._is_dark_theme = is_dark_theme
        self._play = colored_pixmap("play.svg", 20, "#ffffff")
        self._note_cache = {}

    def set_dark_theme(self, is_dark_theme):
        """Задаёт тему явно (None — определять из QSettings при отрисовке)."""
        self._is_dark_theme = None if is_dark_theme is None else bool(is_dark_theme)

    def is_dark(self):
        if self._is_dark_theme is not None:
            return self._is_dark_theme
        return _theme_is_dark()

    def _palette(self):
        if self.is_dark():
            return {
                "title": QColor("#ffffff"),
                "cover_bg": QColor("#282828"),
                "note": "#888888",
            }
        return {
            "title": QColor("#000000"),
            "cover_bg": QColor("#f0f0f0"),
            "note": "#000000",
        }

    def _note_pixmap(self, color):
        """Нота-заглушка, перекрашенная и кэшированная по цвету."""
        note = self._note_cache.get(color)
        if note is None:
            note = colored_pixmap("music-note.svg", 48, color)
            self._note_cache[color] = note
        return note

    def sizeHint(self, option, index):
        return QSize(self.TILE_WIDTH, self.TILE_HEIGHT)

    @classmethod
    def cover_rect(cls, item_rect):
        return QRect(
            item_rect.x() + (item_rect.width() - cls.COVER_SIZE) // 2,
            item_rect.y() + 8,
            cls.COVER_SIZE,
            cls.COVER_SIZE,
        )

    @classmethod
    def play_rect(cls, item_rect):
        cover = cls.cover_rect(item_rect)
        return QRect(
            cover.right() - cls.PLAY_BTN_SIZE - cls.PLAY_MARGIN,
            cover.bottom() - cls.PLAY_BTN_SIZE - cls.PLAY_MARGIN,
            cls.PLAY_BTN_SIZE,
            cls.PLAY_BTN_SIZE,
        )

    def paint(self, painter, option, index):
        if painter is None:
            return

        data = index.data(Qt.UserRole) or {}
        rect = option.rect
        hover = bool(option.state & QStyle.State_MouseOver)
        palette = self._palette()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        self._draw_cover(
            painter,
            self.cover_rect(rect),
            data.get("cover_path"),
            hover,
            palette,
            data.get("cover_version", 0),
        )

        title_font = QFont(painter.font())
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette["title"])

        text_rect = QRect(
            rect.x() + 8,
            self.cover_rect(rect).bottom() + 10,
            rect.width() - 16,
            20,
        )
        title = QFontMetrics(title_font).elidedText(
            data.get("name") or "Unknown", Qt.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, title)

        painter.restore()

    def _draw_cover(
        self, painter, rect, cover_path, hover, palette, cover_version=0
    ):
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), self.COVER_RADIUS, self.COVER_RADIUS)

        painter.save()
        painter.setClipPath(clip)

        pixmap = cached_cover(
            cover_path, rect.width(), rect.height(), cover_version
        )
        if not draw_cover(painter, QRectF(rect), pixmap):
            painter.fillRect(rect, palette["cover_bg"])
            note = self._note_pixmap(palette["note"])
            draw_centered(painter, QRectF(rect), note)

        if hover:
            painter.fillRect(rect, QColor(0, 0, 0, 120))

        painter.restore()

        if hover:
            btn = QRect(
                rect.right() - self.PLAY_BTN_SIZE - self.PLAY_MARGIN,
                rect.bottom() - self.PLAY_BTN_SIZE - self.PLAY_MARGIN,
                self.PLAY_BTN_SIZE,
                self.PLAY_BTN_SIZE,
            )
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#1DB954"))
            painter.drawEllipse(btn)
            draw_centered(painter, QRectF(btn), self._play)
            painter.restore()
