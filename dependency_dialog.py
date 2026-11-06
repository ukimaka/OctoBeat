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

"""Стеклянный диалог об отсутствующем FFmpeg и его авто-установке."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from dialog_base import _FramelessDialog, _dialog_lang
from translations import tr


def _format_size(value):
    """Байты → компактная строка для прогресса."""
    value = max(0, int(value or 0))
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


class DependencyDialog(_FramelessDialog):
    """Предлагает скачать статический FFmpeg в папку данных приложения."""

    download_requested = pyqtSignal()

    def __init__(self, parent=None, missing=None, target_dir=""):
        lang = _dialog_lang()
        super().__init__(parent, tr("FFmpeg is required", lang))

        self._lang = lang
        self._downloading = False
        self._target_dir = str(target_dir or "")

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(20, 8, 20, 6)
        col.setSpacing(8)

        message = QLabel(
            tr(
                "OctoBeat needs FFmpeg to download and convert music.",
                lang,
            )
            + "\n"
            + tr(
                "FFmpeg and FFprobe were not found in the system PATH "
                "or in the application data folder.",
                lang,
            )
        )
        message.setObjectName("cdMessage")
        message.setWordWrap(True)
        col.addWidget(message)

        tools = QLabel(
            tr("Missing:", lang) + " " + ", ".join(missing or [])
        )
        tools.setObjectName("cdMessage")
        tools.setWordWrap(True)
        col.addWidget(tools)

        hint = QLabel(
            tr(
                "OctoBeat will download a static build and place it in:",
                lang,
            )
            + "\n"
            + self._target_dir
        )
        hint.setObjectName("cdHint")
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(hint)

        self.progress = QProgressBar()
        self.progress.setObjectName("cdProgress")
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 0)
        self.progress.hide()
        col.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("cdHint")
        self.status.setWordWrap(True)
        self.status.hide()
        col.addWidget(self.status)

        self.body.addWidget(content)

        self.cancel_button = self._make_button(
            "cdCancel", tr("Later", lang), "cancel.svg"
        )
        self.cancel_button.clicked.connect(self.reject)

        self.download_button = self._make_button(
            "cdConfirm",
            tr("Download automatically", lang),
            "confirm.svg",
        )
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self._on_download_clicked)

        self._add_footer([self.cancel_button, self.download_button])
        self.setMinimumWidth(440)
        self.download_button.setFocus()

    # ------------------------------------------------------------------
    #  Состояния
    # ------------------------------------------------------------------
    def _fit(self):
        """Пересчитывает размер после показа/скрытия прогресса."""
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()

    def _on_download_clicked(self):
        if self._downloading:
            return
        self.set_downloading()
        self.download_requested.emit()

    def set_downloading(self):
        self._downloading = True
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.progress.setFormat(tr("Preparing download...", self._lang))
        self.progress.show()
        self.status.setText(tr("Downloading...", self._lang))
        self.status.show()
        self.download_button.setEnabled(False)
        self.download_button.setText(tr("Downloading...", self._lang))
        self.cancel_button.setText(tr("Cancel", self._lang))
        self._fit()

    def set_progress(self, downloaded, total):
        self._downloading = True
        if total and total > 0:
            value = max(0, min(int(downloaded), int(total)))
            self.progress.setRange(0, int(total))
            self.progress.setValue(value)
            percent = int(value * 100 / total)
            self.progress.setFormat(
                f"{_format_size(value)} / {_format_size(total)} "
                f"({percent}%)"
            )
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat(
                tr("Downloading...", self._lang)
                + f" {_format_size(downloaded)}"
            )

    def set_error(self, message):
        self._downloading = False
        self.progress.hide()
        self.status.setText(
            tr("Installation failed:", self._lang) + " " + str(message)
        )
        self.status.show()
        self.cancel_button.setText(tr("Later", self._lang))
        self.download_button.setEnabled(True)
        self.download_button.setText(tr("Try again", self._lang))
        self._fit()

    def set_cancelled(self):
        self._downloading = False
        self.progress.hide()
        self.status.hide()
        self.cancel_button.setText(tr("Later", self._lang))
        self.download_button.setEnabled(True)
        self.download_button.setText(
            tr("Download automatically", self._lang)
        )
        self._fit()

    def set_success(self, tools=None):
        self._downloading = False
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setFormat("100%")
        self.progress.show()
        installed = ", ".join(
            str(path) for path in (tools or {}).values() if path
        )
        self.status.setText(
            tr("FFmpeg installed successfully.", self._lang)
            + ((" " + installed) if installed else "")
        )
        self.status.show()
        self.cancel_button.hide()
        self.download_button.setEnabled(True)
        self.download_button.setText(tr("Close", self._lang))
        try:
            self.download_button.clicked.disconnect()
        except TypeError:
            pass
        self.download_button.clicked.connect(self.accept)
        self._fit()
