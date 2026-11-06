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

"""Компактный мини-плеер: безрамочное стеклянное окно поверх всех окон.

Виджет не хранит собственную логику воспроизведения: он подписывается на
сигналы ``PlayerController`` и его медиаплеера, а кнопки вызывают методы
контроллера. Переключением главное окно <-> мини-плеер управляет
``MainWindow`` через сигналы ``expand_requested`` и ``closed``.
"""

from collections import OrderedDict
from pathlib import Path

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import db
import metadata
from styles import is_dark_theme, theme_accent
from translations import tr
from ui_common import ClickSlider, ElidedLabel, fmt_time
from vlc_backend import PlaybackState


class MiniPlayer(QWidget):
    """Компактное окно плеера с обложкой и управлением."""

    expand_requested = pyqtSignal()
    closed = pyqtSignal()

    COVER_SIZE = 150
    WINDOW_WIDTH = 372
    WINDOW_HEIGHT = 178
    TINT_ANIMATION_MS = 420
    COLOR_CACHE_LIMIT = 96

    def __init__(self, controller, icons, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("miniPlayer")
        self.setWindowTitle("OctoBeat")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)

        self.controller = controller
        self.media_player = controller.media_player
        self.icons = icons
        self.settings = settings

        self._drag_offset = None
        self._positioned = False
        self._track_id = None
        self._duration = 0
        self._playing = False
        self._dark = True
        self._accent = QColor(theme_accent("dark"))
        self._foreground = QColor("#ffffff")

        # Динамический градиент: исходные цвета обложки и анимируемый
        # переход между предыдущей и новой парой цветов.
        self._cover_colors_raw = None
        self._tint_from = None
        self._tint_target = None
        self._tint_current = None
        self._cover_color_cache = OrderedDict()
        self._tint_anim = QVariantAnimation(self)
        self._tint_anim.setDuration(self.TINT_ANIMATION_MS)
        self._tint_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._tint_anim.valueChanged.connect(self._on_tint_value_changed)
        self._tint_anim.finished.connect(self._on_tint_animation_finished)

        self._build_ui()
        self._apply_theme_colors()
        self._connect_signals()
        self.apply_theme()
        self.sync_from_controller()

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------
    def _lang(self):
        return self.settings.value("language", "en")

    def _icon_button(self, icon_name, tooltip, size, object_name=None):
        button = QPushButton()
        if object_name:
            button.setObjectName(object_name)
        button.setIcon(self.icons.icon(icon_name))
        button.setIconSize(QSize(size, size))
        button.setFixedSize(size + 12, size + 12)
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip)
        return button

    def _build_ui(self):
        lang = self._lang()

        self.cover_label = QLabel()
        self.cover_label.setObjectName("miniCover")
        self.cover_label.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self._set_cover(None)

        self.title_label = ElidedLabel("—")
        self.title_label.setObjectName("miniTitle")
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self.title_label.setFont(title_font)

        self.artist_label = ElidedLabel("")
        self.artist_label.setObjectName("miniArtist")

        self.expand_button = self._icon_button(
            "expand.svg", tr("Expand", lang), 14, "miniExpandButton"
        )
        self.close_button = self._icon_button(
            "cancel.svg", tr("Close", lang), 12, "miniCloseButton"
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.artist_label)
        header.addLayout(text_column, 1)
        header.addWidget(self.expand_button, 0, Qt.AlignTop)
        header.addWidget(self.close_button, 0, Qt.AlignTop)

        self.seek_slider = ClickSlider(Qt.Horizontal)
        self.seek_slider.setObjectName("miniSeek")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setFixedHeight(18)
        self.seek_slider.setCursor(Qt.PointingHandCursor)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("miniTime")
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(8)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.time_label)

        self.prev_button = self._icon_button(
            "prev.svg", tr("Previous", lang), 20, "miniPrevButton"
        )
        self.next_button = self._icon_button(
            "next.svg", tr("Next", lang), 20, "miniNextButton"
        )
        self.play_button = QPushButton()
        self.play_button.setObjectName("miniPlayButton")
        self.play_button.setFixedSize(44, 44)
        self.play_button.setIconSize(QSize(22, 22))
        self.play_button.setFlat(True)
        self.play_button.setCursor(Qt.PointingHandCursor)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        controls.addStretch(1)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)
        right.addLayout(header)
        right.addStretch(1)
        right.addLayout(seek_row)
        right.addLayout(controls)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)
        root.addWidget(self.cover_label, 0, Qt.AlignTop)
        root.addLayout(right, 1)

    def _connect_signals(self):
        self.play_button.clicked.connect(self.controller.toggle_play)
        self.prev_button.clicked.connect(self.controller.prev)
        self.next_button.clicked.connect(self.controller.next)
        self.expand_button.clicked.connect(self._request_expand)
        self.close_button.clicked.connect(self._request_close)

        self.seek_slider.clickedValue.connect(self._seek_to)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        self.seek_slider.sliderReleased.connect(
            lambda: self._seek_to(self.seek_slider.value())
        )

        self.controller.track_changed.connect(self._on_track_changed)
        self.controller.playback_state_changed.connect(
            self._on_playback_state_changed
        )
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        # Состояние может измениться и без PlayerController (например,
        # прямой stop() у медиаплеера) — иконка должна оставаться верной.
        self.media_player.stateChanged.connect(self._on_media_state_changed)

    # ------------------------------------------------------------------
    #  Состояние из контроллера
    # ------------------------------------------------------------------
    def sync_from_controller(self):
        """Подтягивает текущее состояние при открытии окна."""
        track_id = self.controller.current_track_id
        self._on_track_changed(
            track_id if track_id is not None else -1, ""
        )
        # Если медиаплеер ещё не знает длительность, оставляем значение
        # из БД, которое выставил _on_track_changed.
        duration = self.media_player.duration()
        if duration > 0:
            self._on_duration_changed(duration)
        self._on_position_changed(self.media_player.position())
        self._on_playback_state_changed(self.media_player.is_playing())

    def _on_track_changed(self, track_id, title=""):
        row = None
        if track_id is not None and track_id >= 0:
            row = db.get_track_by_id(track_id)

        self._track_id = track_id if row is not None else None

        if row is None:
            self.title_label.setText(tr("Nothing playing", self._lang()))
            self.artist_label.setText("")
            self._set_cover(None)
            self._duration = 0
            self.seek_slider.setRange(0, 0)
            self.seek_slider.setValue(0)
            self._update_time_label(0, 0)
            self.setWindowTitle("OctoBeat")
            return

        track_title = str(row["title"] or title or "").strip()
        if not track_title:
            track_title = Path(row["file_path"]).stem
        artist = str(row["artist"] or "").strip()
        self.title_label.setText(track_title)
        self.artist_label.setText(artist)
        self.setWindowTitle(f"OctoBeat — {track_title}")

        cover_path = metadata.extract_cover(row["file_path"], track_id)
        self._set_cover(cover_path)

        if self.media_player.duration() <= 0 and row["duration"]:
            self._on_duration_changed(int(row["duration"]) * 1000)

    def _on_playback_state_changed(self, playing):
        self._playing = bool(playing)
        self._update_play_icon()

    def _on_media_state_changed(self, state):
        playing = (
            state if isinstance(state, bool)
            else state == PlaybackState.PLAYING
        )
        if playing != self._playing:
            self._on_playback_state_changed(playing)

    def _on_position_changed(self, position):
        if self.seek_slider.isSliderDown():
            return
        position = max(0, int(position))
        self.seek_slider.setValue(position)
        self._update_time_label(position, self._duration)

    def _on_duration_changed(self, duration):
        self._duration = max(0, int(duration))
        self.seek_slider.setRange(0, self._duration)
        if not self.seek_slider.isSliderDown():
            self._update_time_label(self.seek_slider.value(), self._duration)

    def _on_slider_moved(self, value):
        self._update_time_label(int(value), self._duration)

    def _seek_to(self, value):
        self.media_player.set_position(max(0, int(value)))
        self._update_time_label(int(value), self._duration)

    def _update_time_label(self, position, duration):
        self.time_label.setText(
            f"{fmt_time(position)} / {fmt_time(duration)}"
        )

    def _set_cover(self, cover_path):
        pixmap = self.icons.cover_pixmap(
            cover_path, self.COVER_SIZE, radius=14
        )
        self.cover_label.setPixmap(pixmap)

        colors = None
        if cover_path and pixmap is not None and not pixmap.isNull():
            colors = self._cover_gradient_colors(str(cover_path), pixmap)
        self._cover_colors_raw = colors
        # Пока окно скрыто, незачем крутить анимацию в фоне — сразу
        # применяем новые цвета, чтобы при открытии они были актуальны.
        self._apply_tint(colors, animate=self.isVisible())

    # ------------------------------------------------------------------
    #  Динамический градиент по обложке
    # ------------------------------------------------------------------
    def _cover_gradient_colors(self, cover_path, pixmap):
        """Возвращает (верхний, нижний) цвета обложки с кэшем по файлу.

        Ключ кэша включает mtime и размер: если обложку перезаписали,
        цвета пересчитаются. Для быстрых переключений треков повторное
        извлечение не выполняется вовсе.
        """
        try:
            stat = Path(cover_path).stat()
        except OSError:
            return None

        key = (cover_path, stat.st_mtime_ns, stat.st_size)
        if key in self._cover_color_cache:
            self._cover_color_cache.move_to_end(key)
            return self._cover_color_cache[key]

        try:
            # QPixmap уже декодирован для самой обложки — не читаем файл
            # с диска второй раз, только уменьшаем готовый QImage.
            image = pixmap.toImage()
            colors = self._extract_dominant_colors(image)
        except Exception:
            colors = None

        self._cover_color_cache[key] = colors
        while len(self._cover_color_cache) > self.COLOR_CACHE_LIMIT:
            self._cover_color_cache.popitem(last=False)
        return colors

    @classmethod
    def _extract_dominant_colors(cls, image):
        """Извлекает цветовую пару из QImage уменьшением до 1x1 и 2x2.

        ``1x1`` даёт усреднённый доминирующий цвет (запасной вариант и
        база для выравнивания контраста), ``2x2`` — верхнюю и нижнюю
        половины для направленного градиента. Оба масштабирования идут
        через ``Qt.SmoothTransformation`` и стоят доли миллисекунды.
        """
        if image is None or image.isNull():
            return None

        dominant_image = image.scaled(
            1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        if dominant_image.isNull():
            return None
        dominant = dominant_image.pixelColor(0, 0)
        if dominant.alpha() == 0:
            return None

        small = image.scaled(
            2, 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        if small.isNull():
            return dominant, dominant

        top = cls._average_color(
            small.pixelColor(0, 0), small.pixelColor(1, 0)
        )
        bottom = cls._average_color(
            small.pixelColor(0, 1), small.pixelColor(1, 1)
        )
        if top.alpha() == 0:
            top = QColor(dominant)
        if bottom.alpha() == 0:
            bottom = QColor(dominant)

        # У однотонных обложек верх и низ почти совпадают — разводим их
        # по яркости, чтобы градиент не выглядел плоской заливкой.
        distance = (
            abs(top.red() - bottom.red())
            + abs(top.green() - bottom.green())
            + abs(top.blue() - bottom.blue())
        )
        if distance < 36:
            hue, sat, value, _ = dominant.getHsvF()
            hue = max(0.0, min(1.0, hue))
            sat = max(0.0, min(1.0, sat))
            value = max(0.0, min(1.0, value))
            top = QColor.fromHsvF(
                hue, sat, min(1.0, max(value, 0.35) * 1.12)
            )
            bottom = QColor.fromHsvF(hue, sat, max(0.08, value * 0.70))

        return top, bottom

    @staticmethod
    def _average_color(first, second):
        return QColor(
            (first.red() + second.red()) // 2,
            (first.green() + second.green()) // 2,
            (first.blue() + second.blue()) // 2,
        )

    @staticmethod
    def _blend_color(first, second, ratio):
        ratio = max(0.0, min(1.0, ratio))
        return QColor(
            round(first.red() * (1 - ratio) + second.red() * ratio),
            round(first.green() * (1 - ratio) + second.green() * ratio),
            round(first.blue() * (1 - ratio) + second.blue() * ratio),
        )

    def _tone_for_theme(self, color):
        """Приглушает цвет обложки под тему, сохраняя читаемость текста."""
        hue, sat, value, _ = color.getHsvF()
        hue = max(0.0, min(1.0, hue))
        sat = max(0.0, min(1.0, sat))
        value = max(0.0, min(1.0, value))
        if self._dark:
            sat = min(1.0, sat * 1.05)
            value = min(max(value, 0.20), 0.74)
        else:
            sat = min(sat, 0.42)
            value = min(max(value, 0.72), 0.96)
        return QColor.fromHsvF(hue, sat, value)

    def _theme_tint_colors(self):
        """Запасная пара цветов из текущей темы (когда обложки нет)."""
        if self._dark:
            top = QColor(34, 36, 48)
            bottom = QColor(14, 15, 20)
        else:
            top = QColor(255, 255, 255)
            bottom = QColor(234, 238, 247)
        top = self._blend_color(top, self._accent, 0.16 if self._dark else 0.10)
        return top, bottom

    def _apply_tint(self, colors, animate=True):
        if colors is None:
            target_top, target_bottom = self._theme_tint_colors()
        else:
            target_top = self._tone_for_theme(colors[0])
            target_bottom = self._tone_for_theme(colors[1])

        if (
            self._tint_target is not None
            and target_top == self._tint_target[0]
            and target_bottom == self._tint_target[1]
        ):
            return

        if not animate or self._tint_current is None:
            self._tint_anim.stop()
            self._tint_from = (QColor(target_top), QColor(target_bottom))
            self._tint_target = (QColor(target_top), QColor(target_bottom))
            self._tint_current = (QColor(target_top), QColor(target_bottom))
            self.update()
            return

        # Стартуем с текущего (возможно, промежуточного) цвета — быстрое
        # переключение треков не даёт рывка.
        self._tint_from = (
            QColor(self._tint_current[0]),
            QColor(self._tint_current[1]),
        )
        self._tint_target = (QColor(target_top), QColor(target_bottom))
        self._tint_anim.stop()
        self._tint_anim.setStartValue(0.0)
        self._tint_anim.setEndValue(1.0)
        self._tint_anim.start()

    def _on_tint_value_changed(self, value):
        if self._tint_from is None or self._tint_target is None:
            return
        ratio = max(0.0, min(1.0, float(value)))
        self._tint_current = (
            self._blend_color(
                self._tint_from[0], self._tint_target[0], ratio
            ),
            self._blend_color(
                self._tint_from[1], self._tint_target[1], ratio
            ),
        )
        self.update()

    def _on_tint_animation_finished(self):
        if self._tint_target is None:
            return
        self._tint_current = (
            QColor(self._tint_target[0]),
            QColor(self._tint_target[1]),
        )
        self.update()

    def _update_play_icon(self):
        lang = self._lang()
        icon_name = "pause.svg" if self._playing else "play.svg"
        self.play_button.setIcon(self.icons.icon(icon_name, color="white"))
        self.play_button.setToolTip(
            tr("Pause", lang) if self._playing else tr("Play", lang)
        )

    # ------------------------------------------------------------------
    #  Тема / стеклянный фон
    # ------------------------------------------------------------------
    def apply_theme(self):
        self._apply_theme_colors()
        self._update_play_icon()
        self.update()

    def _apply_theme_colors(self):
        theme = str(self.settings.value("theme", "dark"))
        self._dark = is_dark_theme(theme)
        self._accent = QColor(theme_accent(theme))
        self._foreground = QColor("#ffffff" if self._dark else "#20242e")
        muted = (
            "rgba(255, 255, 255, 0.62)"
            if self._dark
            else "rgba(32, 36, 46, 0.60)"
        )
        hover = (
            "rgba(255, 255, 255, 0.10)"
            if self._dark
            else "rgba(0, 0, 0, 0.07)"
        )
        foreground = self._foreground.name()
        accent = self._accent.name()
        accent_hover = self._accent.lighter(115).name()

        self.setStyleSheet(f"""
            QWidget#miniPlayer {{
                background: transparent;
            }}
            QWidget#miniPlayer QLabel {{
                background: transparent;
                color: {foreground};
            }}
            QWidget#miniPlayer QLabel#miniArtist {{
                color: {muted};
                font-size: 12px;
            }}
            QWidget#miniPlayer QLabel#miniTime {{
                color: {muted};
                font-size: 11px;
            }}
            QWidget#miniPlayer QPushButton {{
                background: transparent;
                border: none;
                border-radius: 9px;
            }}
            QWidget#miniPlayer QPushButton:hover {{
                background-color: {hover};
            }}
            QWidget#miniPlayer QPushButton#miniPlayButton {{
                background-color: {accent};
                border-radius: 22px;
            }}
            QWidget#miniPlayer QPushButton#miniPlayButton:hover {{
                background-color: {accent_hover};
            }}
            QWidget#miniPlayer QPushButton#miniCloseButton:hover {{
                background-color: rgba(232, 17, 35, 0.85);
            }}
            QWidget#miniPlayer QSlider::groove:horizontal {{
                height: 3px;
                border-radius: 2px;
            }}
            QWidget#miniPlayer QSlider::handle:horizontal {{
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }}
        """)

        self.prev_button.setIcon(
            self.icons.icon("prev.svg", color=foreground)
        )
        self.next_button.setIcon(
            self.icons.icon("next.svg", color=foreground)
        )
        self.expand_button.setIcon(
            self.icons.icon("expand.svg", color=foreground)
        )
        self.close_button.setIcon(
            self.icons.icon("cancel.svg", color=foreground)
        )

        # Смена темы меняет тон-маппинг цветов обложки — пересчитываем
        # градиент мгновенно, без анимации.
        self._apply_tint(self._cover_colors_raw, animate=False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 20, 20)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self._dark:
            gradient.setColorAt(0.0, QColor(34, 36, 48, 238))
            gradient.setColorAt(1.0, QColor(14, 15, 20, 244))
        else:
            gradient.setColorAt(0.0, QColor(255, 255, 255, 240))
            gradient.setColorAt(1.0, QColor(234, 238, 247, 244))
        painter.fillPath(path, QBrush(gradient))

        # Полупрозрачный цветной слой поверх стеклянной базы: альфа
        # 150–185 сохраняет эффект стекла и лишь мягко тонирует окно.
        if self._tint_current is not None:
            tint = QLinearGradient(rect.topLeft(), rect.bottomRight())
            tint_top = QColor(self._tint_current[0])
            tint_bottom = QColor(self._tint_current[1])
            tint_top.setAlpha(185 if self._dark else 160)
            tint_bottom.setAlpha(165 if self._dark else 150)
            tint.setColorAt(0.0, tint_top)
            tint.setColorAt(1.0, tint_bottom)
            painter.fillPath(path, QBrush(tint))

        glow_color = (
            QColor(self._tint_current[0])
            if self._cover_colors_raw is not None
            else QColor(self._accent)
        )
        glow_color.setAlpha(46 if self._dark else 32)
        glow = QRadialGradient(
            rect.left() + 46,
            rect.top() + 18,
            max(1.0, rect.width() * 0.85),
        )
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(
            1.0,
            QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 0),
        )
        painter.fillPath(path, QBrush(glow))

        sheen = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.55)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 30 if self._dark else 130))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, QBrush(sheen))

        border = (
            QColor(255, 255, 255, 62)
            if self._dark
            else QColor(0, 0, 0, 38)
        )
        painter.setPen(QPen(border, 1.2))
        painter.drawPath(path)
        painter.end()

    # ------------------------------------------------------------------
    #  Кнопки развернуть / закрыть
    # ------------------------------------------------------------------
    def _request_expand(self):
        self.hide()
        self.expand_requested.emit()

    def _request_close(self):
        self.hide()
        self.closed.emit()

    # ------------------------------------------------------------------
    #  Перетаскивание безрамочного окна
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPos() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._request_expand()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    #  Позиция окна
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned:
            self._positioned = True
            self._restore_position()

    def hideEvent(self, event):
        self._save_position()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._save_position()
        self.hide()
        self.closed.emit()
        event.ignore()

    def _save_position(self):
        pos = self.pos()
        self.settings.setValue(
            "mini_player_pos", f"{pos.x()},{pos.y()}"
        )

    def _restore_position(self):
        raw = self.settings.value("mini_player_pos")
        pos = self._parse_position(raw)
        if pos is not None and self._position_on_screen(pos):
            self.move(pos)
            return
        self._position_near_parent()

    @staticmethod
    def _parse_position(value):
        if isinstance(value, QPoint):
            return value
        if isinstance(value, str) and "," in value:
            try:
                x, y = value.split(",", 1)
                return QPoint(int(x), int(y))
            except (TypeError, ValueError):
                return None
        return None

    def _position_on_screen(self, pos):
        candidate = QRect(pos, self.size())
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(candidate):
                return True
        return False

    def _position_near_parent(self):
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            reference = parent.frameGeometry()
        else:
            screen = QApplication.primaryScreen()
            reference = (
                screen.availableGeometry()
                if screen is not None
                else QRect(0, 0, 1280, 800)
            )

        x = reference.right() - self.width() - 24
        y = reference.bottom() - self.height() - 24

        screen = QApplication.screenAt(QPoint(x, y))
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = max(
                available.left() + 8,
                min(x, available.right() - self.width() - 8),
            )
            y = max(
                available.top() + 8,
                min(y, available.bottom() - self.height() - 8),
            )
        self.move(x, y)
