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

"""Окно настроек приложения (вкладки: General, Appearance, YouTube, About)."""

import shutil
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dialogs import colored_icon
from translations import tr

COVERS_DIR = Path.home() / ".cache" / "music_player" / "covers"
PLAYLIST_COVERS_DIR = Path.home() / ".local" / "share" / "music_player" / "playlist_covers"

# Замени на ссылку своего репозитория.
PROJECT_GITHUB_URL = "https://github.com/yourname/music_player"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("MusicPlayer", "MusicPlayer")

        self.setWindowTitle(tr("Settings", self._lang()))
        self.setMinimumWidth(460)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), tr("General", self._lang()))
        self.tabs.addTab(self._build_appearance_tab(), tr("Appearance", self._lang()))
        self.tabs.addTab(self._build_youtube_tab(), tr("YouTube", self._lang()))
        self.tabs.addTab(self._build_about_tab(), tr("About", self._lang()))

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, self
        )
        self._apply_button_icons()
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.buttons)

        self._load_settings()

    def _lang(self):
        return self.settings.value("language", "en")

    def _apply_button_icons(self):
        """Кастомные иконки Save/Cancel, перекрашенные под текущую тему."""
        theme = self.settings.value("theme", "dark")
        icon_color = "#ffffff" if theme != "light" else "#000000"
        for standard_button, text, icon_name in (
            (QDialogButtonBox.Save, tr("Save", self._lang()), "save.svg"),
            (QDialogButtonBox.Cancel, tr("Cancel", self._lang()), "cancel.svg"),
        ):
            button = self.buttons.button(standard_button)
            if button is None:
                continue
            button.setText(text)
            button.setIcon(colored_icon(icon_name, icon_color))
            button.setIconSize(QSize(18, 18))

    def showEvent(self, event):
        # Окно открывается после применения темы — перекрашиваем иконки заново.
        self._apply_button_icons()
        super().showEvent(event)

    # ------------------------------------------------------------------
    #  Вкладки
    # ------------------------------------------------------------------
    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)

        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Русский", "ru")
        form.addRow(tr("Language:", self._lang()), self.language_combo)

        self.clear_cache_button = QPushButton(tr("Clear Cache", self._lang()))
        self.clear_cache_button.setAutoDefault(False)
        self.clear_cache_button.clicked.connect(self._on_clear_cache)
        form.addRow("", self.clear_cache_button)

        return tab

    def _build_appearance_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)

        self.zoom_combo = QComboBox()
        for value in (75, 100, 125, 150):
            self.zoom_combo.addItem(f"{value}%", value)
        form.addRow(tr("Interface zoom:", self._lang()), self.zoom_combo)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem(tr("Dark", self._lang()), "dark")
        self.theme_combo.addItem(tr("Light", self._lang()), "light")
        form.addRow(tr("Theme:", self._lang()), self.theme_combo)

        return tab

    def _build_youtube_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel(tr("Path to cookies.txt (used for YouTube):", self._lang())))

        row = QHBoxLayout()
        self.cookies_edit = QLineEdit()
        self.cookies_edit.setReadOnly(True)
        self.cookies_edit.setPlaceholderText(tr("No file selected", self._lang()))

        self.browse_button = QPushButton(tr("Browse...", self._lang()))
        self.browse_button.setIcon(colored_icon("show-folder-with-music.svg"))
        self.browse_button.setAutoDefault(False)
        self.browse_button.clicked.connect(self._on_browse_cookies)

        row.addWidget(self.cookies_edit, 1)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        layout.addStretch()

        return tab

    def _build_about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel(tr("Music Player v1.0.0", self._lang())))

        self.report_bug_button = QPushButton(tr("Report a Bug", self._lang()))
        self.report_bug_button.setIcon(colored_icon("bug.svg"))
        self.report_bug_button.setAutoDefault(False)
        self.report_bug_button.clicked.connect(self._on_report_bug)

        layout.addWidget(self.report_bug_button)
        layout.addStretch()

        return tab

    # ------------------------------------------------------------------
    #  Иконки
    # ------------------------------------------------------------------
    @staticmethod
    def _icon(filename):
        return colored_icon(filename)

    # ------------------------------------------------------------------
    #  Настройки
    # ------------------------------------------------------------------
    def _load_settings(self):
        language = self.settings.value("language", "en")
        index = self.language_combo.findData(language)
        self.language_combo.setCurrentIndex(max(index, 0))

        zoom = self.settings.value("zoom", 100)
        try:
            zoom = int(zoom)
        except (TypeError, ValueError):
            zoom = 100
        index = self.zoom_combo.findData(zoom)
        self.zoom_combo.setCurrentIndex(max(index, 0))

        theme = self.settings.value("theme", "dark")
        index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(max(index, 0))

        self.cookies_edit.setText(self.settings.value("youtube_cookies", "") or "")

    def _save_settings(self):
        self.settings.setValue("language", self.language_combo.currentData())
        self.settings.setValue("zoom", self.zoom_combo.currentData())
        self.settings.setValue("theme", self.theme_combo.currentData())
        self.settings.setValue("youtube_cookies", self.cookies_edit.text())

    def _on_save(self):
        self._save_settings()
        self.accept()

    # ------------------------------------------------------------------
    #  Действия
    # ------------------------------------------------------------------
    def _on_clear_cache(self):
        removed = 0
        for directory in (COVERS_DIR, PLAYLIST_COVERS_DIR):
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                    removed += 1
                except OSError:
                    continue

        lang = self._lang()
        QMessageBox.information(
            self,
            tr("Clear Cache", lang),
            tr("Cache cleared successfully.\nRemoved {n} item(s).", lang).format(n=removed),
        )

    def _on_browse_cookies(self):
        start_dir = self.cookies_edit.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select cookies.txt", self._lang()),
            start_dir,
            "Cookies files (*.txt);;All files (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.cookies_edit.setText(path)

    def _on_report_bug(self):
        QDesktopServices.openUrl(QUrl(PROJECT_GITHUB_URL))
