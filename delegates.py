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

"""Кастомная отрисовка строк списка треков."""

import os
from pathlib import Path

from PyQt5.QtCore import QEvent, QRect, QRectF, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PyQt5.QtWidgets import QStyle, QStyledItemDelegate

from pixmap_utils import (
    draw_centered,
    draw_cover,
    draw_source_badge,
    svg_file_pixmap,
)
from styles import is_dark_theme

ICONS_DIR = Path(__file__).parent / "icons"


def _svg_pixmap(filename, size=24, color="#888888"):
    """Иконка из icons/black/<filename> с DPR-осознанным разрешением."""
    path = ICONS_DIR / "black" / filename
    if not path.is_file():
        return QPixmap()
    return svg_file_pixmap(path, size, color=color)


def _music_note_pixmap(size=24, color="#888888"):
    """Иконка ноты (заглушка обложки)."""
    return _svg_pixmap("music-note.svg", size, color)


def _folder_pixmap(size=24, color="#cfcfcf"):
    """Иконка папки для заголовков дерева."""
    return _svg_pixmap("show-folder-with-music.svg", size, color)


def _theme_is_dark():
    """Текущая тема из QSettings (делегат не всегда знает её заранее)."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return is_dark_theme(settings.value("theme", "dark"))


def _blend(first, second, ratio):
    """Смешивает два цвета: ``ratio`` — доля ``first`` (0..1)."""
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(first.red() * ratio + second.red() * (1 - ratio)),
        round(first.green() * ratio + second.green() * (1 - ratio)),
        round(first.blue() * ratio + second.blue() * (1 - ratio)),
    )


class TrackDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 60
    FOLDER_HEIGHT = 44
    COVER_SIZE = 50
    COVER_RADIUS = 6
    ACCENT_WIDTH = 3
    # Зона слева, где рисуется порядковый номер / иконка Play при наведении.
    PLAY_BTN_X = 4
    PLAY_BTN_WIDTH = 26
    delete_requested = pyqtSignal(int)

    def __init__(self, parent=None, is_dark_theme=None, controller=None):
        super().__init__(parent)
        self._is_dark_theme = is_dark_theme
        self._controller = controller
        self._icons = {}
        # id трека, который сейчас играет: акцентная полоска слева + фон строки
        self.current_playing_id = None
        # Флаг показа бейджей источников метаданных (M/Y/F на обложках)
        self._show_metadata_badges = False
        # CHANGED: индекс и rect иконки мусорки под курсором (задаёт view).
        self.hovered_trash_index = None
        self.hovered_trash_rect = None

    def set_dark_theme(self, is_dark_theme):
        """Задаёт тему явно (None — определять из QSettings при отрисовке)."""
        self._is_dark_theme = None if is_dark_theme is None else bool(is_dark_theme)
        self._icons.clear()
        self._repaint_owner()

    def set_current_playing(self, track_id):
        """Помечает трек как играющий и перерисовывает виджет-владелец."""
        if track_id == self.current_playing_id:
            return
        self.current_playing_id = track_id
        self._repaint_owner()

    def set_current_track_id(self, track_id):
        """Обратная совместимость: старый вход в set_current_playing."""
        self.set_current_playing(track_id)

    def set_show_metadata_badges(self, enabled: bool):
        """Включает/выключает отрисовку бейджей источников метаданных."""
        if self._show_metadata_badges != enabled:
            self._show_metadata_badges = enabled
            self._repaint_owner()

    def _repaint_owner(self):
        """Форсирует перерисовку viewport'а виджета-владельца."""
        parent = self.parent()
        viewport = getattr(parent, "viewport", None)
        if callable(viewport):
            viewport().update()
        elif parent is not None:
            parent.update()

    def is_dark(self):
        if self._is_dark_theme is not None:
            return self._is_dark_theme
        return _theme_is_dark()

    def _palette(self, option=None):
        """Цвета строки.

        Если передан ``option`` — берём цвета из его ``QPalette``, поэтому
        делегат автоматически следует любой QSS-теме: текст, приглушённый
        текст, акцент и фон строки. Без ``option`` остаётся прежний
        тёмный/светлый фолбэк (для вызовов вне отрисовки).
        """
        if option is not None:
            pal = option.palette
            text = pal.color(QPalette.Text)
            window_text = pal.color(QPalette.WindowText)
            highlight = pal.color(QPalette.Highlight)

            artist = QColor(window_text)
            artist.setAlpha(150)
            missing = QColor(text)
            missing.setAlpha(110)
            # Мягкая подсветка играющего трека — акцент темы с прозрачностью.
            playing_bg = QColor(highlight)
            playing_bg.setAlpha(40)
            selected_bg = QColor(highlight)
            selected_bg.setAlpha(30)
            hover = QColor(window_text)
            hover.setAlpha(15)

            base = pal.color(QPalette.Base)
            # Иконки-заглушки приглушаем, чтобы не светились ярче текста.
            note = _blend(text, base, 0.55).name()
            folder_icon = _blend(window_text, base, 0.75).name()

            return {
                "title": text,
                "artist": artist,
                "missing": missing,
                "selection": playing_bg,
                "selected": selected_bg,
                "hover": hover,
                "cover_bg": base,
                "note": note,
                "folder_icon": folder_icon,
                "play": text.name(),
                "accent": highlight,
            }

        if self.is_dark():
            return {
                "title": QColor("#ffffff"),
                "artist": QColor("#8a8a8a"),
                "missing": QColor("#888888"),
                "selection": QColor("#282828"),
                "selected": QColor(255, 255, 255, 8),  # dim highlight for multi-selection
                "hover": QColor(255, 255, 255, 15),
                "cover_bg": QColor("#282828"),
                "note": "#888888",
                "folder_icon": "#cfcfcf",
                "play": "#ffffff",
                "accent": QColor("#5151ab"),
            }
        return {
            "title": QColor("#000000"),
            "artist": QColor("#666666"),
            "missing": QColor("#999999"),
            "selection": QColor("#e0e0e0"),
            "selected": QColor(0, 0, 0, 8),  # dim highlight for multi-selection
            "hover": QColor(0, 0, 0, 15),
            "cover_bg": QColor("#f0f0f0"),
            "note": "#000000",
            "folder_icon": "#666666",
            "play": "#000000",
            "accent": QColor("#5151ab"),
        }

    def _cached_icon(self, kind, color, size):
        """Кэширует перекрашенные иконки по (тип, цвет, размер)."""
        key = (kind, color, size)
        pixmap = self._icons.get(key)
        if pixmap is None:
            if kind == "note":
                pixmap = _music_note_pixmap(size, color)
            elif kind == "play":
                pixmap = _svg_pixmap("play-mini.svg", size, color)
            elif kind == "trash":
                pixmap = _svg_pixmap("trash.svg", size, color)
            else:
                pixmap = _folder_pixmap(size, color)
            self._icons[key] = pixmap
        return pixmap

    def get_trash_rect_for_index(self, view, index):
        """CHANGED: rect иконки мусорки для индекса в координатах viewport."""
        option = view.viewOptions()
        option.rect = view.visualRect(index)
        data = index.data(Qt.UserRole) or {}
        if data.get("is_folder"):
            return None
        duration = data.get("duration") or 0
        dur_text = f"{duration // 60}:{duration % 60:02d}"
        font = QFont(option.font)
        font.setPixelSize(11)
        dur_w = QFontMetrics(font).horizontalAdvance(dur_text) + 24
        rect = option.rect
        text_right = rect.right() - dur_w
        trash_size = 16
        return QRect(
            text_right - trash_size - 10,
            rect.y() + (self.ROW_HEIGHT - trash_size) // 2,
            trash_size,
            trash_size,
        )

    def sizeHint(self, option, index):
        data = index.data(Qt.UserRole) or {}
        if isinstance(data, dict) and data.get("is_folder"):
            return QSize(option.rect.width(), self.FOLDER_HEIGHT)
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    @staticmethod
    def is_play_click(pos, rect):
        """Попал ли клик в левую зону, где рисуется номер / иконка Play."""
        x = pos.x() - rect.x()
        return 0 <= x <= TrackDelegate.PLAY_BTN_X + TrackDelegate.PLAY_BTN_WIDTH

    def paint(self, painter, option, index):
        if painter is None:
            return
        data = index.data(Qt.UserRole) or {}
        if isinstance(data, dict) and data.get("is_folder"):
            self._paint_folder(painter, option, data)
        else:
            self._paint_track(painter, option, data, index)

    @staticmethod
    def _row_rect(option):
        """Прямоугольник на всю ширину viewport — фон строки выделения/hover.

        option.rect у tree-item'ов сдвинут вправо на отступ дерева, поэтому
        для подсветки берём полную ширину строки."""
        rect = option.rect
        view = option.widget
        if view is not None and hasattr(view, "viewport"):
            return QRect(0, rect.y(), view.viewport().width(), rect.height())
        return rect

    def _paint_track(self, painter, option, data, index=None):
        rect = option.rect
        palette = self._palette(option)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Стираем следы прошлой отрисовки Qt.
        painter.fillRect(option.rect, Qt.transparent)

        # Фон строки. Фон и синяя полоска рисуются ТОЛЬКО у текущего играющего
        # трека. Клик мышью (State_Selected) не учитывается — выделенный, но не
        # играющий трек остаётся с прозрачным фоном.
        row_rect = self._row_rect(option)
        track_id = data.get("id")
        is_playing = track_id is not None and track_id == self.current_playing_id

        if is_playing:
            # Фон играющего трека.
            painter.fillRect(row_rect, palette["selection"])
            # Акцентная полоска слева от обложки, на всю высоту строки.
            # Цвет — highlight активной темы (без прозрачности).
            painter.fillRect(
                QRect(row_rect.x(), row_rect.y(), self.ACCENT_WIDTH, row_rect.height()),
                palette["accent"],
            )
        elif option.state & QStyle.State_Selected:
            painter.fillRect(row_rect, palette["selected"])  # <-- NEW
        elif option.state & QStyle.State_MouseOver:
            # Лёгкий фон наведения для не-играющего трека
            # (тёмная тема rgba(255,255,255,15), светлая rgba(0,0,0,15)).
            painter.fillRect(row_rect, palette["hover"])

        # Порядковый номер трека (или иконка play при наведении курсора) в
        # освободившемся слева месте.
        marker_size = 12
        marker_cx = rect.x() + 15
        marker_cy = rect.y() + self.ROW_HEIGHT // 2
        if option.state & QStyle.State_MouseOver:
            play_icon = self._cached_icon("play", palette["play"], marker_size)
            draw_centered(
                painter,
                QRectF(
                    marker_cx - marker_size // 2,
                    marker_cy - marker_size // 2,
                    marker_size,
                    marker_size,
                ),
                play_icon,
            )
        else:
            index_num = data.get("index")
            if index_num is not None:
                num_font = QFont(painter.font())
                num_font.setPixelSize(11)
                num_font.setBold(False)
                painter.setFont(num_font)
                painter.setPen(palette["artist"])
                painter.drawText(
                    QRect(rect.x(), rect.y(), 30, self.ROW_HEIGHT),
                    Qt.AlignCenter, str(index_num),
                )

        # Обложка (сдвинута вправо, чтобы освободить место слева)
        cover_rect = QRect(
            rect.x() + 40,
            rect.y() + (self.ROW_HEIGHT - self.COVER_SIZE) // 2,
            self.COVER_SIZE,
            self.COVER_SIZE,
        )
        self._draw_cover(
            painter,
            cover_rect,
            data.get("cover_path"),
            palette,
            data.get("metadata_source"),
        )

        # Длительность (измеряем до текстов)
        duration = data.get("duration") or 0
        dur_text = f"{duration // 60}:{duration % 60:02d}"
        dur_font = QFont(painter.font())
        dur_font.setPixelSize(11)
        dur_w = QFontMetrics(dur_font).horizontalAdvance(dur_text) + 24

        text_left = rect.x() + 100
        text_right = rect.right() - dur_w
        text_width = max(0, text_right - text_left)

        missing = not os.path.exists(data.get("path") or "")

        # Название
        title_font = QFont(painter.font())
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette["missing"] if missing else palette["title"])
        title = QFontMetrics(title_font).elidedText(
            data.get("title") or "Unknown Title", Qt.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, rect.y() + 11, text_width, 16),
            Qt.AlignLeft | Qt.AlignVCenter, title,
        )

        # Исполнитель
        artist_font = QFont(painter.font())
        artist_font.setPixelSize(11)
        artist_font.setBold(False)
        painter.setFont(artist_font)
        painter.setPen(palette["artist"])
        artist = QFontMetrics(artist_font).elidedText(
            data.get("artist") or "Unknown Artist", Qt.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, rect.y() + 30, text_width, 15),
            Qt.AlignLeft | Qt.AlignVCenter, artist,
        )

        # Длительность
        painter.setFont(dur_font)
        painter.setPen(palette["artist"])
        painter.drawText(
            QRect(text_right, rect.y(), dur_w - 10, self.ROW_HEIGHT),
            Qt.AlignRight | Qt.AlignVCenter, dur_text,
        )

        # CHANGED: Отрисовка иконки мусорки при наведении.
        if option.state & QStyle.State_MouseOver:
            trash_size = 16
            # Иконка слева от текста длительности (10px слева от текста)
            trash_x = text_right - trash_size - 10
            trash_y = rect.y() + (self.ROW_HEIGHT - trash_size) // 2
            trash_rect = QRect(trash_x, trash_y, trash_size, trash_size)

            # CHANGED: кружок рисуем, только если view сообщил, что мышь
            # находится на этой конкретной иконке.
            if (
                self.hovered_trash_index == index
                and self.hovered_trash_rect == trash_rect
            ):
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(Qt.NoPen)
                circle = QColor(palette["title"])
                circle.setAlpha(30)
                painter.setBrush(circle)
                painter.drawEllipse(
                    QRectF(
                        trash_x - 4,
                        trash_y - 4,
                        trash_size + 8,
                        trash_size + 8,
                    )
                )
                painter.restore()

            # Саму иконку рисуем всегда, когда мышь над строкой
            trash_icon = self._cached_icon("trash", "#e05a4a", trash_size)
            draw_centered(painter, QRectF(trash_rect), trash_icon)

        painter.restore()

    def _paint_folder(self, painter, option, data):
        rect = option.rect
        palette = self._palette(option)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        row_rect = self._row_rect(option)
        if option.state & QStyle.State_Selected:
            painter.fillRect(row_rect, palette["selection"])
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(row_rect, palette["hover"])

        # Иконка папки
        icon_size = 22
        icon_x = rect.x() + 10
        icon_y = rect.y() + (rect.height() - icon_size) // 2
        folder_icon = self._cached_icon("folder", palette["folder_icon"], icon_size)
        painter.drawPixmap(icon_x, icon_y, folder_icon)

        # Название папки — крупным жирным шрифтом, без артиста и длительности
        font = QFont(painter.font())
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette["title"])

        text_left = icon_x + icon_size + 10
        text_width = max(0, rect.right() - text_left)
        name = QFontMetrics(font).elidedText(
            data.get("name") or "Folder", Qt.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, rect.y(), text_width, rect.height()),
            Qt.AlignLeft | Qt.AlignVCenter, name,
        )

        painter.restore()

    def _draw_cover(
        self, painter, rect, cover_path, palette, metadata_source=None
    ):
        radius = self.COVER_RADIUS
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), radius, radius)

        painter.save()
        painter.setClipPath(clip)

        pixmap = QPixmap(cover_path) if cover_path else QPixmap()
        if not draw_cover(painter, QRectF(rect), pixmap):
            painter.fillRect(rect, palette["cover_bg"])
            icon_size = 24
            note = self._cached_icon("note", palette["note"], icon_size)
            draw_centered(painter, QRectF(rect), note)

        painter.restore()

        if self._show_metadata_badges:
            draw_source_badge(painter, rect, metadata_source, size=13)

    # ВНИМАНИЕ: editorEvent теперь на том же уровне, что и _draw_cover!
    def editorEvent(self, event, model, option, index):
        if event is None:
            return False

        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            data = index.data(Qt.UserRole) or {}
            if not data.get("is_folder") and data.get("id") is not None:
                duration = data.get("duration") or 0
                dur_text = f"{duration // 60}:{duration % 60:02d}"
                font = QFont(option.font)
                font.setPixelSize(11)
                dur_w = QFontMetrics(font).horizontalAdvance(dur_text) + 24

                # Координаты иконки мусорки (совпадают с тем, что в _paint_track)
                rect = option.rect
                text_right = rect.right() - dur_w
                trash_size = 16
                trash_x = text_right - trash_size - 10
                trash_y = rect.y() + (self.ROW_HEIGHT - trash_size) // 2
                trash_rect = QRect(trash_x, trash_y, trash_size, trash_size)

                if trash_rect.contains(event.pos()):
                    self.delete_requested.emit(data.get("id"))
                    return True # Поглощаем клик

        # Вызов super() теперь на нужном уровне!
        return super().editorEvent(event, model, option, index)
