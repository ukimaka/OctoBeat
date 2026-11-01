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

"""Виджеты профиля: About Me, баннер, аватарка и BBCode-редактор."""

import re

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from PyQt5.QtCore import QRectF, QSize, Qt, QVariant, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QTextDocument,
)
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dialogs import CustomInputDialog, colored_icon
from paths import RESOURCE_DIR
from pixmap_utils import draw_centered, draw_cover, new_pixmap, svg_file_pixmap
from profile_assets import _lang, _svg_icon
from translations import tr

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
    background-color: palette(window);
}
#bbRoot {
    background-color: palette(window);
    border: none;
    outline: none;
    border-radius: 12px;
}
#bbTitle {
    color: palette(window-text);
    font-size: 14px;
    font-weight: bold;
}
#bbHint {
    color: palette(mid);
    font-size: 11px;
}
QPushButton#bbTool {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px;
}
QPushButton#bbTool:hover {
    background: rgba(127, 127, 127, 0.18);
}
QPushButton#bbTool:pressed {
    background: palette(highlight);
}
QPushButton#bbClose {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
}
QPushButton#bbClose:hover {
    background: rgba(127, 127, 127, 0.22);
}
QTextEdit {
    border: 1px solid palette(mid);
}
QTextEdit#bbEditor {
    background: palette(base);
    border: 1px solid palette(mid);
    border-radius: 8px;
    color: palette(text);
    font-size: 13px;
    padding: 8px;
    selection-background-color: palette(highlight);
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
    background: palette(base);
    border: 1px solid palette(mid);
    border-radius: 8px;
    color: palette(text);
    padding: 8px;
}
QSplitter#bbSplitter::handle {
    background: transparent;
    width: 6px;
}
QPushButton#bbSave {
    background: palette(highlight);
    color: palette(highlighted-text);
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
    font-weight: bold;
}
QPushButton#bbSave:hover {
    background: palette(highlight);
}
QPushButton#bbCancel {
    background: palette(button);
    color: palette(button-text);
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
}
QPushButton#bbCancel:hover {
    background: palette(mid);
}
"""


def parse_bbcode(text):
    """BBCode → HTML (поддерживаются теги osu!-профиля)."""
    if not text:
        return ""

    html = str(text)
    flags = re.IGNORECASE | re.DOTALL

    html = re.sub(
        r"\[youtube\](.*?)\[/youtube\]",
        lambda m: '<a href="https://youtu.be/%s">YouTube Video</a>'  # noqa: UP031
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
            r"\[%s\](.*?)\[/%s\]" % (tag, tag),  # noqa: UP031
            open_tag + r"\1" + close_tag,
            html,
            flags=flags,
        )

    return html.replace("\r\n", "\n").replace("\n", "<br>")


def _description_html(text):
    """BBCode → HTML для описания профиля."""
    return parse_bbcode(text)


class ProfileTextBrowser(QTextBrowser):
    """QTextBrowser для About Me: внешние картинки и двойной клик."""

    doubleClicked = pyqtSignal()
    MAX_HEIGHT = 450
    MAX_IMAGE_CACHE = 6

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

                # Держим только несколько последних картинок: About Me
                # может содержать много внешних изображений, и без лимита
                # они оставались бы в памяти до закрытия приложения.
                if len(self._image_cache) >= self.MAX_IMAGE_CACHE:
                    self._image_cache.pop(
                        next(iter(self._image_cache)), None
                    )
                variant = QVariant(image)
                self._image_cache[key] = variant
                return variant

        return super().loadResource(resource_type, url)


class _DialogTitleBar(QWidget):
    """Заголовок безрамочного диалога с перетаскиванием окна мышью.
    Фон — QPalette.Window, слегка затемнённый (darker(110)).
    """

    def __init__(self, dialog, title, parent=None, bg_color=None):
        super().__init__(parent)
        self._dialog = dialog
        self._drag_pos = None
        self.setFixedHeight(44)
        # QSS темы применяется при полировке; без неё палитра остаётся
        # системной, и заголовок/иконка не совпадают с темой.
        self.ensurePolished()

        # Фон заголовка = QPalette.Window, слегка затемнённый. Так строка
        # заголовка совпадает с темой (светлой или тёмной) и не выбивается
        # из общего фона диалога.
        if bg_color is None:
            bg_color = QColor(self.palette().window().color()).darker(110)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, bg_color)
        self.setPalette(pal)

        # Тень под заголовком для визуального отрыва от тела диалога.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

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
        close_button.setIcon(colored_icon("cancel.svg", self.palette().windowText().color().name()))
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


class HoverImageLabel(QLabel):
    """QLabel с подсветкой и карандашом при наведении и сигналом clicked."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._editable = True
        self.setCursor(Qt.PointingHandCursor)
        icons_dir = RESOURCE_DIR / "icons" / "black"
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
            accent = self.palette().color(QPalette.Highlight)
            gradient.setColorAt(0.0, accent)
            gradient.setColorAt(1.0, accent.darker(160))
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

        # Заголовок (безрамочное окно перетаскивается за него).
        # Цвет фона _DialogTitleBar вычисляет сам после полировки палитры.
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
        url, ok = CustomInputDialog.get_text(
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
        url, ok = CustomInputDialog.get_text(
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
