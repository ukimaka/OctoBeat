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

"""Базовая обвязка безрамочных диалогов и общие иконки."""

from PyQt5.QtCore import QEvent, QSettings, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from paths import RESOURCE_DIR
from pixmap_utils import svg_file_pixmap
from styles import is_dark_theme
from translations import tr


ICONS_DIR = RESOURCE_DIR / "icons"

# Логический размер рендера SVG для QIcon. QStyle выберет из него
# физический вариант под текущий DPR.
ICON_RENDER_SIZE = 64


def colored_pixmap(filename, size, color):
    """Чёрный вектор из icons/black/ перекрашивается в color, возвращает QPixmap."""
    path = ICONS_DIR / "black" / filename
    if not path.is_file():
        return QPixmap()
    return svg_file_pixmap(path, size, color=color)


def colored_icon(filename, color="#ffffff"):
    """Перекрашенная иконка (чёрный вектор → color)."""
    pixmap = colored_pixmap(filename, ICON_RENDER_SIZE, color)
    if pixmap.isNull():
        return QIcon()
    return QIcon(pixmap)


def _theme_is_dark():
    """Текущая тема из QSettings (делегат не всегда знает её заранее)."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return is_dark_theme(settings.value("theme", "dark"))


def _dialog_lang():
    """Язык интерфейса из QSettings (диалоги создаются автономно)."""
    return QSettings("MusicPlayer", "MusicPlayer").value("language", "en")


_CUSTOM_DIALOG_QSS_TEMPLATE = """
QDialog {
    background: transparent;
}
#cdRoot {
    background-color: @BG@;
    border: none;
    outline: none;
    border-radius: 12px;
}
#cdTitle {
    color: @TEXT@;
    font-size: 14px;
    font-weight: bold;
}
#cdMessage {
    color: @TEXT_DIM@;
    font-size: 13px;
}
#cdHint {
    color: @MUTED@;
    font-size: 11px;
}
QPushButton#cdClose {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
}
QPushButton#cdClose:hover {
    background: @HOVER@;
}
QLineEdit#cdInput {
    background: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    color: @TEXT@;
    font-size: 13px;
    padding: 8px;
    selection-background-color: @ACCENT@;
}
QComboBox#cdInput {
    background: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    color: @TEXT@;
    font-size: 13px;
    padding: 8px;
}
QComboBox#cdInput::drop-down {
    border: none;
}
QComboBox#cdInput QAbstractItemView {
    background: @FIELD@;
    border: 1px solid @BORDER@;
    color: @TEXT@;
    selection-background-color: @ACCENT@;
}
QListWidget#cdBulkList {
    background: @FIELD@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    outline: none;
    color: @TEXT@;
}
QListWidget#cdBulkList::item {
    border: none;
    padding: 0;
}
*:focus {
    outline: none;
}
QFocusFrame {
    border: none;
    background: transparent;
}
QPushButton#cdConfirm {
    background: @ACCENT@;
    color: @ACCENT_TEXT@;
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
    font-weight: bold;
}
QPushButton#cdConfirm:hover {
    background: @ACCENT_HOVER@;
}
QPushButton#cdCancel {
    background: @CANCEL_BG@;
    color: @CANCEL_TEXT@;
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
}
QPushButton#cdCancel:hover {
    background: @CANCEL_HOVER@;
}
"""


def _rgba(color, alpha=1.0):
    """QColor → строка ``rgba(r, g, b, a)`` для QSS."""
    return "rgba({}, {}, {}, {:.2f})".format(
        color.red(), color.green(), color.blue(), alpha
    )


def _mix_color(first, second, ratio):
    """Смешивает два QColor: ``ratio`` — доля ``second`` (0..1)."""
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(first.red() * (1 - ratio) + second.red() * ratio),
        round(first.green() * (1 - ratio) + second.green() * ratio),
        round(first.blue() * (1 - ratio) + second.blue() * ratio),
    )


def _custom_dialog_qss(palette):
    """Собирает QSS безрамочного диалога из палитры активной темы.

    Фон, текст, поля и акцент берутся из ``QPalette`` (в неё тема кладёт
    свой highlight), поэтому диалог одинаково выглядит в тёмных и светлых
    темах и следует акцентному цвету.
    """
    window = palette.color(QPalette.Window)
    text = palette.color(QPalette.WindowText)
    accent = palette.color(QPalette.Highlight)
    accent_text = palette.color(QPalette.HighlightedText)
    if not accent_text.isValid() or accent_text.alpha() == 0:
        accent_text = QColor("#ffffff")

    # Поля делаем чуть отличными от фона окна, иначе они «сливаются».
    field = _mix_color(window, text, 0.07)

    tokens = {
        "@BG@": window.name(),
        "@TEXT@": text.name(),
        "@TEXT_DIM@": _rgba(text, 0.85),
        "@MUTED@": _rgba(text, 0.55),
        "@HOVER@": _rgba(text, 0.12),
        "@FIELD@": field.name(),
        "@BORDER@": _mix_color(window, text, 0.18).name(),
        "@ACCENT@": accent.name(),
        "@ACCENT_HOVER@": accent.lighter(115).name(),
        "@ACCENT_TEXT@": accent_text.name(),
        "@CANCEL_BG@": _mix_color(window, text, 0.10).name(),
        "@CANCEL_HOVER@": _mix_color(window, text, 0.18).name(),
        "@CANCEL_TEXT@": _rgba(text, 0.85),
    }
    qss = _CUSTOM_DIALOG_QSS_TEMPLATE
    for token, value in tokens.items():
        qss = qss.replace(token, value)
    return qss



class _CustomTitleBar(QWidget):
    """Заголовок безрамочного диалога с перетаскиванием окна мышью."""

    def __init__(self, dialog, title, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self.setFixedHeight(44)
        # Полируем до чтения палитры: QSS темы применяется при полировке,
        # иначе windowText остаётся системным (чёрным) в тёмной теме.
        self.ensurePolished()

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cdTitle")
        row.addWidget(self.title_label)
        row.addStretch(1)

        close_button = QPushButton()
        close_button.setObjectName("cdClose")
        close_button.setFlat(True)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setIcon(
            colored_icon(
                "cancel.svg",
                self.palette().windowText().color().name(),
            )
        )
        close_button.setIconSize(QSize(16, 16))
        close_button.setToolTip(tr("Cancel", _dialog_lang()))
        close_button.clicked.connect(dialog.reject)
        row.addWidget(close_button)

    def _resize_edges(self, global_pos):
        """Определяет края диалога под курсором для системного resize."""
        rect = self._dialog.frameGeometry()
        margin = 6
        edges = Qt.Edges()
        if global_pos.x() - rect.left() <= margin:
            edges |= Qt.LeftEdge
        elif rect.right() - global_pos.x() <= margin:
            edges |= Qt.RightEdge
        if global_pos.y() - rect.top() <= margin:
            edges |= Qt.TopEdge
        elif rect.bottom() - global_pos.y() <= margin:
            edges |= Qt.BottomEdge
        return edges

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._dialog.windowHandle()
            if handle is not None:
                edges = self._resize_edges(event.globalPos())
                if (
                    edges
                    and hasattr(handle, "startSystemResize")
                    and handle.startSystemResize(edges)
                ):
                    event.accept()
                    return
                if (
                    hasattr(handle, "startSystemMove")
                    and handle.startSystemMove()
                ):
                    event.accept()
                    return
        super().mousePressEvent(event)


class _FramelessDialog(QDialog):
    """Общая обвязка безрамочных диалогов: тёмный фон, скругления, тень."""

    _NORMAL_MARGINS = (16, 16, 16, 16)

    def __init__(self, parent=None, title=""):
        super().__init__(parent)
        self.setWindowTitle(title or "")
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(*self._NORMAL_MARGINS)
        self._root_layout = root

        self._container = QFrame()
        self._container.setObjectName("cdRoot")
        self._container.setFocusPolicy(Qt.NoFocus)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        self._container.setGraphicsEffect(shadow)
        root.addWidget(self._container)

        self.body = QVBoxLayout(self._container)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.body.addWidget(_CustomTitleBar(self, title))

        # Ручка изменения размера — в самом углу окна отдельным виджетом,
        # чтобы не оттеснять кнопки от правого нижнего угла.
        self._size_grip = QSizeGrip(self._container)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.raise_()

        # Палитру темы виджет получает только после полировки (QSS
        # приложения), поэтому собираем стиль после ensurePolished().
        self.ensurePolished()
        self.setStyleSheet(_custom_dialog_qss(self.palette()))

    def changeEvent(self, event):
        """Убирает внешние поля диалога в развёрнутом состоянии."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            layout = getattr(self, "_root_layout", None)
            if layout is not None:
                margins = (
                    (0, 0, 0, 0) if self.isMaximized()
                    else self._NORMAL_MARGINS
                )
                layout.setContentsMargins(*margins)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        grip = getattr(self, "_size_grip", None)
        if grip is not None:
            grip.move(
                self._container.width() - grip.width(),
                self._container.height() - grip.height(),
            )

    def _make_button(self, object_name, text, icon_name):
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        if icon_name:
            palette = self.palette()
            if object_name == "cdConfirm":
                # Иконка на акцентной кнопке — цвет текста выделения.
                icon_color = palette.color(QPalette.HighlightedText).name()
            else:
                icon_color = palette.color(QPalette.WindowText).name()
            button.setIcon(colored_icon(icon_name, icon_color))
            button.setIconSize(QSize(16, 16))
        return button

    def _add_footer(self, buttons):
        footer = QWidget()
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 10, 16, 12)
        row.setSpacing(10)
        # Прижимаем кнопки к правому нижнему углу окна.
        row.addStretch(1)
        for button in buttons:
            row.addWidget(button)
        self.body.addWidget(footer)


class CustomInputDialog(_FramelessDialog):
    """Безрамочный диалог ввода одной строки (замена QInputDialog.getText)."""

    def __init__(self, parent=None, title="", label="", text="",
                 placeholder="", items=None, current=0):
        super().__init__(parent, title)
        lang = _dialog_lang()

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 4, 20, 6)
        col.setSpacing(8)

        if label:
            label_widget = QLabel(label)
            label_widget.setObjectName("cdMessage")
            label_widget.setWordWrap(True)
            col.addWidget(label_widget)

        # CHANGED: items включает режим выпадающего списка.
        self.input = None
        self.combo = None
        if items is not None:
            self.combo = QComboBox()
            self.combo.setObjectName("cdInput")
            self.combo.addItems(list(items))
            if items:
                self.combo.setCurrentIndex(
                    max(0, min(int(current), len(items) - 1))
                )
            col.addWidget(self.combo)
        else:
            self.input = QLineEdit()
            self.input.setObjectName("cdInput")
            self.input.setText(text or "")
            if placeholder:
                self.input.setPlaceholderText(placeholder)
            self.input.selectAll()
            col.addWidget(self.input)
        self.body.addWidget(content)

        self.cancel_button = self._make_button(
            "cdCancel", tr("Cancel", lang), "cancel.svg"
        )
        self.cancel_button.clicked.connect(self.reject)

        self.confirm_button = self._make_button(
            "cdConfirm", tr("OK", lang), "confirm.svg"
        )
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)

        self._add_footer([self.cancel_button, self.confirm_button])
        if self.input is not None:
            self.input.returnPressed.connect(self.accept)
            self.input.setFocus()
        elif self.combo is not None:
            self.combo.setFocus()
        self.setMinimumWidth(380)

    def text_value(self):
        if self.input is not None:
            return self.input.text()
        return self.combo.currentText() if self.combo is not None else ""

    @staticmethod
    def get_text(parent, title, label, text="", placeholder=""):
        """Аналог QInputDialog.getText: возвращает (строка, ok)."""
        dialog = CustomInputDialog(parent, title, label, text, placeholder)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.text_value(), True
        return "", False

    @staticmethod
    def get_item(parent, title, label, items, current=0):
        """Аналог QInputDialog.getItem: возвращает (строка, ok)."""
        dialog = CustomInputDialog(
            parent, title, label, items=list(items), current=current
        )
        if dialog.exec_() == QDialog.Accepted:
            return dialog.text_value(), True
        return "", False


class CustomConfirmDialog(_FramelessDialog):
    """Безрамочный диалог подтверждения (Yes/No) и уведомления (OK)."""

    def __init__(self, parent=None, title="", text="", confirm_text=None,
                 cancel_text=None):
        super().__init__(parent, title)
        lang = _dialog_lang()

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 8, 20, 6)
        col.setSpacing(8)

        message = QLabel(text)
        message.setObjectName("cdMessage")
        message.setWordWrap(True)
        col.addWidget(message)
        self.body.addWidget(content)

        # cancel_text is None → режим уведомления с единственной кнопкой OK.
        info_mode = cancel_text is None

        self.confirm_button = self._make_button(
            "cdConfirm",
            confirm_text or tr("OK" if info_mode else "Yes", lang),
            "confirm.svg",
        )
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)

        buttons = [self.confirm_button]
        if not info_mode:
            self.cancel_button = self._make_button(
                "cdCancel", cancel_text or tr("No", lang), "cancel.svg"
            )
            self.cancel_button.clicked.connect(self.reject)
            buttons = [self.cancel_button, self.confirm_button]

        self._add_footer(buttons)
        self.setMinimumWidth(400)
        self.confirm_button.setFocus()

    @staticmethod
    def question(parent, title, text):
        """Аналог QMessageBox.question: True, если пользователь выбрал «Да»."""
        lang = _dialog_lang()
        dialog = CustomConfirmDialog(
            parent, title, text,
            confirm_text=tr("Yes", lang), cancel_text=tr("No", lang),
        )
        return dialog.exec_() == QDialog.Accepted

    @staticmethod
    def information(parent, title, text):
        """Аналог QMessageBox.information: уведомление с одной кнопкой OK."""
        dialog = CustomConfirmDialog(parent, title, text)
        dialog.exec_()
