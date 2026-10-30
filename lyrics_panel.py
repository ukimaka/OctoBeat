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

"""Панель с текстом песни.

Виджет только отображает то, что ему передал ``LyricsManager``, и сообщает
намерения пользователя (сдвиг текста, fullscreen, karaoke) через сигналы.
"""

import html

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from translations import tr


class LyricsPanel(QWidget):
    """Скрытая панель с текстом песни (показывается кнопкой Lyrics)."""

    offset_delta_requested = pyqtSignal(int)
    fullscreen_requested = pyqtSignal()
    karaoke_requested = pyqtSignal()

    def __init__(self, settings, icons, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icons = icons

        self._lines = []          # [(время_мс, строка, слова)]
        self._plain = ""          # обычный текст (без таймкодов)
        self._index = -1          # активная строка
        self._word_index = -1     # активное слово в строке

        lang = self.settings.value("language", "en")
        self.setObjectName("lyricsPanel")

        self.view = QTextBrowser()
        self.view.setObjectName("lyricsView")
        self.view.setOpenExternalLinks(False)
        # Высота адаптируется к доступному месту: фиксированные 150 px
        # вылезали за нижнюю границу окна при нестандартном масштабе.
        self.view.setMinimumHeight(96)
        self.view.setMaximumHeight(180)
        self.view.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )

        self.fullscreen_button = QPushButton()
        self.fullscreen_button.setIcon(self.icons.icon("expand.svg"))
        self.fullscreen_button.setIconSize(QSize(16, 16))
        self.fullscreen_button.setFlat(True)
        self.fullscreen_button.setCursor(Qt.PointingHandCursor)
        self.fullscreen_button.setToolTip(tr("Fullscreen", lang))
        self.fullscreen_button.clicked.connect(
            lambda: self.fullscreen_requested.emit()
        )

        self.karaoke_button = QPushButton()
        self.karaoke_button.setIcon(self.icons.icon("karaoke.svg"))
        self.karaoke_button.setIconSize(QSize(18, 18))
        self.karaoke_button.setFlat(True)
        self.karaoke_button.setCursor(Qt.PointingHandCursor)
        self.karaoke_button.setToolTip(tr("Karaoke", lang))
        self.karaoke_button.clicked.connect(
            lambda: self.karaoke_requested.emit()
        )

        # Кнопки синхронизации текста: тексты с LRCLIB часто отстают/спешат.
        self.offset_down_button = QPushButton("-0.5s")
        self.offset_down_button.setFlat(True)
        self.offset_down_button.setCursor(Qt.PointingHandCursor)
        self.offset_down_button.setFixedWidth(46)
        self.offset_down_button.setToolTip(tr("Sync lyrics: -0.5s", lang))
        self.offset_down_button.clicked.connect(
            lambda: self.offset_delta_requested.emit(-500)
        )

        self.offset_up_button = QPushButton("+0.5s")
        self.offset_up_button.setFlat(True)
        self.offset_up_button.setCursor(Qt.PointingHandCursor)
        self.offset_up_button.setFixedWidth(46)
        self.offset_up_button.setToolTip(tr("Sync lyrics: +0.5s", lang))
        self.offset_up_button.clicked.connect(
            lambda: self.offset_delta_requested.emit(500)
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 6, 0)
        header.addStretch(1)
        header.addWidget(self.offset_down_button)
        header.addWidget(self.offset_up_button)
        header.addWidget(self.karaoke_button)
        header.addWidget(self.fullscreen_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.view)
        self.hide()

    # ------------------------------------------------------------------
    #  API для LyricsManager / MainWindow
    # ------------------------------------------------------------------
    def set_content(self, mode, lines, plain):
        """Показывает LRC, обычный текст, загрузку или заглушку."""
        lang = self.settings.value("language", "en")
        self._lines = list(lines or [])
        self._plain = plain or ""
        self._index = -1
        self._word_index = -1

        if mode == "loading":
            self._set_html(tr("Loading lyrics...", lang), color="#8a8a8a")
            return

        if mode == "synced":
            self._render_lines()
            return

        if mode == "plain":
            escaped = html.escape(self._plain).replace("\n", "<br>")
            self._set_html(escaped, color="#8a8a8a")
            return

        self._set_html(tr("No lyrics found", lang), color="#8a8a8a")

    def set_highlight(self, line_index, word_index):
        """Запоминает активную строку/слово и перерисовывает панель."""
        self._index = line_index
        self._word_index = word_index
        if self.view.isVisible():
            self._render_lines()

    def scroll_to_current(self):
        """Прокручивает панель к активной строке, если она есть."""
        if 0 <= self._index < len(self._lines):
            self.view.scrollToAnchor(f"lrc{self._index}")

    def apply_theme(self):
        """Перекрашивает иконки панели после смены темы."""
        self.fullscreen_button.setIcon(self.icons.icon("expand.svg"))
        self.karaoke_button.setIcon(self.icons.icon("karaoke.svg"))

    # ------------------------------------------------------------------
    #  Внутреннее
    # ------------------------------------------------------------------
    def _set_html(self, body, color="#8a8a8a"):
        self.view.setHtml(
            f'<div style="color:{color}; line-height:1.6;">{body}</div>'
        )

    def _line_html(self, index, text, words, anchor=True):
        """HTML одной строки: с пословной подсветкой или целиком.

        Если у строки есть пословные таймкоды и она текущая — подсвечиваем
        только текущее слово (``#5151ab``), остальные слова строки белые.
        Иначе — подсвечиваем строку целиком.
        """
        current = (index == self._index)
        anchor_html = f'<a name="lrc{index}"></a>' if anchor else ""

        if current and words:
            spans = []
            for wi, (_wms, word) in enumerate(words):
                active = (wi == self._word_index)
                color = "#5151ab" if active else "#ffffff"
                weight = "bold" if active else "normal"
                spans.append(
                    f'<span style="color:{color}; font-weight:{weight};">'
                    f"{html.escape(word)}</span>"
                )
            body = " ".join(spans) if spans else html.escape(text)
            return f'<div style="font-weight:bold;">{anchor_html}{body}</div>'

        color = "#5151ab" if current else "#8a8a8a"
        weight = "bold" if current else "normal"
        safe = html.escape(text) or "&nbsp;"
        return (
            f'<div style="color:{color}; font-weight:{weight};">'
            f"{anchor_html}{safe}</div>"
        )

    def _render_lines(self):
        """Перерисовывает LRC-строки, подсвечивая текущую строку/слово."""
        parts = [
            self._line_html(i, text, words)
            for i, (_ms, text, words) in enumerate(self._lines)
        ]
        self.view.setHtml(
            '<div style="line-height:1.6;">' + "".join(parts) + "</div>"
        )
        if 0 <= self._index < len(self._lines):
            self.view.scrollToAnchor(f"lrc{self._index}")
