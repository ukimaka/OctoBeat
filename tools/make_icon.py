#!/usr/bin/env python3
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

"""Генерирует icons/icon.ico из icons/OctoBeat.svg.

Pillow не умеет читать SVG, поэтому вектор рендерится через QtSvg в каждый
нужный размер (так мелкие иконки остаются резкими), а многоразмерный ICO
собирается и сохраняется через Pillow.

Запуск (из корня проекта):

    python tools/make_icon.py

Скрипт использует offscreen-платформу Qt и не требует графической сессии.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# QtSvg не должен пытаться открыть реальный дисплей на CI/сервере.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PyQt5.QtCore import QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt5.QtSvg import QSvgRenderer  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_SVG = PROJECT_ROOT / "icons" / "OctoBeat.svg"
OUTPUT_ICO = PROJECT_ROOT / "icons" / "icon.ico"

# В ICO кладём отдельный рендер под каждый размер: Windows выбирает
# подходящий кадр для плитки, списка файлов и крупного значка.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _render_svg(renderer, size, target):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    # OctoBeat.svg — не квадрат (1279×989): сохраняем пропорции и
    # добавляем прозрачные поля, иначе персонаж будет растянут.
    renderer.setAspectRatioMode(Qt.KeepAspectRatio)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"Cannot render {SOURCE_SVG} at {size}px")
    return Image.open(target).convert("RGBA")


def main():
    if not SOURCE_SVG.is_file():
        raise SystemExit(f"Source icon not found: {SOURCE_SVG}")

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(SOURCE_SVG))
    if not renderer.isValid():
        raise SystemExit(f"Cannot read SVG: {SOURCE_SVG}")

    with tempfile.TemporaryDirectory(prefix="octobeat-icon-") as temp_dir:
        frames = []
        for size in ICON_SIZES:
            target = Path(temp_dir) / f"icon-{size}.png"
            frames.append(_render_svg(renderer, size, target))

        base = frames[-1]  # 256×256 — основной кадр ICO
        base.save(
            OUTPUT_ICO,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
            append_images=frames[:-1],
            bitmap_format="png",
        )

    print(f"Wrote {OUTPUT_ICO} ({', '.join(str(s) for s in ICON_SIZES)} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
