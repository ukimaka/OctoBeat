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

"""Диалог визуальной обрезки аудио."""

from pathlib import Path

from PyQt5.QtCore import QThread, QTimer, Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressDialog,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import workers
from dialogs import (
    CustomConfirmDialog,
    _dialog_lang,
    _FramelessDialog,
    colored_icon,
)
from trim_waveform import WaveformLoader, WaveformWidget, _format_time
from translations import tr
from vlc_backend import PlaybackState, VlcAudioPlayer

# QThread нельзя удалять, пока он работает. Если диалог закрыли во время
# загрузки волны, поток живёт до завершения; этот словарь не даёт Python
# собрать его wrapper раньше времени.
_WAVE_JOBS = {}


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

        self.player = VlcAudioPlayer(self)
        self.player.set_volume(70)
        self.player.set_media(file_path)
        self.player.positionChanged.connect(self._on_player_position)
        self.player.durationChanged.connect(self._on_player_duration)
        self.player.stateChanged.connect(self._on_player_state)
        self.player.endReached.connect(self._on_player_end_reached)

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
        self.player.set_position(0)
        self._update_labels()

    def _dependency_error(self, message):
        """Переводит ошибки отсутствующих pydub/numpy на текущий язык."""
        text = str(message)
        if "pydub" not in text and "numpy" not in text:
            return text
        parts = []
        if "pydub" in text:
            parts.append(tr(
                "pydub is not installed. Install it with: pip install pydub",
                self._lang(),
            ))
        if "numpy" in text:
            parts.append(tr(
                "numpy is not installed. Install it with: pip install numpy",
                self._lang(),
            ))
        return "\n".join(parts)

    def _on_wave_error(self, message):
        if self._closing:
            return
        self.waveform.set_placeholder(tr("Waveform unavailable", self._lang))
        self.save_button.setEnabled(False)
        CustomConfirmDialog.information(
            self,
            tr("Trim audio", self._lang),
            tr("Could not load waveform:\n{e}", self._lang).format(
                e=self._dependency_error(message)
            ),
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
            # Не даём приложению уничтожить ещё работающий QThread.
            thread.wait(2000)

    # ------------------------------------------------------------------
    #  Плеер
    # ------------------------------------------------------------------
    def _toggle_play(self):
        if self._busy or not self._wave_loaded:
            return
        if self.player.state() == PlaybackState.PLAYING:
            self.player.pause()
            return

        start, end = self.waveform.selection()
        if end <= start:
            return
        position = self.player.position()
        if position < start or position >= end:
            self.player.set_position(start)
            self.waveform.set_position(start)
        self.player.play()

    def _seek_to(self, position_ms):
        if self._busy or not self._wave_loaded:
            return
        position_ms = max(0, min(int(position_ms), self._duration_ms))
        self.player.set_position(position_ms)
        self.waveform.set_position(position_ms)
        self._update_labels()

    def _on_markers_changed(self, start, end):
        self._update_labels()
        if self.player.state() != PlaybackState.PLAYING:
            return
        position = self.player.position()
        if position < start:
            self.player.set_position(start)
        elif position >= end:
            self._pause_at_end()

    def _on_player_position(self, position):
        self.waveform.set_position(position)
        self._update_labels()
        if (
            self.player.state() == PlaybackState.PLAYING
            and self._wave_loaded
            and position >= self.waveform.end_ms()
        ):
            self._pause_at_end()

    def _on_player_duration(self, duration):
        self._media_duration_ms = max(0, int(duration))
        self._update_labels()

    def _on_player_state(self, state):
        if state == PlaybackState.PLAYING:
            self._end_timer.start()
            self.play_button.setText(tr("Pause", self._lang))
            self.play_button.setIcon(colored_icon("pause.svg", "#ffffff"))
        else:
            self._end_timer.stop()
            self.play_button.setText(tr("Play", self._lang))
            self.play_button.setIcon(colored_icon("play.svg", "#ffffff"))

    def _on_player_end_reached(self):
        self._end_timer.stop()
        if self._wave_loaded:
            end = self.waveform.end_ms()
            self.player.set_position(end)
            self.waveform.set_position(end)
            self._update_labels()

    # CHANGED: обработчик изменения громкости
    def _on_volume_changed(self, value):
        self.player.set_volume(value)

    def _enforce_preview_end(self):
        if self.player.state() != PlaybackState.PLAYING:
            self._end_timer.stop()
            return
        if self._wave_loaded and self.player.position() >= self.waveform.end_ms():
            self._pause_at_end()

    def _pause_at_end(self):
        end = self.waveform.end_ms()
        self.player.pause()
        self.player.set_position(end)
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
            CustomConfirmDialog.information(
                self,
                tr("Trim audio", self._lang),
                tr("The selection is too short.", self._lang),
            )
            return

        self.player.pause()
        self._release_player()
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
            CustomConfirmDialog.information(
                self, tr("Trim audio", self._lang), self._pending_warning
            )
        self.accept()

    def _on_trim_error(self, message):
        if self._progress is not None:
            self._progress.close()
        self._busy = False
        self._release_player()
        self._restore_player()
        self._set_controls_enabled(True)
        CustomConfirmDialog.information(
            self,
            tr("Trim audio", self._lang),
            tr("Could not trim audio:\n{e}", self._lang).format(
                e=self._dependency_error(message)
            ),
        )

    def _on_trim_cancelled(self):
        if self._progress is not None:
            self._progress.close()
        self._busy = False
        self._restore_player()
        self._set_controls_enabled(True)

    def _on_trim_thread_finished(self):
        if self.sender() is self._trim_thread:
            self._trim_thread = None
            self._trim_worker = None
            self._progress = None

    # ------------------------------------------------------------------
    #  Завершение
    # ------------------------------------------------------------------
    def _release_player(self):
        """Отпускает файл, чтобы Windows разрешил его заменить."""
        self.player.release_media()

    def _restore_player(self):
        """Возвращает файл в плеер после неудачной/отменённой обрезки."""
        self.player.set_media(self._file_path)

    def _close_player(self):
        self._end_timer.stop()
        self.player.shutdown()

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
QSlider {
    background: transparent;
    border: none;
}
QSlider::groove:horizontal {
    border: none;
    background: transparent;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: palette(highlight);
    height: 4px;
    border-radius: 2px;
}
QSlider::add-page:horizontal {
    background: palette(mid);
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: palette(highlight);
    border: none;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: palette(highlight);
    border: none;
}
"""
