"""Полноэкранный оверлей с текстом песни.

Отдельное безрамочное окно поверх рабочего стола: крупный шрифт,
центрированный текст и пословная подсветка. Управляется из
``lyrics_manager.py``: ему передают уже разобранные строки LRC и текущую
позицию плеера.

Оверлей — обычный дочерний виджет-окно (``Qt.Window``): его закрытие
лишь скрывает окно и никак не влияет на работу основного плеера.
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

HIGHLIGHT_COLOR = "#5151ab"      # активная строка / активное слово
DIM_COLOR = "#8a8a8a"            # неактивные строки
ACTIVE_WORD_COLOR = "#ffffff"    # остальные слова активной строки
OVERLAY_BG = "rgba(0, 0, 0, 220)"  # полупрозрачный чёрный фон


class LyricsOverlay(QWidget):
    """Безрамочное полноэкранное окно с синхронизированным текстом."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Lyrics")
        self.setStyleSheet(
            f"LyricsOverlay {{ background-color: {OVERLAY_BG}; }}"
        )

        self._lang = QSettings("MusicPlayer", "MusicPlayer").value(
            "language", "en"
        )
        self._lines = []          # [(время_мс, строка, слова)]
        self._plain = ""          # обычный текст (если синхронного нет)
        self._index = -1          # активная строка
        self._word_index = -1     # активное слово в строке

        self.view = QTextBrowser()
        self.view.setObjectName("overlayLyricsView")
        self.view.setOpenExternalLinks(False)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet(
            "QTextBrowser#overlayLyricsView {"
            " background: transparent; border: none;"
            " color: #ffffff; font-size: 36px; padding: 40px 80px; }"
        )

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("overlayCloseButton")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedSize(40, 40)
        self.close_button.setToolTip(tr("Close", self._lang))
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(
            "QPushButton#overlayCloseButton {"
            " color: #ffffff; background: rgba(255, 255, 255, 0.12);"
            " border: none; border-radius: 20px; font-size: 20px; }"
            "QPushButton#overlayCloseButton:hover {"
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
        anchor = f'<a name="ovl{index}"></a>'
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
            self.view.scrollToAnchor(f"ovl{self._index}")

    def keyPressEvent(self, event):  # noqa: N802 - имя из Qt API
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
