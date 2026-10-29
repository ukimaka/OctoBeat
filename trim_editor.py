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

"""Интерактивный редактор обрезки аудио.

Модуль намеренно не импортирует pydub/numpy на уровне модуля: это
необязательные зависимости, и при их отсутствии плеер должен продолжать
работать. Тяжёлое чтение волны выполняется в отдельном QThread.
"""

import os
from pathlib import Path

from PyQt5.QtCore import (
    QLineF, QObject, QPointF, QRectF, QThread, QTimer, Qt, QUrl, pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton,
    QSizeGrip, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

import workers
from dialogs import _FramelessDialog, _dialog_lang, colored_icon
from translations import tr


SNAP_MS = 500                 # шаг снапа маркеров
MIN_SELECTION_MS = 500        # минимальная длина выделения
WAVEFORM_BUCKETS = 4000       # количество пиков, достаточное для любого экрана

# QThread нельзя удалять, пока он работает. Если диалог закрыли во время
# загрузки волны, поток живёт до завершения; этот словарь не даёт Python
# собрать его wrapper раньше времени.
_WAVE_JOBS = {}


def _format_time(ms):
    """Форматирует миллисекунды как m:ss или h:mm:ss."""
    total_seconds = max(0, int(ms)) // 1000
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class WaveformLoader(QObject):
    """Читает аудио через pydub и готовит пики для отрисовки."""

    ready = pyqtSignal(object, int)   # peaks (list[float]), duration_ms
    error = pyqtSignal(str)

    def __init__(self, file_path, buckets=WAVEFORM_BUCKETS):
        super().__init__()
        self.file_path = file_path
        self.buckets = max(1, int(buckets))

    def _interrupted(self):
        thread = QThread.currentThread()
        return thread is not None and thread.isInterruptionRequested()

    def run(self):
        # Ленивый импорт: pydub/numpy — необязательные зависимости.
        try:
            import numpy as np
            from pydub import AudioSegment
        except ImportError as e:
            self.error.emit(
                f"Missing dependency: {e}. "
                "Install it with: pip install pydub numpy"
            )
            return

        try:
            audio = AudioSegment.from_file(self.file_path)
            if self._interrupted():
                return

            duration_ms = len(audio)
            if duration_ms <= 0:
                self.error.emit("Audio file is empty.")
                return

            # Для волны достаточно моно-сигнала.
            audio = audio.set_channels(1)
            raw = audio.get_array_of_samples()
            if len(raw) == 0:
                self.error.emit("Audio file is empty.")
                return

            sample_width = audio.sample_width
            dtype = {
                1: np.int8,
                2: np.int16,
                4: np.int32,
            }.get(sample_width, np.int32)
            # pydub хранит 24-битные сэмплы в array('i'), т.е. в int32.
            samples = np.frombuffer(raw, dtype=dtype)
            total_samples = samples.size
            if total_samples == 0:
                self.error.emit("Audio file is empty.")
                return

            bucket_count = min(self.buckets, total_samples)
            chunk = max(1, total_samples // bucket_count)
            max_amp = float(2 ** (8 * sample_width - 1)) or 1.0

            # Считаем пики блоками, чтобы не держать в памяти второй
            # float-массив размером со весь трек.
            peaks = np.empty(bucket_count, dtype=np.float32)
            for i in range(bucket_count):
                if self._interrupted():
                    return
                start = i * chunk
                if start >= total_samples:
                    peaks = peaks[:i]
                    break
                end = (
                    total_samples
                    if i == bucket_count - 1
                    else min(total_samples, start + chunk)
                )
                block = samples[start:end]
                # int32 защищает от переполнения abs(-32768).
                peaks[i] = float(np.abs(block.astype(np.int32)).max()) / max_amp

            if peaks.size == 0:
                self.error.emit("Audio file is empty.")
                return

            peak_max = float(peaks.max())
            if peak_max > 0:
                peaks /= peak_max

            self.ready.emit(peaks.astype(float).tolist(), int(duration_ms))
        except Exception as e:
            if not self._interrupted():
                self.error.emit(str(e))


class WaveformWidget(QWidget):
    """Волна с маркерами начала/конца, таймлайном и playhead."""

    seekRequested = pyqtSignal(int)          # position_ms
    markersChanged = pyqtSignal(int, int)    # start_ms, end_ms

    MARGIN_X = 10
    RULER_H = 20
    BOTTOM_PAD = 18
    MARKER_HIT_PX = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = []
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._position_ms = 0
        self._drag_marker = None
        self._placeholder = ""

        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    # ------------------------------------------------------------------
    #  Публичное API
    # ------------------------------------------------------------------
    def set_waveform(self, peaks, duration_ms):
        self._peaks = list(peaks or [])
        self._duration_ms = max(0, int(duration_ms))
        self._start_ms = 0
        self._end_ms = self._duration_ms
        self._position_ms = 0
        self._placeholder = ""
        self.update()

    def set_placeholder(self, text):
        self._placeholder = text or ""
        self.update()

    def set_position(self, position_ms):
        position_ms = max(0, min(int(position_ms), self._duration_ms))
        if position_ms != self._position_ms:
            self._position_ms = position_ms
            self.update()

    def set_selection(self, start_ms, end_ms):
        if self._duration_ms <= 0:
            return
        start_ms = max(0, min(int(start_ms), self._duration_ms))
        end_ms = max(start_ms, min(int(end_ms), self._duration_ms))
        if (start_ms, end_ms) != (self._start_ms, self._end_ms):
            self._start_ms, self._end_ms = start_ms, end_ms
            self.update()
            self.markersChanged.emit(self._start_ms, self._end_ms)

    def selection(self):
        return self._start_ms, self._end_ms

    def start_ms(self):
        return self._start_ms

    def end_ms(self):
        return self._end_ms

    def duration_ms(self):
        return self._duration_ms

    # ------------------------------------------------------------------
    #  Геометрия
    # ------------------------------------------------------------------
    def _outer_rect(self):
        return QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    def _plot_rect(self):
        outer = self._outer_rect()
        top = outer.top() + self.RULER_H + 6
        height = max(1.0, outer.height() - self.RULER_H - 6 - self.BOTTOM_PAD)
        width = max(1.0, outer.width() - 2 * self.MARGIN_X)
        return QRectF(outer.left() + self.MARGIN_X, top, width, height)

    def _x_at_ms(self, ms):
        plot = self._plot_rect()
        if self._duration_ms <= 0:
            return plot.left()
        ratio = max(0.0, min(1.0, float(ms) / self._duration_ms))
        return plot.left() + ratio * plot.width()

    def _ms_at_x(self, x):
        plot = self._plot_rect()
        if plot.width() <= 0 or self._duration_ms <= 0:
            return 0
        ratio = (x - plot.left()) / plot.width()
        return int(round(max(0.0, min(1.0, ratio)) * self._duration_ms))

    def _snap(self, ms):
        return int(round(ms / SNAP_MS) * SNAP_MS)

    def _min_gap(self):
        return min(MIN_SELECTION_MS, self._duration_ms)

    def _marker_at(self, x):
        if self._duration_ms <= 0:
            return None
        start_x = self._x_at_ms(self._start_ms)
        end_x = self._x_at_ms(self._end_ms)
        d_start = abs(x - start_x)
        d_end = abs(x - end_x)
        if min(d_start, d_end) > self.MARKER_HIT_PX:
            return None
        return "start" if d_start <= d_end else "end"

    # ------------------------------------------------------------------
    #  Отрисовка
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer = self._outer_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#181818"))
        painter.drawRoundedRect(outer, 8, 8)

        plot = self._plot_rect()
        if plot.width() <= 0 or plot.height() <= 0:
            return

        self._draw_ruler(painter, outer, plot)

        if not self._peaks or self._duration_ms <= 0:
            painter.setPen(QColor("#777777"))
            font = QFont(self.font())
            font.setPointSizeF(11.0)
            painter.setFont(font)
            painter.drawText(plot, Qt.AlignCenter, self._placeholder)
        else:
            self._draw_waveform(painter, plot)
            self._draw_selection(painter, plot)

        self._draw_markers(painter, outer, plot)
        self._draw_playhead(painter, plot)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#2e2e2e"), 1))
        painter.drawRoundedRect(outer, 8, 8)

    def _draw_ruler(self, painter, outer, plot):
        if self._duration_ms <= 0:
            return

        interval = self._tick_interval(plot.width())
        tick_font = QFont(self.font())
        tick_font.setPointSizeF(8.0)

        t = 0
        while t <= self._duration_ms:
            x = self._x_at_ms(t)
            if t > 0:
                painter.setPen(QPen(QColor("#242424"), 1, Qt.DotLine))
                painter.drawLine(QLineF(x, plot.top(), x, plot.bottom()))
            painter.setPen(QColor("#777777"))
            painter.setFont(tick_font)
            painter.drawText(
                QRectF(x - 30, outer.top() + 2, 60, 16),
                Qt.AlignCenter,
                _format_time(t),
            )
            t += interval

        painter.setPen(QPen(QColor("#2e2e2e"), 1))
        painter.drawLine(
            QLineF(plot.left(), plot.top() - 4, plot.right(), plot.top() - 4)
        )

    def _tick_interval(self, width):
        candidates = (
            500, 1000, 2000, 5000, 10000, 15000, 30000, 60000,
            120000, 300000, 600000, 900000, 1800000, 3600000,
        )
        for interval in candidates:
            if interval / self._duration_ms * width >= 60:
                return interval
        return candidates[-1]

    def _draw_waveform(self, painter, plot):
        peaks = self._peaks
        count = len(peaks)
        if count == 0:
            return

        width = max(1, int(plot.width()))
        center = plot.center().y()
        max_half = plot.height() * 0.46

        painter.setPen(QPen(QColor("#7d7de6"), 1.0))
        for px in range(width):
            i0 = int(px * count / width)
            i1 = max(i0 + 1, int((px + 1) * count / width))
            if i0 >= count:
                break
            amplitude = max(peaks[i0:min(i1, count)])
            if amplitude <= 0:
                continue
            half = max(1.0, float(amplitude) * max_half)
            x = plot.left() + px + 0.5
            painter.drawLine(QLineF(x, center - half, x, center + half))

    def _draw_selection(self, painter, plot):
        start_x = self._x_at_ms(self._start_ms)
        end_x = self._x_at_ms(self._end_ms)

        painter.setPen(Qt.NoPen)
        # Затемняем всё, что не попадёт в результат.
        painter.setBrush(QColor(18, 18, 18, 175))
        if start_x > plot.left():
            painter.drawRect(
                QRectF(plot.left(), plot.top(), start_x - plot.left(),
                       plot.height())
            )
        if end_x < plot.right():
            painter.drawRect(
                QRectF(end_x, plot.top(), plot.right() - end_x, plot.height())
            )

        # Лёгкая подсветка выбранного фрагмента.
        painter.setBrush(QColor(81, 81, 171, 45))
        painter.drawRect(
            QRectF(start_x, plot.top(), max(0.0, end_x - start_x),
                   plot.height())
        )

    def _draw_markers(self, painter, outer, plot):
        if self._duration_ms <= 0:
            return
        self._draw_marker(
            painter, outer, plot, self._start_ms, QColor("#1DB954"), "S"
        )
        self._draw_marker(
            painter, outer, plot, self._end_ms, QColor("#e05a4a"), "E"
        )

    def _draw_marker(self, painter, outer, plot, ms, color, label):
        x = self._x_at_ms(ms)
        painter.setPen(QPen(color, 2))
        painter.drawLine(QLineF(x, plot.top(), x, plot.bottom()))

        handle_w = 26.0
        handle_h = 16.0
        hx = max(outer.left() + 2, min(x - handle_w / 2,
                                       outer.right() - handle_w - 2))
        handle = QRectF(hx, plot.top() + 2, handle_w, handle_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(handle, 4, 4)

        painter.setPen(QColor("#ffffff"))
        handle_font = QFont(self.font())
        handle_font.setPointSizeF(8.0)
        handle_font.setBold(True)
        painter.setFont(handle_font)
        painter.drawText(handle, Qt.AlignCenter, label)

        painter.setPen(color)
        time_font = QFont(self.font())
        time_font.setPointSizeF(8.0)
        painter.setFont(time_font)
        painter.drawText(
            QRectF(hx - 20, plot.bottom() + 2, handle_w + 40, 14),
            Qt.AlignCenter,
            _format_time(ms),
        )

    def _draw_playhead(self, painter, plot):
        if self._position_ms <= 0:
            return
        x = self._x_at_ms(self._position_ms)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        painter.drawLine(QLineF(x, plot.top(), x, plot.bottom()))

        path = QPainterPath()
        path.moveTo(x - 5, plot.top())
        path.lineTo(x + 5, plot.top())
        path.lineTo(x, plot.top() + 7)
        path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(path)

    # ------------------------------------------------------------------
    #  Мышь
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self._duration_ms <= 0:
            return
        x = event.pos().x()

        if event.button() == Qt.LeftButton:
            marker = self._marker_at(x)
            if marker is not None:
                self._drag_marker = marker
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.seekRequested.emit(self._ms_at_x(x))
            event.accept()
            return

        if event.button() == Qt.RightButton:
            self._set_nearest_marker(x)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._duration_ms <= 0:
            return
        x = event.pos().x()

        if self._drag_marker is not None:
            self._move_marker(self._drag_marker, x)
            event.accept()
            return

        marker = self._marker_at(x)
        self.setCursor(
            Qt.SizeHorCursor if marker is not None else Qt.PointingHandCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_marker is not None and event.button() == Qt.LeftButton:
            self._drag_marker = None
            self.setCursor(Qt.PointingHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._drag_marker is None:
            self.setCursor(Qt.PointingHandCursor)
        super().leaveEvent(event)

    def _set_nearest_marker(self, x):
        ms = self._ms_at_x(x)
        if abs(ms - self._start_ms) <= abs(ms - self._end_ms):
            self._move_marker("start", x)
        else:
            self._move_marker("end", x)

    def _move_marker(self, marker, x):
        ms = self._snap(self._ms_at_x(x))
        gap = self._min_gap()

        if marker == "start":
            new_start = max(0, min(ms, self._end_ms - gap))
            if new_start == self._start_ms:
                return
            self._start_ms = new_start
        else:
            new_end = max(self._start_ms + gap, min(ms, self._duration_ms))
            if new_end == self._end_ms:
                return
            self._end_ms = new_end

        self.update()
        self.markersChanged.emit(self._start_ms, self._end_ms)


class AudioTrimDialog(_FramelessDialog):
    """Диалог визуальной обрезки: волна, маркеры и мини-плеер."""

    def __init__(self, parent=None, file_path="", track_title=""):
        lang = _dialog_lang()
        super().__init__(parent, tr("Trim audio", lang))

        self._lang = lang
        self._file_path = file_path
        self._duration_ms = 0
        self._media_duration_ms = 0
        self._wave_loaded = False
        self._busy = False
        self._closing = False
        self._trimmed_duration = None
        self._pending_warning = None
        self._wave_thread = None
        self._wave_loader = None
        self._trim_thread = None
        self._trim_worker = None
        self._progress = None

        self.setMinimumSize(780, 470)
        self.resize(900, 520)

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 4, 20, 8)
        col.setSpacing(8)

        title = QLabel(track_title or Path(file_path).stem)
        title.setObjectName("trimTitle")
        title.setWordWrap(True)
        col.addWidget(title)

        hint = QLabel(
            tr(
                "Drag the markers to set the start and end. "
                "Click to seek, right-click to move the nearest marker.",
                lang,
            )
        )
        hint.setObjectName("trimHint")
        hint.setWordWrap(True)
        col.addWidget(hint)

        self.waveform = WaveformWidget()
        self.waveform.set_placeholder(tr("Loading waveform...", lang))
        col.addWidget(self.waveform, 1)

        info = QHBoxLayout()
        info.setSpacing(18)
        self.position_label = QLabel()
        self.start_label = QLabel()
        self.end_label = QLabel()
        self.selection_label = QLabel()
        for label in (
            self.position_label, self.start_label,
            self.end_label, self.selection_label,
        ):
            label.setObjectName("trimTime")
            info.addWidget(label)
        info.addStretch(1)
        col.addLayout(info)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.play_button = QPushButton(tr("Play", lang))
        self.play_button.setObjectName("trimPlay")
        self.play_button.setFlat(True)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setIcon(colored_icon("play.svg", "#ffffff"))
        self.play_button.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_button)

        # CHANGED: регулятор громкости
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(6)
        volume_icon = QLabel()
        volume_icon.setPixmap(colored_icon("volume-high.svg", "#ffffff").pixmap(18, 18))
        volume_layout.addWidget(volume_icon)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setCursor(Qt.PointingHandCursor)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        controls.addLayout(volume_layout)

        controls.addStretch(1)
        col.addLayout(controls)

        self.body.addWidget(content)

        self.cancel_button = self._make_button(
            "cdCancel", tr("Cancel", lang), "cancel.svg"
        )
        self.cancel_button.clicked.connect(self.reject)

        self.save_button = self._make_button(
            "cdConfirm", tr("Save", lang), "save.svg"
        )
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)

        self._add_footer([self.cancel_button, self.save_button])
        self.setStyleSheet(self.styleSheet() + _TRIM_DIALOG_QSS)

        self.waveform.seekRequested.connect(self._seek_to)
        self.waveform.markersChanged.connect(self._on_markers_changed)

        self.player = QMediaPlayer(self)
        self.player.setVolume(70)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
        self.player.positionChanged.connect(self._on_player_position)
        self.player.durationChanged.connect(self._on_player_duration)
        self.player.stateChanged.connect(self._on_player_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self._end_timer = QTimer(self)
        self._end_timer.setInterval(50)
        self._end_timer.timeout.connect(self._enforce_preview_end)

        self._update_labels()
        self._start_waveform_loading()

    # ------------------------------------------------------------------
    #  Загрузка волны
    # ------------------------------------------------------------------
    def _start_waveform_loading(self):
        self._wave_thread = QThread()
        self._wave_loader = WaveformLoader(self._file_path)
        self._wave_loader.moveToThread(self._wave_thread)
        _WAVE_JOBS[self._wave_thread] = self._wave_loader

        self._wave_thread.started.connect(self._wave_loader.run)
        self._wave_loader.ready.connect(self._on_wave_ready)
        self._wave_loader.error.connect(self._on_wave_error)
        self._wave_loader.ready.connect(self._wave_thread.quit)
        self._wave_loader.error.connect(self._wave_thread.quit)
        self._wave_thread.finished.connect(self._on_wave_thread_finished)
        self._wave_thread.finished.connect(self._wave_loader.deleteLater)
        self._wave_thread.finished.connect(self._wave_thread.deleteLater)
        self._wave_thread.finished.connect(
            lambda t=self._wave_thread: _WAVE_JOBS.pop(t, None)
        )
        self._wave_thread.start()

    def _on_wave_ready(self, peaks, duration_ms):
        if self._closing:
            return
        self._wave_loaded = True
        self._duration_ms = int(duration_ms)
        self.waveform.set_waveform(peaks, duration_ms)
        self.save_button.setEnabled(True)
        self.player.setPosition(0)
        self._update_labels()

    def _on_wave_error(self, message):
        if self._closing:
            return
        self.waveform.set_placeholder(tr("Waveform unavailable", self._lang))
        self.save_button.setEnabled(False)
        QMessageBox.warning(
            self,
            tr("Trim audio", self._lang),
            tr("Could not load waveform:\n{e}", self._lang).format(e=message),
        )

    def _on_wave_thread_finished(self):
        if self.sender() is self._wave_thread:
            self._wave_thread = None
            self._wave_loader = None

    def _stop_waveform_loading(self):
        thread = self._wave_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.quit()

    # ------------------------------------------------------------------
    #  Плеер
    # ------------------------------------------------------------------
    def _toggle_play(self):
        if self._busy or not self._wave_loaded:
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
            return

        start, end = self.waveform.selection()
        if end <= start:
            return
        position = self.player.position()
        if position < start or position >= end:
            self.player.setPosition(start)
            self.waveform.set_position(start)
        self.player.play()

    def _seek_to(self, position_ms):
        if self._busy or not self._wave_loaded:
            return
        position_ms = max(0, min(int(position_ms), self._duration_ms))
        self.player.setPosition(position_ms)
        self.waveform.set_position(position_ms)
        self._update_labels()

    def _on_markers_changed(self, start, end):
        self._update_labels()
        if self.player.state() != QMediaPlayer.PlayingState:
            return
        position = self.player.position()
        if position < start:
            self.player.setPosition(start)
        elif position >= end:
            self._pause_at_end()

    def _on_player_position(self, position):
        self.waveform.set_position(position)
        self._update_labels()
        if (
            self.player.state() == QMediaPlayer.PlayingState
            and self._wave_loaded
            and position >= self.waveform.end_ms()
        ):
            self._pause_at_end()

    def _on_player_duration(self, duration):
        self._media_duration_ms = max(0, int(duration))
        self._update_labels()

    def _on_player_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self._end_timer.start()
            self.play_button.setText(tr("Pause", self._lang))
            self.play_button.setIcon(colored_icon("pause.svg", "#ffffff"))
        else:
            self._end_timer.stop()
            self.play_button.setText(tr("Play", self._lang))
            self.play_button.setIcon(colored_icon("play.svg", "#ffffff"))

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.player.pause()
            if self._wave_loaded:
                end = self.waveform.end_ms()
                self.player.setPosition(end)
                self.waveform.set_position(end)

    # CHANGED: обработчик изменения громкости
    def _on_volume_changed(self, value):
        self.player.setVolume(value)

    def _enforce_preview_end(self):
        if self.player.state() != QMediaPlayer.PlayingState:
            self._end_timer.stop()
            return
        if self._wave_loaded and self.player.position() >= self.waveform.end_ms():
            self._pause_at_end()

    def _pause_at_end(self):
        end = self.waveform.end_ms()
        self.player.pause()
        self.player.setPosition(end)
        self.waveform.set_position(end)
        self._update_labels()

    def _update_labels(self):
        total = self._duration_ms or self._media_duration_ms
        position = max(0, self.player.position())
        self.position_label.setText(
            f"{_format_time(position)} / {_format_time(total)}"
        )

        start, end = self.waveform.selection()
        self.start_label.setText(
            f"{tr('Start', self._lang)}: {_format_time(start)}"
        )
        self.end_label.setText(
            f"{tr('End', self._lang)}: {_format_time(end)}"
        )
        self.selection_label.setText(
            f"{tr('Selection', self._lang)}: {_format_time(end - start)}"
        )

    # ------------------------------------------------------------------
    #  Сохранение
    # ------------------------------------------------------------------
    def _save(self):
        if self._busy or not self._wave_loaded:
            return

        start, end = self.waveform.selection()
        if end - start < 100:
            QMessageBox.warning(
                self,
                tr("Trim audio", self._lang),
                tr("The selection is too short.", self._lang),
            )
            return

        self.player.pause()
        self._end_timer.stop()
        self._busy = True
        self._set_controls_enabled(False)

        self._progress = QProgressDialog(
            tr("Trimming audio...", self._lang),
            tr("Cancel", self._lang),
            0, 100, self,
        )
        self._progress.setWindowTitle(tr("Trim audio", self._lang))
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(0)
        self._progress.show()

        thread = QThread()
        worker = workers.TrimWorker(self._file_path, start, end)
        worker.moveToThread(thread)
        self._trim_thread = thread
        self._trim_worker = worker

        worker.progress.connect(self._progress.setValue)
        worker.finished.connect(self._on_trim_finished)
        worker.error.connect(self._on_trim_error)
        worker.cancelled.connect(self._on_trim_cancelled)
        worker.warning.connect(self._on_trim_warning)

        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_trim_thread_finished)

        self._progress.canceled.connect(thread.requestInterruption)
        thread.started.connect(worker.run)
        thread.start()

    def _set_controls_enabled(self, enabled):
        self.play_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled and self._wave_loaded)
        self.cancel_button.setEnabled(enabled)
        self.waveform.setEnabled(enabled)

    def _on_trim_warning(self, message):
        self._pending_warning = tr(message, self._lang)

    def _on_trim_finished(self, duration):
        self._trimmed_duration = float(duration)
        if self._progress is not None:
            self._progress.setValue(100)
            self._progress.close()
        self._busy = False
        self._set_controls_enabled(True)
        self._close_player()

        if self._pending_warning:
            QMessageBox.warning(
                self, tr("Trim audio", self._lang), self._pending_warning
            )
        self.accept()

    def _on_trim_error(self, message):
        if self._progress is not None:
            self._progress.close()
        self._busy = False
        self._set_controls_enabled(True)
        QMessageBox.warning(
            self,
            tr("Trim audio", self._lang),
            tr("Could not trim audio:\n{e}", self._lang).format(e=message),
        )

    def _on_trim_cancelled(self):
        if self._progress is not None:
            self._progress.close()
        self._busy = False
        self._set_controls_enabled(True)

    def _on_trim_thread_finished(self):
        if self.sender() is self._trim_thread:
            self._trim_thread = None
            self._trim_worker = None
            self._progress = None

    # ------------------------------------------------------------------
    #  Завершение
    # ------------------------------------------------------------------
    def _close_player(self):
        self._end_timer.stop()
        self.player.stop()
        self.player.setMedia(QMediaContent())

    def done(self, result):
        if self._busy and result == QDialog.Rejected:
            return
        self._closing = True
        self._stop_waveform_loading()
        self._close_player()
        super().done(result)

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        self._closing = True
        self._stop_waveform_loading()
        self._close_player()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not self._busy:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def trimmed_duration(self):
        """Длительность результата в секундах или None, если не сохраняли."""
        return self._trimmed_duration


_TRIM_DIALOG_QSS = """
QLabel#trimTitle {
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
}
QLabel#trimHint {
    color: #8a8a8a;
    font-size: 11px;
}
QLabel#trimTime {
    color: #dddddd;
    font-size: 12px;
}
QPushButton#trimPlay {
    background: #2a2a2a;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: bold;
}
QPushButton#trimPlay:hover {
    background: #3a3a3a;
}
QPushButton#trimPlay:disabled {
    color: #777777;
    background: #222222;
}
QSlider::groove:horizontal {
    border: none;
    background: #2e2e2e;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #5151ab;
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #6161c4;
}
"""
