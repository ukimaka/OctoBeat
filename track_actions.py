"""Мутации треков: удаление, favorite, плейлисты и метаданные.

Действия ничего не знают о конкретных виджетах библиотеки. После успешной
мутации они эмитят ``changed``, а MainWindow обновляет списки.
"""

import os
import re
from pathlib import Path

from PyQt5.QtCore import QObject, QSettings, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
from mutagen.easyid3 import EasyID3

from dialogs import CustomConfirmDialog, CustomInputDialog
from translations import tr


class TrackActions(QObject):
    """Выполняет действия над треком и сообщает об изменениях."""

    changed = pyqtSignal()
    favorite_changed = pyqtSignal()

    def __init__(
        self,
        db,
        controller,
        playlists_page,
        parent=None,
        settings=None,
    ):
        super().__init__(parent)
        self.db = db
        self.controller = controller
        self.playlists_page = playlists_page
        self.parent_widget = parent
        self.settings = settings or QSettings("MusicPlayer", "MusicPlayer")

    def _lang(self):
        return self.settings.value("language", "en")

    # ------------------------------------------------------------------
    #  Удаление
    # ------------------------------------------------------------------
    def remove(self, track_id, scope):
        """Удаляет трек из библиотеки или из текущего плейлиста."""
        if scope == "library":
            self.remove_track(track_id)
        elif scope == "playlist":
            self.remove_from_current_playlist(track_id)

    def remove_track(self, track_id):
        """Удаляет трек из библиотеки, контекста плеера и кэша обложек."""
        if track_id is None:
            return
        self.controller.remove_from_context(track_id)
        self.db.delete_track(track_id)

        cover_cache = os.path.expanduser(
            f"~/.cache/music_player/covers/{track_id}.jpg"
        )
        if os.path.exists(cover_cache):
            os.remove(cover_cache)

        self.changed.emit()

    def remove_from_current_playlist(self, track_id):
        playlist_id = self.playlists_page.current_playlist_id
        if playlist_id is None:
            return
        self.db.remove_track_from_playlist(playlist_id, track_id)
        self.changed.emit()

    # ------------------------------------------------------------------
    #  Favorite / очередь
    # ------------------------------------------------------------------
    def set_favorite(self, track_id):
        """Назначает трек любимым и обновляет вкладку профиля."""
        self.db.set_favorite_track(track_id)
        self.favorite_changed.emit()
        self.changed.emit()

    def add_to_queue(self, track_id):
        self.controller.add_to_queue(track_id)

    # ------------------------------------------------------------------
    #  Плейлисты
    # ------------------------------------------------------------------
    def add_to_playlist(self, playlist_id, track_id):
        existing = {
            row["id"]
            for row in self.db.get_tracks_in_playlist(playlist_id)
        }
        if track_id in existing:
            lang = self._lang()
            CustomConfirmDialog.information(
                self.parent_widget, tr("Already there", lang),
                tr("This track is already in the playlist.", lang),
            )
            return
        self.db.add_track_to_playlist(playlist_id, track_id)
        self.changed.emit()

    # ------------------------------------------------------------------
    #  Метаданные
    # ------------------------------------------------------------------
    def edit_metadata(self, track_id):
        """Ручное редактирование "Artist - Title" с переименованием файла."""
        lang = self._lang()
        row = self.db.get_track_by_id(track_id)
        if row is None:
            return

        media_player = self.controller.media_player
        old_path = row["file_path"]
        default_text = "{} - {}".format(
            row["artist"] or "Unknown Artist",
            row["title"] or Path(old_path).stem,
        )

        text, ok = CustomInputDialog.get_text(
            self.parent_widget, tr("Fix metadata", lang),
            tr("Enter 'Artist - Title':", lang),
            text=default_text,
        )
        if not ok or not (text or "").strip():
            return

        text = text.strip()
        if " - " in text:
            artist, title = text.split(" - ", 1)
        else:
            artist, title = "Unknown Artist", text
        artist = artist.strip() or "Unknown Artist"
        title = title.strip()
        if not title:
            return

        # Редактируем ли мы трек, который сейчас в плеере?
        is_current = (track_id == self.controller.current_track_id)
        was_playing = is_current and media_player.is_playing()

        # Переименовываем файл на диске
        safe_name = re.sub(
            r'[\\/:*?"<>|]', "_", f"{artist} - {title}"
        ).strip()
        new_path = str(
            Path(old_path).with_name(safe_name + Path(old_path).suffix)
        )
        renamed = False
        stopped = False
        if new_path != old_path:
            # Новый путь может быть уже занят другим треком в БД. Без этой
            # проверки UPDATE упрётся в UNIQUE constraint на tracks.file_path.
            if self.db.get_track_by_path(new_path) is not None:
                QMessageBox.warning(
                    self.parent_widget, tr("Fix metadata", lang),
                    tr(
                        "A file with this name already exists in the database",
                        lang,
                    ),
                )
                return
            if is_current:
                # Останавливаем плеер, чтобы отпустить файл перед переименованием
                media_player.stop()
                stopped = True
            try:
                # Сначала файл на диске, и только потом запись в БД: если
                # переименование упало — путь в базе не трогаем.
                os.rename(old_path, new_path)
            except Exception as e:
                QMessageBox.warning(
                    self.parent_widget, tr("Fix metadata", lang),
                    tr("Could not rename file:\n{e}", lang).format(e=e),
                )
                new_path = old_path
            else:
                self.db.update_track_path(track_id, new_path)
                renamed = True

        # Записываем теги
        try:
            try:
                audio = EasyID3(new_path)
            except Exception:
                audio = EasyID3()
            audio["artist"] = artist
            audio["title"] = title
            audio.save(new_path, v2_version=3)
        except Exception as e:
            print(f"[fix metadata] tag write failed: {e}")

        self.db.update_track_metadata(
            track_id,
            title=title,
            artist=artist,
            album=row["album"],
            duration=row["duration"],
        )

        # Возобновляем воспроизведение по пути (новому или исходному, если
        # переименование не удалось — плеер мы уже остановили)
        if is_current and (renamed or stopped):
            loudness = row["loudness"]
            if was_playing:
                media_player.play(new_path, loudness=loudness)
            else:
                # Трек был на паузе — просто обновляем путь, не запуская
                media_player.set_media(new_path, loudness=loudness)

        self.changed.emit()
