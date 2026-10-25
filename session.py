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

"""Сохранение и восстановление состояния плеера между запусками."""

import db
from translations import tr


def restore(controller, settings):
    """Восстанавливает громкость, режимы и последний контекст.

    Возвращает громкость для ``PlayerBar``: сам контроллер не владеет
    слайдером, поэтому визуальную часть применяет композиционный корень.
    """
    volume = int(settings.value("volume", 70))

    # Режимы — восстанавливаем прямо в контроллер
    mode = settings.value("repeat_mode", "off")
    if mode not in ("off", "all", "one"):
        mode = "off"
    controller.repeat_mode = mode
    controller.shuffle = settings.value("shuffle", False, type=bool)

    # Контекст
    last_id = settings.value("last_track_id", None)
    if last_id is None:
        return volume
    try:
        last_id = int(last_id)
    except (TypeError, ValueError):
        return volume

    last_context_type = settings.value("last_context_type", None)
    last_playlist_id = settings.value("last_playlist_id", None)
    try:
        last_playlist_id = (
            int(last_playlist_id) if last_playlist_id is not None else None
        )
    except (TypeError, ValueError):
        last_playlist_id = None

    # Пытаемся восстановить плейлист
    if last_context_type == "playlist" and last_playlist_id is not None:
        pl = next(
            (
                p for p in db.get_all_playlists()
                if p["id"] == last_playlist_id
            ),
            None,
        )
        if pl is not None:
            tracks = db.get_tracks_in_playlist(last_playlist_id)
            ids = [t["id"] for t in tracks]
            if last_id in ids:
                controller.set_context(
                    ids,
                    ids.index(last_id),
                    "playlist",
                    pl["name"],
                    last_playlist_id,
                )
                controller.show_current()
                return volume

    # Fallback: Library
    ids = [row["id"] for row in db.get_all_tracks()]
    if not ids:
        return volume
    idx = ids.index(last_id) if last_id in ids else 0
    controller.set_context(
        ids, idx, "library",
        tr("Library", settings.value("language", "en")), None,
    )
    controller.show_current()
    return volume


def save(controller, settings, volume=None):
    """Сохраняет только состояние, которое раньше писал ``closeEvent``.

    ``volume`` можно передать явно из ``PlayerBar``; без него используется
    текущая пользовательская громкость медиаплеера.
    """
    if volume is None:
        volume = controller.media_player.volume()
    settings.setValue("volume", volume)
    settings.setValue("repeat_mode", controller.repeat_mode)
    settings.setValue("shuffle", controller.shuffle)

    if controller.current_track_id is not None:
        settings.setValue("last_track_id", controller.current_track_id)
        if controller.play_context_type:
            settings.setValue(
                "last_context_type", controller.play_context_type
            )
        if controller.play_context_playlist_id is not None:
            settings.setValue(
                "last_playlist_id",
                controller.play_context_playlist_id,
            )
