"""Парсинг LRC и управление текстом песни.

Модуль отделяет логику текстов от ``MainWindow``: здесь живут разбор
таймкодов, фоновый ``LyricsWorker``, расчёт активной строки/слова,
ручной сдвиг и полноэкранные оверлеи. Панель текста (``LyricsPanel``)
получает готовые данные через сигналы и ничего не знает о воркере.
"""

import re

from PyQt5.QtCore import QObject, pyqtSignal

import db
from lyrics_api import LyricsWorker


# Таймкод LRC: [mm:ss.xx], [mm:ss.xxx] или [mm:ss:xx]
_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
# Пословный таймкод (enhanced LRC): <mm:ss.xx>
_LRC_WORD_RE = re.compile(r"<(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)>")


def _timecode_to_ms(minutes, seconds):
    """Переводит ``mm``/``ss.xx`` в миллисекунды."""
    return int(round((int(minutes) * 60 + float(seconds.replace(":", "."))) * 1000))


def _parse_lrc_words(content):
    """Разбирает пословные таймкоды ``<mm:ss.xx>`` внутри строки.

    Возвращает список ``(время_мс_или_None, слово)`` либо пустой список,
    если пословных таймкодов нет. ``None`` у первого слова означает, что
    оно относится к началу строки (шло до первого ``<...>``).
    """
    parts = _LRC_WORD_RE.split(content)
    if len(parts) == 1:
        return []

    words = []
    lead = parts[0].strip()
    if lead:
        words.append((None, lead))

    count = (len(parts) - 1) // 3
    for k in range(count):
        minutes = parts[1 + 3 * k]
        seconds = parts[2 + 3 * k]
        word = parts[3 + 3 * k].strip()
        if not word:
            continue
        words.append((_timecode_to_ms(minutes, seconds), word))
    return words


def parse_lrc(text):
    """Парсит LRC в список ``(время_в_мс, строка, слова)`` по времени.

    ``слова`` — список ``(время_мс_или_None, слово)`` из пословных
    таймкодов ``<mm:ss.xx>`` (пустой, если их нет). Поддерживает формат
    ``[mm:ss.xx] текст`` и несколько таймкодов в одной строке (тогда текст
    относится ко всем ним). Строки без таймкода и пустые строки пропускаются.
    """
    lines = []
    if not text:
        return lines
    for raw in text.splitlines():
        matches = list(_LRC_TIME_RE.finditer(raw))
        if not matches:
            continue
        content = raw[matches[-1].end():].strip()
        words = _parse_lrc_words(content)
        # В отображаемом тексте пословные таймкоды не нужны.
        display = _LRC_WORD_RE.sub("", content).strip()
        for match in matches:
            ms = _timecode_to_ms(match.group(1), match.group(2))
            lines.append((ms, display, words))
    lines.sort(key=lambda item: item[0])
    return lines


class LyricsManager(QObject):
    """Загружает текст, считает подсветку и управляет оверлеями."""

    # (mode, lines, plain), где mode: "loading" | "synced" | "plain" | "empty"
    content_changed = pyqtSignal(str, list, str)
    # (line_index, word_index)
    highlight_changed = pyqtSignal(int, int)

    def __init__(self, settings, media_player, db_module=None,
                 parent_window=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.media_player = media_player
        self.db = db_module or db
        self._parent_window = parent_window

        self._lyrics_worker = None
        self._lyrics_workers = set()   # все живые воркеры (для shutdown)
        # Треки, для которых загрузка уже пробовалась в этой сессии. Не
        # дёргаем провайдеров повторно при каждом переключении, но при
        # следующем запуске попробуем снова.
        self._lyrics_attempted = set()
        self._lyrics_lines = []
        self._lyrics_plain = ""
        self._lyrics_index = -1
        self._lyrics_word_index = -1
        self._lyrics_overlay = None
        self._karaoke_overlay = None
        self._lyrics_offset_ms = 0
        self._current_track_id = None

    # ------------------------------------------------------------------
    #  Загрузка
    # ------------------------------------------------------------------
    def set_track(self, track_id):
        """Показывает сохранённый текст или запускает фоновую загрузку.

        ``track_id`` приходит из сигнала контроллера (``int``), но на всякий
        случай нормализуем его: QVariant/строка из QSettings не должны ронять
        сравнение ``track_id < 0`` или приводить к чужому тексту в БД.
        """
        try:
            track_id = int(track_id)
        except (TypeError, ValueError):
            track_id = None

        # Повторный сигнал для того же трека (например, при crossfade) не
        # должен отменять уже идущую загрузку и заново её запускать.
        if (track_id is not None
                and track_id == self._current_track_id
                and self._lyrics_worker is not None):
            return

        # Безопасно отпускаем предыдущий воркер. Не блокируем главный поток:
        # сетевой запрос всё равно выполняется в отдельном QThread.
        self._cancel_lyrics_worker()
        self._current_track_id = track_id
        self._lyrics_lines = []
        self._lyrics_plain = ""
        self._lyrics_index = -1
        self._lyrics_word_index = -1
        self._sync_overlay_lines()

        if track_id is None or track_id < 0:
            self._render_lyrics(None)
            return

        synced, plain, checked = self.db.get_track_lyrics(track_id)
        if not checked:
            # Результата ещё нет либо прошлая попытка сорвалась (например,
            # сеть). Показываем сохранённое (если есть) и пробуем загрузить.
            if track_id in self._lyrics_attempted:
                self._render_lyrics(synced, plain)
                return
            self._lyrics_attempted.add(track_id)
            self._render_lyrics(
                synced, plain, loading=not (synced or plain)
            )
            self._start_lyrics_worker(track_id)
            return
        self._render_lyrics(synced, plain)

    def _start_lyrics_worker(self, track_id):
        row = self.db.get_track_by_id(track_id)
        if row is None:
            # Трека нет в БД — не оставляем панель навсегда в «Loading...».
            self._render_lyrics(None)
            return
        worker = LyricsWorker(
            track_id, row["artist"], row["title"], row["duration"], self
        )
        worker.loaded.connect(self._on_lyrics_loaded)
        worker.failed.connect(self._on_lyrics_failed)
        # Подключаем bound-метод, а не lambda: слот гарантированно выполнится
        # в потоке менеджера (главном), а воркер найдём через sender().
        worker.finished.connect(self._on_lyrics_worker_finished)
        self._lyrics_worker = worker
        self._lyrics_workers.add(worker)
        worker.start()

    def _on_lyrics_worker_finished(self):
        """Воркер завершился: забываем его и планируем удаление."""
        worker = self.sender()
        if worker is self._lyrics_worker:
            self._lyrics_worker = None
        if worker is not None:
            self._lyrics_workers.discard(worker)
            try:
                worker.deleteLater()
            except RuntimeError:
                # C++-объект уже удалён — ничего делать не нужно.
                pass

    def _cancel_lyrics_worker(self):
        """Отпускает текущий воркер, не дожидаясь сети.

        ``quit()`` бесполезен для QThread с переопределённым ``run()``, а
        ``wait()`` замораживал бы UI на всё время запроса к syncedlyrics.
        Воркер сам проверит флаг отмены и не запишет/не отдаст результат.
        """
        worker = self._lyrics_worker
        if worker is None:
            return
        self._lyrics_worker = None
        try:
            worker.cancel()
        except RuntimeError:
            # C++-объект уже удалён — ничего делать не нужно.
            pass

    def _on_lyrics_loaded(self, track_id, synced, plain):
        self._lyrics_attempted.add(track_id)
        if track_id != self._current_track_id:
            return
        # Провайдеры могут ответить «нет текста» при сбое. Если в панели уже
        # показан сохранённый текст, не затираем его пустым ответом.
        if not synced and not plain and (self._lyrics_lines or self._lyrics_plain):
            return
        self._render_lyrics(synced, plain)

    def _on_lyrics_failed(self, track_id, error):
        print(f"[lyrics] failed for track {track_id}: {error}")
        self._lyrics_attempted.add(track_id)
        if track_id != self._current_track_id:
            return
        if self._lyrics_lines or self._lyrics_plain:
            return
        self._render_lyrics(None)

    # ------------------------------------------------------------------
    #  Отрисовка состояния
    # ------------------------------------------------------------------
    def _render_lyrics(self, synced, plain=None, loading=False):
        """Готовит данные для панели: LRC, обычный текст или заглушку."""
        self._lyrics_index = -1
        self._lyrics_word_index = -1
        self._lyrics_lines = parse_lrc(synced)
        self._lyrics_plain = plain or ""
        self._sync_overlay_lines()

        if loading:
            mode = "loading"
        elif self._lyrics_lines:
            mode = "synced"
        elif plain:
            mode = "plain"
        else:
            mode = "empty"

        self.content_changed.emit(mode, list(self._lyrics_lines), self._lyrics_plain)

        if mode == "synced":
            # Сразу подсвечиваем актуальную строку/слово для текущей позиции.
            self.on_position(self._position())

    @staticmethod
    def _line_index_for_pos(lines, pos):
        """Индекс строки LRC для позиции (мс); -1, если рано."""
        index = -1
        for i, (time_ms, _text, _words) in enumerate(lines):
            if time_ms <= pos:
                index = i
            else:
                break
        return index

    def _word_index_for_pos(self, line_index, pos):
        """Индекс текущего слова в строке (мс); -1, если слов нет."""
        if not (0 <= line_index < len(self._lyrics_lines)):
            return -1
        line_ms, _text, words = self._lyrics_lines[line_index]
        if not words:
            return -1
        word_index = -1
        for wi, (word_ms, _word) in enumerate(words):
            ts = line_ms if word_ms is None else word_ms
            if ts <= pos:
                word_index = wi
            else:
                break
        return word_index

    def on_position(self, pos):
        """Подсвечивает строку/слово LRC, соответствующие позиции (мс)."""
        # Тексты с LRCLIB часто отстают/спешат — учитываем ручной сдвиг.
        adjusted = pos + self._lyrics_offset_ms

        # Полноэкранный оверлей синхронизируем, если он открыт.
        if self._lyrics_overlay is not None and self._lyrics_overlay.isVisible():
            self._lyrics_overlay.set_position(adjusted)
        if self._karaoke_overlay is not None and self._karaoke_overlay.isVisible():
            self._karaoke_overlay.set_position(adjusted)

        if not self._lyrics_lines:
            return
        index = self._line_index_for_pos(self._lyrics_lines, adjusted)
        word_index = self._word_index_for_pos(index, adjusted)
        if index == self._lyrics_index and word_index == self._lyrics_word_index:
            return  # ничего не сменилось — UI не трогаем
        self._lyrics_index = index
        self._lyrics_word_index = word_index
        self.highlight_changed.emit(index, word_index)

    def refresh_highlight(self):
        """Пересчитывает подсветку для текущей позиции плеера."""
        self.on_position(self._position())

    def adjust_offset(self, delta_ms):
        """Сдвигает подсветку текста вперёд/назад на delta_ms."""
        self._lyrics_offset_ms += delta_ms
        # Сбрасываем индексы, иначе on_position посчитает, что ничего
        # не изменилось, и не перерисует текст.
        self._lyrics_index = -1
        self._lyrics_word_index = -1
        self.on_position(self._position())

    def _position(self):
        if self.media_player is None:
            return 0
        return self.media_player.position()

    # ------------------------------------------------------------------
    #  Полноэкранные оверлеи
    # ------------------------------------------------------------------
    def show_fullscreen(self):
        """Открывает полноэкранный оверлей с текущим текстом."""
        if self._lyrics_overlay is None:
            from lyrics_overlay import LyricsOverlay

            self._lyrics_overlay = LyricsOverlay(self._parent_window)
        self._lyrics_overlay.set_lines(self._lyrics_lines, self._lyrics_plain)
        self._lyrics_overlay.set_position(
            self._position() + self._lyrics_offset_ms
        )
        self._lyrics_overlay.showFullScreen()

    def show_karaoke(self):
        """Открывает полноэкранный караоке-режим с текущим текстом."""
        if self._karaoke_overlay is None:
            from karaoke_overlay import KaraokeOverlay

            self._karaoke_overlay = KaraokeOverlay(self._parent_window)
        self._karaoke_overlay.set_lines(self._lyrics_lines, self._lyrics_plain)
        self._karaoke_overlay.set_position(
            self._position() + self._lyrics_offset_ms
        )
        self._karaoke_overlay.showFullScreen()

    def _sync_overlay_lines(self):
        """Обновляет строки в оверлеях, если они открыты."""
        if self._lyrics_overlay is not None:
            self._lyrics_overlay.set_lines(self._lyrics_lines, self._lyrics_plain)
        if self._karaoke_overlay is not None:
            self._karaoke_overlay.set_lines(self._lyrics_lines, self._lyrics_plain)

    # ------------------------------------------------------------------
    #  Завершение работы
    # ------------------------------------------------------------------
    def shutdown(self):
        """Останавливает воркеры и закрывает оверлеи."""
        self._cancel_lyrics_worker()
        workers = list(self._lyrics_workers)
        # На закрытии приложения короткое ожидание допустимо: иначе Python
        # может уничтожить ещё работающий QThread и уронить процесс.
        for worker in workers:
            try:
                worker.cancel()
                if worker.isRunning():
                    worker.wait(2000)
            except RuntimeError:
                pass
        self._lyrics_workers.clear()
        # Закрываем полноэкранный оверлей (основной плеер не трогаем).
        if self._lyrics_overlay is not None:
            self._lyrics_overlay.close()
        if self._karaoke_overlay is not None:
            self._karaoke_overlay.close()
