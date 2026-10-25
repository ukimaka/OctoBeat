"""Общие UI-примитивы: иконки, слайдеры, метки и форматирование времени.

Модуль не зависит от ``MainWindow`` и не читает ``QSettings``: тему ему
передаёт владелец через :meth:`IconProvider.set_dark`. Это позволяет
переиспользовать примитивы в новых изолированных виджетах.
"""

from pathlib import Path

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPixmap,
)
from PyQt5.QtWidgets import QLabel, QPushButton, QSlider, QStyle

from pixmap_utils import (
    draw_centered, draw_cover, new_pixmap, svg_file_pixmap,
)


def fmt_time(ms):
    if ms < 0:
        ms = 0
    total_sec = ms // 1000
    m, s = divmod(total_sec, 60)
    return f"{m}:{s:02d}"


class ClickSlider(QSlider):
    """Слайдер, который сообщает о клике по groove отдельным сигналом."""

    clickedValue = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.x(), self.width(),
            )
            self.setValue(value)
            self.clickedValue.emit(value)
        super().mousePressEvent(event)


class LyricsButton(QPushButton):
    """Кнопка текста: обычный клик — панель, двойной клик — караоке-режим."""

    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        # Поглощаем событие, иначе базовый QPushButton сгенерирует лишний
        # ``clicked`` и панель успеет мигнуть.
        self.doubleClicked.emit()
        event.accept()


class ElidedLabel(QLabel):
    """QLabel, который сам обрезает текст по ширине с многоточием справа."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full_text = text

    def setText(self, text):
        self._full_text = text
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self):
        """Позволяет метке сжиматься: иначе длинный текст раздувает layout.

        ``QLabel`` без word-wrap возвращает в ``minimumSizeHint`` ширину всего
        текста, из-за чего длинное название трека выталкивает соседние виджеты
        за пределы панели. Для элидящей метки минимум по ширине не нужен.
        """
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
        painter.drawText(self.rect(), self.alignment(), elided)


class IconProvider:
    """Загружает и перекрашивает иконки с учётом текущей темы.

    Основа всегда берётся из ``icons/black/``. Цвет можно задать явно
    (``"white"``/``"black"``/``"blue"`` или произвольный hex), иначе он
    выбирается по теме: белый для тёмной, чёрный для светлой.

    SVG рендерится сразу в физическом разрешении (``size * DPR``), а
    полученному QPixmap выставляется ``devicePixelRatio``. Благодаря этому
    Qt не растягивает готовую картинку при ``QT_SCALE_FACTOR``.
    """

    # Достаточный логический размер для QIcon: Qt выберет из него
    # физический вариант под текущий DPR и масштаб виджета.
    ICON_RENDER_SIZE = 64

    def __init__(self, icons_dir=None, is_dark=True):
        self._icons_dir = (
            Path(icons_dir) if icons_dir is not None
            else Path(__file__).resolve().parent / "icons"
        )
        self._is_dark = bool(is_dark)

    @property
    def is_dark(self):
        return self._is_dark

    def set_dark(self, is_dark):
        self._is_dark = bool(is_dark)

    def _color(self, color):
        if color:
            if color == "white":
                return "#ffffff"
            if color == "blue":
                return "#5151ab"
            return color
        return "white" if self._is_dark else "black"

    def pixmap(self, filename, size, color=None):
        """Готовая DPR-осознанная иконка (для ``QLabel.setPixmap``)."""
        if not filename:
            return QPixmap()

        path = self._icons_dir / "black" / filename
        if not path.is_file():
            return QPixmap()

        return svg_file_pixmap(path, size, color=self._color(color))

    def icon(self, filename, color=None):
        """Возвращает иконку, перекрашенную в нужный цвет."""
        # Рендерим крупнее реального iconSize: QIcon/QStyle сам выберет
        # подходящий физический вариант под DPR, не размывая картинку.
        pixmap = self.pixmap(filename, self.ICON_RENDER_SIZE, color)
        if pixmap.isNull():
            return QIcon()
        return QIcon(pixmap)

    def icon_button(self, icon_name, tooltip, size=22, event_filter=None):
        """Плоская кнопка-иконка (фон и hover задаются в DARK_THEME)."""
        btn = QPushButton()
        btn.setIcon(self.icon(icon_name))
        btn.setIconSize(QSize(size, size))
        btn.setFlat(True)
        btn.setToolTip(tooltip)
        # Фильтр нужен для корректного скрытия залипающих тултипов.
        if event_filter is not None:
            btn.installEventFilter(event_filter)
        return btn

    def cover_pixmap(self, path, size, radius=6):
        """Квадратная обложка со скруглёнными углами (заглушка — нота)."""
        result = new_pixmap(size, size)

        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        painter.setClipPath(clip)

        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            dark = self._is_dark
            painter.fillRect(
                QRectF(0, 0, size, size),
                QColor("#282828") if dark else QColor("#efefef"),
            )
            note = self.pixmap(
                "music-note.svg", size - 14,
                color="white" if dark else "black",
            )
            draw_centered(painter, QRectF(0, 0, size, size), note)
        else:
            draw_cover(painter, QRectF(0, 0, size, size), pixmap)

        painter.end()
        return result
