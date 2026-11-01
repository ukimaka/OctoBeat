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

"""libVLC backend: one media-player slot bridged into Qt signals.

VLC's ``MediaPlayer`` is a ctypes/C object and cannot be a QObject.  This
module uses composition: ``VlcAudioPlayer`` owns a ``vlc.MediaPlayer`` and
exposes a normal Qt API.  VLC event callbacks only copy event data into a
queued Qt signal; they never call libVLC themselves (libVLC is not
reentrant from its event handlers).
"""

from __future__ import annotations

import os
import sys
import threading
from enum import IntEnum
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot

import paths


class PlaybackState(IntEnum):
    """Playback states matching the previous integer contract."""

    STOPPED = 0
    PLAYING = 1
    PAUSED = 2


class VlcUnavailable(RuntimeError):
    """Raised when python-vlc or the libVLC runtime cannot be loaded."""


_STATE_LOCK = threading.RLock()
_VLC = None
_VLC_ERROR = None
_INSTANCE = None
_DLL_DIR_HANDLES = []

_INSTANCE_OPTIONS = (
    "--no-video",
    "--no-osd",
    "--no-video-title-show",
    "--no-stats",
    "--quiet",
)


def _existing_file(candidates):
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _existing_dir(candidates):
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _find_vlc_paths(base):
    """Return (library, plugins) for a bundled VLC directory, if present."""
    base = Path(base)
    if sys.platform == "win32":
        library = _existing_file(
            (base / "libvlc.dll", base / "lib" / "libvlc.dll")
        )
    elif sys.platform == "darwin":
        library = _existing_file(
            (
                base / "lib" / "libvlc.dylib",
                base / "libvlc.dylib",
                base / "VLC.app" / "Contents" / "MacOS" / "lib" / "libvlc.dylib",
            )
        )
    else:
        library = _existing_file(
            (
                base / "libvlc.so",
                base / "libvlc.so.5",
                base / "lib" / "libvlc.so",
                base / "lib" / "libvlc.so.5",
            )
        )
        if library is None:
            try:
                matches = sorted(base.glob("libvlc.so*")) + sorted(
                    base.glob("lib/libvlc.so*")
                )
                library = next((p for p in matches if p.is_file()), None)
            except OSError:
                library = None

    plugins = _existing_dir(
        (
            base / "plugins",
            base / "lib" / "plugins",
            base / "modules",
            base / "lib" / "modules",
        )
    )
    return library, plugins


def _configure_vlc_environment():
    """Point python-vlc at bundled libVLC before it imports the C library."""
    lib_env = os.environ.get("PYTHON_VLC_LIB_PATH")
    module_env = os.environ.get("PYTHON_VLC_MODULE_PATH")

    if lib_env:
        if module_env:
            return
        lib_path = Path(lib_env)
        for candidate in (
            lib_path.parent / "plugins",
            lib_path.parent.parent / "plugins",
            lib_path.parent / "modules",
            lib_path.parent.parent / "modules",
        ):
            if candidate.is_dir():
                os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(candidate))
                return
        return

    candidates = []
    explicit = os.environ.get("OCTOBEAT_VLC_DIR")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(paths.RESOURCE_DIR / "vlc")

    if sys.platform == "win32":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "VideoLAN" / "VLC")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/VLC.app/Contents/MacOS"))

    for base in candidates:
        library, plugins = _find_vlc_paths(base)
        if library is None:
            continue
        os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(library))
        if plugins is not None:
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(plugins))
        if sys.platform == "win32":
            for directory in {library.parent, base, library.parent.parent}:
                try:
                    handle = os.add_dll_directory(str(directory))
                    _DLL_DIR_HANDLES.append(handle)
                except (AttributeError, OSError):
                    pass
            os.environ["PATH"] = (
                str(library.parent) + os.pathsep + os.environ.get("PATH", "")
            )
        return


def _load_vlc():
    """Lazily import python-vlc after configuring the DLL/plugin paths."""
    global _VLC, _VLC_ERROR
    if _VLC is not None:
        return _VLC
    if _VLC_ERROR is not None:
        raise VlcUnavailable(_VLC_ERROR)

    with _STATE_LOCK:
        if _VLC is not None:
            return _VLC
        if _VLC_ERROR is not None:
            raise VlcUnavailable(_VLC_ERROR)

        _configure_vlc_environment()
        try:
            import vlc as module
        except Exception as exc:  # ImportError, OSError from ctypes
            _VLC_ERROR = (
                "python-vlc or libVLC is not installed. Install python-vlc "
                "and the VLC runtime for this platform."
            )
            raise VlcUnavailable(_VLC_ERROR) from exc
        _VLC = module
        return _VLC


def get_instance():
    """Return the one shared VLC instance used by the whole application."""
    global _INSTANCE
    with _STATE_LOCK:
        module = _load_vlc()
        if _INSTANCE is None:
            try:
                instance = module.Instance(*_INSTANCE_OPTIONS)
            except Exception as exc:
                raise VlcUnavailable(
                    "Could not create the libVLC audio instance."
                ) from exc
            if instance is None:
                raise VlcUnavailable(
                    "Could not create the libVLC audio instance."
                )
            _INSTANCE = instance
        return _INSTANCE


def is_available():
    """Return True when the VLC binding and runtime can be loaded."""
    try:
        _load_vlc()
        return True
    except VlcUnavailable:
        return False


def shutdown_backend():
    """Release the shared VLC instance. Call only after every player is gone."""
    global _INSTANCE
    with _STATE_LOCK:
        instance, _INSTANCE = _INSTANCE, None
        if instance is not None:
            try:
                instance.release()
            except Exception:
                pass


class VlcAudioPlayer(QObject):
    """One reusable libVLC media-player slot exposed as a QObject."""

    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(int)
    endReached = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    _raw_event = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vlc = _load_vlc()
        self._instance = get_instance()
        self._player = self._instance.media_player_new()
        if self._player is None:
            raise VlcUnavailable("Could not create a libVLC media player.")
        self._events = self._player.event_manager()
        if self._events is None:
            raise VlcUnavailable("Could not attach libVLC event handlers.")

        self._alive = True
        self._generation = 0
        self._callbacks = []
        self._media = None
        self._media_path = None

        self._state = PlaybackState.STOPPED
        self._position_ms = 0
        self._duration_ms = 0
        self._volume = 70
        self._pending_volume = None
        self._pending_seek = None
        self._requested_play = False
        self._end_emitted = False

        self._ev_time = int(self._vlc.EventType.MediaPlayerTimeChanged.value)
        self._ev_length = int(self._vlc.EventType.MediaPlayerLengthChanged.value)
        self._ev_playing = int(self._vlc.EventType.MediaPlayerPlaying.value)
        self._ev_paused = int(self._vlc.EventType.MediaPlayerPaused.value)
        self._ev_stopped = int(self._vlc.EventType.MediaPlayerStopped.value)
        self._ev_end = int(self._vlc.EventType.MediaPlayerEndReached.value)
        self._ev_error = int(self._vlc.EventType.MediaPlayerEncounteredError.value)

        self._raw_event.connect(self._on_raw_event, Qt.QueuedConnection)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_position)

        self._attach_events()

    # ------------------------------------------------------------------
    #  VLC -> Qt bridge
    # ------------------------------------------------------------------
    def _attach_events(self):
        if not self._alive or self._events is None:
            return
        self._detach_events()
        event_types = (
            self._vlc.EventType.MediaPlayerPlaying,
            self._vlc.EventType.MediaPlayerPaused,
            self._vlc.EventType.MediaPlayerStopped,
            self._vlc.EventType.MediaPlayerEndReached,
            self._vlc.EventType.MediaPlayerEncounteredError,
            self._vlc.EventType.MediaPlayerTimeChanged,
            self._vlc.EventType.MediaPlayerLengthChanged,
        )

        for event_type in event_types:
            def callback(event, generation):
                if not self._alive or generation != self._generation:
                    return
                event_type_value = self._event_type_value(event)
                if event_type_value is None:
                    return
                payload = 0
                try:
                    if event_type_value == self._ev_time:
                        payload = int(event.u.new_time)
                    elif event_type_value == self._ev_length:
                        payload = int(event.u.new_length)
                except (AttributeError, TypeError, ValueError):
                    payload = 0
                self._raw_event.emit(event_type_value, payload)

            result = self._events.event_attach(
                event_type, callback, self._generation
            )
            if result == 0:
                self._callbacks.append((event_type, callback))
            else:
                print(f"[vlc] event_attach failed for {event_type}")

    def _detach_events(self):
        if self._events is None:
            return
        for event_type, _callback in self._callbacks:
            try:
                self._events.event_detach(event_type)
            except Exception:
                pass
        self._callbacks = []

    @staticmethod
    def _event_type_value(event):
        value = getattr(event, "event_type", None)
        if value is None:
            value = getattr(event, "type", None)
        if value is None:
            return None
        inner = getattr(value, "value", None)
        if inner is not None:
            try:
                return int(inner)
            except (TypeError, ValueError):
                pass
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @pyqtSlot(int, int)
    def _on_raw_event(self, event_type, payload):
        if not self._alive:
            return
        if event_type == self._ev_time:
            if self._media is not None:
                self._set_position(payload)
            return
        if event_type == self._ev_length:
            if self._media is not None:
                self._set_duration(payload)
            return
        if event_type == self._ev_playing:
            # Ignore a stale Playing event left over from a pause/stop.
            if not self._requested_play:
                return
            self._set_state(PlaybackState.PLAYING)
            self._apply_volume()
            self._apply_pending_seek()
            return
        if event_type == self._ev_paused:
            # A Paused event may arrive after resume() has already asked
            # VLC to play again; do not overwrite the newer state.
            if self._requested_play:
                return
            self._set_state(PlaybackState.PAUSED)
            return
        if event_type == self._ev_stopped:
            # The same applies to the Stopped event emitted while replacing
            # media or immediately after a new play() request.
            if self._requested_play:
                return
            self._set_state(PlaybackState.STOPPED)
            return
        if event_type == self._ev_end:
            if self._media is None:
                return
            self._requested_play = False
            if self._duration_ms > 0:
                self._set_position(self._duration_ms, force=True)
            self._set_state(PlaybackState.STOPPED)
            if not self._end_emitted:
                self._end_emitted = True
                self.endReached.emit()
            return
        if event_type == self._ev_error:
            self._requested_play = False
            self._set_state(PlaybackState.STOPPED)
            self.errorOccurred.emit("VLC could not play this file")

    @pyqtSlot()
    def _poll_position(self):
        if (
            not self._alive
            or self._player is None
            or self._media is None
            or self._state != PlaybackState.PLAYING
        ):
            self._poll_timer.stop()
            return
        try:
            position = self._player.get_time()
        except Exception:
            return
        if self._duration_ms <= 0:
            try:
                length = self._player.get_length()
            except Exception:
                length = 0
            if length and length > 0:
                self._set_duration(length)
        if position is not None and position >= 0:
            self._set_position(position)
        if self._pending_volume is not None:
            self._apply_volume()
        if self._pending_seek is not None:
            self._apply_pending_seek()

    # ------------------------------------------------------------------
    #  Cached state helpers
    # ------------------------------------------------------------------
    def _set_state(self, state):
        state = PlaybackState(state)
        if state == self._state:
            if state == PlaybackState.PLAYING:
                if self._alive and not self._poll_timer.isActive():
                    self._poll_timer.start()
            else:
                self._poll_timer.stop()
            return
        self._state = state
        if state == PlaybackState.PLAYING:
            if self._alive:
                self._poll_timer.start()
        else:
            self._poll_timer.stop()
        self.stateChanged.emit(int(state))

    def _set_position(self, value, force=False):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        value = max(0, value)
        if self._duration_ms > 0:
            value = min(value, self._duration_ms)
        if value == self._position_ms and not force:
            return
        self._position_ms = value
        self.positionChanged.emit(value)

    def _set_duration(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        value = max(0, value)
        if value == self._duration_ms:
            return
        self._duration_ms = value
        self.durationChanged.emit(value)

    def _apply_volume(self):
        if not self._alive or self._player is None:
            return
        try:
            result = self._player.audio_set_volume(int(self._volume))
        except Exception:
            result = -1
        if result == 0:
            self._pending_volume = None
        else:
            self._pending_volume = self._volume

    def _apply_pending_seek(self):
        if (
            not self._alive
            or self._player is None
            or self._pending_seek is None
        ):
            return
        try:
            result = self._player.set_time(int(self._pending_seek))
        except Exception:
            result = -1
        if result == 0:
            self._pending_seek = None

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------
    def set_media(self, path=None):
        """Replace the current media without starting playback."""
        if not self._alive or self._player is None:
            return False

        self._generation += 1
        self._detach_events()
        self._poll_timer.stop()

        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.set_media(None)
        except Exception:
            pass
        if self._media is not None:
            try:
                self._media.release()
            except Exception:
                pass
        self._media = None
        self._media_path = None

        self._requested_play = False
        self._end_emitted = False
        self._pending_seek = None
        self._pending_volume = None
        self._set_state(PlaybackState.STOPPED)
        self._set_position(0, force=True)
        self._set_duration(0)

        if path is None:
            self._attach_events()
            return True

        try:
            media = self._instance.media_new_path(os.fspath(path))
        except Exception as exc:
            self._attach_events()
            self.errorOccurred.emit(f"Could not open media: {exc}")
            return False
        if media is None:
            self._attach_events()
            self.errorOccurred.emit("Could not open media.")
            return False

        self._player.set_media(media)
        self._media = media
        self._media_path = os.fspath(path)
        self._attach_events()
        self._apply_volume()
        return True

    def play(self):
        """Start or restart the loaded media."""
        if not self._alive or self._player is None or self._media is None:
            return False

        was_paused = self._state == PlaybackState.PAUSED
        self._requested_play = True
        self._end_emitted = False
        self._set_state(PlaybackState.PLAYING)
        self._apply_volume()

        try:
            if was_paused:
                result = self._player.set_pause(False)
                self._apply_pending_seek()
            else:
                result = self._player.play()
        except Exception:
            result = -1
        if result == -1:
            self._requested_play = False
            self._set_state(PlaybackState.STOPPED)
            self.errorOccurred.emit("VLC could not start playback.")
            return False
        return True

    def pause(self):
        if (
            not self._alive
            or self._player is None
            or self._state != PlaybackState.PLAYING
        ):
            return
        self._requested_play = False
        try:
            result = self._player.set_pause(True)
        except Exception:
            self._requested_play = True
            return
        if result == -1:
            self._requested_play = True
            return
        self._set_state(PlaybackState.PAUSED)

    def resume(self):
        if not self._alive or self._player is None or self._media is None:
            return False
        if self._state == PlaybackState.PAUSED:
            self._requested_play = True
            self._set_state(PlaybackState.PLAYING)
            self._apply_volume()
            try:
                result = self._player.set_pause(False)
            except Exception:
                result = -1
            if result == -1:
                self._requested_play = False
                self._set_state(PlaybackState.STOPPED)
                self.errorOccurred.emit("VLC could not resume playback.")
                return False
            self._apply_pending_seek()
            return True
        return self.play()

    def set_pause(self, paused):
        if paused:
            self.pause()
        else:
            self.resume()

    def stop(self):
        if not self._alive or self._player is None:
            return
        self._requested_play = False
        self._end_emitted = False
        self._pending_seek = None
        try:
            self._player.stop()
        except Exception:
            pass
        self._set_state(PlaybackState.STOPPED)
        self._set_position(0, force=True)

    def set_position(self, position_ms):
        if not self._alive or self._player is None or self._media is None:
            return
        try:
            position_ms = int(position_ms)
        except (TypeError, ValueError):
            return
        position_ms = max(0, position_ms)
        if self._duration_ms > 0:
            position_ms = min(position_ms, self._duration_ms)

        try:
            result = self._player.set_time(position_ms)
        except Exception:
            result = -1
        self._pending_seek = None if result == 0 else position_ms
        self._set_position(position_ms, force=True)

    def position(self):
        return self._position_ms

    def duration(self):
        return self._duration_ms

    def state(self):
        return self._state

    def is_playing(self):
        return self._state == PlaybackState.PLAYING

    def media_is_null(self):
        return self._media is None

    def set_volume(self, volume):
        if not self._alive:
            return
        try:
            volume = max(0, min(100, int(volume)))
        except (TypeError, ValueError):
            return
        if volume == self._volume and self._pending_volume is None:
            return
        self._volume = volume
        self._apply_volume()

    def volume(self):
        return self._volume

    def release_media(self):
        """Drop the current file but keep this VLC player reusable."""
        if not self._alive or self._player is None:
            return
        self._generation += 1
        self._detach_events()
        self._poll_timer.stop()
        self._requested_play = False
        self._end_emitted = False
        self._pending_seek = None
        self._pending_volume = None

        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.set_media(None)
        except Exception:
            pass
        if self._media is not None:
            try:
                self._media.release()
            except Exception:
                pass
        self._media = None
        self._media_path = None
        self._set_state(PlaybackState.STOPPED)
        self._set_position(0, force=True)
        self._set_duration(0)

    def shutdown(self):
        """Detach events and destroy the underlying libVLC player."""
        if not self._alive:
            return
        self._alive = False
        self._poll_timer.stop()
        self._detach_events()
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
            try:
                self._player.set_media(None)
            except Exception:
                pass
            if self._media is not None:
                try:
                    self._media.release()
                except Exception:
                    pass
            self._media = None
            try:
                self._player.release()
            except Exception:
                pass
            self._player = None
        self._events = None
        self._state = PlaybackState.STOPPED
        self._position_ms = 0
        self._duration_ms = 0
        self._pending_seek = None
        self._pending_volume = None
