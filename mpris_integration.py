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

"""Интеграция MPRIS для Linux: медиа-клавиши и управление из трея/панели.

Публикует на D-Bus интерфейс ``org.mpris.MediaPlayer2.MusicPlayer`` и
проксирует команды MPRIS в :class:`controller.PlayerController`.

Библиотека: ``mpris_server`` (https://github.com/alexdelorenzo/mpris_server).
"""

from __future__ import annotations

from mpris_server import (
    EventAdapter,
    MetadataObj,
    MprisAdapter,
    PlayState,
    Server,
)
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtMultimedia import QMediaPlayer

# В библиотеке mpris_server состояние плеера называется PlayState.
# Псевдоним оставлен для читаемости и совместимости с формулировкой задачи.
PlaybackStatus = PlayState

# Базовый D-Bus-путь для неиграющего трека.
DEFAULT_TRACK_PATH = "/com/musicplayer/track/0"


def _track_path(track_id):
    return f"/com/musicplayer/track/{track_id}"


class _MprisCommandBridge(QObject):
    """Мост между D-Bus-потоком и Qt-потоком.

    Методы MPRIS вызываются glib-потоком (в котором крутится D-Bus loop),
    а работа с QMediaPlayer обязана происходить в потоке главного окна.
    Поэтому адаптер не дёргает контроллер напрямую, а испускает Qt-сигналы:
    они доставляются в UI-поток через queued connection.
    """

    play = pyqtSignal()
    pause = pyqtSignal()
    play_pause = pyqtSignal()
    next = pyqtSignal()
    previous = pyqtSignal()
    stop = pyqtSignal()
    seek = pyqtSignal(int)          # микросекунды
    set_volume = pyqtSignal(float)  # 0.0 .. 1.0


class PlayerMprisAdapter(MprisAdapter):
    """Адаптер: отдаёт MPRIS-состояние плеера и принимает команды."""

    def __init__(self, controller, bridge, name="MusicPlayer"):
        super().__init__(name)
        self.controller = controller
        self.bridge = bridge

    # ------------------------------------------------------------------
    #  Метаданные
    # ------------------------------------------------------------------
    def metadata(self):
        """Текущий трек: title, artist, length (в микросекундах)."""
        track_id = self.controller.current_track_id
        if track_id is None:
            return MetadataObj(
                title="—",
                artists=[],
                length=0,
                track_id=DEFAULT_TRACK_PATH,
            )

        row = self.controller.db.get_track_by_id(track_id)
        if row is None:
            return MetadataObj(
                title="", artists=[], length=0, track_id=_track_path(track_id)
            )

        duration = row["duration"] or 0
        artists = [row["artist"]] if row["artist"] else []
        return MetadataObj(
            title=row["title"] or "",
            artists=artists,
            album=row["album"] or None,
            length=int(duration) * 1_000_000,   # секунды -> микросекунды
            url=row["file_path"] or None,
            art_url=self._cover_url(track_id),
            track_id=_track_path(track_id),
        )

    def _cover_url(self, track_id):
        """file:// URL закэшированной обложки, если она уже извлечена."""
        covers_dir = getattr(self.controller.metadata, "COVERS_DIR", None)
        if covers_dir is None:
            return None
        cover = covers_dir / f"{track_id}.jpg"
        try:
            return cover.as_uri() if cover.exists() else None
        except OSError:
            return None

    # ------------------------------------------------------------------
    #  Состояние воспроизведения
    # ------------------------------------------------------------------
    def get_playstate(self):
        # Имя, которое использует mpris_server.
        return self.playback_status()

    def playback_status(self):
        player = self.controller.media_player
        if player.media_is_null():
            return PlaybackStatus.STOPPED
        if player.is_playing():
            return PlaybackStatus.PLAYING
        if player.state() == QMediaPlayer.PausedState:
            return PlaybackStatus.PAUSED
        return PlaybackStatus.STOPPED

    # ------------------------------------------------------------------
    #  Возможности
    # ------------------------------------------------------------------
    def can_control(self):
        return True

    def can_play(self):
        return True

    def can_pause(self):
        return True

    def can_go_next(self):
        return True

    def can_go_previous(self):
        return True

    def can_seek(self):
        return True

    # ------------------------------------------------------------------
    #  Позиция и громкость
    # ------------------------------------------------------------------
    def get_current_position(self):
        """Текущая позиция в микросекундах."""
        return max(0, int(self.controller.media_player.position())) * 1000

    def get_volume(self):
        return max(0.0, min(1.0, self.controller.media_player.volume() / 100.0))

    def is_mute(self):
        return False

    def set_mute(self, value):
        # Mute не поддерживаем: громкость регулируется напрямую.
        pass

    # ------------------------------------------------------------------
    #  Команды (проксируются в UI-поток через bridge)
    # ------------------------------------------------------------------
    def play(self):
        self.bridge.play.emit()

    def pause(self):
        self.bridge.pause.emit()

    def resume(self):
        self.bridge.play.emit()

    def play_pause(self):
        self.bridge.play_pause.emit()

    def next(self):
        self.bridge.next.emit()

    def previous(self):
        self.bridge.previous.emit()

    def stop(self):
        self.bridge.stop.emit()

    def seek(self, time, track_id=None):
        self.bridge.seek.emit(int(time))

    def set_volume(self, value):
        self.bridge.set_volume.emit(float(value))


class PlayerMprisEventHandler(EventAdapter):
    """Шлёт D-Bus-сигналы ``PropertiesChanged`` при изменении состояния."""

    def __init__(self, root, player, playlists, tracklist, controller=None):
        super().__init__(root, player, playlists, tracklist)
        self.controller = controller

    def emit_all(self):
        self.on_player_all()

    def on_playback_state_changed(self, is_playing):
        """Изменение состояния воспроизведения -> сигнал в D-Bus."""
        if is_playing:
            self.on_playpause()
        else:
            self.on_stop()

    def on_stop(self):
        self.on_playback()


def start_mpris(controller, name="MusicPlayer"):
    """Создаёт MPRIS-сервер, публикует его на D-Bus и запускает loop()
    в отдельном потоке, чтобы не блокировать UI.

    Возвращает :class:`Server` либо ``None``, если MPRIS недоступен
    (например, нет сессии D-Bus).
    """
    try:
        bridge = _MprisCommandBridge()

        adapter = PlayerMprisAdapter(controller, bridge, name=name)
        server = Server(name=name, adapter=adapter)
        events = PlayerMprisEventHandler(
            server.root,
            server.player,
            server.playlists,
            server.tracklist,
            controller=controller,
        )
        server.set_event_adapter(events)

        # Команды MPRIS -> публичные методы контроллера (queued в UI-поток).
        bridge.play.connect(controller.play)
        bridge.pause.connect(controller.pause)
        bridge.play_pause.connect(controller.play_pause)
        bridge.next.connect(controller.next)
        bridge.previous.connect(controller.prev)
        bridge.stop.connect(controller.stop)
        bridge.seek.connect(controller.seek_us)
        bridge.set_volume.connect(controller.set_volume_ratio)

        # Изменения состояния -> сигналы D-Bus.
        controller.track_changed.connect(lambda *_: events.on_title())
        controller.playback_state_changed.connect(
            events.on_playback_state_changed
        )

        # Держим ссылки, чтобы объекты не собрал garbage collector.
        controller._mpris_bridge = bridge
        controller.mpris_server = server

        server.loop(background=True)
        print(f"[mpris] started: org.mpris.MediaPlayer2.{name}")
        return server
    except Exception as exc:
        print(f"[mpris] not available: {exc}")
        return None


def stop_mpris(controller):
    """Заглушка: MPRIS-сервер запущен фоновым потоком (loop(background=True))
    и умирает вместе с процессом. server.quit() здесь вызывать нельзя — в
    mpris_server он делает join() самому себе и роняет RuntimeError."""
