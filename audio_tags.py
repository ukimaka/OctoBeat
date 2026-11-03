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

"""Запись тегов и обложек в MP3 (ID3) и M4A (MP4)."""

from __future__ import annotations

from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

MP4_EXTENSIONS = {".m4a", ".mp4"}
MP3_EXTENSIONS = {".mp3"}


def _suffix(path: Path) -> str:
    return path.suffix.lower()


def _mp3_cover_mime(path: Path) -> str:
    suffix = _suffix(path)
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/jpeg"


def _mp4_cover_format(path: Path) -> int | None:
    suffix = _suffix(path)
    if suffix == ".png":
        return MP4Cover.FORMAT_PNG
    if suffix in (".jpg", ".jpeg"):
        return MP4Cover.FORMAT_JPEG
    return None


def embed_cover(file_path: str | Path, cover_path: str | Path) -> bool:
    """Вшивает обложку в MP3 или M4A. Для прочих форматов возвращает False."""
    audio_path = Path(file_path)
    image_path = Path(cover_path)
    if not audio_path.is_file() or not image_path.is_file():
        return False
    if _suffix(audio_path) in MP3_EXTENSIONS:
        try:
            try:
                audio = ID3(str(audio_path))
            except ID3NoHeaderError:
                audio = ID3()
            with open(image_path, "rb") as image:
                audio.add(APIC(
                    encoding=3,
                    mime=_mp3_cover_mime(image_path),
                    type=3,
                    desc="Cover",
                    data=image.read(),
                ))
            audio.save(str(audio_path), v2_version=3)
            return True
        except Exception as exc:
            print(f"[tags] MP3 cover failed: {exc}")
            return False

    if _suffix(audio_path) in MP4_EXTENSIONS:
        image_format = _mp4_cover_format(image_path)
        if image_format is None:
            print(f"[tags] M4A cover unsupported: {image_path.suffix}")
            return False
        try:
            audio = MP4(str(audio_path))
            if audio.tags is None:
                audio.add_tags()
            audio.tags["covr"] = [
                MP4Cover(image_path.read_bytes(), imageformat=image_format)
            ]
            audio.save()
            return True
        except Exception as exc:
            print(f"[tags] M4A cover failed: {exc}")
            return False
    return False


def write_tags(
    file_path: str | Path,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> bool:
    """Пишет базовые теги в MP3 или M4A. Для прочих форматов — False."""
    audio_path = Path(file_path)
    if not audio_path.is_file():
        return False
    if _suffix(audio_path) in MP3_EXTENSIONS:
        try:
            try:
                audio = EasyID3(str(audio_path))
            except Exception:
                audio = EasyID3()
            if artist:
                audio["artist"] = artist
            if title:
                audio["title"] = title
            if album:
                audio["album"] = album
            audio.save(str(audio_path), v2_version=3)
            return True
        except Exception as exc:
            print(f"[tags] MP3 tags failed: {exc}")
            return False

    if _suffix(audio_path) in MP4_EXTENSIONS:
        try:
            audio = MP4(str(audio_path))
            if audio.tags is None:
                audio.add_tags()
            if artist:
                audio.tags["\xa9ART"] = [artist]
            if title:
                audio.tags["\xa9nam"] = [title]
            if album:
                audio.tags["\xa9alb"] = [album]
            audio.save()
            return True
        except Exception as exc:
            print(f"[tags] M4A tags failed: {exc}")
            return False
    return False
