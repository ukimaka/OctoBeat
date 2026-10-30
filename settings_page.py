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

"""Страница настроек в стиле Spotify (вкладка в главном окне).

Две колонки: слева навигация (General / Account / Appearance / YouTube /
Data / About), справа — содержимое выбранного раздела. Кнопок Save/Cancel
нет: все настройки применяются мгновенно и сразу сохраняются в QSettings.
"""

import shutil
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from auth_ui import AuthDialog
from dialogs import colored_icon
from translations import tr

CACHE_DIR = Path.home() / ".cache" / "music_player"
COVERS_DIR = CACHE_DIR / "covers"
PLAYLIST_COVERS_DIR = Path.home() / ".local" / "share" / "music_player" / "playlist_covers"
PROFILE_DATA_DIR = Path.home() / ".local" / "share" / "music_player" / "profile"

# Замени на ссылку своего репозитория.
PROJECT_GITHUB_URL = "https://github.com/yourname/music_player"

# Фирменный цвет акцента (как в остальном приложении).
ACCENT = "#5151ab"


class SettingsPage(QWidget):
    """Полноценная страница настроек: навигация слева, контент справа."""

    # Сигнал «тема/масштаб изменились» — главное окно переприменяет настройки.
    ui_settings_changed = pyqtSignal()

    # Сигнал «кроссфейд включён/выключен» — применяется к плееру сразу.
    crossfade_changed = pyqtSignal(bool)

    # Сигнал «показ бейджей источников метаданных изменён» — списки обновляются.
    metadata_badges_changed = pyqtSignal(bool)

    # Сигнал «пользователь вышел из аккаунта» — главное окно чистит состояние.
    logged_out = pyqtSignal()

    # Сигнал «нужно импортировать треки из CSV» — обрабатывает главное окно.
    csv_import_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self._description_labels = []

        lang = self._lang()

        # --- Левая колонка: навигация ---
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        # Не фиксируем ширину: при системном масштабе/узком окне колонка
        # должна сжиматься, а не выдавливать контент за край.
        self.nav.setMinimumWidth(150)
        self.nav.setMaximumWidth(220)
        self.nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.nav.setFocusPolicy(Qt.NoFocus)

        # --- Правая колонка: контент ---
        self.stack = QStackedWidget()

        self._add_nav_item(tr("General", lang), self._build_general_page())
        self._add_nav_item(tr("Account", lang), self._build_account_page())
        self._add_nav_item(tr("Appearance", lang), self._build_appearance_page())
        self._add_nav_item(tr("YouTube", lang), self._build_youtube_page())
        self._add_nav_item(tr("Data", lang), self._build_data_page())
        self._add_nav_item(tr("About", lang), self._build_about_page())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)

        self._load_settings()

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self._connect_signals()

        self.refresh_auth_state()
        self.apply_theme()

    def _lang(self):
        return self.settings.value("language", "en")

    # ------------------------------------------------------------------
    #  Построение страниц
    # ------------------------------------------------------------------
    def _add_nav_item(self, text, widget):
        item = QListWidgetItem(text)
        item.setSizeHint(QSize(0, 38))
        self.nav.addItem(item)
        self.stack.addWidget(widget)

    def _new_page(self, heading):
        """Создаёт страницу с заголовком и возвращает (page, layout)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)

        heading_label = QLabel(heading)
        heading_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading_label)
        layout.addSpacing(16)

        return page, layout

    def _make_row(self, title, description, control=None):
        """Строка настройки: заголовок + серое описание слева, контрол справа."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        text_col.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            # Цвет описания зависит от темы — задаётся в apply_theme().
            self._description_labels.append(desc_label)
            text_col.addWidget(desc_label)

        row.addLayout(text_col, 1)
        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)

        return container

    def _build_general_page(self):
        page, layout = self._new_page(tr("General", self._lang()))

        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(160)
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Русский", "ru")
        layout.addWidget(self._make_row(
            tr("Language", self._lang()),
            tr("Choose the language of the interface.", self._lang()),
            self.language_combo,
        ))

        self.crossfade_check = QCheckBox(tr("Enable Crossfade", self._lang()))
        self.crossfade_check.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Crossfade", self._lang()),
            tr(
                "Smoothly blend the end of the current track into the next one.",
                self._lang(),
            ),
            self.crossfade_check,
        ))

        self.clear_covers_button = QPushButton(tr("Clear Covers", self._lang()))
        self.clear_covers_button.setAutoDefault(False)
        self.clear_covers_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Clear Covers", self._lang()),
            tr(
                "Delete cached track covers and custom playlist covers.",
                self._lang(),
            ),
            self.clear_covers_button,
        ))

        self.clear_all_cache_button = QPushButton(
            tr("Clear ALL Cache", self._lang())
        )
        self.clear_all_cache_button.setAutoDefault(False)
        self.clear_all_cache_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Clear ALL Cache", self._lang()),
            tr(
                "Delete all cached images and profile avatars/banners.",
                self._lang(),
            ),
            self.clear_all_cache_button,
        ))

        self.show_metadata_badges_check = QCheckBox(
            tr("Show metadata source badges", self._lang())
        )
        self.show_metadata_badges_check.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Metadata source badges", self._lang()),
            tr(
                "Display small M/Y/F badges on track covers indicating the metadata source.",
                self._lang(),
            ),
            self.show_metadata_badges_check,
        ))

        layout.addStretch(1)
        return page

    def _build_account_page(self):
        page, layout = self._new_page(tr("Account", self._lang()))
        lang = self._lang()

        self.account_username_label = QLabel("")
        self.account_username_label.setStyleSheet("font-weight: 600;")
        self._account_username_row = self._make_row(
            tr("Username", lang), "", self.account_username_label
        )
        layout.addWidget(self._account_username_row)

        self.account_logout_button = QPushButton(tr("Log Out", lang))
        self.account_logout_button.setObjectName("accountLogoutButton")
        self.account_logout_button.setAutoDefault(False)
        self.account_logout_button.setCursor(Qt.PointingHandCursor)
        self.account_logout_button.setStyleSheet(
            "QPushButton { background-color: #e05a5a; color: #ffffff;"
            " border: none; border-radius: 6px; padding: 6px 18px; }"
            "QPushButton:hover { background-color: #ef6b6b; }"
            "QPushButton:pressed { background-color: #c94f4f; }"
        )
        self._account_logout_row = self._make_row(
            tr("Log Out", lang),
            tr("Sign out of your account on this device.", lang),
            self.account_logout_button,
        )
        layout.addWidget(self._account_logout_row)

        self.account_login_button = QPushButton(tr("Log In / Register", lang))
        self.account_login_button.setObjectName("accountLoginButton")
        self.account_login_button.setAutoDefault(False)
        self.account_login_button.setCursor(Qt.PointingHandCursor)
        self._account_login_row = self._make_row(
            tr("Log In / Register", lang),
            tr("Sign in to your account or create a new one.", lang),
            self.account_login_button,
        )
        layout.addWidget(self._account_login_row)

        layout.addStretch(1)
        return page

    def _build_appearance_page(self):
        page, layout = self._new_page(tr("Appearance", self._lang()))

        self.zoom_combo = QComboBox()
        self.zoom_combo.setMinimumWidth(160)
        # Qt5 не поддерживает QT_SCALE_FACTOR < 1 (UI обрезается), поэтому
        # минимальный безопасный масштаб — 100%.
        for value in (100, 125, 150):
            self.zoom_combo.addItem(f"{value}%", value)
        layout.addWidget(self._make_row(
            tr("Interface zoom", self._lang()),
            tr("Scale of the interface elements.", self._lang()),
            self.zoom_combo,
        ))

        # Аварийный сброс: при 150% интерфейс может быть настолько крупным,
        # что обычный выбор в комбобоксе становится неудобным.
        self.reset_zoom_button = QPushButton(
            tr("Reset Zoom (100%)", self._lang())
        )
        self.reset_zoom_button.setAutoDefault(False)
        self.reset_zoom_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Reset zoom", self._lang()),
            tr(
                "Return the interface to its normal size. "
                "A restart is required.",
                self._lang(),
            ),
            self.reset_zoom_button,
        ))

        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(160)
        self.theme_combo.addItem(tr("Dark", self._lang()), "dark")
        self.theme_combo.addItem(tr("Light", self._lang()), "light")
        layout.addWidget(self._make_row(
            tr("Theme", self._lang()),
            tr("Choose the color scheme of the application.", self._lang()),
            self.theme_combo,
        ))

        layout.addStretch(1)
        return page

    def _build_youtube_page(self):
        page, layout = self._new_page(tr("YouTube", self._lang()))

        self.cookies_edit = QLineEdit()
        self.cookies_edit.setReadOnly(True)
        self.cookies_edit.setMinimumWidth(240)
        self.cookies_edit.setPlaceholderText(tr("No file selected", self._lang()))

        self.browse_button = QPushButton(tr("Browse...", self._lang()))
        self.browse_button.setAutoDefault(False)

        control = QWidget()
        control_row = QHBoxLayout(control)
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        control_row.addWidget(self.cookies_edit)
        control_row.addWidget(self.browse_button)

        layout.addWidget(self._make_row(
            tr("Path to cookies.txt", self._lang()),
            tr("A cookies.txt file is used to download music from YouTube.", self._lang()),
            control,
        ))



        layout.addStretch(1)
        return page

    def _build_data_page(self):
        page, layout = self._new_page(tr("Data", self._lang()))

        # --- CHANGED: Кнопка импорта из CSV (возвращаем на место) ---
        self.csv_import_button = QPushButton(tr("Import from CSV", self._lang()))
        self.csv_import_button.setAutoDefault(False)
        self.csv_import_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Import from CSV", self._lang()),
            tr("Import a CSV file with tracks (Spotify/Exportify export).", self._lang()),
            self.csv_import_button,
        ))

        # --- Твой код с выбором папки (который LFM написала) ---
        control_widget = QWidget()
        control_row = QHBoxLayout(control_widget)
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)

        self.music_folder_edit = QLineEdit()
        self.music_folder_edit.setReadOnly(True)
        self.music_folder_edit.setPlaceholderText(tr("Folder where downloaded music is stored.", self._lang()))
        self.music_folder_edit.setMinimumWidth(200)
        self.music_folder_edit.setMaximumWidth(400)
        self.music_folder_edit.setToolTip(tr("Select the folder for downloaded music.", self._lang()))

        # --- Кнопка "Выбрать папку" (если LFM её не добавила, добавь сюда) ---
        # Сигнал подключаем ТОЛЬКО в _connect_signals() — здесь не делать.
        self.browse_music_button = QPushButton(tr("Выбрать папку", self._lang()))
        control_row.addWidget(self.music_folder_edit)
        control_row.addWidget(self.browse_music_button)

        layout.addWidget(self._make_row(
            tr("Папка для музыки", self._lang()),
            tr("Путь, куда будут скачиваться треки.", self._lang()),
            control_widget,
        ))

        layout.addStretch(1)
        return page

    def _build_about_page(self):
        page, layout = self._new_page(tr("About", self._lang()))

        layout.addWidget(self._make_row(
            tr("Music Player v1.0.0", self._lang()),
            tr("A lightweight music player built with PyQt5.", self._lang()),
        ))

        self.report_bug_button = QPushButton(tr("Report a Bug", self._lang()))
        self.report_bug_button.setAutoDefault(False)
        self.report_bug_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Report a Bug", self._lang()),
            tr("Open the project page to report a problem.", self._lang()),
            self.report_bug_button,
        ))

        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    #  Тема
    # ------------------------------------------------------------------
    def apply_theme(self):
        """Перекрашивает навигацию, описания и иконки под текущую тему."""
        theme = self.settings.value("theme", "dark")
        is_dark = theme != "light"
        icon_color = "#ffffff" if is_dark else "#000000"

        if is_dark:
            nav_bg = "#181818"
            item_color = "#b3b3b3"
            item_hover = "#ffffff"
            desc_color = "#a7a7a7"
        else:
            nav_bg = "#f5f5f5"
            item_color = "#555555"
            item_hover = "#000000"
            desc_color = "#5e5e5e"

        self.nav.setStyleSheet(f"""
            QListWidget#settingsNav {{
                background-color: {nav_bg};
                border: none;
                outline: none;
                padding: 8px;
                selection-background-color: {ACCENT};
                selection-color: #ffffff;
            }}
            QListWidget#settingsNav::item {{
                color: {item_color};
                padding: 9px 14px;
                border-radius: 6px;
            }}
            QListWidget#settingsNav::item:hover {{
                color: {item_hover};
                background-color: rgba(128, 128, 128, 0.15);
            }}
            QListWidget#settingsNav::item:selected {{
                background-color: {ACCENT};
                color: #ffffff;
            }}
        """)

        for label in self._description_labels:
            label.setStyleSheet(f"color: {desc_color}; font-size: 12px;")

        for button in (self.clear_covers_button, self.clear_all_cache_button):
            button.setIcon(colored_icon("trash.svg", icon_color))
            button.setIconSize(QSize(18, 18))
        self.browse_button.setIcon(colored_icon("show-folder-with-music.svg", icon_color))
        self.browse_button.setIconSize(QSize(18, 18))
        self.report_bug_button.setIcon(colored_icon("bug.svg", icon_color))
        self.report_bug_button.setIconSize(QSize(18, 18))
        self.csv_import_button.setIcon(colored_icon("add-music.svg", icon_color))
        self.csv_import_button.setIconSize(QSize(18, 18))

    # ------------------------------------------------------------------
    #  Настройки
    # ------------------------------------------------------------------
    def _load_settings(self):
        language = self.settings.value("language", "en")
        index = self.language_combo.findData(language)
        self.language_combo.setCurrentIndex(max(index, 0))

        self.crossfade_check.setChecked(
            bool(self.settings.value("enable_crossfade", True, type=bool))
        )

        self.show_metadata_badges_check.setChecked(
            bool(self.settings.value("show_metadata_source_badges", False, type=bool))
        )

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

        self.music_folder_edit.setText(self.settings.value("download_dir", str(Path.home() / "Music")))

    # ------------------------------------------------------------------
    #  Аккаунт
    # ------------------------------------------------------------------
    def refresh_auth_state(self):
        """Показывает имя пользователя и Log Out либо кнопку входа."""
        token = self.settings.value("api_token")
        authenticated = isinstance(token, str) and bool(token.strip())

        username = self.settings.value("api_username") or "—"
        self.account_username_label.setText(str(username))
        self._account_username_row.setVisible(authenticated)
        self._account_logout_row.setVisible(authenticated)
        self._account_login_row.setVisible(not authenticated)

    def _open_auth_dialog(self):
        dialog = AuthDialog(self)
        dialog.logged_in.connect(self._on_logged_in)
        dialog.exec_()

    def _on_logged_in(self, token):
        try:
            user = ApiClient(token=token, timeout=5).get_me()
            username = str(user.get("username") or "")
        except Exception:
            username = str(self.settings.value("api_username") or "")
        if username:
            self.settings.setValue("api_username", username)
        self.refresh_auth_state()

    def _on_logout(self):
        self.settings.remove("api_token")
        self.settings.remove("api_username")
        self.refresh_auth_state()
        self.logged_out.emit()

    # ------------------------------------------------------------------
    #  Сигналы (мгновенное применение)
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # currentIndexChanged подключаем после _load_settings(), иначе
        # установка начальных значений тут же применила бы настройки.
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.crossfade_check.toggled.connect(self._on_crossfade_toggled)
        self.show_metadata_badges_check.toggled.connect(
            self._on_metadata_badges_toggled
        )
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        self.reset_zoom_button.clicked.connect(self._on_reset_zoom)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.clear_covers_button.clicked.connect(self._on_clear_covers)
        self.clear_all_cache_button.clicked.connect(self._on_clear_all_cache)
        self.browse_button.clicked.connect(self._on_browse_cookies)
        self.browse_music_button.clicked.connect(self._on_browse_music_folder)
        self.csv_import_button.clicked.connect(self.csv_import_requested.emit)
        self.report_bug_button.clicked.connect(self._on_report_bug)
        self.account_login_button.clicked.connect(self._open_auth_dialog)
        self.account_logout_button.clicked.connect(self._on_logout)

    def _on_language_changed(self):
        lang = self.language_combo.currentData()
        self.settings.setValue("language", lang)
        QMessageBox.information(
            self,
            tr("Language changed", lang),
            tr("Restart required", lang),
        )

    def _on_crossfade_toggled(self, enabled):
        """Сохраняет флаг и сразу применяет его к работающему плееру."""
        self.settings.setValue("enable_crossfade", bool(enabled))
        self.settings.sync()
        self.crossfade_changed.emit(bool(enabled))

    def _on_metadata_badges_toggled(self, enabled):
        """Сохраняет настройку показа бейджей и уведомляет списки треков."""
        self.settings.setValue("show_metadata_source_badges", bool(enabled))
        self.settings.sync()
        self.metadata_badges_changed.emit(bool(enabled))

    def _on_zoom_changed(self):
        zoom = self.zoom_combo.currentData()
        self.settings.setValue("zoom", zoom)
        # QT_SCALE_FACTOR читается только при создании QApplication,
        # поэтому применяем масштаб после перезапуска.
        lang = self._lang()
        QMessageBox.information(
            self,
            tr("Zoom changed", lang),
            tr(
                "The zoom change will take effect after the application restarts.",
                lang,
            ),
        )

    def _on_reset_zoom(self):
        """Принудительно возвращает 100% — даже если UI сейчас огромный."""
        self.settings.setValue("zoom", 100)
        self.settings.sync()

        index = self.zoom_combo.findData(100)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentIndex(max(index, 0))
        self.zoom_combo.blockSignals(False)

        lang = self._lang()
        QMessageBox.information(
            self,
            tr("Zoom changed", lang),
            tr(
                "The zoom change will take effect after the application restarts.",
                lang,
            ),
        )

    def _on_theme_changed(self):
        self.settings.setValue("theme", self.theme_combo.currentData())
        self.ui_settings_changed.emit()

    # ------------------------------------------------------------------
    #  Действия
    # ------------------------------------------------------------------
    @staticmethod
    def _remove_contents(directory):
        """Удаляет содержимое папки, не трогая саму папку."""
        removed = 0
        if not directory.is_dir():
            return removed
        for entry in directory.iterdir():
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def _on_clear_covers(self):
        """Удаляет только кэш обложек треков и обложки плейлистов."""
        removed = self._remove_contents(COVERS_DIR)
        removed += self._remove_contents(PLAYLIST_COVERS_DIR)

        lang = self._lang()
        QMessageBox.information(
            self,
            tr("Clear Covers", lang),
            tr(
                "Covers cleared successfully.\nRemoved {n} item(s).", lang
            ).format(n=removed),
        )

    def _on_clear_all_cache(self):
        """Полная очистка кэша и пользовательских аватарок/баннеров."""
        lang = self._lang()
        answer = QMessageBox.warning(
            self,
            tr("Clear ALL Cache", lang),
            tr(
                "This will delete all cached images and your profile "
                "avatar/banner. Continue?",
                lang,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._remove_contents(CACHE_DIR)
        if PROFILE_DATA_DIR.is_dir():
            try:
                shutil.rmtree(PROFILE_DATA_DIR)
            except OSError:
                pass

        QMessageBox.information(
            self,
            tr("Clear ALL Cache", lang),
            tr("All cache cleared successfully.", lang),
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
            self.settings.setValue("youtube_cookies", path)
            self.settings.sync()

    def _on_browse_music_folder(self):
        start_dir = self.music_folder_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            tr("Выберите папку", self._lang()),
            start_dir,
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.music_folder_edit.setText(path)
            self.settings.setValue("download_dir", path)
            self.settings.sync()

    def _on_report_bug(self):
        QDesktopServices.openUrl(QUrl("https://github.com/ukimaka/OctoBeat/issues"))
