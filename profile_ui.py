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

"""Вкладка «Профиль»: шапка, локальная статистика и любимый трек."""

import base64
import os
import re
import shutil
from pathlib import Path

import requests
import urllib3

# Загружаем внешние картинки с verify=False (часть хостингов, например
# Wallhaven, падает с SSL-ошибкой на Windows); глушим шум warnings.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtCore import (
    QByteArray, QRectF, QSettings, QSize, Qt, QThread, QVariant, pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPalette,
    QPixmap, QTextDocument,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSizeGrip, QSizePolicy, QSplitter, QTextBrowser, QTextEdit, QVBoxLayout,
    QWidget,
)

import db
import metadata
from api_client import ApiClient, ApiError
from auth_ui import AuthDialog
from dialogs import colored_icon, colored_pixmap
from pixmap_utils import (
    draw_centered, draw_cover, new_pixmap, render_svg, svg_file_pixmap,
)
from translations import tr


PROFILE_COVERS_DIR = Path.home() / ".cache" / "music_player" / "profile_covers"
PROFILE_DIR = Path.home() / ".local" / "share" / "music_player" / "profile"

# Достижения: (ключ, иконка, пороги уровней, подпись для тултипа)
ACHIEVEMENT_TIERS = ("Bronze", "Silver", "Gold", "Diamond")
ACHIEVEMENT_COLORS = ("#cd7f32", "#c0c0c0", "#ffd700", "#7fdfff")
ACHIEVEMENT_LOCKED_COLOR = "#5a5a5a"

ACHIEVEMENTS = (
    ("tracks", "count.svg", (100, 500, 1000, 2000), "Tracks downloaded"),
    ("playlists", "create-playlist.svg", (5, 10, 25, 50), "Playlists created"),
    ("time", "time.svg", (3600, 36000, 180000, 360000), "Listening time"),
    ("age", "favorite.svg", (30, 90, 180, 365), "Library age"),
)

# Иконки панели форматирования BBCode (SVG, цвет подставляется через {color})
_FORMAT_ICONS = {
    "bold": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M7 4h6.2a3.6 3.6 0 0 1 2.05 6.56A3.9 3.9 0 0 1 13.7 20H7V4z'
        'm2.6 2.4v4.2h3.1a1.8 1.8 0 0 0 0-4.2H9.6zm0 6.6v4.6h3.6a2.3 2.3 0 0'
        ' 0 0-4.6H9.6z" fill="{color}"/></svg>'
    ),
    "italic": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M9 4h8v2.3h-3.1l-2.7 11.4H14V20H6v-2.3h3.1l2.7-11.4H9z"'
        ' fill="{color}"/></svg>'
    ),
    "underline": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M7 4h2.4v8.1a2.6 2.6 0 0 0 5.2 0V4H17v8.1a5 5 0 0 1-10 0V4z"'
        ' fill="{color}"/>'
        '<rect x="6" y="19" width="12" height="2.2" rx="1.1" fill="{color}"/></svg>'
    ),
    "link": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round">'
        '<path d="M9.5 14.5l5-5"/>'
        '<path d="M8 12l-1.7 1.7a3 3 0 0 0 4.2 4.2L12.2 16"/>'
        '<path d="M16 12l1.7-1.7a3 3 0 0 0-4.2-4.2L11.8 8"/></g></svg>'
    ),
    "image": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="3.5" y="5" width="17" height="14" rx="2.5" fill="none"'
        ' stroke="{color}" stroke-width="2"/>'
        '<circle cx="8.5" cy="9.5" r="1.6" fill="{color}"/>'
        '<path d="M5.5 17.5l4-4 2.5 2.5 3-3 3.5 3.5" fill="none"'
        ' stroke="{color}" stroke-width="2" stroke-linecap="round"'
        ' stroke-linejoin="round"/></svg>'
    ),
    "center": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="3.5" y="5" width="17" height="2.2" rx="1.1" fill="{color}"/>'
        '<rect x="6.5" y="9" width="11" height="2.2" rx="1.1" fill="{color}"/>'
        '<rect x="3.5" y="13" width="17" height="2.2" rx="1.1" fill="{color}"/>'
        '<rect x="6.5" y="17" width="11" height="2.2" rx="1.1" fill="{color}"/></svg>'
    ),
}

# Стиль современного безрамочного редактора BBCode
_BBCODE_DIALOG_QSS = """
QDialog {
    background: transparent;
}
#bbRoot {
    background-color: #121212;
    border: none;
    outline: none;
    border-radius: 12px;
}
#bbTitle {
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
}
#bbHint {
    color: #8a8a8a;
    font-size: 11px;
}
QPushButton#bbTool {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px;
}
QPushButton#bbTool:hover {
    background: rgba(255, 255, 255, 0.12);
}
QPushButton#bbTool:pressed {
    background: rgba(81, 81, 171, 0.55);
}
QPushButton#bbClose {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
}
QPushButton#bbClose:hover {
    background: rgba(255, 255, 255, 0.14);
}
QTextEdit {
    border: 1px solid #2e2e2e;
}
QTextEdit#bbEditor {
    background: #181818;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
    color: #ffffff;
    font-size: 13px;
    padding: 8px;
    selection-background-color: #5151ab;
}
*:focus {
    outline: none;
    border: none;
}
QTextEdit:focus {
    outline: none;
    border: none;
}
QFocusFrame {
    border: none;
    background: transparent;
}
QTextBrowser#bbPreview {
    background: #181818;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
    color: #ffffff;
    padding: 8px;
}
QSplitter#bbSplitter::handle {
    background: transparent;
    width: 6px;
}
QPushButton#bbSave {
    background: #5151ab;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
    font-weight: bold;
}
QPushButton#bbSave:hover {
    background: #6161c4;
}
QPushButton#bbCancel {
    background: #2a2a2a;
    color: #dddddd;
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
}
QPushButton#bbCancel:hover {
    background: #3a3a3a;
}
"""


def _svg_pixmap(markup, color, size):
    """Рендерит SVG-строку в DPR-осознанный QPixmap ``size``×``size``."""
    renderer = QSvgRenderer(QByteArray(markup.replace("{color}", color).encode()))
    return render_svg(renderer, size)


def _svg_icon(markup, color, render=40):
    """QIcon из SVG-строки (растеризуется крупно для чёткости)."""
    return QIcon(_svg_pixmap(markup, color, render))


def parse_bbcode(text):
    """BBCode → HTML (поддерживаются теги osu!-профиля)."""
    if not text:
        return ""

    html = str(text)
    flags = re.IGNORECASE | re.DOTALL

    html = re.sub(
        r"\[youtube\](.*?)\[/youtube\]",
        lambda m: '<a href="https://youtu.be/%s">YouTube Video</a>'
        % m.group(1).strip(),
        html,
        flags=flags,
    )
    html = re.sub(
        r"\[img\](.*?)\[/img\]",
        r'<img src="\1" style="max-width: 100%;"/>',
        html,
        flags=flags,
    )
    html = re.sub(
        r"\[url=(.*?)\](.*?)\[/url\]",
        r'<a href="\1">\2</a>',
        html,
        flags=flags,
    )
    html = re.sub(
        r"\[color=(.*?)\](.*?)\[/color\]",
        r'<span style="color: \1;">\2</span>',
        html,
        flags=flags,
    )
    html = re.sub(
        r"\[size=(.*?)\](.*?)\[/size\]",
        r'<span style="font-size: \1%;">\2</span>',
        html,
        flags=flags,
    )

    simple_tags = (
        ("b", "<b>", "</b>"),
        ("i", "<i>", "</i>"),
        ("u", "<u>", "</u>"),
        ("s", "<s>", "</s>"),
        ("centre", '<div align="center">', "</div>"),
        ("heading", '<h2 style="color: #ff66aa;">', "</h2>"),
    )
    for tag, open_tag, close_tag in simple_tags:
        html = re.sub(
            r"\[%s\](.*?)\[/%s\]" % (tag, tag),
            open_tag + r"\1" + close_tag,
            html,
            flags=flags,
        )

    return html.replace("\r\n", "\n").replace("\n", "<br>")


def _description_html(text):
    """BBCode → HTML для описания профиля."""
    return parse_bbcode(text)


def _theme_is_dark():
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return settings.value("theme", "dark") != "light"


def _icon_color():
    return "#ffffff" if _theme_is_dark() else "#000000"


def _lang():
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return settings.value("language", "en")


def _cover_pixmap(source, size, radius=6):
    """Квадратная обложка со скруглёнными углами (заглушка — нота).

    `source` — путь к файлу, готовый QPixmap или None.
    """
    result = new_pixmap(size, size)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(clip)

    if isinstance(source, QPixmap):
        pixmap = source
    else:
        pixmap = QPixmap(source) if source else QPixmap()
    if not draw_cover(painter, QRectF(0, 0, size, size), pixmap):
        dark = _theme_is_dark()
        painter.fillRect(
            QRectF(0, 0, size, size),
            QColor("#282828") if dark else QColor("#efefef"),
        )
        note = colored_pixmap(
            "music-note.svg", size - 10,
            "#ffffff" if dark else "#000000",
        )
        draw_centered(painter, QRectF(0, 0, size, size), note)

    painter.end()
    return result


def _round_avatar_pixmap(source, size):
    """Круглая аватарка `size`×`size` (или заглушка user.svg).

    `source` — путь к файлу, QPixmap, байты изображения или None.
    """
    result = new_pixmap(size, size)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(clip)

    if isinstance(source, QPixmap):
        pixmap = source
    elif isinstance(source, (bytes, bytearray)):
        pixmap = QPixmap()
        pixmap.loadFromData(bytes(source))
    else:
        pixmap = QPixmap(source) if source else QPixmap()
    if not draw_cover(painter, QRectF(0, 0, size, size), pixmap):
        dark = _theme_is_dark()
        painter.fillRect(
            QRectF(0, 0, size, size),
            QColor("#282828") if dark else QColor("#efefef"),
        )
        icon_size = int(size * 0.5)
        icon = colored_pixmap(
            "user.svg", icon_size, "#ffffff" if dark else "#000000"
        )
        draw_centered(painter, QRectF(0, 0, size, size), icon)

    painter.end()
    return result


def _copy_profile_image(source, base_name):
    """Копирует выбранную картинку в папку профиля, возвращает новый путь.

    Старые файлы с тем же `base_name`, но другим расширением, удаляются.
    """
    os.makedirs(PROFILE_DIR, exist_ok=True)
    suffix = Path(source).suffix.lower() or ".png"
    dest = PROFILE_DIR / f"{base_name}{suffix}"

    if Path(source).resolve() == dest.resolve():
        return dest

    for old in PROFILE_DIR.glob(f"{base_name}.*"):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass

    shutil.copy2(source, dest)
    return dest


def _achievement_level(value, thresholds):
    """Сколько порогов достигнуто (0..len(thresholds))."""
    level = 0
    for threshold in thresholds:
        if value >= threshold:
            level += 1
        else:
            break
    return level


def _format_achievement_value(key, value):
    """Человекочитаемое значение достижения (время — в часах)."""
    if key == "time":
        return f"{value // 3600}h"
    return str(value)


class _DoubleClickLabel(QLabel):
    """QLabel, сообщающий о двойном клике."""

    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ProfileTextBrowser(QTextBrowser):
    """QTextBrowser для About Me: внешние картинки и двойной клик."""

    doubleClicked = pyqtSignal()
    MAX_HEIGHT = 450

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_cache = {}
        self._failed_images = set()

        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setObjectName("profileScrollBar")
        self.setMaximumHeight(self.MAX_HEIGHT)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
        )
        palette = self.palette()
        palette.setColor(QPalette.Text, QColor("#8a8a8a"))
        palette.setColor(QPalette.Base, QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setStyleSheet("background: transparent;")

        # Высота растёт по содержимому только до MAX_HEIGHT; при
        # переполнении появляется вертикальный скроллбар.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(
            self._sync_height
        )

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()

    def _sync_height(self, *_args):
        width = self.viewport().width()
        if width <= 0:
            return
        height = self.document().size().height()
        margins = self.contentsMargins()
        extra = self.frameWidth() * 2 + margins.top() + margins.bottom()
        new_height = min(
            self.MAX_HEIGHT, max(1, int(height + extra + 1))
        )
        if abs(self.height() - new_height) > 1:
            self.setFixedHeight(new_height)

    def loadResource(self, resource_type, url):
        if resource_type == QTextDocument.ImageResource:
            scheme = url.scheme().lower()
            if scheme in ("http", "https"):
                key = url.toString()
                if key in self._image_cache:
                    return self._image_cache[key]
                if key in self._failed_images:
                    return None

                try:
                    response = requests.get(
                        key,
                        timeout=5,
                        headers={"User-Agent": "Mozilla/5.0"},
                        verify=False,
                    )
                    response.raise_for_status()
                    image = QImage.fromData(response.content)
                except Exception as exc:
                    print(f"[PROFILE IMAGE] Error loading {key}: {exc}")
                    image = QImage()

                if image.isNull():
                    self._failed_images.add(key)
                    return None

                # QTextDocument не применяет max-width из HTML, поэтому
                # вписываем широкие картинки в текущую ширину браузера.
                available = self.viewport().width() - 32
                if available > 0 and image.width() > available:
                    image = image.scaledToWidth(
                        available, Qt.SmoothTransformation
                    )

                variant = QVariant(image)
                self._image_cache[key] = variant
                return variant

        return super().loadResource(resource_type, url)


class _ClickableCard(QFrame):
    """Карточка с курсором-рукой и подсветкой при наведении.

    Сигнал `clicked` несёт id плейлиста.
    """

    clicked = pyqtSignal(int)

    def __init__(self, playlist_id, parent=None):
        super().__init__(parent)
        self.playlist_id = playlist_id
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.playlist_id)
        super().mouseReleaseEvent(event)


class _DialogTitleBar(QWidget):
    """Заголовок безрамочного диалога с перетаскиванием окна мышью."""

    def __init__(self, dialog, title, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self._drag_pos = None
        self.setFixedHeight(44)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("bbTitle")
        row.addWidget(self.title_label)
        row.addStretch(1)

        close_button = QPushButton()
        close_button.setObjectName("bbClose")
        close_button.setFlat(True)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setIcon(colored_icon("cancel.svg", "#ffffff"))
        close_button.setIconSize(QSize(16, 16))
        close_button.setToolTip(tr("Cancel", _lang()))
        close_button.clicked.connect(dialog.reject)
        row.addWidget(close_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPos() - self._dialog.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self._dialog.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class CoverLoader(QThread):
    """Ищет обложку: MusicBrainz/Cover Art Archive → YouTube (fallback)."""

    loaded = pyqtSignal(int, QPixmap)   # track_id, обложка

    def __init__(
        self,
        track_id,
        query,
        parent=None,
        artist=None,
        title=None,
    ):
        super().__init__(parent)
        self.track_id = track_id
        self.query = (query or "").strip()
        self.artist = (artist or "").strip()
        self.title = (title or "").strip()

    def run(self):
        cover_file = PROFILE_COVERS_DIR / f"{self.track_id}.jpg"
        if not (cover_file.exists() and cover_file.stat().st_size > 0):
            source = self._find_cover()
            if not source:
                return
            try:
                PROFILE_COVERS_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, cover_file)
            except Exception as exc:
                print(f"[cover] cannot cache cover: {exc}")
                return

        pixmap = QPixmap()
        if not pixmap.load(str(cover_file)):
            return
        self.loaded.emit(self.track_id, pixmap)

    def _find_cover(self):
        """MusicBrainz → YouTube через общий пайплайн метаданных."""
        from musicbrainz_client import get_track_metadata_with_fallback

        title = self.title or self.query
        if not title:
            return ""
        try:
            info = get_track_metadata_with_fallback(
                self.artist,
                title,
            )
        except Exception as exc:
            print(f"[cover] metadata lookup failed for {self.query!r}: {exc}")
            return ""

        cover_path = info.get("cover_path")
        if cover_path and Path(str(cover_path)).is_file():
            return str(cover_path)
        return ""


class HoverImageLabel(QLabel):
    """QLabel с подсветкой и карандашом при наведении и сигналом clicked."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._editable = True
        self.setCursor(Qt.PointingHandCursor)
        icons_dir = Path(__file__).parent / "icons" / "black"
        self._pencil = svg_file_pixmap(icons_dir / "pencil.svg", 32)

    def set_editable(self, editable: bool) -> None:
        """Включает/выключает клик, курсор и подсветку редактирования."""
        self._editable = editable
        self.setCursor(
            Qt.PointingHandCursor if editable else Qt.ArrowCursor
        )
        if not editable:
            self._hovered = False
        self.update()

    def enterEvent(self, event):
        if self._editable:
            self._hovered = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._editable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hovered and self._editable:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
            if not self._pencil.isNull():
                draw_centered(painter, QRectF(self.rect()), self._pencil)
            painter.end()


class BannerLabel(HoverImageLabel):
    """Баннер: картинка масштабируется и обрезается, сжимается с окном."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setScaledContents(False)
        self._source = QPixmap()

    def set_image(self, source):
        """Задаёт картинку баннера: путь, QPixmap, байты или None."""
        if isinstance(source, QPixmap):
            self._source = source
        elif isinstance(source, (bytes, bytearray)):
            self._source = QPixmap()
            self._source.loadFromData(bytes(source))
        else:
            self._source = QPixmap(source) if source else QPixmap()
        self._update_crop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_crop()

    def _update_crop(self):
        if self._source.isNull():
            self.clear()
            return
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        pixmap = new_pixmap(size.width(), size.height())
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        draw_cover(painter, QRectF(0, 0, size.width(), size.height()), self._source)
        painter.end()
        self.setPixmap(pixmap)

    def paintEvent(self, event):
        if self._source.isNull():
            painter = QPainter(self)
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor("#5151ab"))
            gradient.setColorAt(1.0, QColor("#2b2b6b"))
            painter.fillRect(self.rect(), gradient)
            painter.end()
        super().paintEvent(event)


class BBCodeEditorDialog(QDialog):
    """Современный редактор BBCode: панель форматирования, сплит-предпросмотр."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        lang = _lang()
        self.setWindowTitle(tr("Edit About Me", lang))
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.resize(760, 540)
        self._build_ui(text, lang)

    # ------------------------------------------------------------------
    def _build_ui(self, text, lang):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        container = QFrame()
        container.setObjectName("bbRoot")
        container.setFocusPolicy(Qt.NoFocus)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        container.setGraphicsEffect(shadow)
        root.addWidget(container)

        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Заголовок (безрамочное окно перетаскивается за него)
        col.addWidget(_DialogTitleBar(self, tr("Edit About Me", lang)))

        # Панель форматирования
        toolbar = QWidget()
        toolbar_row = QHBoxLayout(toolbar)
        toolbar_row.setContentsMargins(14, 2, 14, 10)
        toolbar_row.setSpacing(2)

        tools = (
            ("bold", "Bold", lambda: self._wrap("[b]", "[/b]")),
            ("italic", "Italic", lambda: self._wrap("[i]", "[/i]")),
            ("underline", "Underline", lambda: self._wrap("[u]", "[/u]")),
            ("link", "Insert Link", self._insert_link),
            ("image", "Insert Image", self._insert_image),
            ("center", "Align Center",
             lambda: self._wrap("[centre]", "[/centre]")),
        )
        for key, tip_key, handler in tools:
            button = QPushButton()
            button.setObjectName("bbTool")
            button.setFlat(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tr(tip_key, lang))
            button.setIcon(_svg_icon(_FORMAT_ICONS[key], "#ffffff"))
            button.setIconSize(QSize(20, 20))
            button.clicked.connect(handler)
            toolbar_row.addWidget(button)
        toolbar_row.addStretch(1)
        col.addWidget(toolbar)

        # Сплит: редактор BBCode + живой предпросмотр
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("bbSplitter")
        splitter.setFocusPolicy(Qt.NoFocus)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        editor_wrap = QWidget()
        editor_col = QVBoxLayout(editor_wrap)
        editor_col.setContentsMargins(14, 0, 6, 0)
        editor_col.setSpacing(6)
        editor_caption = QLabel(tr("BBCode", lang))
        editor_caption.setObjectName("bbHint")
        self.editor = QTextEdit()
        self.editor.setObjectName("bbEditor")
        self.editor.setAcceptRichText(False)
        self.editor.setPlainText(text or "")
        self.editor.setPlaceholderText(tr("BBCode placeholder", lang))
        editor_col.addWidget(editor_caption)
        editor_col.addWidget(self.editor, 1)

        preview_wrap = QWidget()
        preview_col = QVBoxLayout(preview_wrap)
        preview_col.setContentsMargins(6, 0, 14, 0)
        preview_col.setSpacing(6)
        preview_caption = QLabel(tr("Preview", lang))
        preview_caption.setObjectName("bbHint")
        self.preview = QTextBrowser()
        self.preview.setObjectName("bbPreview")
        self.preview.setOpenExternalLinks(True)
        preview_col.addWidget(preview_caption)
        preview_col.addWidget(self.preview, 1)

        splitter.addWidget(editor_wrap)
        splitter.addWidget(preview_wrap)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        col.addWidget(splitter, 1)

        # Нижняя панель: подсказка + кнопки + ресайз-грип
        footer = QWidget()
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(16, 10, 12, 12)
        footer_row.setSpacing(10)

        hint = QLabel(tr("Live preview", lang))
        hint.setObjectName("bbHint")
        footer_row.addWidget(hint)
        footer_row.addStretch(1)

        self.cancel_button = QPushButton(tr("Cancel", lang))
        self.cancel_button.setObjectName("bbCancel")
        self.cancel_button.setFlat(True)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)

        self.save_button = QPushButton(tr("Save", lang))
        self.save_button.setObjectName("bbSave")
        self.save_button.setFlat(True)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)

        footer_row.addWidget(self.cancel_button)
        footer_row.addWidget(self.save_button)
        footer_row.addWidget(QSizeGrip(container))
        col.addWidget(footer)

        self.editor.textChanged.connect(self._update_preview)
        self._update_preview()

        self.setStyleSheet(_BBCODE_DIALOG_QSS)
        self.editor.setFocus()

    # ------------------------------------------------------------------
    def _wrap(self, open_tag, close_tag):
        """Оборачивает выделение (или вставляет заглушку) BBCode-тегом."""
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if selected:
            cursor.insertText(f"{open_tag}{selected}{close_tag}")
        else:
            placeholder = "text"
            cursor.insertText(f"{open_tag}{placeholder}{close_tag}")
            start = cursor.position() - len(close_tag) - len(placeholder)
            cursor.setPosition(start)
            cursor.setPosition(start + len(placeholder), cursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _insert_link(self):
        """Вставляет [url=...]...[/url] (текст = выделение или сам адрес)."""
        lang = _lang()
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        url, ok = QInputDialog.getText(
            self, tr("Insert Link", lang), tr("URL", lang), text="https://"
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        cursor.insertText(f"[url={url}]{selected or url}[/url]")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _insert_image(self):
        """Вставляет [img]URL[/img]."""
        lang = _lang()
        url, ok = QInputDialog.getText(
            self, tr("Insert Image", lang), tr("Image URL", lang),
            text="https://",
        )
        if not ok or not url.strip():
            return
        cursor = self.editor.textCursor()
        cursor.insertText(f"[img]{url.strip()}[/img]")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _update_preview(self):
        self.preview.setHtml(parse_bbcode(self.editor.toPlainText()))

    def value(self):
        return self.editor.toPlainText().strip()


class _FriendProfileWorker(QThread):
    """Загружает чужой профиль и его публичные плейлисты."""

    loaded = pyqtSignal(dict, list)
    failed = pyqtSignal(str, int)

    def __init__(self, user_id: int, token: str | None, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.token = token

    def run(self) -> None:
        try:
            client = ApiClient(token=self.token)
            profile = client.get_user_profile(self.user_id)
            playlists = client.get_user_playlists(self.user_id)
        except ApiError as exc:
            self.failed.emit(str(exc), exc.status_code or 0)
        except Exception as exc:  # noqa: BLE001 - не роняем UI из-за потока
            self.failed.emit(f"Unexpected error: {exc}", 0)
        else:
            self.loaded.emit(profile, playlists)


class _ProfileSyncWorker(QThread):
    """Отправляет изменения профиля на сервер в фоновом потоке."""

    synced = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        token: str,
        payload: dict,
        avatar_path: str | None = None,
        banner_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.token = token
        self.payload = dict(payload)
        self.avatar_path = avatar_path
        self.banner_path = banner_path

    def run(self) -> None:
        data = dict(self.payload)
        for key, path in (
            ("avatar_base64", self.avatar_path),
            ("banner_base64", self.banner_path),
        ):
            if not path:
                continue
            try:
                data[key] = base64.b64encode(
                    Path(path).read_bytes()
                ).decode("ascii")
            except OSError as exc:
                self.failed.emit(f"Cannot read profile image: {exc}")
                return

        try:
            result = ApiClient(token=self.token).update_my_profile(data)
        except ApiError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - не роняем UI из-за потока
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.synced.emit(result)


class ProfilePage(QWidget):
    """Вкладка «Профиль»: шапка и локальная статистика прослушиваний."""

    playlist_clicked = pyqtSignal(int)
    avatar_changed = pyqtSignal(str)
    back_requested = pyqtSignal()
    playlist_download_requested = pyqtSignal(int)

    BANNER_HEIGHT = 150
    AVATAR_SIZE = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self._icon_labels = []
        self._cover_loaders = {}
        self._cover_labels = {}
        self._banner_path = None
        self._avatar_path = None
        self._friend_mode = False
        self._friend_user_id = None
        self._friend_worker = None
        self._friend_playlists = []
        self._sync_workers = set()
        self._build_ui()
        self._refresh_status()
        self.reload_stats()

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        lang = _lang()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Баннер: сжимается вместе с окном, картинка обрезается.
        self.banner_label = BannerLabel()
        self.banner_label.setFixedHeight(self.BANNER_HEIGHT)
        self.banner_label.clicked.connect(self._change_banner)
        content_layout.addWidget(self.banner_label)

        # --- Шапка: аватарка, никнейм, достижения ---
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 16)
        header_layout.setSpacing(16)

        self.avatar_label = HoverImageLabel()
        self.avatar_label.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
        self.avatar_label.clicked.connect(self._change_avatar)
        header_layout.addWidget(self.avatar_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.back_button = QPushButton(tr("Back", lang))
        self.back_button.setObjectName("profileBackButton")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setIcon(
            colored_icon("back.svg", _icon_color())
        )
        self.back_button.setIconSize(QSize(16, 16))
        self.back_button.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " padding: 2px 0; }"
        )
        self.back_button.clicked.connect(self.back_requested.emit)
        self.back_button.hide()
        text_col.addWidget(self.back_button, 0, Qt.AlignLeft)

        self.nickname_label = _DoubleClickLabel()
        self.nickname_label.setObjectName("profileNickname")
        self.nickname_label.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )
        self.nickname_label.setToolTip(
            tr("Double-click to edit the nickname", lang)
        )
        self.nickname_label.doubleClicked.connect(self._edit_nickname)
        text_col.addWidget(self.nickname_label)

        self.status_label = QLabel()
        self.status_label.setObjectName("profileStatusLabel")
        text_col.addWidget(self.status_label)

        self.auth_button = QPushButton("Log In / Register")
        self.auth_button.setObjectName("profileAuthButton")
        self.auth_button.setCursor(Qt.PointingHandCursor)
        self.auth_button.clicked.connect(self._open_auth_dialog)
        text_col.addWidget(self.auth_button, 0, Qt.AlignLeft)

        text_col.addStretch(1)
        header_layout.addLayout(text_col, 1)

        # Блок достижений (справа от аватарки и никнейма)
        self.achievements_container = QWidget()
        self.achievements_layout = QHBoxLayout(self.achievements_container)
        self.achievements_layout.setContentsMargins(0, 0, 0, 0)
        self.achievements_layout.setSpacing(12)
        header_layout.addWidget(self.achievements_container, 0, Qt.AlignTop)

        content_layout.addWidget(header)

        # --- About Me (на всю ширину, рендер BBCode) ---
        about = QWidget()
        about_layout = QVBoxLayout(about)
        about_layout.setContentsMargins(20, 0, 20, 12)
        about_layout.setSpacing(6)
        about_layout.addWidget(
            self._section_title("user.svg", tr("About Me", lang))
        )
        self.description_label = ProfileTextBrowser()
        self.description_label.setObjectName("profileDescription")
        self.description_label.setToolTip(
            tr("Double-click to edit About Me", lang)
        )
        self.description_label.doubleClicked.connect(self._edit_about)
        about_layout.addWidget(self.description_label)
        content_layout.addWidget(about)

        # --- Статистика: две колонки, выровненные по верхнему краю ---
        stats = QWidget()
        stats_grid = QGridLayout(stats)
        self.stats_grid = stats_grid
        stats_grid.setContentsMargins(20, 8, 20, 20)
        stats_grid.setHorizontalSpacing(32)
        stats_grid.setVerticalSpacing(0)

        # Левая колонка: Total Time, Top Tracks
        left = QWidget()
        self.left_stats_widget = left
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(18)

        # Total Time
        total_box = QVBoxLayout()
        total_box.setSpacing(6)
        total_title = self._section_title("time.svg", tr("Total Time", lang))
        self.total_time_label = QLabel()
        font = self.total_time_label.font()
        font.setPointSize(font.pointSize() + 14)
        font.setBold(True)
        self.total_time_label.setFont(font)
        total_box.addWidget(total_title)
        total_box.addWidget(self.total_time_label)
        left_col.addLayout(total_box)

        # Top Tracks
        self.top_tracks_title = self._section_title(
            "count.svg", tr("Top Tracks", lang)
        )
        left_col.addWidget(self.top_tracks_title)
        self.top_tracks_container = QWidget()
        self.top_tracks_layout = QVBoxLayout(self.top_tracks_container)
        self.top_tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.top_tracks_layout.setSpacing(6)
        left_col.addWidget(self.top_tracks_container)
        left_col.addStretch(1)

        # Правая колонка: Favorite Track, Public Playlists
        right = QWidget()
        self.right_stats_widget = right
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(18)

        # Favorite Track
        self.favorite_title = self._section_title(
            "favorite.svg", tr("Favorite Track", lang)
        )
        right_col.addWidget(self.favorite_title)
        self.favorite_container = QWidget()
        self.favorite_layout = QVBoxLayout(self.favorite_container)
        self.favorite_layout.setContentsMargins(0, 0, 0, 0)
        self.favorite_layout.setSpacing(6)
        right_col.addWidget(self.favorite_container)

        # Public Playlists: компактная сетка кликабельных карточек
        self.public_playlists_title = self._section_title(
            "create-playlist.svg", tr("Public Playlists", lang)
        )
        right_col.addWidget(self.public_playlists_title)
        self.public_playlists_container = QWidget()
        self.public_playlists_grid = QGridLayout(self.public_playlists_container)
        self.public_playlists_grid.setContentsMargins(0, 0, 0, 0)
        self.public_playlists_grid.setSpacing(10)
        self.public_playlists_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        right_col.addWidget(self.public_playlists_container)
        right_col.addStretch(1)

        # Обе колонки начинаются на одном уровне (Qt.AlignTop)
        stats_grid.addWidget(left, 0, 0, Qt.AlignTop)
        stats_grid.addWidget(right, 0, 1, Qt.AlignTop)
        stats_grid.setColumnStretch(0, 1)
        stats_grid.setColumnStretch(1, 1)

        content_layout.addWidget(stats)
        content_layout.addStretch(1)
        self.stats_widget = stats

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidget(content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll_area)

    # ------------------------------------------------------------------
    #  Авторизация
    # ------------------------------------------------------------------
    def _open_auth_dialog(self) -> None:
        dialog = AuthDialog(self)
        dialog.logged_in.connect(self._on_logged_in)
        dialog.exec_()

    def _on_logged_in(self, token: str) -> None:
        try:
            user = ApiClient(token=token).get_me()
        except ApiError as exc:
            QMessageBox.warning(self, "Authorization", str(exc))
            return
        self.set_authenticated(user.get("username", ""))
        self._sync_stats_to_server()

    def set_authenticated(self, username: str) -> None:
        """Запоминает имя пользователя и показывает статус Online."""
        if username:
            self.settings.setValue("api_username", username)
        self._refresh_status()

    def reset_auth_button(self) -> None:
        """Сбрасывает кнопку входа и пересчитывает статус по токену."""
        self.auth_button.setText("Log In / Register")
        self.auth_button.setEnabled(True)
        self.auth_button.setToolTip("")
        self._refresh_status()

    def _has_token(self) -> bool:
        token = self.settings.value("api_token")
        return isinstance(token, str) and bool(token.strip())

    def _refresh_status(self) -> None:
        """Online при наличии токена, иначе Offline."""
        lang = _lang()
        if self._has_token():
            self.status_label.setText("● " + tr("Online", lang))
            self.status_label.setStyleSheet(
                "color: #1db954; font-weight: 600; font-size: 13px;"
            )
            self.auth_button.hide()
        else:
            self.status_label.setText("● " + tr("Offline", lang))
            self.status_label.setStyleSheet(
                "color: #8a8a8a; font-weight: 600; font-size: 13px;"
            )
            self.auth_button.show()

    # ------------------------------------------------------------------
    #  Чужой профиль
    # ------------------------------------------------------------------
    def _set_friend_mode(self, enabled: bool) -> None:
        """Переключает режим просмотра чужого профиля без редактирования."""
        lang = _lang()
        self._friend_mode = enabled
        self.back_button.setVisible(enabled)
        self.achievements_container.setVisible(not enabled)
        self.status_label.setVisible(not enabled)
        self.avatar_label.set_editable(not enabled)
        self.banner_label.set_editable(not enabled)

        # Статистика и любимый трек остаются на месте: в режиме друга
        # они заполняются данными с сервера.
        self.left_stats_widget.setVisible(True)
        self.favorite_title.setVisible(True)
        self.favorite_container.setVisible(True)
        self.stats_grid.addWidget(self.right_stats_widget, 0, 1, Qt.AlignTop)

        if enabled:
            self.auth_button.hide()
            self.nickname_label.setToolTip("")
            self.description_label.setToolTip("")
        else:
            self._friend_user_id = None
            self.nickname_label.setToolTip(
                tr("Double-click to edit the nickname", lang)
            )
            self.description_label.setToolTip(
                tr("Double-click to edit About Me", lang)
            )
            self._refresh_status()

    def load_friend_profile(self, user_id: int) -> None:
        """Загружает чужой профиль и его публичные плейлисты с сервера."""
        lang = _lang()
        token = self.settings.value("api_token")
        if not isinstance(token, str) or not token.strip():
            QMessageBox.warning(
                self,
                tr("Profile", lang),
                tr("Please log in to view profiles", lang),
            )
            return

        self._set_friend_mode(True)
        self._friend_user_id = int(user_id)
        self._cover_labels = {}
        self.nickname_label.setText(tr("Loading...", lang))
        self.description_label.setText("")
        self._apply_banner(None)
        self._apply_avatar(None)
        self.total_time_label.setText(self._format_total(0))
        self._fill_friend_top_tracks([], lang)
        self._fill_friend_favorite(None, lang)
        self._clear_layout(self.public_playlists_grid)
        loading = QLabel(tr("Loading...", lang))
        loading.setStyleSheet("color: #8a8a8a;")
        self.public_playlists_grid.addWidget(loading, 0, 0)

        worker = _FriendProfileWorker(self._friend_user_id, token, self)
        worker.loaded.connect(self._on_friend_profile_loaded)
        worker.failed.connect(
            lambda message, code, uid=self._friend_user_id: (
                self._on_friend_profile_error(uid, message, code)
            )
        )
        worker.finished.connect(
            lambda w=worker: self._on_friend_worker_finished(w)
        )
        self._friend_worker = worker
        worker.start()

    def _on_friend_profile_loaded(
        self, profile: dict, playlists: list
    ) -> None:
        if not self._friend_mode:
            return
        if int(profile.get("id") or 0) != self._friend_user_id:
            return

        lang = _lang()
        username = str(profile.get("username") or "")
        nickname = str(profile.get("nickname") or username or "Music Lover")
        self.nickname_label.setText(nickname)

        description = str(profile.get("description") or "")
        if description:
            self.description_label.setText(_description_html(description))
        else:
            self.description_label.setText(tr("No description", lang))

        self._apply_banner(
            profile.get("banner_bytes") or profile.get("banner_path")
        )
        self._apply_avatar(
            profile.get("avatar_bytes") or profile.get("avatar_path")
        )

        self.total_time_label.setText(
            self._format_total(int(profile.get("listening_time") or 0))
        )
        self._fill_friend_top_tracks(profile.get("top_tracks") or [], lang)
        self._fill_friend_favorite(profile.get("favorite_track"), lang)

        self._friend_playlists = list(playlists or [])
        self._fill_friend_playlists(lang)

    def _on_friend_profile_error(
        self, user_id: int, message: str, status_code: int
    ) -> None:
        if not self._friend_mode or user_id != self._friend_user_id:
            return
        lang = _lang()
        text = (
            tr("This profile is private", lang)
            if status_code == 403
            else message
        )
        self.description_label.setText(text)
        self.total_time_label.setText(self._format_total(0))
        self._fill_friend_top_tracks([], lang)
        self._fill_friend_favorite(None, lang)
        self._clear_layout(self.public_playlists_grid)
        empty = QLabel(tr("No playlists yet", lang))
        empty.setStyleSheet("color: #8a8a8a;")
        self.public_playlists_grid.addWidget(empty, 0, 0)
        QMessageBox.warning(self, tr("Profile", lang), text)

    def _on_friend_worker_finished(self, worker) -> None:
        if self._friend_worker is worker:
            self._friend_worker = None
        worker.deleteLater()

    def show_own_profile(self) -> None:
        """Возвращает страницу к локальному (своему) профилю."""
        self.reload_stats()

    def _remote_track_row(self, track, index):
        """Строка трека из JSON-статистики друга."""
        if not isinstance(track, dict):
            return None
        title = str(track.get("title") or "Unknown track")
        artist = str(track.get("artist") or "")
        cover = track.get("cover") or ""
        if not (
            isinstance(cover, (str, Path))
            and cover
            and Path(cover).is_file()
        ):
            cover = ""

        raw_key = (
            f"{self._friend_user_id}:{index}:"
            f"{track.get('id')}:{title}:{artist}"
        )
        track_key = -(abs(hash(raw_key)) % 2_000_000_000 + 1)
        return self._track_row(
            track_key,
            cover,
            title,
            artist or None,
            query=self._cover_query(artist, title),
        )

    def _fill_friend_top_tracks(self, tracks, lang):
        self._clear_layout(self.top_tracks_layout)
        if not tracks:
            empty = QLabel(tr("No plays yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.top_tracks_layout.addWidget(empty)
            return
        for index, track in enumerate(tracks):
            row = self._remote_track_row(track, index)
            if row is not None:
                self.top_tracks_layout.addWidget(row)

    def _fill_friend_favorite(self, track, lang):
        self._clear_layout(self.favorite_layout)
        if not isinstance(track, dict) or not track:
            label = QLabel(tr("No favorite track yet", lang))
            label.setStyleSheet("color: #8a8a8a;")
            self.favorite_layout.addWidget(label)
            return
        row = self._remote_track_row(track, 0)
        if row is None:
            label = QLabel(tr("No favorite track yet", lang))
            label.setStyleSheet("color: #8a8a8a;")
            self.favorite_layout.addWidget(label)
        else:
            self.favorite_layout.addWidget(row)

    def _fill_friend_playlists(self, lang: str) -> None:
        self._clear_layout(self.public_playlists_grid)
        if not self._friend_playlists:
            empty = QLabel(tr("No playlists yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.public_playlists_grid.addWidget(empty, 0, 0)
            return

        dark = _theme_is_dark()
        for index, playlist in enumerate(self._friend_playlists):
            card = QFrame()
            card.setObjectName("remotePlaylistCard")
            card.setFixedWidth(190)
            card.setStyleSheet(
                "#remotePlaylistCard { background: transparent;"
                " border-radius: 10px; }"
                + (
                    "#remotePlaylistCard:hover {"
                    " background: rgba(255, 255, 255, 0.08); }"
                    if dark
                    else "#remotePlaylistCard:hover {"
                    " background: rgba(0, 0, 0, 0.06); }"
                )
            )
            col = QVBoxLayout(card)
            col.setContentsMargins(6, 6, 6, 6)
            col.setSpacing(6)

            cover = QLabel()
            cover.setFixedSize(64, 64)
            cover.setAlignment(Qt.AlignCenter)
            cover.setPixmap(_cover_pixmap(None, 64))
            col.addWidget(cover, 0, Qt.AlignHCenter)

            row = QHBoxLayout()
            row.setSpacing(6)
            name = QLabel(str(playlist.get("name") or ""))
            name.setWordWrap(True)
            row.addWidget(name, 1)

            download = QPushButton(tr("Download", lang))
            download.setCursor(Qt.PointingHandCursor)
            download.setIcon(
                colored_icon("download.svg", _icon_color())
            )
            download.setIconSize(QSize(14, 14))
            download.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                " padding: 2px 4px; }"
                "QPushButton:hover { color: #5151ab; }"
            )
            playlist_id = int(playlist.get("id") or 0)
            download.clicked.connect(
                lambda _checked=False, pid=playlist_id: (
                    self.playlist_download_requested.emit(pid)
                )
            )
            row.addWidget(download)
            col.addLayout(row)

            self.public_playlists_grid.addWidget(
                card, index // 2, index % 2
            )

    def _section_title(self, icon_name, text):
        """Заголовок секции: иконка + подпись."""
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(
            colored_pixmap(icon_name, 20, _icon_color())
        )
        self._icon_labels.append((icon_label, icon_name))

        caption = QLabel(text)
        font = caption.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        caption.setFont(font)

        row.addWidget(icon_label)
        row.addWidget(caption)
        row.addStretch(1)
        return widget

    def _track_row(self, track_id, cover_path, title, subtitle=None, query=None):
        """Карточка трека: обложка + название (+ вторичный текст)."""
        wrapper = QFrame()
        wrapper.setFrameShape(QFrame.NoFrame)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        cover = QLabel()
        cover.setFixedSize(36, 36)
        self._set_cover(
            cover,
            track_id,
            cover_path,
            query,
            artist=subtitle,
            title=title,
        )
        row.addWidget(cover)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(title)
        font = title_label.font()
        font.setBold(True)
        title_label.setFont(font)
        text_col.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet("color: #8a8a8a;")
            text_col.addWidget(subtitle_label)

        row.addLayout(text_col, 1)
        return wrapper

    def _set_cover(
        self,
        cover_label,
        track_id,
        cover_path,
        query,
        artist=None,
        title=None,
    ):
        """Ставит локальную обложку или заглушку + подгружает её из сети."""
        if cover_path:
            cover_label.setPixmap(_cover_pixmap(cover_path, 36))
            return

        cached = PROFILE_COVERS_DIR / f"{track_id}.jpg"
        if cached.exists() and cached.stat().st_size > 0:
            cover_label.setPixmap(_cover_pixmap(str(cached), 36))
            return

        cover_label.setPixmap(_cover_pixmap(None, 36))
        self._cover_labels.setdefault(track_id, []).append(cover_label)
        self._start_cover_loader(
            track_id,
            query,
            artist=artist,
            title=title,
        )

    def _start_cover_loader(self, track_id, query, artist=None, title=None):
        if not query and not title:
            return
        loader = self._cover_loaders.get(track_id)
        if loader is not None and loader.isRunning():
            return
        loader = CoverLoader(
            track_id,
            query,
            self,
            artist=artist,
            title=title,
        )
        loader.loaded.connect(self._on_cover_loaded)
        self._cover_loaders[track_id] = loader
        loader.start()

    def _on_cover_loaded(self, track_id, pixmap):
        for label in self._cover_labels.get(track_id, []):
            label.setPixmap(_cover_pixmap(pixmap, 36))

    @staticmethod
    def _cover_query(artist, title):
        return " ".join(p for p in (artist, title) if p).strip()

    # ------------------------------------------------------------------
    #  Данные
    # ------------------------------------------------------------------
    def reload_stats(self):
        """Перечитывает профиль и статистику из БД."""
        lang = _lang()
        self._set_friend_mode(False)
        self._apply_icon_theme()
        self._cover_labels = {}

        profile = db.get_profile()
        nickname = (profile["nickname"] if profile else "") or "Music Lover"
        description = (profile["description"] if profile else "") or ""
        self.nickname_label.setText(nickname)
        if description:
            self.description_label.setText(_description_html(description))
        else:
            self.description_label.setText(
                tr("Double-click to add a description", lang)
            )
        self._apply_banner(profile["banner_path"] if profile else None)
        self._apply_avatar(profile["avatar_path"] if profile else None)

        total_sec = db.get_total_play_time()
        self.total_time_label.setText(self._format_total(total_sec))

        self._fill_achievements()
        self._fill_top_tracks(db.get_top_tracks(5), lang)
        self._fill_favorite(
            profile["favorite_track_id"] if profile else None, lang
        )
        self._fill_public_playlists(lang)

    def _apply_icon_theme(self):
        """Перекрашивает иконки под текущую тему."""
        color = _icon_color()
        for icon_label, icon_name in self._icon_labels:
            icon_label.setPixmap(colored_pixmap(icon_name, 20, color))

    def _apply_banner(self, source):
        """Показывает баннер (путь/QPixmap/байты) или градиентную заглушку."""
        if isinstance(source, (str, Path)) and source:
            self._banner_path = str(source)
            self.banner_label.set_image(
                self._banner_path
                if Path(self._banner_path).is_file()
                else None
            )
        elif isinstance(source, (QPixmap, bytes, bytearray)):
            self._banner_path = None
            self.banner_label.set_image(source)
        else:
            self._banner_path = None
            self.banner_label.set_image(None)

    def _apply_avatar(self, source):
        """Показывает круглую аватарку (путь/QPixmap/байты) или заглушку."""
        if isinstance(source, (str, Path)) and source:
            self._avatar_path = str(source)
            source = self._avatar_path if Path(self._avatar_path).is_file() else None
        else:
            self._avatar_path = None
        self.avatar_label.setPixmap(
            _round_avatar_pixmap(source, self.AVATAR_SIZE)
        )

    def _fill_achievements(self):
        """Пересобирает блок достижений в шапке."""
        self._clear_layout(self.achievements_layout)

        values = {
            "tracks": db.get_tracks_count(),
            "playlists": db.get_playlists_count(),
            "time": db.get_total_play_time(),
            "age": db.get_app_age_days(),
        }
        lang = _lang()

        for key, icon_name, thresholds, caption in ACHIEVEMENTS:
            value = values.get(key, 0)
            level = _achievement_level(value, thresholds)
            color = (
                ACHIEVEMENT_COLORS[level - 1]
                if level > 0 else ACHIEVEMENT_LOCKED_COLOR
            )
            shown = _format_achievement_value(key, value)
            label = tr(caption, lang)
            if level >= len(thresholds):
                tier = tr(ACHIEVEMENT_TIERS[level - 1], lang)
                tooltip = f"{label}: {shown} \u2014 {tier}"
            else:
                target = _format_achievement_value(key, thresholds[level])
                tooltip = f"{label}: {shown} / {target}"

            box = QWidget()
            box.setToolTip(tooltip)
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)

            icon_label = QLabel()
            icon_label.setPixmap(colored_pixmap(icon_name, 28, color))
            icon_label.setAlignment(Qt.AlignCenter)

            value_label = QLabel(shown)
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet("color: #8a8a8a; font-size: 10px;")

            col.addWidget(icon_label)
            col.addWidget(value_label)
            self.achievements_layout.addWidget(box)

    @staticmethod
    def _format_total(seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}:{minutes:02d}"

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_top_tracks(self, rows, lang):
        self._clear_layout(self.top_tracks_layout)
        if not rows:
            empty = QLabel(tr("No plays yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.top_tracks_layout.addWidget(empty)
            return
        for row in rows:
            cover_path = metadata.extract_cover(row["file_path"], row["id"])
            title = row["title"] or Path(row["file_path"]).stem
            self.top_tracks_layout.addWidget(
                self._track_row(
                    row["id"], cover_path, title,
                    query=self._cover_query(row["artist"], title),
                )
            )

    def _fill_favorite(self, track_id, lang):
        self._clear_layout(self.favorite_layout)
        track = db.get_track_by_id(track_id) if track_id else None
        if track is None:
            label = QLabel(tr("No favorite track yet", lang))
            label.setStyleSheet("color: #8a8a8a;")
            self.favorite_layout.addWidget(label)
            return
        cover_path = metadata.extract_cover(track["file_path"], track["id"])
        title = track["title"] or Path(track["file_path"]).stem
        self.favorite_layout.addWidget(
            self._track_row(
                track["id"], cover_path, title, track["artist"],
                query=self._cover_query(track["artist"], title),
            )
        )

    def _playlist_card(self, playlist):
        """Компактная кликабельная карточка плейлиста: обложка + название."""
        cover_path = playlist["cover_path"]
        if not cover_path:
            first = db.get_first_track_in_playlist(playlist["id"])
            if first:
                cover_path = metadata.extract_cover(
                    first["file_path"], first["id"]
                )

        card = _ClickableCard(playlist["id"])
        card.setObjectName("playlistCard")
        card.setStyleSheet(
            "#playlistCard { background: transparent; border-radius: 10px; }"
            "#playlistCard:hover { background: rgba(255, 255, 255, 0.08); }"
        )
        card.setFixedWidth(96)
        card.setToolTip(playlist["name"])
        col = QVBoxLayout(card)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(4)

        cover = QLabel()
        cover.setFixedSize(64, 64)
        cover.setAlignment(Qt.AlignCenter)
        cover.setPixmap(_cover_pixmap(cover_path, 64))
        col.addWidget(cover, 0, Qt.AlignHCenter)

        name = QLabel(playlist["name"])
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        col.addWidget(name)

        return card

    def _fill_public_playlists(self, lang):
        self._clear_layout(self.public_playlists_grid)
        playlists = db.get_all_playlists()
        if not playlists:
            empty = QLabel(tr("No playlists yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.public_playlists_grid.addWidget(empty, 0, 0)
            return
        for index, playlist in enumerate(playlists):
            card = self._playlist_card(playlist)
            card.clicked.connect(self.playlist_clicked.emit)
            self.public_playlists_grid.addWidget(card, index // 2, index % 2)

    def shutdown(self):
        """Дожидается фоновой подгрузки обложек при закрытии приложения."""
        if self._friend_worker is not None and self._friend_worker.isRunning():
            self._friend_worker.wait(3000)
        for worker in list(self._sync_workers):
            if worker.isRunning():
                worker.wait(3000)
        self._sync_workers.clear()
        for loader in list(self._cover_loaders.values()):
            if loader.isRunning():
                loader.wait(3000)
        self._cover_loaders.clear()

    # ------------------------------------------------------------------
    #  Синхронизация с сервером
    # ------------------------------------------------------------------
    def _track_stats_payload(self, track):
        """Преобразует локальный трек в JSON-совместимый словарь."""
        if track is None:
            return None
        file_path = track["file_path"]
        title = track["title"] or Path(file_path).stem
        try:
            cover = metadata.extract_cover(file_path, track["id"]) or ""
        except Exception:
            cover = ""
        return {
            "id": track["id"],
            "title": title,
            "artist": track["artist"] or "",
            "cover": cover,
        }

    def _build_stats_payload(self):
        profile = db.get_profile()
        favorite_id = profile["favorite_track_id"] if profile else None
        favorite = (
            self._track_stats_payload(db.get_track_by_id(favorite_id))
            if favorite_id
            else None
        )
        top_tracks = [
            payload
            for payload in (
                self._track_stats_payload(row)
                for row in db.get_top_tracks(5)
            )
            if payload is not None
        ]
        return {
            "listening_time": db.get_total_play_time(),
            "tracks_count": db.get_tracks_count(),
            "playlists_count": db.get_playlists_count(),
            "app_age_days": db.get_app_age_days(),
            "favorite_track": favorite,
            "top_tracks": top_tracks,
        }

    def _sync_stats_to_server(self) -> None:
        """Отправляет актуальную локальную статистику на сервер."""
        token = self.settings.value("api_token")
        if not isinstance(token, str) or not token.strip():
            return
        self._sync_profile_to_server(
            stats=self._build_stats_payload(), silent=True
        )

    def sync_stats_to_server(self) -> None:
        """Публичная точка входа для периодической синхронизации."""
        self._sync_stats_to_server()

    def _sync_profile_to_server(
        self,
        *,
        avatar_path=None,
        banner_path=None,
        nickname=None,
        description=None,
        stats=None,
        silent=False,
    ) -> None:
        """Отправляет изменения профиля на сервер в фоновом потоке."""
        token = self.settings.value("api_token")
        if not isinstance(token, str) or not token.strip():
            return

        payload = {}
        if nickname is not None:
            payload["nickname"] = nickname
        if description is not None:
            payload["description"] = description
        if stats is not None:
            payload["stats"] = stats
        if not payload and not avatar_path and not banner_path:
            return

        worker = _ProfileSyncWorker(
            token,
            payload,
            avatar_path=str(avatar_path) if avatar_path else None,
            banner_path=str(banner_path) if banner_path else None,
            parent=self,
        )
        if not silent:
            worker.failed.connect(self._on_profile_sync_failed)
        worker.finished.connect(
            lambda w=worker: self._on_profile_sync_finished(w)
        )
        self._sync_workers.add(worker)
        worker.start()

    def _on_profile_sync_failed(self, message: str) -> None:
        lang = _lang()
        QMessageBox.warning(self, tr("Profile", lang), message)

    def _on_profile_sync_finished(self, worker) -> None:
        self._sync_workers.discard(worker)
        worker.deleteLater()

    # ------------------------------------------------------------------
    #  Действия
    # ------------------------------------------------------------------
    def _change_banner(self):
        if self._friend_mode:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select Banner", _lang()), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            new_path = _copy_profile_image(path, "banner")
        except OSError:
            return
        db.update_profile(banner_path=str(new_path))
        self._apply_banner(str(new_path))
        self._sync_profile_to_server(banner_path=str(new_path))

    def _change_avatar(self):
        if self._friend_mode:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Select Avatar", _lang()), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            new_path = _copy_profile_image(path, "avatar")
        except OSError:
            return
        db.update_profile(avatar_path=str(new_path))
        self._apply_avatar(str(new_path))
        self.avatar_changed.emit(str(new_path))
        self._sync_profile_to_server(avatar_path=str(new_path))

    def _edit_nickname(self):
        """Смена никнейма по двойному клику."""
        if self._friend_mode:
            return
        profile = db.get_profile()
        current = (profile["nickname"] if profile else "") or ""
        lang = _lang()
        name, ok = QInputDialog.getText(
            self, tr("Edit Nickname", lang), tr("Nickname", lang), text=current
        )
        if not ok:
            return
        nickname = name.strip() or "Music Lover"
        db.update_profile(nickname=nickname)
        self.reload_stats()
        self._sync_profile_to_server(nickname=nickname)

    def _edit_about(self):
        """Редактирование описания в BBCode по двойному клику."""
        if self._friend_mode:
            return
        profile = db.get_profile()
        dialog = BBCodeEditorDialog(
            profile["description"] if profile else "", self
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        description = dialog.value()
        db.update_profile(description=description)
        self.reload_stats()
        self._sync_profile_to_server(description=description)
