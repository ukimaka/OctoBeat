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

"""Хелперы для чёткой отрисовки QPixmap при дробном масштабе Qt.

При ``QT_SCALE_FACTOR`` (например, 1.5) Qt рисует виджеты в логических
координатах, но физически — крупнее. Если создать ``QPixmap(22, 22)`` и
отдать его в ``QLabel``/``QIcon``, Qt растянет картинку и она замылится.
Поэтому все растровые ресурсы создаются в физическом размере
``логический_размер * devicePixelRatio``, а затем им выставляется
``setDevicePixelRatio(dpr)``: Qt показывает их в прежнем логическом размере,
но с полным физическим разрешением.
"""

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication


def device_pixel_ratio():
    """Текущий DPR приложения (учитывает ``QT_SCALE_FACTOR``)."""
    app = QApplication.instance()
    if app is None:
        return 1.0
    try:
        dpr = float(app.devicePixelRatio())
    except (AttributeError, TypeError, ValueError):
        screen = app.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    return max(1.0, dpr)


def physical(value, dpr=None):
    """Логические пиксели → физические (минимум 1)."""
    dpr = device_pixel_ratio() if dpr is None else dpr
    return max(1, int(round(value * dpr)))


def new_pixmap(width, height=None, dpr=None):
    """Прозрачный QPixmap с физическим размером и выставленным DPR."""
    dpr = device_pixel_ratio() if dpr is None else dpr
    height = width if height is None else height
    pixmap = QPixmap(physical(width, dpr), physical(height, dpr))
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def pixmap_size(pixmap):
    """Логический размер QPixmap (с учётом его devicePixelRatio)."""
    if pixmap is None or pixmap.isNull():
        return QSize(0, 0)
    dpr = pixmap.devicePixelRatio() or 1.0
    return QSize(
        max(0, int(round(pixmap.width() / dpr))),
        max(0, int(round(pixmap.height() / dpr))),
    )


def render_svg(renderer, size, color=None, dpr=None):
    """Рендерит QSvgRenderer в DPR-осознанный QPixmap ``size``×``size``."""
    if renderer is None or not renderer.isValid():
        return QPixmap()

    pixmap = new_pixmap(size, size, dpr=dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    if color is not None:
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(QRectF(0, 0, size, size), QColor(color))
    painter.end()
    return pixmap


def svg_file_pixmap(path, size, color=None, dpr=None):
    """Загружает SVG-файл и рендерит его в нужном разрешении."""
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QPixmap()
    return render_svg(renderer, size, color=color, dpr=dpr)


def svg_data_pixmap(data, size, color=None, dpr=None):
    """Рендерит SVG из bytes/QByteArray (например, встроенную разметку)."""
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return QPixmap()
    return render_svg(renderer, size, color=color, dpr=dpr)


def icon_pixmap_rect(icon, width, height, dpr=None):
    """QPixmap из QIcon с сохранением дробного DPR.

    В ``main.py`` включён ``Qt.AA_UseHighDpiPixmaps``, поэтому QIcon сам
    возвращает pixmap в физическом разрешении с выставленным DPR. Если
    атрибут не включён (например, в изолированном тесте), запрашиваем
    физический размер вручную и выставляем DPR сами.
    """
    if icon is None or icon.isNull():
        return QPixmap()
    dpr = device_pixel_ratio() if dpr is None else dpr
    pixmap = icon.pixmap(width, height)
    if pixmap.isNull():
        return pixmap
    if pixmap.devicePixelRatio() >= dpr:
        return pixmap

    # Fallback для QIcon с высоким разрешением, но без высоко-DPI режима.
    fallback = icon.pixmap(physical(width, dpr), physical(height, dpr))
    if fallback.isNull():
        return pixmap
    fallback.setDevicePixelRatio(dpr)
    return fallback


def icon_pixmap(icon, size, dpr=None):
    """Квадратный вариант :func:`icon_pixmap_rect`."""
    return icon_pixmap_rect(icon, size, size, dpr=dpr)


def draw_cover(painter, rect, pixmap):
    """Рисует pixmap с заполнением прямоугольника (KeepAspectRatioByExpanding).

    ``rect`` задаётся в логических координатах; QPainter сам масштабирует
    физические пиксели источника под DPR устройства.
    """
    if pixmap is None or pixmap.isNull():
        return False
    scale = max(
        rect.width() / max(1, pixmap.width()),
        rect.height() / max(1, pixmap.height()),
    )
    width = pixmap.width() * scale
    height = pixmap.height() * scale
    target = QRectF(
        rect.x() + (rect.width() - width) / 2,
        rect.y() + (rect.height() - height) / 2,
        width,
        height,
    )
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    return True


SOURCE_BADGE_LABELS = {
    "musicbrainz": "M",
    "youtube": "Y",
    "fallback": "F",
}
SOURCE_BADGE_COLORS = {
    "musicbrainz": QColor("#5151ab"),
    "youtube": QColor("#c62828"),
    "fallback": QColor("#6d6d6d"),
}
SOURCE_BADGE_NAMES = {
    "musicbrainz": "MusicBrainz",
    "youtube": "YouTube",
    "fallback": "filename / fallback",
}


def source_display_name(source):
    """Человекочитаемое имя источника метаданных для тултипа."""
    return SOURCE_BADGE_NAMES.get(str(source or "").casefold(), "")


def draw_source_badge(painter, rect, source, size=14):
    """Рисует маленький бейдж M/Y/F в правом нижнем углу обложки.

    Используется только как debug-индикация источника метаданных.
    """
    key = str(source or "").casefold()
    label = SOURCE_BADGE_LABELS.get(key)
    color = SOURCE_BADGE_COLORS.get(key)
    if painter is None or not label or color is None:
        return False

    rect = QRectF(rect)
    badge_size = min(
        float(size),
        max(9.0, min(rect.width(), rect.height()) * 0.34),
    )
    margin = max(2.0, badge_size * 0.16)
    badge_rect = QRectF(
        rect.right() - badge_size - margin,
        rect.bottom() - badge_size - margin,
        badge_size,
        badge_size,
    )

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    radius = badge_size * 0.25
    painter.drawRoundedRect(badge_rect, radius, radius)

    font = painter.font()
    font.setPixelSize(max(7, int(round(badge_size * 0.62))))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(badge_rect, Qt.AlignCenter, label)
    painter.restore()
    return True


def draw_centered(painter, rect, pixmap):
    """Рисует pixmap по центру логического прямоугольника ``rect``."""
    if pixmap is None or pixmap.isNull():
        return False
    size = pixmap_size(pixmap)
    x = rect.x() + (rect.width() - size.width()) / 2
    y = rect.y() + (rect.height() - size.height()) / 2
    painter.drawPixmap(QPointF(x, y), pixmap)
    return True
