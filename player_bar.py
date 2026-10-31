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

"""Нижняя панель плеера: таймлайн, управление, режимы и громкость.

Виджет не знает о ``PlayerController``: клики и изменения он передаёт
сигналами, а состояние (трек, контекст, режимы, позиция) получает методами.
Логика ``ClickSlider`` (клик, перетаскивание, финальный seek) остаётся здесь,
чтобы не менять поведение таймлайна.
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from translations import tr
from ui_common import ClickSlider, ElidedLabel, LyricsButton, fmt_time

# Ширина блока громкости (иконка + слайдер). Нужна, чтобы симметричным
# отступом слева удерживать кнопки управления строго по центру панели.
VOLUME_BLOCK_WIDTH = 150


class PlayerBar(QWidget):
    """Панель управления воспроизведением."""

    play_pause_clicked = pyqtSignal()
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    seek_requested = pyqtSignal(int)
    volume_changed = pyqtSignal(int)
    repeat_clicked = pyqtSignal()
    shuffle_clicked = pyqtSignal()
    lyrics_toggled = pyqtSignal(bool)
    karaoke_requested = pyqtSignal()

    def __init__(self, settings, icons, event_filter=None, parent=None):
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.settings = settings
        self.icons = icons
        self._duration = 0
        self._playing = False
        self._repeat_mode = "off"
        self._shuffle = False

        lang = self.settings.value("language", "en")

        # Верхняя строка панели: текущий трек + контекст
        self.current_track_label = ElidedLabel(
            f"{tr('Current Track', lang)}: —"
        )
        self.current_track_label.setObjectName("currentTrack")
        # Игнорируем собственный sizeHint: длинное название не должно
        # расширять окно и выталкивать «Playing from». Текст обрезается
        # многоточием внутри отведённой ширины.
        self.current_track_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.current_track_label.setMinimumWidth(0)
        self.context_label = QLabel(f"{tr('Playing from', lang)}: —")
        self.context_label.setObjectName("contextLabel")
        self.context_label.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )

        row1 = QHBoxLayout()
        row1.addWidget(self.current_track_label, 1)
        row1.addWidget(self.context_label)

        # Timeline
        self.timeline = ClickSlider(Qt.Horizontal)
        self.timeline.setRange(0, 100)
        self.timeline.setValue(0)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setMinimumWidth(64)
        self.time_label.setSizePolicy(
            QSizePolicy.Minimum, QSizePolicy.Preferred
        )

        timeline_row = QHBoxLayout()
        timeline_row.addWidget(self.timeline, 1)
        timeline_row.addWidget(self.time_label)

        # Кнопки управления (иконки вместо текста)
        self.prev_button = self.icons.icon_button(
            "prev.svg", tr("Previous", lang), event_filter=event_filter
        )
        self.prev_button.setIconSize(QSize(24, 24))

        self.play_button = QPushButton()
        self.play_button.setIcon(self.icons.icon("play.svg"))
        self.play_button.setIconSize(QSize(32, 32))
        self.play_button.setFixedSize(50, 50)
        self.play_button.setFlat(True)

        self.next_button = self.icons.icon_button(
            "next.svg", tr("Next", lang), event_filter=event_filter
        )
        self.next_button.setIconSize(QSize(24, 24))

        self.repeat_button = QPushButton()
        self.repeat_button.setIcon(self.icons.icon("repeat.svg"))
        self.repeat_button.setIconSize(QSize(20, 20))
        self.repeat_button.setFlat(True)
        self.repeat_button.setCheckable(True)

        self.shuffle_button = QPushButton()
        self.shuffle_button.setIcon(self.icons.icon("shuffle.svg"))
        self.shuffle_button.setIconSize(QSize(20, 20))
        self.shuffle_button.setFlat(True)
        self.shuffle_button.setCheckable(True)

        self.lyrics_button = LyricsButton()
        self.lyrics_button.setIcon(self.icons.icon("karaoke.svg"))
        self.lyrics_button.setIconSize(QSize(20, 20))
        self.lyrics_button.setFlat(True)
        self.lyrics_button.setCheckable(True)
        self.lyrics_button.setToolTip(tr("Lyrics", lang))

        self.volume_icon_label = QLabel()
        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(120)

        # Блок громкости — в контейнере фиксированной ширины. Такой же
        # невидимый отступ слева компенсирует его ширину, поэтому группа
        # кнопок управления стоит ровно по центру панели, а не смещена вбок.
        volume_block = QWidget()
        volume_block.setFixedWidth(VOLUME_BLOCK_WIDTH)
        volume_row = QHBoxLayout(volume_block)
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(6)
        volume_row.addWidget(self.volume_icon_label)
        volume_row.addWidget(self.volume_slider)

        controls = QHBoxLayout()
        controls.addSpacing(VOLUME_BLOCK_WIDTH)
        controls.addStretch(1)
        controls.addWidget(self.repeat_button)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.shuffle_button)
        controls.addWidget(self.lyrics_button)
        controls.addStretch(1)
        controls.addWidget(volume_block)

        layout = QVBoxLayout(self)
        layout.addLayout(row1)
        layout.addLayout(timeline_row)
        layout.addLayout(controls)

        # Внутренние связи: клики превращаются в сигналы наружу.
        self.play_button.clicked.connect(
            lambda: self.play_pause_clicked.emit()
        )
        self.prev_button.clicked.connect(lambda: self.prev_clicked.emit())
        self.next_button.clicked.connect(lambda: self.next_clicked.emit())
        self.repeat_button.clicked.connect(lambda: self.repeat_clicked.emit())
        self.shuffle_button.clicked.connect(lambda: self.shuffle_clicked.emit())
        self.lyrics_button.toggled.connect(self._on_lyrics_toggled)
        self.lyrics_button.doubleClicked.connect(self.karaoke_requested.emit)

        self.timeline.clickedValue.connect(self._on_timeline_clicked)
        self.timeline.sliderMoved.connect(self._on_timeline_dragged)
        self.timeline.sliderReleased.connect(self._on_timeline_released)

        self.volume_slider.sliderMoved.connect(self._on_volume_changed)
        self.volume_slider.clickedValue.connect(self._on_volume_changed)
        self.volume_slider.valueChanged.connect(self._update_volume_icon)

        self._update_volume_icon(self.volume_slider.value())

    # ------------------------------------------------------------------
    #  Состояние из MainWindow
    # ------------------------------------------------------------------
    def set_current_track(self, track_id, title):
        lang = self.settings.value("language", "en")
        if track_id < 0:
            self.current_track_label.setText(f"{tr('Current Track', lang)}: —")
        elif title == "(unknown)":
            self.current_track_label.setText(
                f"{tr('Current Track', lang)}: {tr('(unknown)', lang)}"
            )
        else:
            self.current_track_label.setText(
                f"{tr('Current Track', lang)}: {title}"
            )

    def set_context(self, name):
        lang = self.settings.value("language", "en")
        if name:
            self.context_label.setText(f"{tr('Playing from', lang)}: {name}")
        else:
            self.context_label.setText(f"{tr('Playing from', lang)}: —")

    def set_playing(self, playing):
        self._playing = bool(playing)
        self.play_button.setIcon(
            self.icons.icon("pause.svg" if playing else "play.svg")
        )

    def set_repeat_mode(self, mode):
        self._repeat_mode = mode
        lang = self.settings.value("language", "en")
        tips = {
            "off": tr("Repeat: off", lang),
            "all": tr("Repeat: all", lang),
            "one": tr("Repeat: one track", lang),
        }
        self.repeat_button.setToolTip(tips[mode])
        self.repeat_button.setChecked(mode != "off")
        if mode == "off":
            icon = self.icons.icon("repeat.svg")
        elif mode == "all":
            icon = self.icons.icon("repeat.svg", color="blue")
        else:  # "one"
            icon = self.icons.icon("repeat-one.svg", color="blue")
        self.repeat_button.setIcon(icon)

    def set_shuffle(self, shuffle):
        self._shuffle = bool(shuffle)
        lang = self.settings.value("language", "en")
        self.shuffle_button.setToolTip(
            tr("Shuffle: on", lang) if shuffle else tr("Shuffle: off", lang)
        )
        self.shuffle_button.setChecked(shuffle)
        icon = self.icons.icon(
            "shuffle.svg", color="blue" if shuffle else None
        )
        self.shuffle_button.setIcon(icon)

    def apply_theme(self):
        """Перекрашивает все иконки панели после смены темы."""
        self.prev_button.setIcon(self.icons.icon("prev.svg"))
        self.next_button.setIcon(self.icons.icon("next.svg"))
        self._update_volume_icon(self.volume_slider.value())
        self.set_repeat_mode(self._repeat_mode)
        self.set_shuffle(self._shuffle)
        self._update_lyrics_icon()

    def activate_lyrics(self):
        """Гарантирует включённую кнопку Lyrics (для караоке)."""
        if not self.lyrics_button.isChecked():
            self.lyrics_button.setChecked(True)

    # ------------------------------------------------------------------
    #  Таймлайн
    # ------------------------------------------------------------------
    def _on_timeline_clicked(self, value):
        # Клик по groove — применяем сразу + обновляем метку
        self.time_label.setText(
            f"{fmt_time(value)} / {fmt_time(self._duration)}"
        )
        self.seek_requested.emit(value)

    def _on_timeline_dragged(self, value):
        # Тянем handle — обновляем ТОЛЬКО метку, seek не делаем
        self.time_label.setText(
            f"{fmt_time(value)} / {fmt_time(self._duration)}"
        )

    def _on_timeline_released(self):
        # Отпустил handle — применяем финальную позицию ОДИН раз
        self.seek_requested.emit(self.timeline.value())

    def set_position(self, pos, duration):
        # Пока пользователь тянет handle — вообще не трогаем ни слайдер, ни метку.
        # Метку обновляет _on_timeline_dragged.
        if self.timeline.isSliderDown():
            return
        self.timeline.setValue(pos)
        self.time_label.setText(
            f"{fmt_time(pos)} / {fmt_time(duration)}"
        )

    def set_duration(self, duration, position):
        self._duration = duration
        self.timeline.setRange(0, duration)
        # Обновим метку, даже если тянут — но только если не идёт драг
        if not self.timeline.isSliderDown():
            self.time_label.setText(
                f"{fmt_time(position)} / {fmt_time(duration)}"
            )

    # ------------------------------------------------------------------
    #  Громкость
    # ------------------------------------------------------------------
    def volume(self):
        return self.volume_slider.value()

    def set_volume(self, value):
        self.volume_slider.setValue(value)
        self._on_volume_changed(value)

    def nudge_volume(self, delta):
        """Меняет громкость на delta (в процентах), зажимая в диапазон."""
        slider = self.volume_slider
        value = max(slider.minimum(), min(slider.maximum(), slider.value() + delta))
        slider.setValue(value)
        self._on_volume_changed(value)

    def _on_volume_changed(self, value):
        self.volume_changed.emit(value)

    def _update_volume_icon(self, value):
        if value == 0:
            name = "volume-mute.svg"
        elif value < 50:
            name = "volume-low.svg"
        else:
            name = "volume-high.svg"

        pixmap = self.icons.pixmap(name, 24)
        if not pixmap.isNull():
            self.volume_icon_label.setPixmap(pixmap)

    # ------------------------------------------------------------------
    #  Lyrics
    # ------------------------------------------------------------------
    def _on_lyrics_toggled(self, checked):
        self._update_lyrics_icon()
        self.lyrics_toggled.emit(checked)

    def _update_lyrics_icon(self, _checked=None):
        self.lyrics_button.setIcon(
            self.icons.icon(
                "karaoke.svg",
                color="blue" if self.lyrics_button.isChecked() else None,
            )
        )
