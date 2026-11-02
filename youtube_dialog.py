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

"""Диалог поиска и скачивания музыки с YouTube.

Сверху — строка поиска, в центре — результаты с превью, снизу — кнопка
скачивания выбранного трека. Поиск и скачивание выполняются в фоновых
потоках, чтобы интерфейс не подвисал.
"""

import hashlib
import time

import requests
from PyQt5.QtCore import (
    QObject,
    QRect,
    QRectF,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from dialogs import (
    CustomConfirmDialog,
    _DimmedDialog,
    _FramelessDialog,
    colored_icon,
    colored_pixmap,
)
from paths import CACHE_DIR
from pixmap_utils import draw_centered, draw_cover, icon_pixmap_rect
from styles import is_dark_theme
from qt_diagnostics import (
    hold_worker,
    log_warning,
    note,
    track_pool,
    track_thread,
    untrack_pool,
)
from qt_lifecycle import retire_thread
from translations import tr
from youtube_worker import YoutubeSearchWorker, YoutubeWorker

THUMBS_DIR = CACHE_DIR / "yt_thumbs"


class SearchResultDelegate(QStyledItemDelegate):
    """Строка результата: превью 80x45, название/канал, длительность."""

    ROW_HEIGHT = 66
    THUMB_WIDTH = 80
    THUMB_HEIGHT = 45
    THUMB_RADIUS = 4
    PADDING = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._placeholder_cache = {}

    # ------------------------------------------------------------------
    #  Оформление
    # ------------------------------------------------------------------
    def _palette(self):
        settings = QSettings("MusicPlayer", "MusicPlayer")
        if is_dark_theme(settings.value("theme", "dark")):
            return {
                "title": QColor("#ffffff"),
                "subtitle": QColor("#8a8a8a"),
                "duration": QColor("#8a8a8a"),
                "selection": QColor("#282828"),
                "hover": QColor(255, 255, 255, 15),
                "cover_bg": QColor("#282828"),
                "note": "#888888",
            }
        return {
            "title": QColor("#000000"),
            "subtitle": QColor("#666666"),
            "duration": QColor("#666666"),
            "selection": QColor("#e0e0e0"),
            "hover": QColor(0, 0, 0, 15),
            "cover_bg": QColor("#f0f0f0"),
            "note": "#000000",
        }

    def _placeholder(self, color):
        pixmap = self._placeholder_cache.get(color)
        if pixmap is None:
            pixmap = colored_pixmap("music-note.svg", 22, color)
            self._placeholder_cache[color] = pixmap
        return pixmap

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter, option, index):
        if painter is None:
            return

        data = index.data(Qt.UserRole) or {}
        rect = option.rect
        palette = self._palette()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(rect, Qt.transparent)

        # Фон строки: выделение или наведение.
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, palette["selection"])
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, palette["hover"])

        # Превью.
        thumb_rect = QRect(
            rect.x() + self.PADDING,
            rect.y() + (rect.height() - self.THUMB_HEIGHT) // 2,
            self.THUMB_WIDTH,
            self.THUMB_HEIGHT,
        )
        self._draw_thumbnail(painter, thumb_rect, index, palette)

        # Длительность — измеряем заранее, чтобы освободить место справа.
        duration = data.get("duration") or 0
        dur_text = self._format_duration(duration)
        dur_font = QFont(painter.font())
        dur_font.setPixelSize(11)
        dur_width = QFontMetrics(dur_font).horizontalAdvance(dur_text) + 20

        text_left = thumb_rect.right() + 12
        text_right = rect.right() - self.PADDING - dur_width
        text_width = max(0, text_right - text_left)

        # Название (жирным).
        title_font = QFont(painter.font())
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette["title"])
        title = QFontMetrics(title_font).elidedText(
            data.get("title") or "Unknown", Qt.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, rect.y() + 14, text_width, 16),
            Qt.AlignLeft | Qt.AlignVCenter, title,
        )

        # Канал (серым).
        sub_font = QFont(painter.font())
        sub_font.setPixelSize(11)
        sub_font.setBold(False)
        painter.setFont(sub_font)
        painter.setPen(palette["subtitle"])
        uploader = QFontMetrics(sub_font).elidedText(
            data.get("uploader") or "", Qt.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, rect.y() + 34, text_width, 15),
            Qt.AlignLeft | Qt.AlignVCenter, uploader,
        )

        # Длительность (справа).
        painter.setFont(dur_font)
        painter.setPen(palette["duration"])
        painter.drawText(
            QRect(text_right, rect.y(), dur_width - 8, rect.height()),
            Qt.AlignRight | Qt.AlignVCenter, dur_text,
        )

        painter.restore()

    def _draw_thumbnail(self, painter, rect, index, palette):
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), self.THUMB_RADIUS, self.THUMB_RADIUS)

        painter.save()
        painter.setClipPath(clip)

        pixmap = QPixmap()
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pixmap = icon_pixmap_rect(
                icon, rect.width(), rect.height()
            )

        if not draw_cover(painter, QRectF(rect), pixmap):
            painter.fillRect(rect, palette["cover_bg"])
            note = self._placeholder(palette["note"])
            draw_centered(painter, QRectF(rect), note)

        painter.restore()

    @staticmethod
    def _format_duration(seconds):
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0:
            return "--:--"
        return f"{seconds // 60}:{seconds % 60:02d}"


class _ThumbnailSignals(QObject):
    """Мост сигналов из пула потоков в GUI-поток."""

    loaded = pyqtSignal(str, bytes)   # ключ превью, содержимое картинки


class _ThumbnailTask(QRunnable):
    """Скачивает превью (с запасным URL) в фоновом потоке."""

    def __init__(self, urls, key, dest, signals, cancel_check=None):
        super().__init__()
        self.urls = urls
        self.key = key
        self.dest = dest
        self.signals = signals
        self.cancel_check = cancel_check

    def _cancelled(self):
        try:
            return bool(self.cancel_check and self.cancel_check())
        except Exception:
            return False

    def run(self):
        try:
            if self._cancelled():
                return
            if self.dest.is_file():
                data = self.dest.read_bytes()
                if data:
                    self.signals.loaded.emit(self.key, data)
                    return

            for url in self.urls:
                if self._cancelled():
                    return
                try:
                    response = requests.get(
                        url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    response.raise_for_status()
                    content = response.content
                    if not content:
                        continue
                    if self._cancelled():
                        return
                    self.dest.parent.mkdir(parents=True, exist_ok=True)
                    self.dest.write_bytes(content)
                    self.signals.loaded.emit(self.key, content)
                    return
                except Exception:
                    continue
        except Exception:
            # Превью не критично — при ошибке останется заглушка.
            pass


class DownloadProgressDialog(_DimmedDialog):
    """Маленькое окно прогресса, отдельное от поиска YouTube."""

    cancelled = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._finished = False
        lang = QSettings("MusicPlayer", "MusicPlayer").value(
            "language", "en"
        )
        self.setObjectName("downloadProgressDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(250, 150)
        # Безрамочное окно, как остальные кастомные диалоги: без системного
        # заголовка, белой рамки и кнопок ОС.
        self.setWindowFlags(
            Qt.Dialog
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        # Окно и его содержимое должны быть полностью непрозрачными.
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)

        background = self.palette().window().color().name()
        text = self.palette().windowText().color().name()
        border = self.palette().mid().color().name()

        # Сплошная непрозрачная подложка внутри окна. Даже если родитель
        # передал прозрачность на уровне нативного окна, этот QFrame
        # закрашивает всю клиентскую область.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._container = QFrame()
        self._container.setObjectName("downloadProgressRoot")
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self._container)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.title_label = QLabel(title)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.progress.setFixedHeight(10)

        self.cancel_button = QPushButton(tr("Cancel", lang))
        self.cancel_button.setObjectName("downloadProgressCancel")
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_button, 0, Qt.AlignCenter)

        self.setStyleSheet(
            "QDialog#downloadProgressDialog {"
            f" background-color: {background};"
            "}"
            "QFrame#downloadProgressRoot {"
            f" background-color: {background};"
            f" border: 1px solid {border};"
            "}"
            f"QLabel {{ color: {text}; }}"
            "QProgressBar {"
            " background-color: rgba(127, 127, 127, 0.22);"
            " border: none;"
            " border-radius: 4px;"
            " text-align: center;"
            f" color: {text};"
            "}"
            "QProgressBar::chunk {"
            " background-color: palette(highlight);"
            " border-radius: 4px;"
            "}"
            "QPushButton#downloadProgressCancel {"
            " background-color: rgba(127, 127, 127, 0.18);"
            f" color: {text};"
            " border: none;"
            " border-radius: 6px;"
            " padding: 6px 18px;"
            "}"
            "QPushButton#downloadProgressCancel:hover {"
            " background-color: rgba(127, 127, 127, 0.28);"
            "}"
        )

    def setValue(self, value):
        self.progress.setValue(max(0, min(100, int(value))))

    def finish(self):
        """Close without emitting cancelled (download completed)."""
        self._finished = True
        self.hide()

    def _on_cancel(self):
        self.cancel_button.setEnabled(False)
        self.reject()

    def reject(self):
        if not self._finished:
            self._finished = True
            self.cancelled.emit()
        super().reject()


class YoutubeDialog(_FramelessDialog):
    def __init__(self, parent=None, target_folder=None):
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        super().__init__(parent, tr("Download from YouTube", self._lang()))
        self.target_folder = target_folder
        self.downloaded_path = None

        self._search_thread = None
        self._search_worker = None
        self._download_thread = None
        self._download_worker = None
        self._progress_dialog = None
        self._shutting_down = False

        self._thumb_dir = THUMBS_DIR
        self._thumb_signals = _ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_pool = track_pool(QThreadPool(), "yt-thumb-pool")

        # Это полноценное окно поиска, а не маленький прогресс-диалог.
        self.setMinimumSize(600, 420)
        self.resize(640, 480)

        self._build_ui()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)
        note("youtube dialog created")

    def _lang(self):
        return self.settings.value("language", "en")

    def _icon_color(self):
        return (
            "#ffffff"
            if is_dark_theme(self.settings.value("theme", "dark"))
            else "#000000"
        )

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        lang = self._lang()
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 8, 16, 6)
        root.setSpacing(8)
        self.body.addWidget(content, 1)

        # --- Верх: поиск ---
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(tr("Search YouTube...", lang))
        self.input.returnPressed.connect(self._on_search)

        self.btn_search = QPushButton(tr("Search", lang), self)
        self.btn_search.setAutoDefault(False)
        # Make Enter act as Search instead of QDialog's implicit accept().
        self.btn_search.setDefault(True)
        self.btn_search.setIcon(colored_icon("search.svg", self._icon_color()))
        self.btn_search.setIconSize(QSize(18, 18))
        self.btn_search.clicked.connect(self._on_search)

        search_row.addWidget(self.input, 1)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # --- Центр: результаты ---
        self.list = QListWidget(self)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setItemDelegate(SearchResultDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setMinimumHeight(120)
        self.list.setIconSize(QSize(
            SearchResultDelegate.THUMB_WIDTH,
            SearchResultDelegate.THUMB_HEIGHT,
        ))
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self._on_download())
        root.addWidget(self.list, 1)

        self.status = QLabel("", self)
        root.addWidget(self.status)

        # --- Низ: кнопки ---
        self.btn_cancel = QPushButton(tr("Cancel", lang), self)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setDefault(False)
        self.btn_cancel.setIcon(colored_icon("cancel.svg", self._icon_color()))
        self.btn_cancel.setIconSize(QSize(18, 18))
        self.btn_cancel.clicked.connect(self._on_cancel)

        self.btn_download = QPushButton(tr("Download Selected", lang), self)
        self.btn_download.setAutoDefault(False)
        self.btn_download.setDefault(False)
        self.btn_download.setEnabled(False)
        self.btn_download.setMinimumWidth(220)
        self.btn_download.setStyleSheet(f"""
            QPushButton {{
                background-color: palette(highlight);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: palette(highlight);
            }}
            QPushButton:disabled {{
                background-color: rgba(128, 128, 128, 0.35);
                color: rgba(255, 255, 255, 0.6);
            }}
        """)
        self.btn_download.clicked.connect(self._on_download)

        self._add_footer([self.btn_cancel, self.btn_download])

    # ------------------------------------------------------------------
    #  Поиск
    # ------------------------------------------------------------------
    def _on_search(self):
        if self._search_thread is not None or self._download_thread is not None:
            return

        query = self.input.text().strip()
        if not query:
            self.status.setText(tr("Enter a search query", self._lang()))
            return

        lang = self._lang()
        self.list.clear()
        self.btn_download.setEnabled(False)
        self._set_searching(True)
        self.status.setText(tr("Searching...", lang))

        self._search_thread = track_thread(QThread(), "yt-search")
        self._search_worker = YoutubeSearchWorker(query)
        self._search_worker.setObjectName("yt-search-worker")
        note(f"youtube search started: {query[:80]!r}")
        self._search_worker.moveToThread(self._search_thread)
        hold_worker(self._search_thread, self._search_worker, "yt-search-worker")

        self._search_thread.started.connect(self._search_worker.run)
        self._search_thread.finished.connect(self._search_worker.deleteLater)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error.connect(self._on_search_error)
        self._search_thread.start()

    def _on_search_finished(self, results):
        if self._shutting_down:
            return
        lang = self._lang()
        self._cleanup_search_thread()
        self._set_searching(False)

        for result in results:
            # Ключ превью нужно проставить до setData: Qt копирует dict.
            self._queue_thumbnail(result)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, result)
            self.list.addItem(item)

        if self.list.count():
            self.list.setCurrentRow(0)
            self.status.setText(
                tr("Results: {n}", lang).format(n=len(results))
            )
        else:
            self.status.setText(tr("Nothing found", lang))

    def _on_search_error(self, message):
        if self._shutting_down:
            return
        self._cleanup_search_thread()
        self._set_searching(False)
        self.status.setText(tr("Error", self._lang()))
        CustomConfirmDialog.information(
            self, tr("Error", self._lang()), message
        )

    def _set_searching(self, searching):
        self.btn_search.setEnabled(not searching)
        self.input.setEnabled(not searching)

    # ------------------------------------------------------------------
    #  Превью
    # ------------------------------------------------------------------
    def _queue_thumbnail(self, result):
        if self._shutting_down or self._thumb_pool is None:
            return
        video_id = result.get("video_id") or ""
        direct = (
            f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
            if video_id else ""
        )
        fallback = result.get("thumbnail") or ""

        urls = []
        for url in (direct, fallback):
            if url and url not in urls:
                urls.append(url)
        if not urls:
            return

        key = urls[0]
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        dest = self._thumb_dir / f"{digest}.jpg"

        result["thumb_url"] = key
        self._thumb_pool.start(
            _ThumbnailTask(
                urls, key, dest, self._thumb_signals,
                cancel_check=lambda: self._shutting_down,
            )
        )

    def _on_thumbnail_loaded(self, key, data):
        if self._shutting_down:
            return
        image = QImage()
        if not image.loadFromData(data):
            return
        icon = QIcon(QPixmap.fromImage(image))

        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is None:
                continue
            info = item.data(Qt.UserRole)
            if isinstance(info, dict) and info.get("thumb_url") == key:
                item.setIcon(icon)
                break

        viewport = self.list.viewport()
        if viewport is not None:
            viewport.update()

    # ------------------------------------------------------------------
    #  Скачивание
    # ------------------------------------------------------------------
    def _on_selection_changed(self):
        if self._download_thread is not None:
            return
        self.btn_download.setEnabled(self.list.currentItem() is not None)

    def _on_download(self):
        if self._download_thread is not None:
            return

        item = self.list.currentItem()
        if item is None:
            return

        data = item.data(Qt.UserRole) or {}
        url = data.get("id")
        if not url:
            return

        lang = self._lang()
        # Не вызываем self.hide(): QDialog::setVisible(False) завершает
        # вложенный event loop exec_(), и импорт-флоу сразу решает, что
        # диалог отменён. Из-за этого окно поиска теряло ссылку, а сигналы
        # progress/finished от воркера больше не доходили до прогресс-бара.
        # Окно поиска остаётся под модальным прогресс-диалогом.
        # Родитель — главное окно, а не безрамочный поиск:
        # иначе дочерний диалог наследует прозрачность/стили поисковика.
        progress_parent = self.parentWidget()
        self._progress_dialog = DownloadProgressDialog(
            tr("Downloading...", lang), progress_parent
        )
        self._progress_dialog.cancelled.connect(
            self._on_download_cancelled
        )
        self._progress_dialog.show()
        self._progress_dialog.raise_()

        self._download_thread = track_thread(QThread(), "yt-download")
        self._download_worker = YoutubeWorker(url, self.target_folder)
        self._download_worker.setObjectName("yt-download-worker")
        note(f"youtube download started: {url[:120]!r}")
        self._download_worker.moveToThread(self._download_thread)
        hold_worker(
            self._download_thread, self._download_worker,
            "yt-download-worker",
        )

        self._download_thread.started.connect(self._download_worker.run)
        self._download_thread.finished.connect(
            self._download_worker.deleteLater
        )
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_thread.start()

    def _on_download_progress(self, value):
        if self._shutting_down:
            return
        dialog = self._progress_dialog
        if dialog is not None:
            dialog.setValue(value)

    def _on_download_finished(self, path):
        if self._shutting_down or self._download_thread is None:
            note(f"youtube download finished after cancel/shutdown: {path}")
            return
        note(f"youtube download finished: {path}")
        self.downloaded_path = path
        self._cleanup_download_thread()
        self._close_progress_dialog()
        self.accept()

    def _on_download_error(self, message):
        if self._shutting_down or self._download_thread is None:
            note(f"youtube download error after cancel/shutdown: {message[:160]}")
            return
        note(f"youtube download error: {message[:160]}")
        self._cleanup_download_thread()
        self._close_progress_dialog()
        self.show()
        self.raise_()
        self._set_searching(False)
        self.btn_download.setEnabled(self.list.currentItem() is not None)
        self.status.setText(tr("Error", self._lang()))
        CustomConfirmDialog.information(
            self, tr("Error", self._lang()), message
        )

    def _on_download_cancelled(self):
        self._cleanup_download_thread()
        self._close_progress_dialog()
        self.show()
        self.raise_()
        self._set_searching(False)
        self.btn_download.setEnabled(self.list.currentItem() is not None)
        self.status.setText(tr("Cancelled", self._lang()))

    def _close_progress_dialog(self):
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is None:
            return
        dialog.finish()
        dialog.deleteLater()

    # ------------------------------------------------------------------
    #  Очистка
    # ------------------------------------------------------------------
    @staticmethod
    def _stop_thread(thread, worker):
        """Останавливает worker, не уничтожая работающий QThread."""
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass
        if thread is None:
            return
        retire_thread(thread, 2000)

    def _cleanup_search_thread(self):
        thread = self._search_thread
        worker = self._search_worker
        self._search_thread = None
        self._search_worker = None
        self._stop_thread(thread, worker)

    def _cleanup_download_thread(self):
        thread = self._download_thread
        worker = self._download_worker
        self._download_thread = None
        self._download_worker = None
        self._stop_thread(thread, worker)

    def _shutdown(self):
        # reject() и closeEvent() могут прийти подряд — не дублируем остановку.
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True
        note("youtube dialog shutdown begin")

        # Сначала гарантированно останавливаем фоновые потоки: иначе при
        # уничтожении диалога Qt получит QThread: Destroyed while running.
        self._cleanup_search_thread()
        self._cleanup_download_thread()
        self._close_progress_dialog()

        pool = self._thumb_pool
        if pool is not None:
            # Новые превью больше не ставятся в очередь; уже запущенные
            # доработают и будут дожданы без магического таймаута.
            pool.clear()
            note(
                "thumbnail pool wait: "
                f"active={pool.activeThreadCount()}"
            )
            started = time.monotonic()
            pool.waitForDone()
            elapsed = time.monotonic() - started
            note(f"thumbnail pool finished in {elapsed:.2f}s")
            if elapsed >= 2.0:
                log_warning(
                    "thumbnail pool close took "
                    f"{elapsed:.2f}s (waited fully)"
                )
            self._thumb_pool = None
            untrack_pool(pool)
        note("youtube dialog shutdown end")

    def shutdown(self):
        """Публичная остановка диалога (в т.ч. при выходе из приложения)."""
        self._shutdown()

    def _on_cancel(self):
        self.reject()

    def done(self, result):
        # Все пути закрытия (accept/reject/close) проходят через done().
        self._shutdown()
        super().done(result)

    def reject(self):
        # Esc и кнопка Cancel должны останавливать фоновые задачи.
        self._shutdown()
        super().reject()

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)
