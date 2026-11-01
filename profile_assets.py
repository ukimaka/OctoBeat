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

"""Общие ресурсы профиля: пути, тема и отрисовка аватарок/обложек."""

import os
import shutil
from pathlib import Path

from PyQt5.QtCore import QByteArray, QRectF, QSettings
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt5.QtSvg import QSvgRenderer

from dialogs import colored_pixmap
from pixmap_utils import draw_centered, draw_cover, new_pixmap, render_svg
from styles import is_dark_theme

PROFILE_COVERS_DIR = Path.home() / ".cache" / "music_player" / "profile_covers"
PROFILE_DIR = Path.home() / ".local" / "share" / "music_player" / "profile"


def _svg_pixmap(markup, color, size):
    """Рендерит SVG-строку в DPR-осознанный QPixmap ``size``×``size``."""
    renderer = QSvgRenderer(QByteArray(markup.replace("{color}", color).encode()))
    return render_svg(renderer, size)


def _svg_icon(markup, color, render=40):
    """QIcon из SVG-строки (растеризуется крупно для чёткости)."""
    return QIcon(_svg_pixmap(markup, color, render))


def _theme_is_dark():
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return is_dark_theme(settings.value("theme", "dark"))


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
