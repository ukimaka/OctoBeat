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
from collections import deque
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


def _event_type_value(event):
    """Read a libVLC event type without touching any Qt object."""
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
        self._seeking = False
        self._seek_was_playing = False
        self._seek_muted = False
        self._seek_resume_generation = -1
        self._polling = False
        self._length_known = False
        self._volume_ready = False
        self._last_logged_volume = None
        self._event_queue = deque()

        self._ev_time = int(self._vlc.EventType.MediaPlayerTimeChanged.value)
        self._ev_length = int(self._vlc.EventType.MediaPlayerLengthChanged.value)
        self._ev_playing = int(self._vlc.EventType.MediaPlayerPlaying.value)
        self._ev_paused = int(self._vlc.EventType.MediaPlayerPaused.value)
        self._ev_stopped = int(self._vlc.EventType.MediaPlayerStopped.value)
        self._ev_end = int(self._vlc.EventType.MediaPlayerEndReached.value)
        self._ev_error = int(self._vlc.EventType.MediaPlayerEncounteredError.value)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_position)

        # libVLC needs a moment to flush the old audio buffer after a seek.
        # Keep the output muted, resume shortly afterwards and let the
        # Playing event unmute it once the new position is audible.
        self._seek_resume_timer = QTimer(self)
        self._seek_resume_timer.setSingleShot(True)
        self._seek_resume_timer.setInterval(20)
        self._seek_resume_timer.timeout.connect(self._resume_after_seek)

        self._seek_unmute_timer = QTimer(self)
        self._seek_unmute_timer.setSingleShot(True)
        self._seek_unmute_timer.setInterval(250)
        self._seek_unmute_timer.timeout.connect(self._restore_seek_audio)

        # Drain libVLC events on the Qt thread.  The VLC callback itself
        # only appends to a plain deque: if the QObject is being destroyed
        # it must never touch Qt or libVLC.
        self._event_timer = QTimer(self)
        self._event_timer.setInterval(40)
        self._event_timer.timeout.connect(self._drain_events)
        self._event_timer.start()

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

        event_queue = self._event_queue
        time_type = self._ev_time
        length_type = self._ev_length

        for event_type in event_types:
            def callback(event, generation):
                event_type_value = _event_type_value(event)
                if event_type_value is None:
                    return
                payload = 0
                try:
                    if event_type_value == time_type:
                        payload = int(event.u.new_time)
                    elif event_type_value == length_type:
                        payload = int(event.u.new_length)
                except (AttributeError, TypeError, ValueError):
                    payload = 0
                event_queue.append((generation, event_type_value, payload))

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

    @pyqtSlot()
    def _drain_events(self):
        if not self._alive:
            return
        queue = self._event_queue
        # The callback only appends to this deque (append/popleft are atomic
        # in CPython).  Drain a bounded batch per tick: a flood of stale
        # TimeChanged events must never block the Qt event loop.
        for _ in range(256):
            try:
                generation, event_type, payload = queue.popleft()
            except IndexError:
                break
            if generation != self._generation:
                continue
            self._handle_event(event_type, payload)

    def _handle_event(self, event_type, payload):
        if not self._alive:
            return
        if event_type == self._ev_time:
            if self._seeking or not self._length_known:
                return
            if self._media is not None:
                self._set_position(payload)
            return
        if event_type == self._ev_length:
            if self._media is not None:
                # LengthChanged means VLC has parsed the file.  Only now is
                # it safe to poll get_time() without causing first-play
                # decoder stutter.
                self._length_known = True
                self._set_duration(payload)
                if (
                    self._alive
                    and self._state == PlaybackState.PLAYING
                    and not self._seeking
                    and not self._poll_timer.isActive()
                ):
                    self._poll_timer.start()
            return
        if event_type == self._ev_playing:
            # Ignore a stale Playing event left over from a pause/stop.
            if not self._requested_play:
                return
            if self._seeking:
                # The pause-before-seek may still emit Playing; the resume
                # timer will request the event that starts the new audio.
                return
            # The output now exists: this is the only place where the
            # initial gain-adjusted volume is pushed to libVLC.
            self._volume_ready = True
            self._apply_volume()
            self._set_state(PlaybackState.PLAYING)
            if self._pending_seek is not None:
                self._apply_pending_seek()
                return
            self._restore_seek_audio()
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
            self._restore_seek_audio()
            return
        if event_type == self._ev_end:
            if self._media is None:
                return
            if self._seeking:
                self._cancel_seek_wait()
            self._requested_play = False
            if self._duration_ms > 0:
                self._set_position(self._duration_ms, force=True)
            self._set_state(PlaybackState.STOPPED)
            self._restore_seek_audio()
            if not self._end_emitted:
                self._end_emitted = True
                self.endReached.emit()
            return
        if event_type == self._ev_error:
            if self._seeking:
                self._cancel_seek_wait()
            self._requested_play = False
            self._set_state(PlaybackState.STOPPED)
            self._restore_seek_audio()
            self.errorOccurred.emit("VLC could not play this file")

    @pyqtSlot()
    def _poll_position(self):
        # safe_seek() can be triggered from this slot via a pending seek.
        # Guard against re-entry so the timer cannot recursively seek.
        if self._polling:
            return
        self._polling = True
        try:
            if self._seeking:
                return
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
        finally:
            self._polling = False

    # ------------------------------------------------------------------
    #  Cached state helpers
    # ------------------------------------------------------------------
    def _set_state(self, state):
        state = PlaybackState(state)
        can_poll = (
            state == PlaybackState.PLAYING
            and self._alive
            and self._length_known
            and not self._seeking
        )
        if state == self._state:
            if state == PlaybackState.PLAYING:
                if can_poll and not self._poll_timer.isActive():
                    self._poll_timer.start()
            else:
                self._poll_timer.stop()
            return
        self._state = state
        if can_poll:
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
        volume = (
            0 if self._seek_muted
            else max(0, min(200, int(self._volume)))
        )
        # Before MediaPlayerPlaying/MediaPlayerLengthChanged libVLC has no
        # output yet.  Calling audio_set_volume here is what caused the
        # first-play stutter, so just remember the request.
        if not self._volume_ready:
            self._pending_volume = volume
            return
        try:
            result = self._player.audio_set_volume(volume)
        except Exception:
            result = -1
        if result == 0:
            self._pending_volume = None
            if volume != self._last_logged_volume:
                print(f"[vlc] actual volume set: {volume}")
                self._last_logged_volume = volume
        else:
            self._pending_volume = volume

    def _apply_pending_seek(self):
        if (
            not self._alive
            or self._player is None
            or self._pending_seek is None
        ):
            return
        pending = self._pending_seek
        self.safe_seek(pending)

    def _mute_for_seek(self):
        """Silence the output while libVLC flushes the old buffer."""
        if not self._alive or self._player is None or self._seek_muted:
            return
        self._seek_muted = True
        try:
            self._player.audio_set_mute(True)
        except Exception:
            pass
        # Volume 0 is the reliable fallback when aout muting is unavailable.
        try:
            self._player.audio_set_volume(0)
        except Exception:
            pass

    @pyqtSlot()
    def _restore_seek_audio(self):
        """Unmute and restore the user volume after a seek."""
        self._seek_unmute_timer.stop()
        if not self._seek_muted:
            return
        self._seek_muted = False
        if not self._alive or self._player is None:
            return
        try:
            self._player.audio_set_mute(False)
        except Exception:
            pass
        self._apply_volume()

    def _cancel_seek_wait(self):
        self._seek_resume_timer.stop()
        self._seek_unmute_timer.stop()
        self._seeking = False
        self._seek_was_playing = False
        self._seek_resume_generation = -1

    @pyqtSlot()
    def _resume_after_seek(self):
        """Resume playback after the seek flush window."""
        if (
            not self._alive
            or self._player is None
            or self._media is None
            or not self._seek_was_playing
            or self._seek_resume_generation != self._generation
        ):
            self._seeking = False
            self._seek_was_playing = False
            self._restore_seek_audio()
            return

        self._seeking = False
        self._seek_was_playing = False
        self._requested_play = True
        try:
            result = self._player.set_pause(False)
        except Exception:
            result = -1
        if result == -1:
            self._requested_play = False
            self._set_state(PlaybackState.PAUSED)
            self._restore_seek_audio()
            return
        # The cached state may have been overwritten by a Paused/Stopped
        # event emitted by libVLC while set_time() was blocking.  The seek
        # snapshot is authoritative here, otherwise the poll timer never
        # restarts and the UI looks frozen.
        self._set_state(PlaybackState.PLAYING)
        self._poll_timer.start()
        # Normally the Playing event restores the sound; this only protects
        # against a backend that does not emit it after a seek.
        self._seek_unmute_timer.start()

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------
    def set_media(self, path=None):
        """Replace the current media without starting playback."""
        if not self._alive or self._player is None:
            return False

        self._generation += 1
        self._cancel_seek_wait()
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
        self._restore_seek_audio()
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
        self._length_known = False
        self._volume_ready = False
        self._last_logged_volume = None
        self._event_queue.clear()
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
        # Volume is applied from the Playing event, once VLC is ready.
        return True

    def play(self):
        """Start or restart the loaded media."""
        if not self._alive or self._player is None or self._media is None:
            return False

        was_paused = self._state == PlaybackState.PAUSED
        self._requested_play = True
        self._end_emitted = False
        # The state is updated immediately for the UI, but _set_state only
        # starts the position timer once LengthChanged has armed it.
        self._set_state(PlaybackState.PLAYING)

        try:
            if was_paused:
                result = self._player.set_pause(False)
            else:
                result = self._player.play()
        except Exception:
            result = -1
        if result == -1:
            self._requested_play = False
            self._set_state(PlaybackState.STOPPED)
            self._restore_seek_audio()
            self.errorOccurred.emit("VLC could not start playback.")
            return False
        if was_paused:
            if self._pending_seek is not None:
                self._apply_pending_seek()
            else:
                self._restore_seek_audio()
        return True

    def pause(self):
        if (
            not self._alive
            or self._player is None
            or self._state != PlaybackState.PLAYING
        ):
            return
        self._cancel_seek_wait()
        self._requested_play = False
        try:
            result = self._player.set_pause(True)
        except Exception:
            self._requested_play = True
            self._restore_seek_audio()
            return
        if result == -1:
            self._requested_play = True
            self._restore_seek_audio()
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
                self._restore_seek_audio()
                self.errorOccurred.emit("VLC could not resume playback.")
                return False
            if self._pending_seek is not None:
                self._apply_pending_seek()
            else:
                self._restore_seek_audio()
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
        self._cancel_seek_wait()
        self._requested_play = False
        self._end_emitted = False
        self._pending_seek = None
        try:
            self._player.stop()
        except Exception:
            pass
        self._set_state(PlaybackState.STOPPED)
        self._set_position(0, force=True)
        self._restore_seek_audio()

    def safe_seek(self, position_ms):
        """Seek without blocking playback or leaving an audible echo.

        libVLC's ``set_time()`` can block while the input/decoder thread is
        running, so playback is paused first and position polling is stopped.
        The output is muted for the whole seek and resumed 20 ms later: this
        gives libVLC time to flush the old audio buffers while nothing can be
        heard.  The volume is restored when the Playing event confirms that
        the new position is audible.  This method is only called from the Qt
        thread; VLC event callbacks only copy data into a plain deque.
        """
        if not self._alive or self._player is None or self._media is None:
            return False
        try:
            position_ms = int(position_ms)
        except (TypeError, ValueError):
            return False
        position_ms = max(0, position_ms)
        if self._duration_ms > 0:
            position_ms = min(position_ms, self._duration_ms)

        was_playing = self._state == PlaybackState.PLAYING
        had_input = self._state in (
            PlaybackState.PLAYING, PlaybackState.PAUSED
        )
        generation = self._generation

        # A new seek supersedes a pending resume from the previous one.
        self._seek_resume_timer.stop()
        self._seek_unmute_timer.stop()
        self._seek_was_playing = was_playing
        self._seek_resume_generation = -1
        self._seeking = True
        self._poll_timer.stop()
        seek_ok = False
        resume_scheduled = False
        try:
            if was_playing:
                # Mark the play intent before pausing: libVLC may emit a
                # Paused event from inside set_time(), and the event handler
                # uses this flag to ignore stale state transitions.
                self._requested_play = True
                try:
                    self._player.set_pause(True)
                except Exception:
                    pass
                self._mute_for_seek()
            try:
                # python-vlc returns None here (the C API is void), so a
                # return-code check would wrongly retry a successful seek
                # every 100 ms and block playback.
                self._player.set_time(position_ms)
                seek_ok = True
            except Exception:
                seek_ok = False
            if was_playing and self._alive and self._player is not None:
                self._requested_play = True
                self._seek_resume_generation = generation
                resume_scheduled = True
        finally:
            if resume_scheduled:
                self._seek_resume_timer.start()
            else:
                self._seeking = False
                self._seek_was_playing = False
                self._restore_seek_audio()

        # If playback had not started yet, set_time() is a no-op; keep the
        # position pending so the Playing event applies it.
        if had_input and seek_ok:
            self._pending_seek = None
        elif was_playing:
            self._pending_seek = None
        else:
            self._pending_seek = position_ms
        self._set_position(position_ms, force=True)
        return seek_ok

    def set_position(self, position_ms):
        """Seek to a position using the pause/seek/resume workaround."""
        return self.safe_seek(position_ms)

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
            # libVLC accepts 0..200; normalization uses the >100
            # headroom for quiet tracks.  Clamp explicitly so a bad
            # loudness value can never overflow the mixer.
            volume = max(0, min(200, int(volume)))
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
        self._cancel_seek_wait()
        self._detach_events()
        self._poll_timer.stop()
        self._requested_play = False
        self._end_emitted = False
        self._pending_seek = None
        self._pending_volume = None
        self._seeking = False
        self._length_known = False
        self._volume_ready = False
        self._last_logged_volume = None
        self._event_queue.clear()

        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.set_media(None)
        except Exception:
            pass
        self._restore_seek_audio()
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
        self._cancel_seek_wait()
        self._restore_seek_audio()
        self._alive = False
        self._poll_timer.stop()
        self._event_timer.stop()
        self._event_queue.clear()
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
