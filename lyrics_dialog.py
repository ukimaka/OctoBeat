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

"""Диалог ручного ввода/редактирования текста песни.

Использует ту же безрамочную «стеклянную» обвязку, что и остальные
диалоги приложения. Поддерживаются оба формата: обычный текст и LRC с
таймкодами — разбором занимается ``lyrics_manager.parse_lrc``.
"""

from pathlib import Path

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dialog_base import _FramelessDialog, _dialog_lang
from translations import tr
from ui_common import get_open_file_name


def read_lyrics_file(path):
    """Читает .lrc/.txt с автоопределением кодировки.

    LRCLIB и большинство редакторов пишут UTF-8, но старые .lrc часто
    сохранены в cp1251. Порядок проверок покрывает оба случая, а
    ``latin-1`` в конце декодирует любой файл без исключения.
    """
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1251"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        # UTF-16 без BOM иногда «успешно» декодируется как utf-8 мусором,
        # поэтому отсеиваем результат с нулевыми байтами.
        if "\x00" in text:
            continue
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return data.decode("latin-1", errors="replace").replace("\r\n", "\n")


class LyricsEditorDialog(_FramelessDialog):
    """Ручное добавление и редактирование текста песни."""

    def __init__(self, parent=None, track_title="", text=""):
        lang = _dialog_lang()
        super().__init__(parent, tr("Add / Edit Lyrics", lang))

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 4, 20, 6)
        col.setSpacing(8)

        if track_title:
            title_label = QLabel(track_title)
            title_label.setObjectName("cdMessage")
            title_label.setWordWrap(True)
            col.addWidget(title_label)

        hint = QLabel(
            tr(
                "Paste lyrics here. LRC timecodes like [00:12.34] are "
                "supported; plain text is shown without highlighting.",
                lang,
            )
        )
        hint.setObjectName("cdHint")
        hint.setWordWrap(True)
        col.addWidget(hint)

        self.editor = QTextEdit()
        self.editor.setObjectName("cdLyricsEdit")
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText(tr("Lyrics text", lang))
        self.editor.setPlainText(text or "")
        self.editor.setTabChangesFocus(True)
        self.editor.setMinimumHeight(280)
        col.addWidget(self.editor, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("cdHint")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        col.addWidget(self.status_label)

        self.body.addWidget(content)

        # Нижняя панель: «Загрузить файл» слева, Save/Cancel справа.
        footer = QWidget()
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 10, 16, 12)
        row.setSpacing(10)

        self.load_button = self._make_button(
            "cdCancel", tr("Load file", lang), "add-folder.svg"
        )
        self.load_button.clicked.connect(self._load_file)
        row.addWidget(self.load_button)
        row.addStretch(1)

        self.cancel_button = self._make_button(
            "cdCancel", tr("Cancel", lang), "cancel.svg"
        )
        self.cancel_button.clicked.connect(self.reject)

        self.save_button = self._make_button(
            "cdConfirm", tr("Save", lang), "save.svg"
        )
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        self.body.addWidget(footer)

        self.setMinimumSize(560, 420)
        self.resize(660, 560)
        self.editor.setFocus()
        # Ставим курсор в конец: при редактировании существующего текста
        # пользователь чаще дописывает, чем начинает заново.
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)

    def lyrics_text(self):
        """Текст из редактора без изменения содержимого."""
        return self.editor.toPlainText()

    def _load_file(self):
        lang = _dialog_lang()
        path, _selected_filter = get_open_file_name(
            self,
            tr("Load lyrics file", lang),
            "",
            "Lyrics (*.lrc *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            content = read_lyrics_file(path)
        except OSError as e:
            self.status_label.setText(
                tr("Could not read lyrics file:\n{error}", lang).format(
                    error=e
                )
            )
            self.status_label.show()
            return
        self.editor.setPlainText(content)
        self.status_label.setText(
            tr("Loaded: {name}", lang).format(name=Path(path).name)
        )
        self.status_label.show()
        self.editor.setFocus()
