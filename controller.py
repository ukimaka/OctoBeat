"""Контроллер воспроизведения: контекст, очередь, переходы, режимы.

Изолирует логику "что играть дальше" от UI. Общается с представлением
исключительно через сигналы.
"""

import random

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

import db
import metadata
from player import CrossfadePlayer


class PlayerController(QObject):
    """Логика воспроизведения, вынесенная из MainWindow."""

    # (track_id, title) — текущий трек изменился
    track_changed = pyqtSignal(int, str)
    # (context_name) — контекст воспроизведения изменился
    context_changed = pyqtSignal(str)
    # (is_playing) — состояние воспроизведения
    playback_state_changed = pyqtSignal(bool)
    # ("off" | "all" | "one")
    repeat_mode_changed = pyqtSignal(str)
    # (shuffle)
    shuffle_changed = pyqtSignal(bool)
    # (queue_size) — ручная очередь изменилась
    queue_changed = pyqtSignal(int)
    # (track_id, title) — какой трек пойдёт следующим («островок» Next Track)
    next_track_changed = pyqtSignal(int, str)

    def __init__(self, media_player=None, settings=None,
                 db_module=None, metadata_module=None, parent=None):
        super().__init__(parent)
        self.db = db_module or db
        self.metadata = metadata_module or metadata
        self.media_player = media_player or CrossfadePlayer()
        self.settings = settings or QSettings("MusicPlayer", "MusicPlayer")

        # Настройка crossfade читается один раз при старте и передаётся
        # плееру; дальше SettingsPage обновляет её сигналом на лету.
        set_crossfade = getattr(
            self.media_player, "set_crossfade_enabled", None
        )
        if callable(set_crossfade):
            set_crossfade(
                bool(self.settings.value("enable_crossfade", True, type=bool))
            )

        # --- Состояние воспроизведения ---
        self.current_track_id = None
        self.play_history = []              # стек прослушанных треков (для Prev)

        # Контекст воспроизведения
        self.play_context = []              # список id в текущем контексте
        self.play_context_original = []     # исходный порядок (для отключения shuffle)
        self.play_context_index = -1        # позиция текущего трека
        self.play_context_type = None       # "library" | "playlist" | None
        self.play_context_playlist_id = None
        self.play_context_name = ""

        # Ручная очередь (играется перед контекстом)
        self.manual_queue = []

        # Режимы
        self.repeat_mode = "off"            # "off" | "all" | "one"
        self.shuffle = False

        # Порядок треков в текущем списке библиотеки (задаёт UI)
        self.library_ids_provider = None    # callable -> list[int]

    # ------------------------------------------------------------------
    #  Утилиты
    # ------------------------------------------------------------------
    def _path_by_id(self, track_id):
        row = self.db.get_track_by_id(track_id)
        return row["file_path"] if row else None

    # ------------------------------------------------------------------
    #  Контекст
    # ------------------------------------------------------------------
    def _set_context(self, ids, index, context_type, name, playlist_id=None):
        """Устанавливает новый контекст. НЕ начинает воспроизведение."""
        self.play_context_original = list(ids)
        self.play_context = list(ids)
        self.play_context_index = index
        self.play_context_type = context_type
        self.play_context_name = name
        self.play_context_playlist_id = playlist_id
        # текущий трек — это id по индексу (для показа в Current Track)
        if 0 <= index < len(ids):
            self.current_track_id = ids[index]
        else:
            self.current_track_id = None
        self._update_context_label()
        if self.shuffle:
            self._apply_shuffle_keeping_current()
        self._emit_next_track()

    def _apply_shuffle_keeping_current(self):
        """Перемешать контекст, оставив текущий трек на позиции 0."""
        if not self.play_context:
            return
        if self.play_context_index < 0 or self.play_context_index >= len(self.play_context):
            return
        current_id = self.play_context[self.play_context_index]
        others = [i for i in self.play_context_original if i != current_id]
        random.shuffle(others)
        self.play_context = [current_id] + others
        self.play_context_index = 0

    def _restore_original_order(self):
        """Вернуть исходный порядок, сохранив позицию текущего трека."""
        if not self.play_context or self.current_track_id is None:
            return
        if self.current_track_id not in self.play_context_original:
            return
        self.play_context = list(self.play_context_original)
        self.play_context_index = self.play_context.index(self.current_track_id)

    def _update_context_label(self):
        self.context_changed.emit(self.play_context_name or "")

    # ------------------------------------------------------------------
    #  Воспроизведение по контексту
    # ------------------------------------------------------------------
    def _play_from_list(self, ids, clicked_id, context_type, name, playlist_id=None):
        """Строит контекст, находит clicked_id, начинает воспроизведение."""
        if clicked_id not in ids:
            return

        # Автоматический режим Repeat в зависимости от контекста:
        # плейлист → зацикливается, Library → не зацикливается
        if context_type == "playlist":
            self.repeat_mode = "all"
        else:
            self.repeat_mode = "off"
        self.repeat_mode_changed.emit(self.repeat_mode)

        index = ids.index(clicked_id)
        self._set_context(ids, index, context_type, name, playlist_id)
        self._play_current()

    def _play_current(self):
        """Загружает трек по текущему индексу контекста и играет."""
        if not self.play_context:
            return
        if self.play_context_index < 0 or self.play_context_index >= len(self.play_context):
            return
        track_id = self.play_context[self.play_context_index]
        path = self._path_by_id(track_id)
        if path is None:
            print(f"[play] no path for track_id={track_id}")
            return
        self.current_track_id = track_id
        self.db.log_play(track_id)
        # пишем в историю (стек) — нужно для корректного Prev в shuffle
        self.play_history.append(track_id)
        self.play_history = self.play_history[-50:]
        # передаём loudness прямо в play, чтобы громкость была сразу правильной
        row = self.db.get_track_by_id(track_id)
        loudness = row["loudness"] if row else None
        self.media_player.play(path, loudness=loudness)
        self._show_current_from_context()
        self.playback_state_changed.emit(True)
        self._emit_next_track()

    def _show_current_from_context(self):
        """Сообщает UI о текущем треке. НЕ играет."""
        if self.current_track_id is None:
            self.track_changed.emit(-1, "—")
            return
        row = self.db.get_track_by_id(self.current_track_id)
        if row is None:
            self.track_changed.emit(self.current_track_id, "(unknown)")
            return
        self.track_changed.emit(
            self.current_track_id,
            self.metadata.format_track(row, with_duration=False),
        )

    def _emit_next_track(self):
        """Сообщает UI трек, который пойдёт следующим.

        Учитывает ручную очередь, режим Repeat и позицию в контексте."""
        # 1. Ручная очередь играется раньше контекста
        if self.manual_queue:
            self._emit_next_track_id(self.manual_queue[0])
            return

        # 2. Контекст
        if not self.play_context or not (
            0 <= self.play_context_index < len(self.play_context)
        ):
            self.next_track_changed.emit(-1, "")
            return

        if self.repeat_mode == "one":
            self._emit_next_track_id(self.play_context[self.play_context_index])
            return

        next_index = self.play_context_index + 1
        if next_index >= len(self.play_context):
            if self.repeat_mode != "all":
                self.next_track_changed.emit(-1, "")
                return
            next_index = 0
        self._emit_next_track_id(self.play_context[next_index])

    def _emit_next_track_id(self, track_id):
        """Эмитит следующий трек по его id (заголовок — format_track)."""
        row = self.db.get_track_by_id(track_id)
        if row is None:
            self.next_track_changed.emit(track_id, "")
            return
        self.next_track_changed.emit(
            track_id, self.metadata.format_track(row, with_duration=False)
        )

    def _next_in_context(self, from_end_of_track=False):
        """Переход к следующему треку в контексте."""
        # Если в ручной очереди есть треки — играем их в первую очередь
        if self._play_from_queue():
            return

        if not self.play_context:
            return

        # Repeat One срабатывает только при автопереходе
        if from_end_of_track and self.repeat_mode == "one":
            self.media_player.set_position(0)
            self.media_player.resume()
            self.playback_state_changed.emit(True)
            return

        new_index = self.play_context_index + 1
        if new_index >= len(self.play_context):
            if self.repeat_mode == "all":
                new_index = 0
            else:
                self.media_player.stop()
                self.playback_state_changed.emit(False)
                return

        self.play_context_index = new_index
        self._play_current()

    def _prev_in_context(self):
        """Переход к предыдущему треку (или в начало текущего)."""
        if not self.play_context:
            return

        # Если играем больше 3 секунд — вернуться в начало трека
        if self.media_player.position() > 3000:
            self.media_player.set_position(0)
            return

        # Стек истории: пропускаем текущий (верх стека) и берём предыдущий.
        # Это корректно работает и в shuffle.
        if len(self.play_history) > 1:
            self.play_history.pop()             # убрать текущий
            prev_id = self.play_history.pop()   # взять предыдущий
            if prev_id in self.play_context:
                self.play_context_index = self.play_context.index(prev_id)
                self._play_current()
                return
            # если трека уже нет в контексте — падаем на обычную логику
            self.play_history.append(prev_id)

        new_index = self.play_context_index - 1
        if new_index < 0:
            if self.repeat_mode == "all":
                new_index = len(self.play_context) - 1
            else:
                new_index = 0

        self.play_context_index = new_index
        self._play_current()

    # ------------------------------------------------------------------
    #  Ручная очередь
    # ------------------------------------------------------------------
    def _add_to_queue(self, track_id):
        self.manual_queue.append(track_id)
        print(f"[queue] added track_id={track_id}, queue size={len(self.manual_queue)}")
        self.queue_changed.emit(len(self.manual_queue))
        self._emit_next_track()

    def _play_from_queue(self):
        """Играет первый трек из ручной очереди. True, если что-то запустили."""
        if not self.manual_queue:
            return False
        track_id = self.manual_queue.pop(0)
        path = self._path_by_id(track_id)
        if path is None:
            print(f"[queue] no path for track_id={track_id}")
            self.queue_changed.emit(len(self.manual_queue))
            return False
        row = self.db.get_track_by_id(track_id)
        loudness = row["loudness"] if row else None
        self.current_track_id = track_id
        self.media_player.play(path, loudness=loudness)
        self._show_current_from_context()
        self.playback_state_changed.emit(True)
        self.queue_changed.emit(len(self.manual_queue))
        self._emit_next_track()
        return True

    # ------------------------------------------------------------------
    #  Публичный API для UI
    # ------------------------------------------------------------------
    def play_from_list(self, ids, clicked_id, context_type, name, playlist_id=None):
        self._play_from_list(ids, clicked_id, context_type, name, playlist_id)

    def set_context(self, ids, index, context_type, name, playlist_id=None):
        self._set_context(ids, index, context_type, name, playlist_id)

    def show_current(self):
        self._show_current_from_context()

    def add_to_queue(self, track_id):
        self._add_to_queue(track_id)

    def clear_context(self):
        self.play_context = []
        self.play_context_original = []
        self.play_context_index = -1
        self.play_context_type = None
        self.play_context_playlist_id = None
        self.play_context_name = ""
        self._update_context_label()
        self._emit_next_track()

    def remove_from_context(self, track_id):
        """Убирает трек из контекста (например, при удалении из библиотеки)."""
        if track_id == self.current_track_id:
            self.media_player.stop()
            self.current_track_id = None
            self._show_current_from_context()
            self.playback_state_changed.emit(False)
        if track_id in self.play_context:
            idx = self.play_context.index(track_id)
            self.play_context.pop(idx)
            if track_id in self.play_context_original:
                self.play_context_original.remove(track_id)
            if idx < self.play_context_index:
                self.play_context_index -= 1
            elif idx == self.play_context_index:
                if self.play_context:
                    self.play_context_index = min(self.play_context_index, len(self.play_context) - 1)
                else:
                    self.play_context_index = -1
        self._emit_next_track()

    def toggle_play(self, checked=False):
        if self.media_player.media_is_null():
            if self.play_context and self.play_context_index >= 0:
                self._play_current()
                return
            ids = (self.library_ids_provider() if self.library_ids_provider
                   else [row["id"] for row in self.db.get_all_tracks()])
            if ids:
                self._set_context(ids, 0, "library", "Library", None)
                self._play_current()
            return
        if self.media_player.is_playing():
            self.media_player.pause()
            self.playback_state_changed.emit(False)
        else:
            self.media_player.resume()
            self.playback_state_changed.emit(True)

    def next(self, checked=False):
        self._next_in_context(from_end_of_track=False)

    def prev(self, checked=False):
        self._prev_in_context()

    # ------------------------------------------------------------------
    #  Внешнее управление (MPRIS / медиа-клавиши)
    # ------------------------------------------------------------------
    def play(self):
        """Возобновить воспроизведение или начать его с текущего контекста."""
        if self.media_player.media_is_null():
            self.toggle_play()
            return
        if not self.media_player.is_playing():
            self.media_player.resume()
            self.playback_state_changed.emit(True)

    def pause(self):
        """Поставить на паузу, если трек играет."""
        if self.media_player.is_playing():
            self.media_player.pause()
            self.playback_state_changed.emit(False)

    def play_pause(self):
        """Переключить воспроизведение/паузу."""
        self.toggle_play()

    def stop(self):
        """Полностью остановить воспроизведение."""
        self.media_player.stop()
        self.playback_state_changed.emit(False)

    def seek_us(self, microseconds):
        """Перейти к позиции, заданной в микросекундах (MPRIS Position)."""
        self.media_player.set_position(max(0, int(microseconds)) // 1000)

    def set_volume_ratio(self, ratio):
        """Установить громкость в диапазоне 0.0..1.0 (MPRIS Volume)."""
        value = max(0.0, min(1.0, float(ratio)))
        self.media_player.set_volume(round(value * 100))

    def on_track_finished(self):
        self._next_in_context(from_end_of_track=True)

    def prepare_crossfade(self):
        """Вызывается за crossfade_duration до конца трека."""
        if self.repeat_mode == "one":
            return
        if not self.play_context:
            return
        next_index = self.play_context_index + 1
        if next_index >= len(self.play_context):
            if self.repeat_mode == "all":
                next_index = 0
            else:
                return
        next_id = self.play_context[next_index]
        next_path = self._path_by_id(next_id)
        if next_path is None:
            return
        row = self.db.get_track_by_id(next_id)
        loudness = row["loudness"] if row else None
        self.media_player.crossfade_to(next_path, loudness=loudness)
        self.play_context_index = next_index
        self.current_track_id = next_id
        self._show_current_from_context()
        self.playback_state_changed.emit(True)
        self._emit_next_track()

    # ------------------------------------------------------------------
    #  Режимы
    # ------------------------------------------------------------------
    def toggle_repeat(self):
        if self.repeat_mode == "off":
            self.repeat_mode = "all"
        elif self.repeat_mode == "all":
            self.repeat_mode = "one"
        else:
            self.repeat_mode = "off"
        self.repeat_mode_changed.emit(self.repeat_mode)

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        if self.shuffle:
            self._apply_shuffle_keeping_current()
        else:
            self._restore_original_order()
        self.shuffle_changed.emit(self.shuffle)
        self._emit_next_track()
