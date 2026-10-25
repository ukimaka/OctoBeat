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

"""Обёртка над двумя QMediaPlayer для плавных переходов (crossfade)."""

import math

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent


class CrossfadePlayer(QObject):
    """Плеер с поддержкой crossfade между двумя внутренними QMediaPlayer."""

    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(int)
    aboutToFinish = pyqtSignal()       # за crossfade_duration до конца трека
    trackFinished = pyqtSignal()       # трек реально закончился (без crossfade)

    def __init__(self):
        super().__init__()
        self._players = [QMediaPlayer(), QMediaPlayer()]
        self._active_index = 0

        self._user_volume = 70
        self._track_loudness = None         # dB текущего трека или None
        self._reference_db = -18.0          # опорный уровень нормализации
        self._crossfade_enabled = True
        self._crossfade_duration = 3000    # желаемая длительность, мс
        self._crossfade_started = False
        self._in_crossfade = False

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(50)
        self._fade_timer.timeout.connect(self._on_fade_tick)

        self._fade_step = 0
        self._fade_steps = 0
        self._fade_from_active = 0
        self._fade_target_volume = 0

        for p in self._players:
            p.stateChanged.connect(self._on_state_changed)
            p.positionChanged.connect(self._on_position_changed)
            p.durationChanged.connect(self._on_duration_changed)
            p.mediaStatusChanged.connect(self._on_media_status_changed)

    # ------------------------------------------------------------------
    #  Внутренние хелперы
    # ------------------------------------------------------------------
    def _active(self):
        return self._players[self._active_index]

    def _standby(self):
        return self._players[1 - self._active_index]

    def _swap(self):
        self._active_index = 1 - self._active_index

    def _effective_crossfade_duration(self):
        """Динамическая длина crossfade: не больше 1/3 трека и не меньше 500мс."""
        dur = self._active().duration()
        if dur <= 0:
            return self._crossfade_duration
        return min(self._crossfade_duration, max(500, dur // 3))

    def _complete_swap_now(self):
        """Завершить crossfade мгновенно (без ожидания таймера)."""
        self._fade_timer.stop()
        old_active = self._active()
        self._swap()
        old_active.stop()
        self._in_crossfade = False
        self._crossfade_started = False
        # Применяем нормализованную громкость к новому активному
        self._apply_current_volume()
        self.stateChanged.emit(self._active().state())
        self.durationChanged.emit(self._active().duration())
        self.positionChanged.emit(self._active().position())

    def _cancel_fade(self):
        """Прервать fade без swap: standby стоп, active восстановить громкость."""
        self._fade_timer.stop()
        if self._in_crossfade:
            self._standby().stop()
            self._standby().setVolume(self._user_volume)
            self._active().setVolume(self._user_volume)
        self._in_crossfade = False
        self._crossfade_started = False

    # ------------------------------------------------------------------
    #  Обработчики сигналов QMediaPlayer
    # ------------------------------------------------------------------
    def _on_state_changed(self, state):
        if self.sender() is self._active():
            self.stateChanged.emit(state)

    def _on_position_changed(self, pos):
        if self.sender() is not self._active():
            return
        self.positionChanged.emit(pos)

        if (self._crossfade_enabled
                and not self._crossfade_started
                and not self._in_crossfade
                and self._user_volume > 0):
            dur = self._active().duration()
            if dur > 0:
                remaining = dur - pos
                threshold = self._effective_crossfade_duration()
                # Минимум 500мс до конца трека — иначе пропускаем fade
                if 500 < remaining <= threshold:
                    # Флаг НЕ ставим тут — только уведомляем.
                    # Флаг будет установлен в crossfade_to(), если UI решит делать fade.
                    self.aboutToFinish.emit()

    def _on_duration_changed(self, dur):
        if self.sender() is self._active():
            self.durationChanged.emit(dur)

    def _on_media_status_changed(self, status):
        if self.sender() is self._active() and status == QMediaPlayer.EndOfMedia:
            # Если crossfade уже обработал переход — игнорируем
            if self._crossfade_started or self._in_crossfade:
                return
            self.trackFinished.emit()

    # ------------------------------------------------------------------
    #  Публичный API
    # ------------------------------------------------------------------
    def play(self, path, loudness=None):
        """Мгновенное переключение на трек (без crossfade)."""
        self._track_loudness = loudness
        self._cancel_fade()
        for p in self._players:
            p.stop()

        active = self._active()
        active.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        # устанавливаем с учётом loudness
        gain = self._compute_gain()
        actual = max(0, min(100, int(self._user_volume * gain)))
        active.setVolume(actual)
        active.play()

    def set_media(self, path, loudness=None):
        """Загружает трек без запуска — для обновления пути после
        переименования файла (медиа сбрасывается на новый путь)."""
        self._track_loudness = loudness
        self._cancel_fade()
        for p in self._players:
            p.stop()

        active = self._active()
        active.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        gain = self._compute_gain()
        actual = max(0, min(100, int(self._user_volume * gain)))
        active.setVolume(actual)

    def crossfade_to(self, path, loudness=None):
        """Плавно перейти на новый трек (наложение)."""
        self._track_loudness = loudness
        # Crossfade выключен в настройках (или звук полностью убран) —
        # переключаемся мгновенно, без затухания и наложения.
        if not self._crossfade_enabled or self._user_volume == 0:
            self.play(path, loudness=loudness)
            return

        # Если уже в crossfade — сначала завершим текущий мгновенно
        if self._in_crossfade:
            self._complete_swap_now()

        # Ставим флаг ЗДЕСЬ — раз UI реально решил делать fade
        self._crossfade_started = True

        standby = self._standby()
        standby.stop()
        standby.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        standby.setVolume(0)
        standby.play()

        effective = self._effective_crossfade_duration()
        steps = max(1, effective // self._fade_timer.interval())

        self._fade_step = 0
        self._fade_steps = steps
        self._fade_from_active = self._active().volume()
        # Целевая громкость fade-in: user_volume с учётом gain НОВОГО трека
        gain = self._compute_gain()
        self._fade_target_volume = max(0, min(100, int(self._user_volume * gain)))
        self._in_crossfade = True
        self._fade_timer.start()

    def _on_fade_tick(self):
        self._fade_step += 1
        t = min(1.0, self._fade_step / self._fade_steps)
        # Equal-power кривая: cos²(t·π/2) + sin²(t·π/2) = 1, поэтому
        # суммарная мощность двух треков остаётся постоянной. На слух
        # переход не «проваливается» в тишину на середине, в отличие от
        # линейной интерполяции или smoothstep.
        active_vol = max(
            0, int(self._fade_from_active * math.cos(t * math.pi / 2))
        )
        standby_vol = min(
            self._fade_target_volume,
            int(self._fade_target_volume * math.sin(t * math.pi / 2)),
        )
        self._active().setVolume(active_vol)
        self._standby().setVolume(standby_vol)

        if self._fade_step >= self._fade_steps:
            self._complete_swap_now()

    def pause(self):
        # Если fade в процессе — завершаем его мгновенно, потом пауза
        if self._in_crossfade:
            self._complete_swap_now()
        self._active().pause()

    def resume(self):
        self._crossfade_started = False
        self._in_crossfade = False
        self._active().play()

    def stop(self):
        self._cancel_fade()
        for p in self._players:
            p.stop()

    def volume(self):
        """Текущая пользовательская громкость (0..100)."""
        return self._user_volume

    def set_volume(self, volume):
        volume = max(0, min(100, int(volume)))
        if volume == self._user_volume:
            return   # ничего не поменялось — не трогаем QMediaPlayer
        self._user_volume = volume
        self._apply_current_volume()

    def _apply_current_volume(self):
        """Применяет громкость с учётом loudness текущего трека.
        Если QMediaPlayer сломался от частых setVolume — восстанавливаем."""
        if self._in_crossfade:
            return
        gain = self._compute_gain()
        actual = max(0, min(100, int(self._user_volume * gain)))

        p = self._active()
        was_playing = (p.state() == QMediaPlayer.PlayingState)

        p.setVolume(actual)

        # Watchdog: если плеер играл до setVolume, а после — Stopped,
        # значит GStreamer pipeline сломался. Перезапускаем.
        if was_playing and p.state() == QMediaPlayer.StoppedState:
            print("[player] setVolume killed playback — recovering")
            self._recover_active()
            p.setVolume(actual)   # применим ещё раз после восстановления

    def _recover_active(self):
        """Принудительно перезапускает текущий трек с сохранением позиции."""
        p = self._active()
        if p.media().isNull():
            return
        pos = p.position()
        p.stop()
        p.play()
        # setPosition применяем с небольшой задержкой — GStreamer должен
        # успеть загрузить pipeline, иначе seek проигнорируется
        QTimer.singleShot(50, lambda: p.setPosition(pos))

    def _compute_gain(self):
        """Множитель громкости: тихие треки — громче, громкие — тише.
        Ограничение ±12 dB (0.25x .. 4x)."""
        if self._track_loudness is None:
            return 1.0
        diff_db = self._reference_db - self._track_loudness
        gain = 10 ** (diff_db / 20)
        return max(0.25, min(4.0, gain))

    def set_track_loudness(self, loudness_db):
        """Устанавливает loudness текущего трека (или None для отключения)."""
        self._track_loudness = loudness_db
        self._apply_current_volume()

    def set_position(self, pos):
        """Обрезает позицию по длительности трека — защита от GStreamer assertion."""
        dur = self._active().duration()
        if dur > 0:
            pos = max(0, min(pos, dur))
        else:
            pos = max(0, pos)
        self._active().setPosition(pos)

    def position(self):
        return self._active().position()

    def duration(self):
        return self._active().duration()

    def state(self):
        return self._active().state()

    def is_playing(self):
        return self._active().state() == QMediaPlayer.PlayingState

    def media_is_null(self):
        return self._active().media().isNull()

    def set_crossfade_enabled(self, enabled):
        """Включает/выключает кроссфейд без изменения его длительности."""
        self._crossfade_enabled = bool(enabled)
        # Если пользователь выключил кроссфейд прямо во время перехода,
        # не оставляем второй плеер играть в фоне.
        if not self._crossfade_enabled and self._in_crossfade:
            self._complete_swap_now()

    def set_crossfade(self, enabled, duration_ms=None):
        self.set_crossfade_enabled(enabled)
        if duration_ms is not None:
            self._crossfade_duration = duration_ms
