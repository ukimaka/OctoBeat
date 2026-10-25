import random
from pathlib import Path

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QApplication,
    QVBoxLayout,
    QMessageBox, QMenu, QAction,
    QTreeWidgetItem,
)

import db
import session
import workers
from account_menu import AccountMenu
from appearance import AppearanceManager
from dialogs import CustomConfirmDialog
from controller import PlayerController
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
from track_actions import TrackActions
from track_menu import TrackContextMenu
from translations import tr
from ui_common import IconProvider

# MPRIS (Linux): медиа-клавиши и управление из системного трея/панели.
# Импорт может быть недоступен вне Linux / без D-Bus — приложение не ломаем.
try:
    from mpris_integration import start_mpris, stop_mpris
except Exception as exc:  # noqa: BLE001
    print(f"[mpris] integration unavailable: {exc}")
    start_mpris = None
    stop_mpris = None


MUSIC_FOLDER = Path.home() / "Music"


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Player")
        self.resize(1000, 650)

        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self.event_filter = AppEventFilter(self)
        self.controller = PlayerController(settings=self.settings, parent=self)
        # алиас для UI-сигналов плеера (позиция/длительность/состояние)
        self.media_player = self.controller.media_player

        # --- UI-состояние ---
        self.is_dark_theme = True           # тема (влияет на выбор папки иконок)
        self.icons = IconProvider(is_dark=self.is_dark_theme)

        # --- Тексты песен (syncedlyrics) ---
        self.lyrics_manager = LyricsManager(
            settings=self.settings,
            media_player=self.media_player,
            parent_window=self,
            parent=self,
        )

        # --- UI ---
        lang = self.settings.value("language", "en")
        self.tabs = QTabWidget()
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

        # Friends/Profile доступны только через меню глобальной аватарки:
        # убираем их из tab bar, сами виджеты оставляем живыми.
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
            MUSIC_FOLDER,
            self._sync_library_on_startup,
        )
        self.player_bar = PlayerBar(
            self.settings, self.icons, event_filter=self.event_filter
        )
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

        central = QWidget()
        root = QVBoxLayout()
        root.addWidget(self.tabs, 1)
        root.addWidget(self.lyrics_panel)
        root.addWidget(self.player_bar)
        central.setLayout(root)
        self.setCentralWidget(central)

        self._connect_signals()

        # Хоткеи перехватываем на уровне приложения: QTreeWidget/QListView
        # сами обрабатывают Space и Ctrl+←/→ и не пробрасывают их в
        # keyPressEvent окна (проверено на Qt5).
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

        # MPRIS: публикуем плеер на D-Bus (медиа-клавиши, трей, панель).
        if start_mpris is not None:
            start_mpris(self.controller)

    # ------------------------------------------------------------------
    #  Аккаунт: тонкие обёртки для обратной совместимости
    # ------------------------------------------------------------------
    def _token(self) -> str | None:
        return self.account_menu.token()

    def _show_user_page(self, page) -> None:
        self.account_menu.show_user_page(page)

    def _logout(self, switch_to_library: bool = True) -> None:
        self.account_menu.logout(switch_to_library)

    # ------------------------------------------------------------------
    #  Layouts
    # ------------------------------------------------------------------
    def _load_icon(self, filename, color=None):
        """Делегирует загрузку иконки общему :class:`IconProvider`."""
        return self.icons.icon(filename, color)


    # ------------------------------------------------------------------
    #  Signals
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self.event_filter.search_requested.connect(
            self.library_tab.focus_search
        )
        self.event_filter.play_pause_requested.connect(
            self.controller.toggle_play
        )
        self.event_filter.next_requested.connect(self.controller.next)
        self.event_filter.prev_requested.connect(self.controller.prev)
        self.event_filter.volume_delta_requested.connect(
            self.player_bar.nudge_volume
        )

        self.track_actions.changed.connect(self.library_tab.reload)
        self.track_actions.changed.connect(
            self.playlists_page.refresh_tracks
        )
        self.track_actions.favorite_changed.connect(
            self.profile_page.reload_stats
        )

        self.library_tab.play_requested.connect(
            self._on_library_play_requested
        )
        self.library_tab.random_play_requested.connect(
            self._on_random_play
        )
        self.library_tab.import_requested.connect(
            self.import_flow.import_files
        )
        self.library_tab.rescan_requested.connect(
            self.import_flow.rescan
        )
        self.library_tab.youtube_requested.connect(
            self.import_flow.youtube_dialog
        )
        self.library_tab.csv_import_requested.connect(
            self.import_flow.import_csv
        )
        self.import_flow.library_changed.connect(self.library_tab.reload)
        self.library_tab.library_changed.connect(
            self._on_library_changed
        )
        self.library_tab.context_menu_requested.connect(
            lambda pos: self._on_track_context_menu(
                pos, self.library_tab.tracks_list, "library"
            )
        )

        self.settings_page.ui_settings_changed.connect(self._apply_ui_settings)
        self.settings_page.crossfade_changed.connect(
            self.media_player.set_crossfade_enabled
        )
        # CSV-импорт остаётся в настройках, но проходит через общий
        # библиотечный сигнал — единая точка входа для импорта в библиотеку.
        self.settings_page.csv_import_requested.connect(
            self.library_tab.csv_import_requested
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.playlists_page.play_playlist.connect(self._on_play_playlist)
        self.playlists_page.play_track.connect(self._on_playlist_track_play_requested)
        self.playlists_page.playlist_deleted.connect(self._on_playlist_deleted)
        self.playlists_page.settings_requested.connect(self._on_settings_clicked)
        self.profile_page.playlist_clicked.connect(
            self._on_profile_playlist_clicked
        )
        self.friends_page.profile_requested.connect(
            self._on_friend_profile_requested
        )
        self.profile_page.back_requested.connect(self._on_profile_back)
        self.profile_page.playlist_download_requested.connect(
            self.import_flow.download_remote_playlist
        )
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

        # Панель текста сообщает о намерениях пользователя, менеджер
        # занимается воркером и оверлеями.
        self.lyrics_panel.offset_delta_requested.connect(self._on_lyrics_offset)
        self.lyrics_panel.fullscreen_requested.connect(self._on_lyrics_fullscreen)
        self.lyrics_panel.karaoke_requested.connect(self._on_lyrics_karaoke)
        self.lyrics_manager.content_changed.connect(self.lyrics_panel.set_content)
        self.lyrics_manager.highlight_changed.connect(
            self.lyrics_panel.set_highlight
        )

        # Таймлайн и громкость: PlayerBar сам обновляет метку/иконку,
        # а MainWindow только применяет итоговые значения к плееру.
        self.player_bar.seek_requested.connect(self.media_player.set_position)
        self.player_bar.volume_changed.connect(self.media_player.set_volume)

        # Сигналы контроллера
        self.controller.track_changed.connect(self._on_track_changed)
        self.controller.context_changed.connect(self._on_context_changed)
        self.controller.next_track_changed.connect(self._on_next_track_changed)
        self.controller.playback_state_changed.connect(self._on_player_state_changed)
        self.controller.repeat_mode_changed.connect(self.player_bar.set_repeat_mode)
        self.controller.shuffle_changed.connect(self.player_bar.set_shuffle)

        # Сигналы плеера
        self.media_player.stateChanged.connect(self._on_player_state_changed)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.positionChanged.connect(self.lyrics_manager.on_position)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.aboutToFinish.connect(self._on_about_to_finish)
        self.media_player.trackFinished.connect(self._on_track_finished)

    # ------------------------------------------------------------------
    #  Утилиты
    # ------------------------------------------------------------------
    @staticmethod
    def _user_data(item):
        """Достаёт Qt.UserRole у QTreeWidgetItem и QListWidgetItem единообразно."""
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

    # ------------------------------------------------------------------
    #  Настройки: сохранение/восстановление
    # ------------------------------------------------------------------
    def _apply_ui_settings(self):
        """Применяет тему и масштаб интерфейса из настроек."""
        self.appearance.apply_ui_settings()
        self.is_dark_theme = self.appearance.is_dark_theme

    def _on_tab_changed(self, index):
        """Обновляет данные вкладки при её открытии."""
        widget = self.tabs.widget(index)
        if widget is getattr(self, "profile_page", None):
            self.profile_page.reload_stats()
        elif widget is getattr(self, "friends_page", None):
            self.friends_page.refresh()
        elif widget is getattr(self, "settings_page", None):
            self.settings_page.refresh_auth_state()

    def _apply_icons(self):
        """Пересоздаёт иконки с учётом текущей темы (после её смены)."""
        self.appearance.apply_icons()

    def _apply_settings(self):
        volume = session.restore(self.controller, self.settings)
        self.player_bar.set_volume(volume)
        self.player_bar.set_repeat_mode(self.controller.repeat_mode)
        self.player_bar.set_shuffle(self.controller.shuffle)

    def closeEvent(self, event):
        c = self.controller
        session.save(c, self.settings, self.player_bar.volume())

        # Запоминаем, какие папки были свёрнуты, чтобы восстановить при старте
        self.library_tab.save_state()
        if hasattr(self, "profile_page"):
            self.profile_page.sync_stats_to_server()
            self.profile_page.shutdown()
        if hasattr(self, "friends_page"):
            self.friends_page.shutdown()
        self.account_menu.shutdown()
        # Даём фоновой загрузке текста корректно завершиться и закрываем оверлеи.
        self.lyrics_manager.shutdown()
        # MPRIS-сервер живёт фоновым потоком и умирает вместе с процессом:
        # stop_mpris — намеренная заглушка (см. mpris_integration.py).
        if stop_mpris is not None:
            stop_mpris(c)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    #  Слоты контроллера
    # ------------------------------------------------------------------
    def _on_track_changed(self, track_id, title):
        self.player_bar.set_current_track(track_id, title)

        # Маркер играющего трека в обоих списках (не слетает при клике)
        self.playlists_page.set_current_track(track_id)
        self.library_tab.set_current_track(track_id)

        # То же самое для списка плейлиста (если он открыт)
        if self.playlists_page.isVisible():
            page_delegate = self.playlists_page.tracks_list.itemDelegate()
            if hasattr(page_delegate, "set_current_playing"):
                page_delegate.set_current_playing(track_id)
            self.playlists_page.tracks_list.clearSelection()
            self.playlists_page.tracks_list.viewport().update()

        # Текст песни: менеджер сам остановит воркер прошлого трека и
        # загрузит текст нового.
        self.lyrics_manager.set_track(track_id)

    # ------------------------------------------------------------------
    #  Текст песни (syncedlyrics)
    # ------------------------------------------------------------------
    def _on_lyrics_offset(self, delta_ms):
        """Сдвигает подсветку текста вперёд/назад на delta_ms."""
        self.lyrics_manager.adjust_offset(delta_ms)

    def _on_toggle_lyrics(self, checked):
        self.lyrics_panel.setVisible(checked)
        if not checked:
            return
        # Панель могли открыть в середине трека — сразу ставим подсветку.
        self.lyrics_manager.refresh_highlight()
        self.lyrics_panel.scroll_to_current()

    # ------------------------------------------------------------------
    #  Полноэкранный текст
    # ------------------------------------------------------------------
    def _on_lyrics_fullscreen(self):
        """Открывает полноэкранный оверлей с текущим текстом."""
        self.lyrics_manager.show_fullscreen()

    def _on_lyrics_karaoke(self):
        """Открывает полноэкранный караоке-режим с текущим текстом."""
        # Двойной клик по кнопке текста мог снять её отметку — возвращаем
        # панель в открытое состояние, чтобы текст был доступен и под ней.
        self.player_bar.activate_lyrics()
        self.lyrics_manager.show_karaoke()

    def _on_next_track_changed(self, track_id, title=""):
        """Показывает следующий трек; id = -1 (пустая очередь) скрывает островок."""
        self.library_tab.set_next_track(track_id, title)

    def _on_context_changed(self, name):
        self.player_bar.set_context(name)

    # ------------------------------------------------------------------
    #  Library: автосинхронизация и reload
    # ------------------------------------------------------------------
    def _sync_library_on_startup(self):
        if not MUSIC_FOLDER.exists():
            return
        files = workers.find_audio_files(MUSIC_FOLDER)
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
            QMessageBox.warning(
                self, tr("File missing", lang),
                tr("File not found:\n{path}", lang).format(path=path),
            )
            return
        clicked_id = self._item_id(item)
        ids = self.library_tab.library_ids()
        self.controller.play_from_list(
            ids, clicked_id, "library", tr("Library", lang), None
        )

    def _on_random_play(self):
        """Играет случайный трек из всей библиотеки."""
        ids = [row["id"] for row in db.get_all_tracks()]
        if not ids:
            return
        chosen_id = random.choice(ids)
        lang = self.settings.value("language", "en")
        self.controller.play_from_list(
            ids, chosen_id, "library", tr("Library", lang), None
        )

    def _on_library_changed(self):
        """Библиотека изменила БД (drag & drop или новая папка)."""
        self.library_tab.update_track_count()

    def _show_folder_context_menu(self, global_pos, folder_id):
        menu = QMenu(self)
        lang = self.settings.value("language", "en")

        play_action = QAction(tr("Play this folder only", lang), menu)
        play_action.setIcon(self._load_icon("play.svg"))
        play_action.triggered.connect(
            lambda checked=False, fid=folder_id: self._on_play_folder(fid)
        )
        menu.addAction(play_action)

        add_menu = QMenu(tr("Add folder to playlist", lang), menu)
        add_menu.setIcon(self._load_icon("add-to-playlist.svg"))
        playlists = db.get_all_playlists()
        if not playlists:
            empty = QAction(tr("(no playlists)", lang), add_menu)
            empty.setEnabled(False)
            add_menu.addAction(empty)
        else:
            for pl in playlists:
                action = QAction(pl["name"], add_menu)
                action.triggered.connect(
                    lambda checked=False, pid=pl["id"], fid=folder_id:
                        self._add_folder_to_playlist(pid, fid)
                )
                add_menu.addAction(action)
        menu.addMenu(add_menu)

        menu.addSeparator()

        delete_action = QAction(tr("Delete folder", lang), menu)
        delete_action.setIcon(self._load_icon("trash.svg"))
        delete_action.triggered.connect(
            lambda checked=False, fid=folder_id: self._on_delete_folder(fid)
        )
        menu.addAction(delete_action)
        menu.exec_(global_pos)

    def _folder_track_ids(self, folder_id):
        return [row["id"] for row in db.get_tracks_in_folder(folder_id)]

    def _on_play_folder(self, folder_id):
        """Играет только треки выбранной папки."""
        ids = self._folder_track_ids(folder_id)
        if not ids:
            return
        folder = next(
            (f for f in db.get_all_folders() if f["id"] == folder_id), None
        )
        name = folder["name"] if folder is not None else ""
        self.controller.play_from_list(ids, ids[0], "folder", name, None)

    def _add_folder_to_playlist(self, playlist_id, folder_id):
        """Добавляет все треки папки в выбранный плейлист."""
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
            self._show_folder_context_menu(
                source_list.mapToGlobal(pos), self._item_id(item)
            )
            return
        track_id = self._item_id(item)
        if track_id is None:
            return

        menu = TrackContextMenu(
            self,
            self.settings,
            self.icons,
            track_id,
            db.get_all_playlists(),
            scope,
            source_list,
        )
        menu.add_to_playlist_requested.connect(
            self.track_actions.add_to_playlist
        )
        menu.add_to_queue_requested.connect(
            self.track_actions.add_to_queue
        )
        menu.favorite_requested.connect(self.track_actions.set_favorite)
        menu.edit_metadata_requested.connect(
            self.track_actions.edit_metadata
        )
        menu.remove_requested.connect(self.track_actions.remove)
        menu.exec_at(pos)

    def _on_settings_clicked(self):
        """Кнопка-шестерёнка: открываем вкладку настроек вместо диалога."""
        self.tabs.setCurrentWidget(self.settings_page)

    def _on_profile_playlist_clicked(self, playlist_id):
        """Клик по карточке плейлиста в профиле: открываем его во вкладке Playlists."""
        self.tabs.setCurrentWidget(self.playlists_page)
        self.playlists_page.open_playlist(playlist_id)

    def _on_friend_profile_requested(self, user_id: int) -> None:
        """Открывает вкладку Profile с чужим профилем."""
        self._show_user_page(self.profile_page)
        self.profile_page.load_friend_profile(user_id)

    def _on_profile_back(self) -> None:
        """Кнопка Back на чужом профиле: возвращает свой профиль."""
        self.profile_page.show_own_profile()

    # ------------------------------------------------------------------
    #  Playlists
    # ------------------------------------------------------------------
    def _reload_playlists(self):
        self.playlists_page.reload()

    def _on_play_playlist(self, playlist_id):
        """Играть весь плейлист с начала."""
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
        """Двойной клик по треку внутри плейлиста."""
        if not ids:
            return
        pl = db.get_playlist_by_id(playlist_id)
        pl_name = pl["name"] if pl else "Playlist"
        self.controller.play_from_list(ids, track_id, "playlist", pl_name, playlist_id)

    def _on_playlist_deleted(self, playlist_id):
        """Плейлист удалён — если играли из него, переключаемся на Library."""
        c = self.controller
        if c.play_context_type == "playlist" and c.play_context_playlist_id == playlist_id:
            ids = self.library_tab.library_ids()
            if ids and c.current_track_id in ids:
                c.set_context(ids, ids.index(c.current_track_id), "library",
                              tr("Library", self.settings.value("language", "en")), None)
            else:
                c.clear_context()

    # ------------------------------------------------------------------
    #  QMediaPlayer signals
    # ------------------------------------------------------------------
    def _on_player_state_changed(self, state):
        # приходит int из QMediaPlayer.stateChanged и bool из контроллера
        playing = state if isinstance(state, bool) else (state == QMediaPlayer.PlayingState)
        self.player_bar.set_playing(playing)

    def _on_position_changed(self, pos):
        self.player_bar.set_position(pos, self.media_player.duration())

    def _on_duration_changed(self, duration):
        self.player_bar.set_duration(duration, self.media_player.position())

    def _on_about_to_finish(self):
        self.controller.prepare_crossfade()

    def _on_track_finished(self):
        self.controller.on_track_finished()
