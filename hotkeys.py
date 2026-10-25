"""Глобальные горячие клавиши и скрытие «залипших» тултипов."""

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLineEdit,
    QTextEdit,
    QToolTip,
)


class AppEventFilter(QObject):
    """Фильтр событий приложения для хоткеев плеера.

    Фильтр ставится на ``QApplication``, потому что ``QTreeWidget`` и
    ``QListView`` сами обрабатывают Space и Ctrl+←/→ и не пробрасывают их
    в ``keyPressEvent`` окна. Тот же фильтр устанавливается на отдельные
    кнопки-иконки для корректного скрытия подсказок.
    """

    search_requested = pyqtSignal()
    play_pause_requested = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    volume_delta_requested = pyqtSignal(int)

    def __init__(self, window, parent=None):
        super().__init__(parent if parent is not None else window)
        self.window = window

    def eventFilter(self, obj, event):
        """Перехватывает хоткеи приложения до доставки их виджету."""
        etype = event.type()

        # Тултип «залипал» при быстром движении мыши: гасим подсказку при
        # любом движении курсора, а также при входе/уходе с виджета,
        # у которого есть тултип. Так старые подсказки не остаются висеть
        # при переходе к другому элементу.
        if etype == QEvent.MouseMove:
            QToolTip.hideText()
        elif etype in (QEvent.Enter, QEvent.Leave):
            tooltip = getattr(obj, "toolTip", None)
            if callable(tooltip) and tooltip():
                QToolTip.hideText()

        if (etype == QEvent.KeyPress
                and self._is_own_window_focus()
                and self._handle_hotkey(event)):
            return True
        return super().eventFilter(obj, event)

    def _is_own_window_focus(self):
        """Фокус сейчас в этом окне (не в диалоге настроек и не в меню)."""
        focus = QApplication.focusWidget()
        return focus is not None and focus.window() is self.window

    def _handle_hotkey(self, event):
        """Обрабатывает хоткей. True — событие поглощено."""
        key = event.key()
        mods = event.modifiers()
        focus = QApplication.focusWidget()

        # Ctrl+F работает всегда — даже из текстового поля.
        if key == Qt.Key_F and mods == Qt.ControlModifier:
            self.search_requested.emit()
            return True

        # В полях ввода Space и стрелки — обычный ввод текста, а не плеер
        # (в т.ч. Ctrl+←/→ — переход по словам).
        if self._is_text_input(focus):
            return False

        if mods == Qt.ControlModifier:
            if key == Qt.Key_Right:
                self.next_requested.emit()
                return True
            if key == Qt.Key_Left:
                self.prev_requested.emit()
                return True
            if key == Qt.Key_Up:
                self.volume_delta_requested.emit(5)
                return True
            if key == Qt.Key_Down:
                self.volume_delta_requested.emit(-5)
                return True
            return False

        if key == Qt.Key_Space and mods == Qt.NoModifier:
            # Не мешаем активации кнопок и раскрытию списков с клавиатуры.
            if isinstance(focus, (QAbstractButton, QComboBox)):
                return False
            if event.isAutoRepeat():
                return True  # гасим автоповтор, чтобы не дёргать play/pause
            self.play_pause_requested.emit()
            return True

        return False

    @staticmethod
    def _is_text_input(widget):
        """True, если виджет (или его предок) — поле ввода текста."""
        current = widget
        while current is not None:
            if isinstance(current, (QLineEdit, QTextEdit)):
                return True
            current = current.parentWidget()
        return False
