"""Диалог поиска и скачивания музыки с YouTube.

Сверху — строка поиска, в центре — результаты с превью, снизу — кнопка
скачивания выбранного трека. Поиск и скачивание выполняются в фоновых
потоках, чтобы интерфейс не подвисал.
"""

import hashlib
from pathlib import Path

import requests
from PyQt5.QtCore import (
    QObject, QRect, QRectF, QRunnable, QSettings, QSize, Qt,
    QThread, QThreadPool, pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPixmap,
)
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QStyle, QStyledItemDelegate,
    QVBoxLayout,
)

from dialogs import colored_icon, colored_pixmap
from pixmap_utils import draw_centered, draw_cover, icon_pixmap_rect
from translations import tr
from youtube_worker import YoutubeSearchWorker, YoutubeWorker


ACCENT = "#5151ab"
ACCENT_HOVER = "#6161c1"
THUMBS_DIR = Path.home() / ".cache" / "music_player" / "yt_thumbs"


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
        if settings.value("theme", "dark") != "light":
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

    def __init__(self, urls, key, dest, signals):
        super().__init__()
        self.urls = urls
        self.key = key
        self.dest = dest
        self.signals = signals

    def run(self):
        try:
            if self.dest.is_file():
                data = self.dest.read_bytes()
                if data:
                    self.signals.loaded.emit(self.key, data)
                    return

            for url in self.urls:
                try:
                    response = requests.get(
                        url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    response.raise_for_status()
                    content = response.content
                    if not content:
                        continue
                    self.dest.parent.mkdir(parents=True, exist_ok=True)
                    self.dest.write_bytes(content)
                    self.signals.loaded.emit(self.key, content)
                    return
                except Exception:
                    continue
        except Exception:
            # Превью не критично — при ошибке останется заглушка.
            pass


class YoutubeDialog(QDialog):
    def __init__(self, parent=None, target_folder=None):
        super().__init__(parent)
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self.target_folder = target_folder
        self.downloaded_path = None

        self._search_thread = None
        self._search_worker = None
        self._download_thread = None
        self._download_worker = None

        self._thumb_dir = THUMBS_DIR
        self._thumb_signals = _ThumbnailSignals()
        self._thumb_signals.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_pool = QThreadPool(self)

        lang = self._lang()
        self.setWindowTitle(tr("Download from YouTube", lang))
        self.setMinimumSize(600, 460)

        self._build_ui()

    def _lang(self):
        return self.settings.value("language", "en")

    def _icon_color(self):
        return "#ffffff" if self.settings.value("theme", "dark") != "light" else "#000000"

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        lang = self._lang()
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Верх: поиск ---
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText(tr("Search YouTube...", lang))
        self.input.returnPressed.connect(self._on_search)

        self.btn_search = QPushButton(tr("Search", lang), self)
        self.btn_search.setAutoDefault(False)
        self.btn_search.setIcon(colored_icon("search.svg", self._icon_color()))
        self.btn_search.setIconSize(QSize(18, 18))
        self.btn_search.clicked.connect(self._on_search)

        search_row.addWidget(self.input, 1)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # --- Центр: результаты ---
        self.list = QListWidget(self)
        self.list.setItemDelegate(SearchResultDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setIconSize(QSize(
            SearchResultDelegate.THUMB_WIDTH,
            SearchResultDelegate.THUMB_HEIGHT,
        ))
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self._on_download())
        root.addWidget(self.list, 1)

        # --- Прогресс ---
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background: rgba(128, 128, 128, 0.25);
                height: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: {ACCENT};
                border-radius: 4px;
            }}
        """)
        root.addWidget(self.progress)

        self.status = QLabel("", self)
        root.addWidget(self.status)

        # --- Низ: кнопки ---
        button_row = QHBoxLayout()
        button_row.addStretch()

        self.btn_cancel = QPushButton(tr("Cancel", lang), self)
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setIcon(colored_icon("cancel.svg", self._icon_color()))
        self.btn_cancel.setIconSize(QSize(18, 18))
        self.btn_cancel.clicked.connect(self._on_cancel)

        self.btn_download = QPushButton(tr("Download Selected", lang), self)
        self.btn_download.setAutoDefault(False)
        self.btn_download.setEnabled(False)
        self.btn_download.setMinimumWidth(220)
        self.btn_download.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_HOVER};
            }}
            QPushButton:disabled {{
                background-color: rgba(81, 81, 171, 0.45);
                color: rgba(255, 255, 255, 0.6);
            }}
        """)
        self.btn_download.clicked.connect(self._on_download)

        button_row.addWidget(self.btn_cancel)
        button_row.addWidget(self.btn_download)
        root.addLayout(button_row)

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

        self._search_thread = QThread(self)
        self._search_worker = YoutubeSearchWorker(query)
        self._search_worker.moveToThread(self._search_thread)

        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error.connect(self._on_search_error)
        self._search_thread.start()

    def _on_search_finished(self, results):
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
        self._cleanup_search_thread()
        self._set_searching(False)
        self.status.setText(tr("Error", self._lang()))
        QMessageBox.warning(self, tr("Error", self._lang()), message)

    def _set_searching(self, searching):
        self.btn_search.setEnabled(not searching)
        self.input.setEnabled(not searching)

    # ------------------------------------------------------------------
    #  Превью
    # ------------------------------------------------------------------
    def _queue_thumbnail(self, result):
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
            _ThumbnailTask(urls, key, dest, self._thumb_signals)
        )

    def _on_thumbnail_loaded(self, key, data):
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

        self._show_download_mode(True)
        self.progress.setValue(0)
        self.status.setText(tr("Downloading...", self._lang()))

        self._download_thread = QThread(self)
        self._download_worker = YoutubeWorker(url, self.target_folder)
        self._download_worker.moveToThread(self._download_thread)

        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(self.progress.setValue)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_thread.start()

    def _on_download_finished(self, path):
        self.downloaded_path = path
        self._cleanup_download_thread()
        self.accept()

    def _on_download_error(self, message):
        self._cleanup_download_thread()
        self._show_download_mode(False)
        self.btn_download.setEnabled(self.list.currentItem() is not None)
        self.status.setText(tr("Error", self._lang()))
        QMessageBox.warning(self, tr("Error", self._lang()), message)

    def _show_download_mode(self, downloading):
        """Прячет поиск и показывает прогресс (или наоборот)."""
        self.list.setVisible(not downloading)
        self.input.setVisible(not downloading)
        self.btn_search.setVisible(not downloading)
        self.progress.setVisible(downloading)
        self.btn_download.setVisible(not downloading)

    # ------------------------------------------------------------------
    #  Очистка
    # ------------------------------------------------------------------
    def _cleanup_search_thread(self):
        if self._search_thread is not None:
            self._search_thread.quit()
            self._search_thread.wait()
            self._search_thread = None
            self._search_worker = None

    def _cleanup_download_thread(self):
        if self._download_thread is not None:
            self._download_thread.quit()
            self._download_thread.wait()
            self._download_thread = None
            self._download_worker = None

    def _shutdown(self):
        if self._search_worker is not None:
            self._search_worker.stop()
        if self._download_worker is not None:
            self._download_worker.stop()
        if self._thumb_pool is not None:
            self._thumb_pool.clear()
            self._thumb_pool.waitForDone(2000)
        self._cleanup_search_thread()
        self._cleanup_download_thread()

    def _on_cancel(self):
        self.reject()

    def reject(self):
        # Esc и кнопка Cancel должны останавливать фоновые задачи.
        self._shutdown()
        super().reject()

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)
