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

Две колонки: слева навигация (General / Appearance / YouTube /
Data / About), справа — содержимое выбранного раздела. Кнопок Save/Cancel
нет: все настройки применяются мгновенно и сразу сохраняются в QSettings.
"""

import shutil
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cookies_store import find_cookies_file, import_cookies, remove_cookies
from dialogs import CustomConfirmDialog, colored_icon
from paths import CACHE_DIR, DATA_DIR, MUSIC_DIR
from styles import available_themes, is_dark_theme
from translations import tr
from ui_common import get_existing_directory, get_open_file_name
from ytdlp_support import DOWNLOAD_MODE_SETTING, normalize_download_mode

COVERS_DIR = CACHE_DIR / "covers"
PLAYLIST_COVERS_DIR = DATA_DIR / "playlist_covers"
PROFILE_DATA_DIR = DATA_DIR / "profile"

# Замени на ссылку своего репозитория.
PROJECT_GITHUB_URL = "https://github.com/yourname/music_player"


class SettingsComboBox(QComboBox):
    """Комбобокс, который открывает список после отпускания кнопки мыши.

    На части Linux-композиторов стандартный popup QComboBox получает
    mouse release сразу после открытия и закрывается. Открытие по
    release гарантирует, что список останется на экране, пока
    пользователь не выберет пункт или не кликнет мимо.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._popup_was_visible = False

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._press_pos = event.pos()
            self._popup_was_visible = self.view().isVisible()
            # Повторный клик по комбобоксу при открытом списке должен
            # закрыть его, а не оставить висеть.
            if self._popup_was_visible:
                self.hidePopup()
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            press_pos = self._press_pos
            popup_was_visible = self._popup_was_visible
            self._press_pos = None
            self._popup_was_visible = False
            if press_pos is not None and self.rect().contains(event.pos()):
                event.accept()
                if not popup_was_visible:
                    # Нулевой таймер — показать popup уже после того, как
                    # этот mouse release полностью обработан.
                    QTimer.singleShot(0, self.showPopup)
                return
        super().mouseReleaseEvent(event)


class SettingsPage(QWidget):
    """Полноценная страница настроек: навигация слева, контент справа."""

    # Сигнал «тема/масштаб изменились» — главное окно переприменяет настройки.
    ui_settings_changed = pyqtSignal()

    # Сигнал «кроссфейд включён/выключен» — применяется к плееру сразу.
    crossfade_changed = pyqtSignal(bool)

    # Сигнал «показ бейджей источников метаданных изменён» — списки обновляются.
    metadata_badges_changed = pyqtSignal(bool)

    # Сигнал «папка музыки изменена» — File Watcher переподключается.
    music_folder_changed = pyqtSignal(str)

    # Сигнал «нужно импортировать треки из CSV» — обрабатывает главное окно.
    csv_import_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self._description_labels = []

        lang = self._lang()

        # --- Левая колонка: навигация ---
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Не фиксируем ширину: при системном масштабе/узком окне колонка
        # должна сжиматься, а не выдавливать контент за край.
        self.nav.setMinimumWidth(150)
        self.nav.setMaximumWidth(220)
        self.nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        # Стандартный клик сразу активирует список и выбранную строку;
        # NoFocus на некоторых платформах откладывал выбор до release.
        self.nav.setFocusPolicy(Qt.StrongFocus)
        # Обычный список без контекстного меню, drag-ghost и прочих
        # обработчиков мыши: выбор срабатывает сразу по нажатию LMB.
        # Навигацию переключает только currentRowChanged -> stack.
        self.nav.setContextMenuPolicy(Qt.NoContextMenu)
        self.nav.setSelectionMode(QAbstractItemView.SingleSelection)
        self.nav.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.nav.setMouseTracking(True)
        self.nav.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.nav.setDragEnabled(False)
        self.nav.setAcceptDrops(False)
        self.nav.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.nav.setDropIndicatorShown(False)

        # --- Правая колонка: контент ---
        self.stack = QStackedWidget()

        self._add_nav_item(tr("General", lang), self._build_general_page())
        self._add_nav_item(tr("Appearance", lang), self._build_appearance_page())
        self._add_nav_item(tr("YouTube", lang), self._build_youtube_page())
        self._add_nav_item(tr("Data", lang), self._build_data_page())
        self._add_nav_item(tr("About", lang), self._build_about_page())

        layout = QHBoxLayout(self)
        # Небольшой отступ превращает навигацию в отдельную стеклянную
        # панель, а не в жёстко приклеенную к краю полосу.
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)

        self._load_settings()

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self._connect_signals()

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
        """Создаёт прокручиваемую страницу и возвращает (page, layout)."""
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)

        heading_label = QLabel(heading)
        heading_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading_label)
        layout.addSpacing(16)

        # При 125–150% масштабе контент выше окна; прокрутка сохраняет
        # доступ к нижним строкам. Горизонтальную прокрутку отключаем —
        # строки ниже ужимаются под ширину вьюпорта.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setWidget(page)
        return scroll, layout

    def _make_row(self, title, description, control=None):
        """Строка настройки: заголовок + серое описание слева, контрол справа."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(16)

        text_wrap = QWidget()
        text_wrap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_wrap.setMinimumWidth(0)
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_label.setMinimumWidth(0)
        text_col.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setSizePolicy(
                QSizePolicy.Ignored, QSizePolicy.Preferred
            )
            desc_label.setMinimumWidth(0)
            # Цвет описания зависит от темы — задаётся в apply_theme().
            self._description_labels.append(desc_label)
            text_col.addWidget(desc_label)

        # Текстовая колонка забирает остаток ширины, контрол всегда
        # остаётся у правого края и не уезжает за вьюпорт при масштабе.
        row.addWidget(text_wrap, 1)
        if control is not None:
            control.setSizePolicy(
                QSizePolicy.Maximum, QSizePolicy.Fixed
            )
            row.addWidget(
                control, 0, Qt.AlignRight | Qt.AlignVCenter
            )

        return container

    def _build_general_page(self):
        page, layout = self._new_page(tr("General", self._lang()))

        self.language_combo = SettingsComboBox()
        self.language_combo.setMinimumWidth(120)
        self.language_combo.setMaximumWidth(220)
        self.language_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.language_combo.setMinimumContentsLength(6)
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

    def _build_appearance_page(self):
        page, layout = self._new_page(tr("Appearance", self._lang()))

        self.zoom_combo = SettingsComboBox()
        self.zoom_combo.setMinimumWidth(120)
        self.zoom_combo.setMaximumWidth(220)
        self.zoom_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.zoom_combo.setMinimumContentsLength(6)
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

        self.theme_combo = SettingsComboBox()
        self.theme_combo.setMinimumWidth(120)
        self.theme_combo.setMaximumWidth(220)
        self.theme_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.theme_combo.setMinimumContentsLength(6)
        themes = available_themes() or ["dark", "light"]
        for name in themes:
            label = name.replace("_", " ").replace("-", " ").title()
            self.theme_combo.addItem(label, name)
        layout.addWidget(self._make_row(
            tr("Theme", self._lang()),
            tr("Choose the color scheme of the application.", self._lang()),
            self.theme_combo,
        ))

        layout.addStretch(1)
        return page

    def _build_youtube_page(self):
        page, layout = self._new_page(tr("YouTube", self._lang()))
        lang = self._lang()

        self.download_mode_combo = SettingsComboBox()
        self.download_mode_combo.setMinimumWidth(220)
        self.download_mode_combo.setMaximumWidth(300)
        self.download_mode_combo.addItem(
            tr("Speed (original format)", lang), "native"
        )
        self.download_mode_combo.addItem(
            tr("Compatibility (MP3 320 kbps)", lang), "mp3"
        )
        layout.addWidget(self._make_row(
            tr("Download format", lang),
            tr(
                "Speed keeps the original M4A/WebM audio without "
                "re-encoding. Compatibility converts it to MP3 320 kbps.",
                lang,
            ),
            self.download_mode_combo,
        ))

        self.cookies_status_edit = QLineEdit()
        self.cookies_status_edit.setReadOnly(True)
        self.cookies_status_edit.setMinimumWidth(240)
        self.cookies_status_edit.setMaximumWidth(360)
        self.cookies_status_edit.setPlaceholderText(
            tr("No cookies.txt found", lang)
        )

        self.import_cookies_button = QPushButton(
            tr("Import cookies.txt", lang)
        )
        self.import_cookies_button.setAutoDefault(False)
        self.delete_cookies_button = QPushButton(
            tr("Delete cookies", lang)
        )
        self.delete_cookies_button.setAutoDefault(False)

        cookie_control = QWidget()
        cookie_col = QVBoxLayout(cookie_control)
        cookie_col.setContentsMargins(0, 0, 0, 0)
        cookie_col.setSpacing(6)
        cookie_col.addWidget(self.cookies_status_edit)
        cookie_buttons = QHBoxLayout()
        cookie_buttons.setContentsMargins(0, 0, 0, 0)
        cookie_buttons.setSpacing(8)
        cookie_buttons.addWidget(self.import_cookies_button)
        cookie_buttons.addWidget(self.delete_cookies_button)
        cookie_buttons.addStretch(1)
        cookie_col.addLayout(cookie_buttons)

        layout.addWidget(self._make_row(
            tr("Cookies file", lang),
            tr(
                "OctoBeat looks for cookies.txt in the app data folder "
                "and in the music folder. Import a file if YouTube asks "
                "you to sign in.",
                lang,
            ),
            cookie_control,
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
        self.music_folder_edit.setMinimumWidth(140)
        self.music_folder_edit.setMaximumWidth(260)
        self.music_folder_edit.setToolTip(tr("Select the folder for downloaded music.", self._lang()))

        # --- Кнопка "Выбрать папку" (если LFM её не добавила, добавь сюда) ---
        # Сигнал подключаем ТОЛЬКО в _connect_signals() — здесь не делать.
        self.browse_music_button = QPushButton(tr("Select folder", self._lang()))
        control_row.addWidget(self.music_folder_edit)
        control_row.addWidget(self.browse_music_button)

        layout.addWidget(self._make_row(
            tr("Music folder", self._lang()),
            tr("Folder where downloaded music is stored.", self._lang()),
            control_widget,
        ))

        self.auto_update_check = QCheckBox(
            tr("Check for updates automatically", self._lang())
        )
        self.auto_update_check.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._make_row(
            tr("Automatic updates", self._lang()),
            tr("Check GitHub for new releases on startup.", self._lang()),
            self.auto_update_check,
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
        """Перекрашивает описания и иконки под текущую тему.
        Навигация (QListWidget#settingsNav) стилизуется через QSS-тему
        (styles.BASE_QSS + theme.qss), здесь только описания и иконки.
        """
        theme = self.settings.value("theme", "dark")
        is_dark = is_dark_theme(theme)
        icon_color = "#ffffff" if is_dark else "#000000"
        desc_color = "#a7a7a7" if is_dark else "#5e5e5e"

        for label in self._description_labels:
            label.setStyleSheet(f"color: {desc_color}; font-size: 12px;")

        # Принудительно обновляем стиль навигации после смены QSS-темы.
        self.nav.style().unpolish(self.nav)
        self.nav.style().polish(self.nav)
        vp = self.nav.viewport()
        vp.style().unpolish(vp)
        vp.style().polish(vp)

        for button in (self.clear_covers_button, self.clear_all_cache_button):
            button.setIcon(colored_icon("trash.svg", icon_color))
            button.setIconSize(QSize(18, 18))
        self.import_cookies_button.setIcon(
            colored_icon("download.svg", icon_color)
        )
        self.import_cookies_button.setIconSize(QSize(18, 18))
        self.delete_cookies_button.setIcon(
            colored_icon("trash.svg", icon_color)
        )
        self.delete_cookies_button.setIconSize(QSize(18, 18))
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

        self.auto_update_check.setChecked(
            bool(self.settings.value("auto_update", True, type=bool))
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

        mode = normalize_download_mode(
            self.settings.value(DOWNLOAD_MODE_SETTING, "native")
        )
        index = self.download_mode_combo.findData(mode)
        self.download_mode_combo.setCurrentIndex(max(index, 0))
        self._refresh_cookies_status()

        self.music_folder_edit.setText(self.settings.value("download_dir", str(MUSIC_DIR)))

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
        self.auto_update_check.toggled.connect(self._on_auto_update_toggled)
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        self.reset_zoom_button.clicked.connect(self._on_reset_zoom)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.clear_covers_button.clicked.connect(self._on_clear_covers)
        self.clear_all_cache_button.clicked.connect(self._on_clear_all_cache)
        self.download_mode_combo.currentIndexChanged.connect(
            self._on_download_mode_changed
        )
        self.import_cookies_button.clicked.connect(self._on_import_cookies)
        self.delete_cookies_button.clicked.connect(self._on_delete_cookies)
        self.browse_music_button.clicked.connect(self._on_browse_music_folder)
        self.csv_import_button.clicked.connect(self.csv_import_requested.emit)
        self.report_bug_button.clicked.connect(self._on_report_bug)

    def _on_language_changed(self):
        lang = self.language_combo.currentData()
        self.settings.setValue("language", lang)
        CustomConfirmDialog.information(
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

    def _on_auto_update_toggled(self, enabled):
        """Запоминает, проверять ли обновления при запуске."""
        self.settings.setValue("auto_update", bool(enabled))
        self.settings.sync()

    def _on_zoom_changed(self):
        zoom = self.zoom_combo.currentData()
        self.settings.setValue("zoom", zoom)
        # QT_SCALE_FACTOR читается только при создании QApplication,
        # поэтому применяем масштаб после перезапуска.
        lang = self._lang()
        CustomConfirmDialog.information(
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
        CustomConfirmDialog.information(
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
        CustomConfirmDialog.information(
            self,
            tr("Clear Covers", lang),
            tr(
                "Covers cleared successfully.\nRemoved {n} item(s).", lang
            ).format(n=removed),
        )

    def _on_clear_all_cache(self):
        """Полная очистка кэша и пользовательских аватарок/баннеров."""
        lang = self._lang()
        answer = CustomConfirmDialog.question(
            self,
            tr("Clear ALL Cache", lang),
            tr(
                "This will delete all cached images and your profile "
                "avatar/banner. Continue?",
                lang,
            ),
        )
        if not answer:
            return

        self._remove_contents(CACHE_DIR)
        if PROFILE_DATA_DIR.is_dir():
            try:
                shutil.rmtree(PROFILE_DATA_DIR)
            except OSError:
                pass

        CustomConfirmDialog.information(
            self,
            tr("Clear ALL Cache", lang),
            tr("All cache cleared successfully.", lang),
        )

    def _refresh_cookies_status(self):
        path = find_cookies_file()
        if path is not None:
            self.cookies_status_edit.setText(str(path))
            self.cookies_status_edit.setToolTip(str(path))
            self.delete_cookies_button.setEnabled(True)
        else:
            self.cookies_status_edit.clear()
            self.cookies_status_edit.setToolTip("")
            self.delete_cookies_button.setEnabled(False)

    def _on_import_cookies(self):
        lang = self._lang()
        path, _ = get_open_file_name(
            self,
            tr("Select cookies.txt", lang),
            str(Path.home()),
            "Cookies files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            import_cookies(path)
        except OSError as exc:
            CustomConfirmDialog.information(
                self,
                tr("Error", lang),
                tr("Could not import cookies.txt:\n{e}", lang).format(e=exc),
            )
            return
        self._refresh_cookies_status()

    def _on_delete_cookies(self):
        if find_cookies_file() is None:
            return
        lang = self._lang()
        if not CustomConfirmDialog.question(
            self,
            tr("Delete cookies", lang),
            tr(
                "Delete cookies.txt from all OctoBeat cookie locations?",
                lang,
            ),
        ):
            return
        remove_cookies()
        self._refresh_cookies_status()

    def _on_download_mode_changed(self):
        mode = normalize_download_mode(
            self.download_mode_combo.currentData()
        )
        self.settings.setValue(DOWNLOAD_MODE_SETTING, mode)
        self.settings.sync()

    def _on_browse_music_folder(self):
        start_dir = self.music_folder_edit.text() or str(Path.home())
        path = get_existing_directory(
            self,
            tr("Choose folder", self._lang()),
            start_dir,
        )
        if path:
            self.music_folder_edit.setText(path)
            self.settings.setValue("download_dir", path)
            self.settings.sync()
            self.music_folder_changed.emit(path)

    def _on_report_bug(self):
        QDesktopServices.openUrl(QUrl("https://github.com/ukimaka/OctoBeat/issues"))
