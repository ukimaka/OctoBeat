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

import random
from pathlib import Path

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QMainWindow,
    QMenu,
    QProgressDialog,
    QSizeGrip,
    QTabBar,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import db
import session
import workers
from account_menu import AccountMenu
from appearance import AppearanceManager
from controller import PlayerController
from dialogs import CustomConfirmDialog
from friends_ui import FriendsPage
from hotkeys import AppEventFilter
from import_flow import ImportFlow
from library_tab import LibraryTab
from lyrics_manager import LyricsManager
from lyrics_panel import LyricsPanel
from player_bar import PlayerBar
from playlists_ui import PlaylistsPage
from profile_ui import ProfilePage
from settings_page import SettingsPage
from title_bar import CustomTitleBar
from track_actions import TrackActions
from track_menu import TrackContextMenu
from translations import tr
from ui_common import IconProvider, apply_menu_depth
from updater import UpdateChecker, UpdateDownloader, apply_update


class CustomTabBar(QTabBar):
    def sizeHint(self):
        size = super().sizeHint()
        # Принудительно делаем панель вкладок высотой 38 пикселей
        size.setHeight(max(size.height(), 38))
        return size

# MPRIS (Linux): медиа-клавиши и управление из системного трея/панели.
# Импорт может быть недоступен вне Linux / без D-Bus — приложение не ломаем.
try:
    from mpris_integration import start_mpris, stop_mpris
except Exception as exc:
    print(f"[mpris] integration unavailable: {exc}")
    start_mpris = None
    stop_mpris = None


MUSIC_FOLDER = Path.home() / "Music"


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OctoBeat")

        # Делаем окно безрамочным
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.title_bar = CustomTitleBar(self)
        self.title_bar.setAttribute(Qt.WA_StyledBackground, True)

        self.resize(1000, 650)
        self.setMinimumSize(800, 520)

        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self.event_filter = AppEventFilter(self)
        self.controller = PlayerController(settings=self.settings, parent=self)
        self.media_player = self.controller.media_player

        self._listening_pending_seconds = 0
        self._listening_timer = QTimer(self)
        self._listening_timer.setInterval(1000)
        self._listening_timer.timeout.connect(self._on_listening_tick)

        self.is_dark_theme = True
        self.icons = IconProvider(is_dark=self.is_dark_theme)

        self._update_checker = None
        self._update_downloader = None
        self._update_progress = None

        self.lyrics_manager = LyricsManager(
            settings=self.settings,
            media_player=self.media_player,
            parent_window=self,
            parent=self,
        )

        lang = self.settings.value("language", "en")

        self.tabs = QTabWidget()
        self.tabs.setAttribute(Qt.WA_StyledBackground, True)
        self.tabs.setTabBar(CustomTabBar(self.tabs))

        tab_bar = self.tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setMinimumHeight(38)

        self.library_tab = LibraryTab(
            self.settings, self.icons, event_filter=self.event_filter
        )
        self.controller.library_ids_provider = self.library_tab.library_ids
        self.tabs.addTab(self.library_tab, tr("Library", lang))
        self.playlists_page = PlaylistsPage(self)
        self.tabs.addTab(self.playlists_page, tr("Playlists", lang))
        self.friends_page = FriendsPage(self)
        self.tabs.addTab(self.friends_page, tr("Friends", lang))
        self.profile_page = ProfilePage(self)
        self.tabs.addTab(self.profile_page, tr("Profile", lang))
        self.settings_page = SettingsPage(self)
        self.tabs.addTab(self.settings_page, tr("Settings", lang))
        self.track_actions = TrackActions(
            db=db,
            controller=self.controller,
            playlists_page=self.playlists_page,
            parent=self,
            settings=self.settings,
        )

        self.tabs.removeTab(self.tabs.indexOf(self.friends_page))
        self.tabs.removeTab(self.tabs.indexOf(self.profile_page))

        self.account_menu = AccountMenu(
            self,
            self.settings,
            self.tabs,
            self.friends_page,
            self.profile_page,
            self.settings_page,
            self.icons,
        )
        self.avatar_button = self.account_menu.avatar_button
        self.tabs.setCornerWidget(self.avatar_button, Qt.TopRightCorner)
        self.import_flow = ImportFlow(
            self,
            self.settings,
            self.settings.value("download_dir", str(MUSIC_FOLDER)),
            self._sync_library_on_startup,
        )
        self.player_bar = PlayerBar(
            self.settings, self.icons, event_filter=self.event_filter
        )
        self.player_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.lyrics_panel = LyricsPanel(self.settings, self.icons)
        self.appearance = AppearanceManager(
            self.settings,
            self.icons,
            self.library_tab,
            self.playlists_page,
            self.player_bar,
            self.lyrics_panel,
            self.settings_page,
            self.profile_page,
            self.friends_page,
            self.media_player,
            self._on_player_state_changed,
            parent_window=self,
        )
        self.appearance.avatar_update_requested.connect(
            self.account_menu.update_avatar
        )

        # --- Компоновка ---
        central = QWidget()
        root = QVBoxLayout(central)
        # Убираем стандартные отступы для безрамочного окна
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self.title_bar)
        root.addWidget(self.tabs, 1)
        root.addWidget(self.lyrics_panel)
        root.addWidget(self.player_bar)

        self.setCentralWidget(central)

        # Ручка изменения размера (в правом нижнем углу)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.raise_()

        self._connect_signals()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self.event_filter)

        self._apply_ui_settings()
        self._sync_library_on_startup()
        self.library_tab.reload()
        self._reload_playlists()
        self._apply_settings()
        self.account_menu.check_stored_token()
        self.account_menu.start_timers()

        if start_mpris is not None:
            start_mpris(self.controller)

        self._maybe_check_updates()

    # ------------------------------------------------------------------
    #  Обновления
    # ------------------------------------------------------------------
    def _maybe_check_updates(self):
        """Запускает проверку обновлений, если она включена в настройках."""
        if not bool(self.settings.value("auto_update", True, type=bool)):
            return
        self._check_for_updates()

    def _check_for_updates(self):
        if self._update_checker is not None:
            return
        self._update_checker = UpdateChecker(self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.no_update.connect(self._on_no_update)
        self._update_checker.finished.connect(self._on_update_check_finished)
        self._update_checker.start()

    def _on_no_update(self):
        pass

    def _on_update_check_finished(self):
        if self._update_checker is not None:
            self._update_checker.deleteLater()
            self._update_checker = None

    def _on_update_available(self, version, url):
        lang = self.settings.value("language", "en")
        if not CustomConfirmDialog.question(
            self,
            tr("Update available", lang),
            tr(
                "A new version {version} is available. Download it now?",
                lang,
            ).format(version=version),
        ):
            return
        self._start_update_download(url)

    def _start_update_download(self, url):
        lang = self.settings.value("language", "en")
        self._update_progress = QProgressDialog(
            tr("Downloading update...", lang),
            tr("Cancel", lang),
            0, 100, self,
        )
        self._update_progress.setWindowTitle(tr("Update", lang))
        self._update_progress.setWindowModality(Qt.WindowModal)
        self._update_progress.setMinimumDuration(0)
        self._update_progress.setAutoClose(False)
        self._update_progress.setAutoReset(False)
        self._update_progress.setValue(0)

        self._update_downloader = UpdateDownloader(url, self)
        self._update_downloader.progress.connect(
            self._update_progress.setValue
        )
        self._update_downloader.finished.connect(self._on_update_downloaded)
        self._update_downloader.error.connect(self._on_update_error)
        self._update_progress.canceled.connect(self._on_update_cancelled)
        self._update_downloader.start()

    def _on_update_cancelled(self):
        if self._update_downloader is not None:
            self._update_downloader.cancel()

    def _close_update_progress(self):
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress.deleteLater()
            self._update_progress = None

    def _on_update_downloaded(self, filepath):
        self._close_update_progress()
        self._update_downloader = None
        if not apply_update(filepath):
            lang = self.settings.value("language", "en")
            CustomConfirmDialog.information(
                self,
                tr("Update error", lang),
                tr("Could not install the downloaded update.", lang),
            )

    def _on_update_error(self, message):
        self._close_update_progress()
        self._update_downloader = None
        if message:
            lang = self.settings.value("language", "en")
            CustomConfirmDialog.information(
                self, tr("Update error", lang), message
            )

    def resizeEvent(self, event):
        """Позиционирует QSizeGrip в правом нижнем углу при ресайзе."""
        super().resizeEvent(event)
        if hasattr(self, 'size_grip'):
            self.size_grip.move(
                self.width() - self.size_grip.width() - 2,
                self.height() - self.size_grip.height() - 2
            )

    def _token(self) -> str | None:
        return self.account_menu.token()

    def _show_user_page(self, page) -> None:
        self.account_menu.show_user_page(page)

    def _logout(self, switch_to_library: bool = True) -> None:
        self.account_menu.logout(switch_to_library)

    def _load_icon(self, filename, color=None):
        return self.icons.icon(filename, color)

    def _connect_signals(self):
        self.event_filter.search_requested.connect(self.library_tab.focus_search)
        self.event_filter.play_pause_requested.connect(self.controller.toggle_play)
        self.event_filter.next_requested.connect(self.controller.next)
        self.event_filter.prev_requested.connect(self.controller.prev)
        self.event_filter.volume_delta_requested.connect(self.player_bar.nudge_volume)
        self.event_filter.select_all_requested.connect(self._on_select_all_shortcut)

        self.track_actions.changed.connect(self.library_tab.reload)
        self.track_actions.changed.connect(self.playlists_page.refresh_tracks)
        self.track_actions.favorite_changed.connect(self.profile_page.reload_stats)

        self.library_tab.play_requested.connect(self._on_library_play_requested)
        self.library_tab.random_play_requested.connect(self._on_random_play)
        self.library_tab.import_requested.connect(self.import_flow.import_files)
        self.library_tab.rescan_requested.connect(self.import_flow.rescan)
        self.library_tab.youtube_requested.connect(self.import_flow.youtube_dialog)
        self.library_tab.csv_import_requested.connect(self.import_flow.import_csv)
        self.import_flow.library_changed.connect(self.library_tab.reload)
        self.library_tab.library_changed.connect(self._on_library_changed)
        self.library_tab.context_menu_requested.connect(
            lambda pos: self._on_track_context_menu(
                pos, self.library_tab.tracks_list, "library"
            )
        )
        self.library_tab.delete_track_requested.connect(self.track_actions.remove_track)
        self.playlists_page.delete_track_requested.connect(self._on_playlist_track_delete_requested)

        self.settings_page.ui_settings_changed.connect(self._apply_ui_settings)
        self.settings_page.crossfade_changed.connect(self.media_player.set_crossfade_enabled)
        self.settings_page.metadata_badges_changed.connect(self._on_metadata_badges_changed)
        self.settings_page.csv_import_requested.connect(self.library_tab.csv_import_requested)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.playlists_page.play_playlist.connect(self._on_play_playlist)
        self.playlists_page.play_track.connect(self._on_playlist_track_play_requested)
        self.playlists_page.playlist_deleted.connect(self._on_playlist_deleted)
        self.playlists_page.settings_requested.connect(self._on_settings_clicked)
        # CHANGED: Back в плейлистах умеет возвращать в профиль.
        try:
            self.playlists_page.back_button.clicked.disconnect(
                self.playlists_page._go_back
            )
        except TypeError:
            pass
        self.playlists_page.back_button.clicked.connect(self._on_playlist_back)
        self.profile_page.playlist_clicked.connect(self._on_profile_playlist_clicked)
        self.friends_page.profile_requested.connect(self._on_friend_profile_requested)
        self.profile_page.back_requested.connect(self._on_profile_back)
        self.profile_page.playlist_download_requested.connect(self.import_flow.download_remote_playlist)
        self.playlists_page.tracks_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlists_page.tracks_list.customContextMenuRequested.connect(
            lambda pos: self._on_track_context_menu(
                pos, self.playlists_page.tracks_list, "playlist"
            )
        )

        self.player_bar.play_pause_clicked.connect(self.controller.toggle_play)
        self.player_bar.prev_clicked.connect(self.controller.prev)
        self.player_bar.next_clicked.connect(self.controller.next)
        self.player_bar.repeat_clicked.connect(self.controller.toggle_repeat)
        self.player_bar.shuffle_clicked.connect(self.controller.toggle_shuffle)
        self.player_bar.lyrics_toggled.connect(self._on_toggle_lyrics)
        self.player_bar.karaoke_requested.connect(self._on_lyrics_karaoke)

        self.lyrics_panel.offset_delta_requested.connect(self._on_lyrics_offset)
        self.lyrics_panel.fullscreen_requested.connect(self._on_lyrics_fullscreen)
        self.lyrics_panel.karaoke_requested.connect(self._on_lyrics_karaoke)
        self.lyrics_manager.content_changed.connect(self.lyrics_panel.set_content)
        self.lyrics_manager.highlight_changed.connect(self.lyrics_panel.set_highlight)

        self.player_bar.seek_requested.connect(self.media_player.set_position)
        self.player_bar.volume_changed.connect(self.media_player.set_volume)

        self.controller.track_changed.connect(self._on_track_changed)
        self.controller.context_changed.connect(self._on_context_changed)
        self.controller.next_track_changed.connect(self._on_next_track_changed)
        self.controller.playback_state_changed.connect(self._on_player_state_changed)
        self.controller.repeat_mode_changed.connect(self.player_bar.set_repeat_mode)
        self.controller.shuffle_changed.connect(self.player_bar.set_shuffle)

        self.media_player.stateChanged.connect(self._on_player_state_changed)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.positionChanged.connect(self.lyrics_manager.on_position)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.aboutToFinish.connect(self._on_about_to_finish)
        self.media_player.trackFinished.connect(self._on_track_finished)

    @staticmethod
    def _user_data(item):
        if item is None:
            return None
        if isinstance(item, QTreeWidgetItem):
            return item.data(0, Qt.UserRole)
        return item.data(Qt.UserRole)

    @staticmethod
    def _item_id(item):
        data = MainWindow._user_data(item)
        if isinstance(data, dict):
            return data.get("id")
        return data

    @staticmethod
    def _path_of(item):
        data = MainWindow._user_data(item)
        if isinstance(data, dict):
            return data.get("path")
        if isinstance(item, QTreeWidgetItem):
            return item.data(0, Qt.UserRole + 1)
        return item.data(Qt.UserRole + 1)

    def _apply_ui_settings(self):
        self.appearance.apply_ui_settings()
        self.is_dark_theme = self.appearance.is_dark_theme
        # Делегаты кэшируют тему: без явного флага текст остаётся в цветах
        # предыдущей темы (например, чёрным на Dracula).
        for page in (self.library_tab, self.playlists_page):
            delegate = getattr(page, "track_delegate", None)
            if delegate is not None:
                delegate.set_dark_theme(self.is_dark_theme)

    def _on_metadata_badges_changed(self, enabled: bool):
        if hasattr(self, "library_tab") and self.library_tab.track_delegate:
            self.library_tab.track_delegate.set_show_metadata_badges(enabled)
            self.library_tab.tracks_list.viewport().update()
        if hasattr(self, "playlists_page") and self.playlists_page.track_delegate:
            self.playlists_page.track_delegate.set_show_metadata_badges(enabled)
            self.playlists_page.tracks_list.viewport().update()

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is getattr(self, "profile_page", None):
            self._flush_listening_time()
            self.profile_page.reload_stats()
        elif widget is getattr(self, "friends_page", None):
            self.friends_page.refresh()
        elif widget is getattr(self, "settings_page", None):
            self.settings_page.refresh_auth_state()

    def _apply_icons(self):
        self.appearance.apply_icons()

    def _apply_settings(self):
        volume = session.restore(self.controller, self.settings)
        self.player_bar.set_volume(volume)
        self.player_bar.set_repeat_mode(self.controller.repeat_mode)
        self.player_bar.set_shuffle(self.controller.shuffle)

    def closeEvent(self, event):
        c = self.controller
        self._flush_listening_time()
        session.save(c, self.settings, self.player_bar.volume())

        self.library_tab.save_state()
        if hasattr(self, "profile_page"):
            self.profile_page.sync_stats_to_server()
            self.profile_page.shutdown()
        if hasattr(self, "friends_page"):
            self.friends_page.shutdown()
        self.account_menu.shutdown()
        self.lyrics_manager.shutdown()
        if stop_mpris is not None:
            stop_mpris(c)
        super().closeEvent(event)

    def _on_track_changed(self, track_id, title):
        self.player_bar.set_current_track(track_id, title)
        self.playlists_page.set_current_track(track_id)
        self.library_tab.set_current_track(track_id)

        if self.playlists_page.isVisible():
            page_delegate = self.playlists_page.tracks_list.itemDelegate()
            if hasattr(page_delegate, "set_current_playing"):
                page_delegate.set_current_playing(track_id)
            self.playlists_page.tracks_list.clearSelection()
            self.playlists_page.tracks_list.viewport().update()

        self.lyrics_manager.set_track(track_id)

    def _on_lyrics_offset(self, delta_ms):
        self.lyrics_manager.adjust_offset(delta_ms)

    def _on_toggle_lyrics(self, checked):
        self.lyrics_panel.setVisible(checked)
        if not checked:
            return
        self.lyrics_manager.refresh_highlight()
        self.lyrics_panel.scroll_to_current()

    def _on_lyrics_fullscreen(self):
        self.lyrics_manager.show_fullscreen()

    def _on_lyrics_karaoke(self):
        self.player_bar.activate_lyrics()
        self.lyrics_manager.show_karaoke()

    def _on_next_track_changed(self, track_id, title=""):
        self.library_tab.set_next_track(track_id, title)

    def _on_context_changed(self, name):
        self.player_bar.set_context(name)

    def _on_select_all_from_context(self, source_list, scope):
        if source_list is None:
            return
        view = self.library_tab.tracks_list if scope == "library" else self.playlists_page.tracks_list
        view.selectAll()

    def _on_select_all_shortcut(self):
        focus = QApplication.focusWidget()
        view = None
        if focus is not None:
            candidates = (
                getattr(self.library_tab, "tracks_list", None),
                getattr(self.playlists_page, "tracks_list", None),
            )
            for candidate in candidates:
                if candidate is not None and focus in (candidate, candidate.viewport()):
                    view = candidate
                    break
        if view is None:
            return
        scope = "library" if view is self.library_tab.tracks_list else "playlist"
        self._on_select_all_from_context(view, scope)

    def _on_remove_selected_from_context(self, scope, ids):
        for track_id in ids or []:
            self.track_actions.remove(track_id, scope)

    def _on_playlist_track_delete_requested(self, track_id):
        self.track_actions.remove(track_id, "playlist")

    def _sync_library_on_startup(self):
        download_dir = Path(self.settings.value("download_dir", str(MUSIC_FOLDER)))
        if not download_dir.exists():
            return
        files = workers.find_audio_files(download_dir)
        added = 0
        for path in files:
            if db.add_track(path) is not None:
                added += 1
        if added:
            print(f"[startup] new tracks added: {added}")

    def _on_library_play_requested(self, item):
        data = self._user_data(item) or {}
        if data.get("is_folder"):
            return
        path = self._path_of(item)
        lang = self.settings.value("language", "en")
        if path and not Path(path).exists():
            CustomConfirmDialog.information(
                self, tr("File missing", lang),
                tr("File not found:\n{path}", lang).format(path=path),
            )
            return
        clicked_id = self._item_id(item)
        ids = self.library_tab.library_ids()
        self.controller.play_from_list(ids, clicked_id, "library", tr("Library", lang), None)

    def _on_random_play(self):
        ids = [row["id"] for row in db.get_all_tracks()]
        if not ids:
            return
        chosen_id = random.choice(ids)
        lang = self.settings.value("language", "en")
        self.controller.play_from_list(ids, chosen_id, "library", tr("Library", lang), None)

    def _on_library_changed(self):
        self.library_tab.update_track_count()

    def _show_folder_context_menu(self, global_pos, folder_id):
        menu = QMenu(self)
        apply_menu_depth(menu)
        lang = self.settings.value("language", "en")

        play_action = QAction(tr("Play this folder only", lang), menu)
        play_action.setIcon(self._load_icon("play.svg"))
        play_action.triggered.connect(lambda checked=False, fid=folder_id: self._on_play_folder(fid))
        menu.addAction(play_action)

        add_menu = QMenu(tr("Add folder to playlist", lang), menu)
        apply_menu_depth(add_menu)
        add_menu.setIcon(self._load_icon("add-to-playlist.svg"))
        playlists = db.get_all_playlists()
        if not playlists:
            empty = QAction(tr("(no playlists)", lang), add_menu)
            empty.setEnabled(False)
            add_menu.addAction(empty)
        else:
            for pl in playlists:
                action = QAction(pl["name"], add_menu)
                action.triggered.connect(lambda checked=False, pid=pl["id"], fid=folder_id: self._add_folder_to_playlist(pid, fid))
                add_menu.addAction(action)
        menu.addMenu(add_menu)

        menu.addSeparator()

        delete_action = QAction(tr("Delete folder", lang), menu)
        delete_action.setIcon(self._load_icon("trash.svg"))
        delete_action.triggered.connect(lambda checked=False, fid=folder_id: self._on_delete_folder(fid))
        menu.addAction(delete_action)
        menu.exec_(global_pos)

    def _folder_track_ids(self, folder_id):
        return [row["id"] for row in db.get_tracks_in_folder(folder_id)]

    def _on_play_folder(self, folder_id):
        ids = self._folder_track_ids(folder_id)
        if not ids:
            return
        folder = next((f for f in db.get_all_folders() if f["id"] == folder_id), None)
        name = folder["name"] if folder is not None else ""
        self.controller.play_from_list(ids, ids[0], "folder", name, None)

    def _add_folder_to_playlist(self, playlist_id, folder_id):
        lang = self.settings.value("language", "en")
        existing = {row["id"] for row in db.get_tracks_in_playlist(playlist_id)}
        added = 0
        for track_id in self._folder_track_ids(folder_id):
            if track_id in existing:
                continue
            db.add_track_to_playlist(playlist_id, track_id)
            added += 1
        self.playlists_page.refresh_tracks()
        if added == 0:
            CustomConfirmDialog.information(
                self, tr("Nothing added", lang),
                tr("All tracks from this folder are already in the playlist.", lang),
            )

    def _on_delete_folder(self, folder_id):
        db.delete_folder(folder_id)
        self.library_tab.reload()

    def _on_track_context_menu(self, pos, source_list, scope):
        item = source_list.itemAt(pos)
        if item is None:
            return
        data = self._user_data(item) or {}
        if data.get("is_folder"):
            self._show_folder_context_menu(source_list.mapToGlobal(pos), self._item_id(item))
            return
        track_id = self._item_id(item)
        if track_id is None:
            return

        menu = TrackContextMenu(
            self, self.settings, self.icons, track_id,
            db.get_all_playlists(), scope, source_list,
        )
        menu.add_to_playlist_requested.connect(self.track_actions.add_to_playlist)
        menu.add_to_queue_requested.connect(self.track_actions.add_to_queue)
        menu.favorite_requested.connect(self.track_actions.set_favorite)
        menu.edit_metadata_requested.connect(self.track_actions.edit_metadata)
        menu.change_cover_requested.connect(self.track_actions.change_cover)
        menu.trim_audio_requested.connect(self.track_actions.trim_audio)
        menu.remove_requested.connect(self.track_actions.remove)
        menu.remove_selected_requested.connect(
            lambda scope, ids: self._on_remove_selected_from_context(scope, ids)
        )
        menu.select_all_requested.connect(
            lambda scope: self._on_select_all_from_context(source_list, scope)
        )
        menu.exec_at(pos)

    def _on_settings_clicked(self):
        self.tabs.setCurrentWidget(self.settings_page)

    def _on_profile_playlist_clicked(self, playlist_id):
        self.tabs.setCurrentWidget(self.playlists_page)
        self.playlists_page.open_playlist(playlist_id)
        # CHANGED: запоминаем, что вернуться нужно в профиль.
        self._return_to_profile = True

    def _on_playlist_back(self):
        # CHANGED: Возврат в профиль, если пришли оттуда
        if getattr(self, "_return_to_profile", False):
            self._return_to_profile = False
            self.playlists_page._go_back()
            self.tabs.setCurrentWidget(self.profile_page)
        else:
            self.playlists_page._go_back()

    def _on_friend_profile_requested(self, user_id: int) -> None:
        self._show_user_page(self.profile_page)
        self.profile_page.load_friend_profile(user_id)

    def _on_profile_back(self) -> None:
        self.profile_page.show_own_profile()

    def _reload_playlists(self):
        self.playlists_page.reload()

    def _on_play_playlist(self, playlist_id):
        pl = db.get_playlist_by_id(playlist_id)
        if pl is None:
            return
        rows = db.get_tracks_in_playlist(playlist_id)
        if not rows:
            lang = self.settings.value("language", "en")
            CustomConfirmDialog.information(
                self, tr("Empty playlist", lang),
                tr("Playlist '{name}' is empty — nothing to play", lang).format(name=pl['name']),
            )
            return
        ids = [row["id"] for row in rows]
        self.controller.play_from_list(ids, ids[0], "playlist", pl["name"], playlist_id)

    def _on_playlist_track_play_requested(self, playlist_id, track_id, ids):
        if not ids:
            return
        pl = db.get_playlist_by_id(playlist_id)
        pl_name = pl["name"] if pl else "Playlist"
        self.controller.play_from_list(ids, track_id, "playlist", pl_name, playlist_id)

    def _on_playlist_deleted(self, playlist_id):
        c = self.controller
        if c.play_context_type == "playlist" and c.play_context_playlist_id == playlist_id:
            ids = self.library_tab.library_ids()
            if ids and c.current_track_id in ids:
                c.set_context(ids, ids.index(c.current_track_id), "library",
                              tr("Library", self.settings.value("language", "en")), None)
            else:
                c.clear_context()

    def _on_player_state_changed(self, state):
        playing = state if isinstance(state, bool) else (state == QMediaPlayer.PlayingState)
        self.player_bar.set_playing(playing)

        if playing:
            if not self._listening_timer.isActive():
                self._listening_timer.start()
        else:
            self._flush_listening_time()
            self._listening_timer.stop()

    def _on_listening_tick(self):
        if not self.media_player.is_playing():
            self._listening_timer.stop()
            self._flush_listening_time()
            return

        self._listening_pending_seconds += 1
        if self._listening_pending_seconds >= 5:
            self._flush_listening_time()

    def _flush_listening_time(self):
        seconds = self._listening_pending_seconds
        if seconds <= 0:
            return
        self._listening_pending_seconds = 0
        db.add_listening_time(seconds)

    def _on_position_changed(self, pos):
        self.player_bar.set_position(pos, self.media_player.duration())

    def _on_duration_changed(self, duration):
        self.player_bar.set_duration(duration, self.media_player.position())

    def _on_about_to_finish(self):
        self.controller.prepare_crossfade()

    def _on_track_finished(self):
        self.controller.on_track_finished()
