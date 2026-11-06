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

"""Вкладка «Профиль»: шапка, локальная статистика и любимый трек."""

import shutil
import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import db
import metadata
from dialogs import (
    CustomInputDialog,
    colored_pixmap,
)
from profile_assets import (
    PROFILE_COVERS_DIR,
    _copy_profile_image,
    _cover_pixmap,
    _icon_color,
    _lang,
    _round_avatar_pixmap,
)
from profile_widgets import (
    BBCodeEditorDialog,
    BannerLabel,
    HoverImageLabel,
    ProfileTextBrowser,
    _description_html,
)
from translations import tr
from qt_diagnostics import note, track_thread
from qt_lifecycle import retire_thread
from ui_common import get_open_file_name

# Размер обложек в истории/топе треков профиля. Раньше 36 px выглядели
# как сильно сжатые иконки; 56 px читаются как настоящие миниатюры.
TRACK_COVER_SIZE = 56

# Достижения: (ключ, иконка, пороги уровней, подпись для тултипа)
ACHIEVEMENT_TIERS = ("Bronze", "Silver", "Gold", "Diamond")
ACHIEVEMENT_COLORS = ("#cd7f32", "#c0c0c0", "#ffd700", "#7fdfff")
ACHIEVEMENT_LOCKED_COLOR = "#5a5a5a"

ACHIEVEMENTS = (
    ("tracks", "count.svg", (100, 500, 1000, 2000), "Tracks downloaded"),
    ("playlists", "create-playlist.svg", (5, 10, 25, 50), "Playlists created"),
    ("time", "time.svg", (3600, 36000, 180000, 360000), "Listening time"),
    ("age", "favorite.svg", (30, 90, 180, 365), "Library age"),
)


def _achievement_level(value, thresholds):
    """Сколько порогов достигнуто (0..len(thresholds))."""
    level = 0
    for threshold in thresholds:
        if value >= threshold:
            level += 1
        else:
            break
    return level


def _format_achievement_value(key, value):
    """Человекочитаемое значение достижения (время — в часах)."""
    if key == "time":
        return f"{value // 3600}h"
    return str(value)


class _DoubleClickLabel(QLabel):
    """QLabel, сообщающий о двойном клике."""

    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class _ClickableCard(QFrame):
    """Карточка с курсором-рукой и подсветкой при наведении.

    Сигнал `clicked` несёт id плейлиста.
    """

    clicked = pyqtSignal(int)

    def __init__(self, playlist_id, parent=None):
        super().__init__(parent)
        self.playlist_id = playlist_id
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.playlist_id)
        super().mouseReleaseEvent(event)


class CoverLoader(QThread):
    """Локальный кэш обложки для профиля.

    SomeDL уже вшивает обложку 544x544 в теги аудиофайла при скачивании,
    поэтому отдельного поиска в MusicBrainz/YouTube больше не требуется.
    Если обложка ещё не закэширована в профиле, копируем её из тегов
    аудиофайла (встроенная обложка).
    """

    # QImage можно создавать в фоновом потоке, QPixmap — только в GUI.
    loaded = pyqtSignal(int, QImage)   # track_id, обложка

    def __init__(
        self,
        track_id,
        query,
        parent=None,
        artist=None,
        title=None,
        file_path=None,
    ):
        super().__init__(parent)
        track_thread(self, "cover-loader")
        self.track_id = track_id
        self.query = (query or "").strip()
        self.artist = (artist or "").strip()
        self.title = (title or "").strip()
        self.file_path = (file_path or "").strip()
        self._cancelled = False

    def cancel(self) -> None:
        """Отменяет загрузку: результат после закрытия окна не нужен."""
        self._cancelled = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self):
        if self._is_cancelled():
            return
        note(f"cover-loader start track={self.track_id}")
        cover_file = PROFILE_COVERS_DIR / f"{self.track_id}.jpg"
        if not (cover_file.exists() and cover_file.stat().st_size > 0):
            source = self._find_cover()
            if not source or self._is_cancelled():
                return
            try:
                PROFILE_COVERS_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, cover_file)
            except Exception as exc:
                print(f"[cover] cannot cache cover: {exc}")
                return

        # Полноразмерная обложка — лишние мегабайты: в профиле она
        # показывается миниатюрой (TRACK_COVER_SIZE). Уменьшаем до 144 px
        # (запас под High-DPI). QImage безопасен в фоновом потоке; QPixmap
        # создаст GUI-поток в слоте _on_cover_loaded().
        image = QImage(str(cover_file))
        if image.isNull():
            return
        if image.width() > 144 or image.height() > 144:
            image = image.scaled(
                144, 144, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        if self._is_cancelled():
            return
        self.loaded.emit(self.track_id, image)
        note(f"cover-loader done track={self.track_id}")

    def _find_cover(self):
        """Встроенная обложка из тегов SomeDL (без сетевых запросов)."""
        from pathlib import Path

        if not self.file_path or not Path(self.file_path).is_file():
            return ""
        # metadata.read_embedded_cover читает APIC/covr прямо из файла.
        try:
            data = metadata.read_embedded_cover(self.file_path)
        except Exception as exc:
            print(f"[cover] embedded cover read failed: {exc}")
            data = None
        if not data:
            return ""
        # Сохраняем временно, чтобы скопировать в профиль.
        tmp = Path(tempfile.gettempdir()) / f"octobeat_cover_{self.track_id}.jpg"
        try:
            tmp.write_bytes(data)
            return str(tmp)
        except OSError as exc:
            print(f"[cover] cannot write temp cover: {exc}")
            return ""



class ProfilePage(QWidget):
    """Вкладка «Профиль»: шапка и локальная статистика прослушиваний."""

    playlist_clicked = pyqtSignal(int)
    avatar_changed = pyqtSignal(str)

    BANNER_HEIGHT = 150
    AVATAR_SIZE = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("profilePage")
        self._icon_labels = []
        self._cover_loaders = {}
        self._cover_labels = {}
        self._banner_path = None
        self._avatar_path = None
        self._build_ui()
        self.reload_stats()

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        lang = _lang()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Баннер: сжимается вместе с окном, картинка обрезается.
        self.banner_label = BannerLabel()
        self.banner_label.setFixedHeight(self.BANNER_HEIGHT)
        self.banner_label.clicked.connect(self._change_banner)
        content_layout.addWidget(self.banner_label)

        # --- Шапка: аватарка, никнейм, достижения ---
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 16)
        header_layout.setSpacing(16)

        self.avatar_label = HoverImageLabel()
        self.avatar_label.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
        self.avatar_label.clicked.connect(self._change_avatar)
        header_layout.addWidget(self.avatar_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        self.nickname_label = _DoubleClickLabel()
        self.nickname_label.setObjectName("profileNickname")
        self.nickname_label.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )
        self.nickname_label.setToolTip(
            tr("Double-click to edit the nickname", lang)
        )
        self.nickname_label.doubleClicked.connect(self._edit_nickname)
        text_col.addWidget(self.nickname_label)

        text_col.addStretch(1)
        header_layout.addLayout(text_col, 1)

        # Блок достижений (справа от аватарки и никнейма)
        self.achievements_container = QWidget()
        self.achievements_layout = QHBoxLayout(self.achievements_container)
        self.achievements_layout.setContentsMargins(0, 0, 0, 0)
        self.achievements_layout.setSpacing(12)
        header_layout.addWidget(self.achievements_container, 0, Qt.AlignTop)

        content_layout.addWidget(header)

        # --- About Me (на всю ширину, рендер BBCode) ---
        about = QWidget()
        about_layout = QVBoxLayout(about)
        about_layout.setContentsMargins(20, 0, 20, 12)
        about_layout.setSpacing(6)
        about_layout.addWidget(
            self._section_title("user.svg", tr("About Me", lang))
        )
        self.description_label = ProfileTextBrowser()
        self.description_label.setObjectName("profileDescription")
        self.description_label.setToolTip(
            tr("Double-click to edit About Me", lang)
        )
        self.description_label.doubleClicked.connect(self._edit_about)
        about_layout.addWidget(self.description_label)
        content_layout.addWidget(about)

        # --- Статистика: две колонки, выровненные по верхнему краю ---
        stats = QWidget()
        stats_grid = QGridLayout(stats)
        self.stats_grid = stats_grid
        stats_grid.setContentsMargins(20, 8, 20, 20)
        stats_grid.setHorizontalSpacing(32)
        stats_grid.setVerticalSpacing(0)

        # Левая колонка: Total Time, Top Tracks
        left = QWidget()
        self.left_stats_widget = left
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(18)

        # Total Time
        total_box = QVBoxLayout()
        total_box.setSpacing(6)
        total_title = self._section_title("time.svg", tr("Total Time", lang))
        self.total_time_label = QLabel()
        font = self.total_time_label.font()
        font.setPointSize(font.pointSize() + 14)
        font.setBold(True)
        self.total_time_label.setFont(font)
        total_box.addWidget(total_title)
        total_box.addWidget(self.total_time_label)
        left_col.addLayout(total_box)

        # Top Tracks
        self.top_tracks_title = self._section_title(
            "count.svg", tr("Top Tracks", lang)
        )
        left_col.addWidget(self.top_tracks_title)
        self.top_tracks_container = QWidget()
        self.top_tracks_layout = QVBoxLayout(self.top_tracks_container)
        self.top_tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.top_tracks_layout.setSpacing(6)
        left_col.addWidget(self.top_tracks_container)
        left_col.addStretch(1)

        # Правая колонка: Favorite Track, Public Playlists
        right = QWidget()
        self.right_stats_widget = right
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(18)

        # Favorite Track
        self.favorite_title = self._section_title(
            "favorite.svg", tr("Favorite Track", lang)
        )
        right_col.addWidget(self.favorite_title)
        self.favorite_container = QWidget()
        self.favorite_layout = QVBoxLayout(self.favorite_container)
        self.favorite_layout.setContentsMargins(0, 0, 0, 0)
        self.favorite_layout.setSpacing(6)
        right_col.addWidget(self.favorite_container)

        # Public Playlists: компактная сетка кликабельных карточек
        self.public_playlists_title = self._section_title(
            "create-playlist.svg", tr("Public Playlists", lang)
        )
        right_col.addWidget(self.public_playlists_title)
        self.public_playlists_container = QWidget()
        self.public_playlists_grid = QGridLayout(self.public_playlists_container)
        self.public_playlists_grid.setContentsMargins(0, 0, 0, 0)
        self.public_playlists_grid.setSpacing(10)
        self.public_playlists_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        right_col.addWidget(self.public_playlists_container)
        right_col.addStretch(1)

        # Обе колонки начинаются на одном уровне (Qt.AlignTop)
        stats_grid.addWidget(left, 0, 0, Qt.AlignTop)
        stats_grid.addWidget(right, 0, 1, Qt.AlignTop)
        stats_grid.setColumnStretch(0, 1)
        stats_grid.setColumnStretch(1, 1)

        content_layout.addWidget(stats)
        content_layout.addStretch(1)
        self.stats_widget = stats

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidget(content)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(self.scroll_area)

    # ------------------------------------------------------------------
    #  Чужой профиль
    # ------------------------------------------------------------------

    def _section_title(self, icon_name, text):
        """Заголовок секции: иконка + подпись."""
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(
            colored_pixmap(icon_name, 20, _icon_color())
        )
        self._icon_labels.append((icon_label, icon_name))

        caption = QLabel(text)
        font = caption.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        caption.setFont(font)

        row.addWidget(icon_label)
        row.addWidget(caption)
        row.addStretch(1)
        return widget

    def _track_row(self, track_id, cover_path, title, subtitle=None, query=None):
        """Карточка трека: обложка + название (+ вторичный текст)."""
        wrapper = QFrame()
        wrapper.setFrameShape(QFrame.NoFrame)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        cover = QLabel()
        cover.setFixedSize(TRACK_COVER_SIZE, TRACK_COVER_SIZE)
        self._set_cover(
            cover,
            track_id,
            cover_path,
            query,
            artist=subtitle,
            title=title,
        )
        row.addWidget(cover)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(title)
        font = title_label.font()
        font.setBold(True)
        title_label.setFont(font)
        text_col.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet("color: #8a8a8a;")
            text_col.addWidget(subtitle_label)

        row.addLayout(text_col, 1)
        return wrapper

    def _set_cover(
        self,
        cover_label,
        track_id,
        cover_path,
        query,
        artist=None,
        title=None,
    ):
        """Ставит локальную обложку или заглушку + подгружает её из сети."""
        if cover_path:
            cover_label.setPixmap(_cover_pixmap(cover_path, TRACK_COVER_SIZE))
            return

        cached = PROFILE_COVERS_DIR / f"{track_id}.jpg"
        if cached.exists() and cached.stat().st_size > 0:
            cover_label.setPixmap(_cover_pixmap(str(cached), TRACK_COVER_SIZE))
            return

        cover_label.setPixmap(_cover_pixmap(None, TRACK_COVER_SIZE))
        self._cover_labels.setdefault(track_id, []).append(cover_label)
        self._start_cover_loader(
            track_id,
            query,
            artist=artist,
            title=title,
        )

    def _start_cover_loader(self, track_id, query, artist=None, title=None):
        if not query and not title:
            return
        loader = self._cover_loaders.get(track_id)
        if loader is not None and loader.isRunning():
            return
        # Получаем путь к файлу из БД, чтобы прочитать встроенную обложку.
        row = db.get_track_by_id(track_id)
        file_path = row["file_path"] if row else ""
        loader = CoverLoader(
            track_id,
            query,
            artist=artist,
            title=title,
            file_path=file_path,
        )
        loader.loaded.connect(self._on_cover_loaded)
        loader.finished.connect(
            lambda l=loader, tid=track_id: self._on_cover_loader_finished(
                tid, l
            )
        )
        self._cover_loaders[track_id] = loader
        loader.start()

    def _on_cover_loader_finished(self, track_id, loader):
        """Убирает завершённый QThread из словаря и отдаёт его Qt."""
        try:
            if self._cover_loaders.get(track_id) is loader:
                self._cover_loaders.pop(track_id, None)
            loader.deleteLater()
        except RuntimeError:
            pass

    def _on_cover_loaded(self, track_id, image):
        # QPixmap создаётся здесь, в GUI-потоке, а не в CoverLoader.run().
        pixmap = QPixmap.fromImage(image)
        # Ссылки на QLabel больше не нужны после первой установки обложки.
        labels = self._cover_labels.pop(track_id, [])
        for label in labels:
            try:
                label.setPixmap(_cover_pixmap(pixmap, TRACK_COVER_SIZE))
            except RuntimeError:
                # Виджет уже удалён (страница перерисована/закрыта).
                pass

    @staticmethod
    def _cover_query(artist, title):
        return " ".join(p for p in (artist, title) if p).strip()

    # ------------------------------------------------------------------
    #  Данные
    # ------------------------------------------------------------------
    def reload_stats(self):
        """Перечитывает профиль и статистику из БД."""
        lang = _lang()
        self._apply_icon_theme()
        self._cover_labels = {}

        profile = db.get_profile()
        nickname = (profile["nickname"] if profile else "") or "Music Lover"
        description = (profile["description"] if profile else "") or ""
        self.nickname_label.setText(nickname)
        if description:
            self.description_label.setText(_description_html(description))
        else:
            self.description_label.setText(
                tr("Double-click to add a description", lang)
            )
        self._apply_banner(profile["banner_path"] if profile else None)
        self._apply_avatar(profile["avatar_path"] if profile else None)

        total_sec = db.get_total_play_time()
        self.total_time_label.setText(self._format_total(total_sec))

        self._fill_achievements()
        self._fill_top_tracks(db.get_top_tracks(5), lang)
        self._fill_favorite(
            profile["favorite_track_id"] if profile else None, lang
        )
        self._fill_public_playlists(lang)

    def _apply_icon_theme(self):
        """Перекрашивает иконки под текущую тему."""
        color = _icon_color()
        for icon_label, icon_name in self._icon_labels:
            icon_label.setPixmap(colored_pixmap(icon_name, 20, color))

    def _apply_banner(self, source):
        """Показывает баннер (путь/QPixmap/байты) или градиентную заглушку."""
        if isinstance(source, (str, Path)) and source:
            self._banner_path = str(source)
            self.banner_label.set_image(
                self._banner_path
                if Path(self._banner_path).is_file()
                else None
            )
        elif isinstance(source, (QPixmap, bytes, bytearray)):
            self._banner_path = None
            self.banner_label.set_image(source)
        else:
            self._banner_path = None
            self.banner_label.set_image(None)

    def _apply_avatar(self, source):
        """Показывает круглую аватарку (путь/QPixmap/байты) или заглушку."""
        if isinstance(source, (str, Path)) and source:
            self._avatar_path = str(source)
            source = self._avatar_path if Path(self._avatar_path).is_file() else None
        else:
            self._avatar_path = None
        self.avatar_label.setPixmap(
            _round_avatar_pixmap(source, self.AVATAR_SIZE)
        )

    def _fill_achievements(self):
        """Пересобирает блок достижений в шапке."""
        self._clear_layout(self.achievements_layout)

        values = {
            "tracks": db.get_tracks_count(),
            "playlists": db.get_playlists_count(),
            "time": db.get_total_play_time(),
            "age": db.get_app_age_days(),
        }
        lang = _lang()

        for key, icon_name, thresholds, caption in ACHIEVEMENTS:
            value = values.get(key, 0)
            level = _achievement_level(value, thresholds)
            color = (
                ACHIEVEMENT_COLORS[level - 1]
                if level > 0 else ACHIEVEMENT_LOCKED_COLOR
            )
            shown = _format_achievement_value(key, value)
            label = tr(caption, lang)
            if level >= len(thresholds):
                tier = tr(ACHIEVEMENT_TIERS[level - 1], lang)
                tooltip = f"{label}: {shown} \u2014 {tier}"
            else:
                target = _format_achievement_value(key, thresholds[level])
                tooltip = f"{label}: {shown} / {target}"

            box = QWidget()
            box.setToolTip(tooltip)
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)

            icon_label = QLabel()
            icon_label.setPixmap(colored_pixmap(icon_name, 28, color))
            icon_label.setAlignment(Qt.AlignCenter)

            value_label = QLabel(shown)
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet("color: #8a8a8a; font-size: 10px;")

            col.addWidget(icon_label)
            col.addWidget(value_label)
            self.achievements_layout.addWidget(box)

    @staticmethod
    def _format_total(seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}:{minutes:02d}"

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_top_tracks(self, rows, lang):
        self._clear_layout(self.top_tracks_layout)
        if not rows:
            empty = QLabel(tr("No plays yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.top_tracks_layout.addWidget(empty)
            return
        for row in rows:
            cover_path = metadata.extract_cover(row["file_path"], row["id"])
            title = row["title"] or Path(row["file_path"]).stem
            self.top_tracks_layout.addWidget(
                self._track_row(
                    row["id"], cover_path, title,
                    query=self._cover_query(row["artist"], title),
                )
            )

    def _fill_favorite(self, track_id, lang):
        self._clear_layout(self.favorite_layout)
        track = db.get_track_by_id(track_id) if track_id else None
        if track is None:
            label = QLabel(tr("No favorite track yet", lang))
            label.setStyleSheet("color: #8a8a8a;")
            self.favorite_layout.addWidget(label)
            return
        cover_path = metadata.extract_cover(track["file_path"], track["id"])
        title = track["title"] or Path(track["file_path"]).stem
        self.favorite_layout.addWidget(
            self._track_row(
                track["id"], cover_path, title, track["artist"],
                query=self._cover_query(track["artist"], title),
            )
        )

    def _playlist_card(self, playlist):
        """Компактная кликабельная карточка плейлиста: обложка + название."""
        cover_path = playlist["cover_path"]
        if not cover_path:
            first = db.get_first_track_in_playlist(playlist["id"])
            if first:
                cover_path = metadata.extract_cover(
                    first["file_path"], first["id"]
                )

        card = _ClickableCard(playlist["id"])
        card.setObjectName("playlistCard")
        card.setStyleSheet(
            "#playlistCard { background: transparent; border-radius: 10px; }"
            "#playlistCard:hover { background: rgba(255, 255, 255, 0.08); }"
        )
        card.setFixedWidth(96)
        card.setToolTip(playlist["name"])
        col = QVBoxLayout(card)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(4)

        cover = QLabel()
        cover.setFixedSize(64, 64)
        cover.setAlignment(Qt.AlignCenter)
        cover.setPixmap(_cover_pixmap(cover_path, 64))
        col.addWidget(cover, 0, Qt.AlignHCenter)

        name = QLabel(playlist["name"])
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        col.addWidget(name)

        return card

    def _fill_public_playlists(self, lang):
        self._clear_layout(self.public_playlists_grid)
        playlists = db.get_all_playlists()
        if not playlists:
            empty = QLabel(tr("No playlists yet", lang))
            empty.setStyleSheet("color: #8a8a8a;")
            self.public_playlists_grid.addWidget(empty, 0, 0)
            return
        for index, playlist in enumerate(playlists):
            card = self._playlist_card(playlist)
            card.clicked.connect(self.playlist_clicked.emit)
            self.public_playlists_grid.addWidget(card, index // 2, index % 2)

    def shutdown(self):
        """Останавливает все фоновые QThread профиля при закрытии."""
        workers = list(self._cover_loaders.values())
        self._cover_loaders.clear()
        self._cover_labels.clear()

        for worker in workers:
            try:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    worker.requestInterruption()
            except RuntimeError:
                # C++-объект уже удалён своим finished-обработчиком.
                continue
            retire_thread(worker, 2000)

    # ------------------------------------------------------------------
    #  Действия
    # ------------------------------------------------------------------
    def change_avatar(self):
        """Публичный вход для контекстного меню аватарки в главном окне."""
        self._change_avatar()

    def _change_banner(self):
        path, _ = get_open_file_name(
            self, tr("Select Banner", _lang()), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            new_path = _copy_profile_image(path, "banner")
        except OSError:
            return
        db.update_profile(banner_path=str(new_path))
        self._apply_banner(str(new_path))

    def _change_avatar(self):
        path, _ = get_open_file_name(
            self, tr("Select Avatar", _lang()), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            new_path = _copy_profile_image(path, "avatar")
        except OSError:
            return
        db.update_profile(avatar_path=str(new_path))
        self._apply_avatar(str(new_path))
        self.avatar_changed.emit(str(new_path))

    def _edit_nickname(self):
        """Смена никнейма по двойному клику."""
        profile = db.get_profile()
        current = (profile["nickname"] if profile else "") or ""
        lang = _lang()
        name, ok = CustomInputDialog.get_text(
            self, tr("Edit Nickname", lang), tr("Nickname", lang), text=current
        )
        if not ok:
            return
        nickname = name.strip() or "Music Lover"
        db.update_profile(nickname=nickname)
        self.reload_stats()

    def _edit_about(self):
        """Редактирование описания в BBCode по двойному клику."""
        profile = db.get_profile()
        dialog = BBCodeEditorDialog(
            profile["description"] if profile else "", self
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        description = dialog.value()
        db.update_profile(description=description)
        self.reload_stats()
