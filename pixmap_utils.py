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

import math
import os

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPixmap,
    QPixmapCache,
)
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
    return max(1, (round(value * dpr)))


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
        max(0, (round(pixmap.width() / dpr))),
        max(0, (round(pixmap.height() / dpr))),
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

    # CHANGED: видимый контент некоторых SVG (например, select-all.svg)
    # смещён внутри viewBox, из-за чего иконка «съезжает» влево в меню.
    # Центрируем фактический bounding box рисунка, а не пустой viewBox.
    image = pixmap.toImage()
    min_x, min_y = image.width(), image.height()
    max_x = max_y = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 10:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x >= min_x and max_y >= min_y:
        dpr_value = pixmap.devicePixelRatio() or 1.0
        dx = ((image.width() - 1) - min_x - max_x) / 2.0 / dpr_value
        dy = ((image.height() - 1) - min_y - max_y) / 2.0 / dpr_value
        if abs(dx) >= 0.5 / dpr_value or abs(dy) >= 0.5 / dpr_value:
            centered = new_pixmap(size, size, dpr=dpr)
            centered_painter = QPainter(centered)
            centered_painter.setRenderHint(
                QPainter.SmoothPixmapTransform, True
            )
            centered_painter.translate(dx, dy)
            centered_painter.drawPixmap(0, 0, pixmap)
            centered_painter.end()
            pixmap = centered
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


def cover_cache_version(path):
    """Версия обложки для кэша. Вызывать при подготовке данных, не в paint."""
    if not path:
        return 0
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def cached_cover(path, width, height, version=0):
    """Уменьшенная обложка из глобального QPixmapCache.

    ``version`` — mtime файла, вычисленный при подготовке данных, поэтому
    paint() не делает stat(). При первом обращении к обложке она один раз
    декодируется и уменьшается, дальше берётся только готовая копия из кэша.
    """
    if not path:
        return QPixmap()
    key = f"cover:{path}:{version}:{width}x{height}"
    cached = QPixmapCache.find(key)
    if isinstance(cached, QPixmap) and not cached.isNull():
        return cached

    # Файл мог быть удалён после построения списка — не читаем
    # несуществующий путь, возвращаем placeholder.
    if not os.path.exists(path):
        return QPixmap()

    # Декодируем и уменьшаем в QImage, а не в QPixmap. Загрузка
    # QPixmap(path) в Qt подмешивает полноразмерный растр в тот же
    # QPixmapCache и вытесняет готовые миниатюры: при прокрутке каждая
    # строка снова декодировала файл с диска. QImage этого не делает,
    # поэтому 50x50-копии остаются в кэше, а paint читает только его.
    dpr = device_pixel_ratio()
    target = QSize(
        max(1, int(round(width * dpr))),
        max(1, int(round(height * dpr))),
    )
    reader = QImageReader(str(path))
    # Расширение файла может не совпадать с содержимым (обложки часто
    # переименовывают), поэтому формат определяем по данным.
    reader.setDecideFormatFromContent(True)
    source_size = reader.size()
    if source_size.isValid() and not source_size.isEmpty():
        # Просим JPEG/PNG-декодер сразу уменьшить кадр. Для обложки
        # 2400x2400 полное декодирование занимает ~12 мс на строку,
        # масштабированное чтение — ~2 мс.
        ratio = max(
            target.width() / source_size.width(),
            target.height() / source_size.height(),
        )
        if ratio < 1.0:
            reader.setScaledSize(
                QSize(
                    max(1, math.ceil(source_size.width() * ratio)),
                    max(1, math.ceil(source_size.height() * ratio)),
                )
            )
    image = reader.read()
    if image.isNull():
        return QPixmap()
    scaled = image.scaled(
        target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )
    pixmap = QPixmap.fromImage(scaled)
    QPixmapCache.insert(key, pixmap)
    return pixmap


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
    font.setPixelSize(max(7, (round(badge_size * 0.62))))
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
