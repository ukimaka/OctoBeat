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

"""Полноэкранный караоке-режим с текстом песни.

Отдельное безрамочное окно поверх рабочего стола: очень крупный жирный
шрифт (36px), центрированный текст и пословная подсветка активной строки
цветом ``#5151ab``. Управляется из ``lyrics_manager.py``: ему передают уже
разобранные строки LRC и текущую позицию плеера.

Окно — обычный дочерний виджет-окно (``Qt.Window``): его закрытие лишь
скрывает окно и никак не влияет на работу основного плеера.
"""

import html

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from translations import tr

HIGHLIGHT_COLOR = "#5151ab"        # активная строка / активное слово
DIM_COLOR = "#8a8a8a"              # неактивные строки
ACTIVE_WORD_COLOR = "#ffffff"      # остальные слова активной строки
KARAOKE_BG = "rgba(0, 0, 0, 230)"  # плотный полупрозрачный чёрный фон
FONT_SIZE_PX = 36                  # крупный шрифт караоке


class KaraokeOverlay(QWidget):
    """Безрамочное полноэкранное окно караоке с синхронизированным текстом."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Karaoke")
        self.setStyleSheet(
            f"KaraokeOverlay {{ background-color: {KARAOKE_BG}; }}"
        )

        self._lang = QSettings("MusicPlayer", "MusicPlayer").value(
            "language", "en"
        )
        self._lines = []          # [(время_мс, строка, слова)]
        self._plain = ""          # обычный текст (если синхронного нет)
        self._index = -1          # активная строка
        self._word_index = -1     # активное слово в строке

        self.view = QTextBrowser()
        self.view.setObjectName("karaokeView")
        self.view.setOpenExternalLinks(False)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet(
            "QTextBrowser#karaokeView {"
            " background: transparent; border: none;"
            f" color: #ffffff; font-size: {FONT_SIZE_PX}px;"
            " font-weight: bold; padding: 40px 80px; }"
        )

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("karaokeCloseButton")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedSize(44, 44)
        self.close_button.setToolTip(tr("Close", self._lang))
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(
            "QPushButton#karaokeCloseButton {"
            " color: #ffffff; background: rgba(255, 255, 255, 0.12);"
            " border: none; border-radius: 22px; font-size: 22px; }"
            "QPushButton#karaokeCloseButton:hover {"
            " background: rgba(255, 255, 255, 0.25); }"
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 16, 20, 0)
        header.addStretch(1)
        header.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.view, 1)

        self._render()

    # ------------------------------------------------------------------
    #  API для ui.py
    # ------------------------------------------------------------------
    def set_lines(self, lines, plain=""):
        """Задаёт разобранные строки LRC (и обычный текст) и перерисовывает."""
        self._lines = list(lines or [])
        self._plain = plain or ""
        self._index = -1
        self._word_index = -1
        self._render()

    def set_position(self, pos):
        """Синхронизирует подсветку с позицией плеера (мс)."""
        index = self._line_index_for_pos(pos)
        word_index = self._word_index_for_pos(index, pos)
        if index == self._index and word_index == self._word_index:
            return  # ничего не изменилось — не трогаем UI
        self._index = index
        self._word_index = word_index
        self._render()

    def showFullScreen(self):  # noqa: N802 - имя из Qt API
        super().showFullScreen()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    #  Внутреннее
    # ------------------------------------------------------------------
    def _line_index_for_pos(self, pos):
        index = -1
        for i, (time_ms, _text, _words) in enumerate(self._lines):
            if time_ms <= pos:
                index = i
            else:
                break
        return index

    def _word_index_for_pos(self, line_index, pos):
        if not (0 <= line_index < len(self._lines)):
            return -1
        line_ms, _text, words = self._lines[line_index]
        if not words:
            return -1
        word_index = -1
        for wi, (word_ms, _word) in enumerate(words):
            ts = line_ms if word_ms is None else word_ms
            if ts <= pos:
                word_index = wi
            else:
                break
        return word_index

    def _line_html(self, index, text, words):
        anchor = f'<a name="krk{index}"></a>'
        current = (index == self._index)

        if current and words:
            spans = []
            for wi, (_wms, word) in enumerate(words):
                active = (wi == self._word_index)
                color = HIGHLIGHT_COLOR if active else ACTIVE_WORD_COLOR
                spans.append(
                    f'<span style="color:{color};">{html.escape(word)}</span>'
                )
            body = " ".join(spans) if spans else html.escape(text)
            return f'<div style="font-weight:bold;">{anchor}{body}</div>'

        color = HIGHLIGHT_COLOR if current else DIM_COLOR
        weight = "bold" if current else "normal"
        safe = html.escape(text) or "&nbsp;"
        return (
            f'<div style="color:{color}; font-weight:{weight};">'
            f"{anchor}{safe}</div>"
        )

    def _render(self):
        if not self._lines:
            if self._plain:
                body = html.escape(self._plain).replace("\n", "<br>")
            else:
                body = html.escape(tr("No lyrics found", self._lang))
            self.view.setHtml(
                f'<div style="color:#8a8a8a; text-align:center;">{body}</div>'
            )
            return

        parts = [
            self._line_html(i, text, words)
            for i, (_ms, text, words) in enumerate(self._lines)
        ]
        self.view.setHtml(
            '<div style="text-align:center; line-height:1.5;">'
            + "".join(parts) + "</div>"
        )
        if 0 <= self._index < len(self._lines):
            self.view.scrollToAnchor(f"krk{self._index}")

    def keyPressEvent(self, event):  # noqa: N802 - имя из Qt API
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
