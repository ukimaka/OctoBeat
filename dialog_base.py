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

from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    pyqtProperty,
)
from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressDialog,
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
    color: @TEXT@;
}
QTextEdit, QTextBrowser {
    background-color: @FIELD@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    selection-background-color: @ACCENT@;
    selection-color: @ACCENT_TEXT@;
}
#cdRoot {
    background-color: @GLASS_BG@;
    border: 1px solid @GLASS_BORDER@;
    outline: none;
    border-radius: 14px;
}
/* Контент внутри капсулы прозрачный: стекло видно между контролами.
   У полей ввода, списков и кнопок свои фоны из правил ниже. */
#cdRoot QWidget {
    background-color: transparent;
}
/* YouTube: поле поиска и список результатов остаются читаемыми, но
   просвечивают фоном диалога. */
QLineEdit#ytSearch {
    background-color: @GLASS_FIELD@;
    border: 1px solid @GLASS_BORDER@;
    border-radius: 8px;
    color: @TEXT@;
    padding: 8px;
}
QListWidget#ytResults {
    background-color: @GLASS_FIELD@;
    border: 1px solid @GLASS_BORDER@;
    border-radius: 10px;
    outline: none;
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

    dark = window.lightness() < 128
    glass_tint = _mix_color(
        window, QColor("#ffffff"), 0.08 if dark else 0.65
    )
    glass_border = QColor("#ffffff") if dark else QColor("#2e3440")
    tokens = {
        "@BG@": window.name(),
        "@GLASS_BG@": _rgba(glass_tint, 0.78),
        "@GLASS_BORDER@": _rgba(glass_border, 0.14),
        "@GLASS_FIELD@": _rgba(_mix_color(window, text, 0.10), 0.55),
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



# Затемнение под модальными диалогами: ровно 40% чёрного (alpha 102).
_DIM_OVERLAY_ALPHA = 102
_DIM_OVERLAYS = {}
_DIM_COUNTS = {}


class _WindowDimOverlay(QWidget):
    """Полупрозрачный слой, который затемняет окно под модальным диалогом.

    Слой живёт в родительском окне (а не в диалоге), поэтому диалог со
    своим непрозрачным фоном остаётся поверх затемнения. Рисуем alpha
    вручную, без QGraphicsOpacityEffect: так дешевле и не ломается
    композитинг на Wayland/X11.
    """

    def __init__(self, window):
        super().__init__(window)
        self._active = False
        self._alpha = 0.0
        self.setObjectName("windowDimOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._animation = QPropertyAnimation(self, b"dimAlpha", self)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)
        window.installEventFilter(self)
        self._sync_geometry()
        self.hide()

    def _sync_geometry(self):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())

    def eventFilter(self, watched, event):
        if watched is self.parentWidget():
            if event.type() == QEvent.Resize:
                self._sync_geometry()
            elif event.type() == QEvent.Show:
                self._sync_geometry()
                if self._active:
                    self.raise_()
        return False

    def _get_dim_alpha(self):
        return self._alpha

    def _set_dim_alpha(self, value):
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._alpha) > 1e-4:
            self._alpha = value
            self.update()

    dimAlpha = pyqtProperty(float, _get_dim_alpha, _set_dim_alpha)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(
            self.rect(),
            QColor(0, 0, 0, round(_DIM_OVERLAY_ALPHA * self._alpha)),
        )
        painter.end()

    def show_overlay(self):
        self._active = True
        self._sync_geometry()
        self.show()
        self.raise_()
        self._animate_to(1.0, 120)

    def hide_overlay(self):
        self._active = False
        if not self.isVisible():
            # Родительское окно скрыто (свёрнуто/закрыто): анимация не
            # нужна, но сбрасываем alpha, чтобы слой не всплыл снова при
            # следующем показе окна.
            self._animation.stop()
            self._set_dim_alpha(0.0)
            self.hide()
            return
        self._animate_to(0.0, 180)

    def _animate_to(self, target, duration):
        self._animation.stop()
        self._animation.setStartValue(self._alpha)
        self._animation.setEndValue(float(target))
        self._animation.setDuration(duration)
        self._animation.start()

    def _on_animation_finished(self):
        if not self._active and self._alpha <= 0.001:
            self.hide()


def _overlay_for_window(window):
    overlay = _DIM_OVERLAYS.get(window)
    if overlay is None:
        overlay = _WindowDimOverlay(window)
        _DIM_OVERLAYS[window] = overlay
        window.destroyed.connect(
            lambda *_: _forget_overlay(window)
        )
    return overlay


def _forget_overlay(window):
    _DIM_OVERLAYS.pop(window, None)
    _DIM_COUNTS.pop(window, None)


def _acquire_dim(window):
    _DIM_COUNTS[window] = _DIM_COUNTS.get(window, 0) + 1
    _overlay_for_window(window).show_overlay()


def _release_dim(window):
    count = _DIM_COUNTS.get(window, 0)
    if count <= 0:
        return
    if count == 1:
        _DIM_COUNTS.pop(window, None)
        overlay = _DIM_OVERLAYS.get(window)
        if overlay is not None:
            overlay.hide_overlay()
    else:
        _DIM_COUNTS[window] = count - 1


class _DimmedMixin:
    """Общая логика затемнения родительского окна для модальных диалогов.

    Счётчик открытых диалогов не даёт затемнению исчезнуть, если один
    модальный диалог открыт поверх другого.
    """

    def _init_dimming(self):
        self._dim_active = False
        self._dim_target = self._resolve_dim_target()

    def _resolve_dim_target(self):
        parent = self.parentWidget()
        if parent is not None:
            return parent.window()
        active = QApplication.activeWindow()
        if active is not None and active is not self:
            return active
        return None

    def showEvent(self, event):
        super().showEvent(event)
        if self._dim_active:
            return
        target = self._dim_target
        if target is None:
            target = self._resolve_dim_target()
            self._dim_target = target
        if target is not None and target is not self:
            self._dim_active = True
            _acquire_dim(target)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not self._dim_active:
            return
        self._dim_active = False
        target = self._dim_target
        if target is not None:
            _release_dim(target)


class _DimmedDialog(_DimmedMixin, QDialog):
    """Диалог, который при показе затемняет своё родительское окно."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_dimming()


class DimmedProgressDialog(_DimmedMixin, QProgressDialog):
    """Стандартный QProgressDialog с тем же затемнением фона."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_dimming()


class DimmedFileDialog(_DimmedMixin, QFileDialog):
    """QFileDialog с тем же затемнением родительского окна."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_dimming()


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


class _FramelessDialog(_DimmedDialog):
    """Общая обвязка безрамочных диалогов: тёмный фон, скругления, тень."""

    _NORMAL_MARGINS = (16, 16, 16, 16)
    # Тень — QGraphicsDropShadowEffect: на больших списках она заставляет
    # перерисовывать весь контейнер при каждом движении мыши. Диалоги с
    # тяжёлым содержимым могут отключить её, не теряя остального оформления.
    _ENABLE_SHADOW = True

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
        if self._ENABLE_SHADOW:
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
