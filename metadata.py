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

"""Чтение метаданных аудиофайлов: теги через mutagen + fallback на имя файла."""

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture

from paths import CACHE_DIR
from path_utils import find_tool
import playback_trace

COVERS_DIR = CACHE_DIR / "covers"

# Расширения, которые считаются обложкой рядом с треком.
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Имена общих обложек папки (cover.jpg, folder.png, ...).
_FOLDER_COVER_STEMS = ("cover", "folder", "front", "albumart", "artwork")

# Старые версии OctoBeat включали у yt-dlp writethumbnail и
# FFmpegThumbnailsConvertor, из-за чего рядом с .webm оставался
# одноимённый .jpg. Такой файл нельзя считать пользовательским sidecar:
# он перебивает встроенную обложку. Отличаем его по совпадению имени и
# времени создания (с допуском на несколько секунд).
_YDLP_THUMBNAIL_AUDIO_EXTS = (".webm",)
_YDLP_THUMBNAIL_IMAGE_EXTS = (".jpg",)
_YDLP_THUMBNAIL_TIME_WINDOW = 10.0

# Кэш содержимого каталогов: ключ — путь, значение — (mtime каталога, индекс).
# Индекс строится один раз на каталог и сбрасывается, когда в папке
# появляется/исчезает файл (у каталога меняется mtime).
_sidecar_index_lock = threading.Lock()
_sidecar_index: dict[str, tuple[int, dict[str, str]]] = {}

_COVER_MARKER_VERSION = 1

# Ведущие мусорные группы в скобках: [MV], [Official Video], [VOCALOID RUS] ...
_PREFIX_BRACKETS_RE = re.compile(r"^(?:\[[^\]]*\]\s*)+")

# Ключевые слова-мусор внутри скобок
_NOISE_WORDS = (
    r"official|lyrics?|audio|video|visuali[sz]er|\bm/?v\b|prod\b|explicit"
)

# Замыкающие мусорные группы в скобках: (Official Video), [Lyrics], (Audio)
_NOISE_SUFFIX_RE = re.compile(
    r"(?:\s*[\(\[]\s*[^\)\]]*(?:" + _NOISE_WORDS + r")[^\)\]]*[\)\]])+\s*$",
    re.IGNORECASE,
)


def clean_youtube_title(raw_title):
    """Чистит название, полученное из YouTube, и выделяет (artist, clean_title).

    Убирает мусорные префиксы ([MV], [Official Video], ...) и суффиксы
    ((Official Video), [Lyrics], (Audio), ...), затем пробует разбить строку
    по разделителю. Если разделителя нет — artist будет "Unknown Artist"."""
    title = (raw_title or "").strip()

    # 1. Мусорные префиксы в начале строки
    title = _PREFIX_BRACKETS_RE.sub("", title)

    # 2. Мусорные суффиксы в конце строки
    title = _NOISE_SUFFIX_RE.sub("", title)
    title = title.strip()

    # 3. Разделители artist — title
    for sep in (" - ", " – ", " — ", " : ", ": "):
        if sep in title:
            artist, clean_title = title.split(sep, 1)
            artist = artist.strip()
            clean_title = clean_title.strip()
            if not artist or not clean_title:
                return "Unknown Artist", title
            return artist, clean_title

    # 4. Разделителя нет
    return "Unknown Artist", title


def _parse_filename(path):
    stem = Path(path).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()

    # Добавили двоеточие в список разделителей
    for sep in (" — ", " – ", " : ", ": "):
        if sep in stem:
            artist, title = stem.split(sep, 1)
            return title.strip(), artist.strip()

    return stem.strip(), None


# --- Длительность для контейнеров, которые mutagen не разбирает ----------
# mutagen не поддерживает WebM/Matroska, а у части M4A/MP4 в заголовке нет
# длительности (фрагментированные или недописанные файлы). Раньше такие
# треки попадали в библиотеку с duration=None и отображались как 0:00.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"   # EBML header: начало любого WebM/MKV
_EBML_SEGMENT = 0x18538067
_EBML_INFO = 0x1549A966
_EBML_TIMECODE_SCALE = 0x2AD7B1
_EBML_DURATION = 0x4489


def _read_ebml_vint(data, pos, keep_marker=False):
    """Читает EBML variable-length integer. Возвращает (value, next_pos).

    ``keep_marker=True`` сохраняет бит-маркер длины — так читаются ID
    элементов. Для размеров маркер отбрасывается; неизвестный размер
    (все биты единицы) возвращается как None.
    """
    if pos >= len(data):
        return None, pos
    first = data[pos]
    if first == 0:
        return None, pos + 1

    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8 or pos + length > len(data):
        return None, pos + 1

    value = first if keep_marker else (first & (mask - 1))
    for offset in range(1, length):
        value = (value << 8) | data[pos + offset]

    if not keep_marker and value == (1 << (7 * length)) - 1:
        return None, pos + length
    return value, pos + length


def _parse_webm_info(blob):
    """Достаёт Duration из EBML-элемента Info (значение в тиках)."""
    timecode_scale = 1_000_000  # наносекунды на тик (по умолчанию 1 мс)
    duration = None
    pos = 0
    while pos < len(blob):
        element_id, next_pos = _read_ebml_vint(blob, pos, keep_marker=True)
        if element_id is None:
            break
        size, data_pos = _read_ebml_vint(blob, next_pos)
        if size is None or data_pos + size > len(blob):
            break
        payload = blob[data_pos:data_pos + size]
        if element_id == _EBML_TIMECODE_SCALE and payload:
            timecode_scale = int.from_bytes(payload, "big")
        elif element_id == _EBML_DURATION:
            if len(payload) == 4:
                duration = struct.unpack(">f", payload)[0]
            elif len(payload) == 8:
                duration = struct.unpack(">d", payload)[0]
        pos = data_pos + size

    if duration is None or duration <= 0:
        return None
    return duration * timecode_scale / 1_000_000_000


def _webm_duration(path):
    """Читает длительность WebM напрямую из EBML, без ffprobe.

    Ищем EBML-заголовок не строго в начале: некоторые скачанные файлы
    имеют ведущий ID3-тег, из-за которого и mutagen, и ffprobe ошибаются.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(4 * 1024 * 1024)
    except OSError:
        return None

    start = data.find(_EBML_MAGIC)
    if start < 0:
        return None

    # Сначала пропускаем сам EBML-заголовок (DocType и версии), затем
    # читаем Segment. Его размер может быть неизвестным (потоковая запись).
    header_size, pos = _read_ebml_vint(data, start + len(_EBML_MAGIC))
    if header_size is None:
        return None
    pos += header_size

    segment_id, next_pos = _read_ebml_vint(data, pos, keep_marker=True)
    if segment_id != _EBML_SEGMENT:
        return None
    segment_size, pos = _read_ebml_vint(data, next_pos)
    end = len(data) if segment_size is None else min(
        len(data), pos + segment_size
    )

    while pos < end:
        element_id, next_pos = _read_ebml_vint(data, pos, keep_marker=True)
        if element_id is None:
            break
        size, data_pos = _read_ebml_vint(data, next_pos)
        if size is None:
            if element_id == _EBML_INFO:
                return _parse_webm_info(data[data_pos:end])
            break
        data_end = data_pos + size
        if element_id == _EBML_INFO:
            return _parse_webm_info(data[data_pos:min(data_end, len(data))])
        if data_end <= pos:
            break
        pos = data_end
    return None


def _ffprobe_duration(path):
    """Fallback через ffprobe для M4A/MP4 и других контейнеров."""
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration:stream=duration",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None

    try:
        payload = json.loads(proc.stdout)
    except (TypeError, ValueError):
        return None

    candidates = []
    fmt_duration = (payload.get("format") or {}).get("duration")
    if fmt_duration is not None:
        candidates.append(fmt_duration)
    for stream in payload.get("streams") or []:
        stream_duration = stream.get("duration")
        if stream_duration is not None:
            candidates.append(stream_duration)

    longest = 0.0
    for value in candidates:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > longest:
            longest = seconds
    return longest or None


def _fallback_duration(path):
    """Длительность, когда mutagen вернул None/0."""
    suffix = Path(path).suffix.lower()
    if suffix == ".webm":
        # Сначала дешёвый разбор EBML — он же спасает WebM с ID3-префиксом.
        duration = _webm_duration(path)
        if duration:
            return duration
    return _ffprobe_duration(path)


def read_metadata(path):
    """Возвращает dict {title, artist, album, duration}.
    Всё, что не удалось достать — None. duration — целые секунды."""
    result: dict[str, str | int | None] = {
        "title": None, "artist": None, "album": None, "duration": None,
    }
    # 1. Пробуем теги
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            if audio.tags:
                title = audio.get("title")
                artist = audio.get("artist")
                album = audio.get("album")
                if title:
                    result["title"] = title[0]
                if artist:
                    result["artist"] = artist[0]
                if album:
                    result["album"] = album[0]
            if audio.info and audio.info.length and audio.info.length > 0:
                result["duration"] = int(audio.info.length)
    except Exception as e:
        print(f"[metadata] tag read failed for {path}: {e}")

    # 1b. Контейнеры без поддержки в mutagen (WebM) и битые M4A/MP4.
    if not result["duration"]:
        try:
            fallback = _fallback_duration(path)
        except Exception as e:
            print(f"[metadata] duration fallback failed for {path}: {e}")
            fallback = None
        if fallback and fallback > 0:
            result["duration"] = int(fallback)

    # 2. Fallback — имя файла для title/artist
    if not result["title"] or not result["artist"]:
        fname_title, fname_artist = _parse_filename(path)
        if not result["title"]:
            result["title"] = fname_title
        if not result["artist"]:
            result["artist"] = fname_artist

    return result


def _folder_image_index(folder):
    """Возвращает {имя без расширения в нижнем регистре: путь} для картинок.

    Каталог сканируется один раз; при добавлении/удалении файла mtime
    каталога меняется и индекс перестраивается. Это позволяет замечать
    sidecar-обложку, появившуюся уже после создания кэша.
    """
    folder_key = os.path.abspath(str(folder))
    try:
        folder_mtime = os.stat(folder_key).st_mtime_ns
    except OSError:
        return {}

    with _sidecar_index_lock:
        cached = _sidecar_index.get(folder_key)
        if cached is not None and cached[0] == folder_mtime:
            return cached[1]

    index: dict[str, str] = {}
    try:
        with os.scandir(folder_key) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                stem, ext = os.path.splitext(entry.name)
                if ext.casefold() not in _IMAGE_EXTS:
                    continue
                index.setdefault(stem.casefold(), entry.path)
    except OSError:
        return {}

    with _sidecar_index_lock:
        _sidecar_index[folder_key] = (folder_mtime, index)
    return index


def find_sidecar_image(file_path, include_folder_cover=True, exclude=()):
    """Ищет картинку рядом с треком.

    Порядок:
    1. ``<имя трека>.jpg/.jpeg/.png/.webp`` (и ``<файл>.mp3.jpg``);
    2. общая обложка папки — ``cover.*``, ``folder.*``, ``front.*``.

    Сравнение имён регистронезависимое. ``exclude`` — пути, которые нужно
    игнорировать (например, превью, только что скачанное yt-dlp).
    Возвращает путь или None.
    """
    if not file_path:
        return None

    excluded = {
        os.path.abspath(str(path))
        for path in (exclude or ())
        if path
    }

    path = Path(file_path)
    index = _folder_image_index(path.parent)
    if not index:
        return None

    def _allowed(candidate):
        return os.path.abspath(candidate) not in excluded

    for key in (path.stem.casefold(), path.name.casefold()):
        found = index.get(key)
        if found and _allowed(found):
            return found

    if include_folder_cover:
        for stem in _FOLDER_COVER_STEMS:
            found = index.get(stem)
            if found and _allowed(found):
                return found
    return None


def _forget_sidecar_index(folder):
    """Сбрасывает кэш картинок папки после удаления/переименования файла."""
    key = os.path.abspath(str(folder))
    with _sidecar_index_lock:
        _sidecar_index.pop(key, None)


def _timestamps_close(first, second, window=_YDLP_THUMBNAIL_TIME_WINDOW):
    """Сравнивает mtime и время создания двух файлов с допуском."""
    pairs = [(first.st_mtime, second.st_mtime)]

    first_birth = getattr(first, "st_birthtime", None)
    second_birth = getattr(second, "st_birthtime", None)
    if first_birth is not None and second_birth is not None:
        pairs.append((first_birth, second_birth))
    else:
        # На Linux без birthtime st_ctime ближе всего к «времени создания»
        # для только что скачанных файлов.
        pairs.append((first.st_ctime, second.st_ctime))

    return all(abs(left - right) <= window for left, right in pairs)


def is_ytdlp_thumbnail(audio_path, image_path):
    """True, если ``image_path`` — старое превью yt-dlp рядом с аудио.

    Признаки: аудио имеет расширение, для которого OctoBeat раньше не
    вшивал обложку (``.webm``), картинка — одноимённый ``.jpg``, а mtime и
    время создания файлов отличаются не больше чем на несколько секунд.
    Пользовательская обложка, добавленная позже, под это правило не
    попадает.
    """
    try:
        audio = Path(audio_path)
        image = Path(image_path)
    except (TypeError, ValueError):
        return False

    if audio.suffix.casefold() not in _YDLP_THUMBNAIL_AUDIO_EXTS:
        return False
    if image.suffix.casefold() not in _YDLP_THUMBNAIL_IMAGE_EXTS:
        return False
    if audio.stem.casefold() != image.stem.casefold():
        return False

    try:
        audio_stat = audio.stat()
        image_stat = image.stat()
    except OSError:
        return False

    return _timestamps_close(audio_stat, image_stat)


def find_ytdlp_thumbnail(audio_path):
    """Возвращает путь к старому превью yt-dlp рядом с треком или None."""
    try:
        audio = Path(audio_path)
    except (TypeError, ValueError):
        return None
    if audio.suffix.casefold() not in _YDLP_THUMBNAIL_AUDIO_EXTS:
        return None

    try:
        entries = list(os.scandir(str(audio.parent)))
    except OSError:
        return None

    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue

        stem, ext = os.path.splitext(entry.name)
        if ext.casefold() not in _YDLP_THUMBNAIL_IMAGE_EXTS:
            continue
        if stem.casefold() != audio.stem.casefold():
            continue
        candidate = Path(entry.path)
        if is_ytdlp_thumbnail(audio, candidate):
            return str(candidate)
    return None


def cleanup_ytdlp_thumbnail(audio_path):
    """Удаляет старое превью yt-dlp рядом с одним аудиофайлом.

    Возвращает путь удалённого файла или None. Пользовательские sidecar'ы,
    добавленные после скачивания, не трогаем (см. ``is_ytdlp_thumbnail``).
    """
    thumbnail = find_ytdlp_thumbnail(audio_path)
    if not thumbnail:
        return None
    try:
        os.remove(thumbnail)
    except OSError as exc:
        print(f"[cleanup] cannot remove yt-dlp thumbnail {thumbnail}: {exc}")
        return None

    _forget_sidecar_index(Path(audio_path).parent)
    print(f"[cleanup] removed yt-dlp thumbnail: {thumbnail}")
    return thumbnail


def cleanup_ytdlp_thumbnails(folder):
    """Удаляет старые превью yt-dlp во всей папке (рекурсивно).

    Вызывается при сканировании библиотеки, чтобы .jpg, оставшиеся от
    прошлых версий, больше не выигрывали у встроенной обложки. Возвращает
    список удалённых путей.
    """
    root = Path(folder)
    if not root.is_dir():
        return []

    removed = []
    for dirpath, _dirnames, filenames in os.walk(str(root)):
        for name in filenames:
            stem, ext = os.path.splitext(name)
            if ext.casefold() not in _YDLP_THUMBNAIL_AUDIO_EXTS:
                continue
            path = Path(dirpath) / name
            deleted = cleanup_ytdlp_thumbnail(path)
            if deleted:
                removed.append(deleted)
    return removed


def rename_sidecar_image(old_path, new_path):
    """Переносит sidecar-картинки вслед за переименованным аудиофайлом.

    Учитываются только картинки, привязанные к конкретному треку:
    ``<старое имя>.jpg`` и ``<старый файл>.mp3.jpg``. Общие обложки папки
    (``cover.jpg``, ``folder.jpg`` и т.п.) остаются на месте.

    Расширение картинки сохраняется, существующий файл-приёмник не
    перезаписывается. Возвращает список пар ``(старый, новый)``.
    """
    if not old_path or not new_path:
        return []

    old = Path(old_path)
    new = Path(new_path)
    try:
        if os.path.abspath(str(old)) == os.path.abspath(str(new)):
            return []
    except OSError:
        return []

    # Sidecar-файлы лежат в той же папке, что и аудио. При переносе в
    # другую папку переносить их автоматически нельзя.
    if os.path.abspath(str(old.parent)) != os.path.abspath(str(new.parent)):
        return []
    if old.stem == new.stem:
        return []

    try:
        entries = list(os.scandir(str(old.parent)))
    except OSError:
        return []

    old_stem = old.stem.casefold()
    old_name = old.name.casefold()
    new_stem = new.stem
    new_name = new.name
    moved = []

    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue

        stem, ext = os.path.splitext(entry.name)
        if ext.casefold() not in _IMAGE_EXTS:
            continue

        key = stem.casefold()
        if key == old_stem:
            target_stem = new_stem
        elif key == old_name:
            target_stem = new_name
        else:
            continue

        target = old.parent / (target_stem + ext)
        if os.path.abspath(str(target)) == os.path.abspath(entry.path):
            continue
        if os.path.exists(str(target)):
            # Не перезаписываем чужую картинку — лучше оставить старую.
            continue

        try:
            os.rename(entry.path, str(target))
        except OSError as e:
            print(
                f"[metadata] sidecar rename failed "
                f"{entry.path} -> {target}: {e}"
            )
            continue
        moved.append((entry.path, str(target)))

    return moved


def read_embedded_cover(file_path):
    """Байты встроенной обложки (ID3 APIC / FLAC Picture / MP4 covr / Ogg)."""
    if not file_path or not os.path.isfile(file_path):
        return None

    try:
        audio = MutagenFile(file_path)
    except Exception as e:
        print(f"[metadata] cover read failed for {file_path}: {e}")
        return None

    if audio is None:
        return None

    try:
        # FLAC хранит обложку в отдельных блоках Picture, а не в тегах
        # Vorbis. Проверяем их до audio.tags: у «чистого» FLAC без
        # текстовых тегов audio.tags может быть None, но картинка при
        # этом присутствует.
        if isinstance(audio, FLAC):
            for picture in audio.pictures or []:
                if picture.data:
                    return picture.data

        if audio.tags is None:
            return None

        # MP3 (ID3)
        if hasattr(audio.tags, 'getall'):
            for tag in audio.tags.getall('APIC'):
                data = tag.data
                if data:
                    return data

        # MP4/M4A
        if 'covr' in audio.tags:
            covr = audio.tags.get('covr')
            if covr:
                data = bytes(covr[0])
                if data:
                    return data

        # Ogg Opus / Vorbis: обложка хранится в Vorbis-комментарии
        # METADATA_BLOCK_PICTURE (или COVERART в старых файлах) как
        # base64-строка FLAC Picture Block. Декодируем и извлекаем
        # только чистые байты картинки (без 47-байтового заголовка
        # структуры Picture), иначе Qt не сможет распарсить изображение.
        suffix = os.path.splitext(file_path)[1].lower()
        if suffix in (".opus", ".ogg"):
            for key in ("METADATA_BLOCK_PICTURE", "COVERART"):
                values = audio.tags.get(key)
                if not values:
                    continue
                try:
                    raw = base64.b64decode(values[0])
                except Exception:
                    continue
                if not raw:
                    continue
                # COVERART (старый тег Vorbis) хранит уже готовые
                # байты картинки, без заголовка FLAC Picture Block.
                if key == "COVERART":
                    return raw
                try:
                    picture = Picture(raw)
                except Exception:
                    continue
                if picture.data:
                    return picture.data
    except Exception as e:
        print(f"[metadata] cover tag read failed for {file_path}: {e}")

    return None


def find_local_cover(file_path, exclude=()):
    """Локальная обложка: sidecar первого приоритета, затем встроенная.

    Возвращает ``(путь_к_картинке, источник)`` или None. Для встроенной
    обложки путь равен None — она уже находится в файле.
    """
    sidecar = find_sidecar_image(file_path, exclude=exclude)
    if sidecar:
        return sidecar, "sidecar"
    if read_embedded_cover(file_path):
        return None, "embedded"
    return None


def _file_signature(path):
    """Сигнатура файла для проверки актуальности кэша обложки."""
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return {
        "path": str(path),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _read_cover_marker(marker_file):
    try:
        raw = json.loads(marker_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _write_cover_marker(marker_file, marker):
    tmp_file = marker_file.with_name(marker_file.name + ".tmp")
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file.write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_file, marker_file)
    except Exception as e:
        print(f"[metadata] cover marker write failed: {e}")
        try:
            tmp_file.unlink()
        except OSError:
            pass


def _cover_cache_is_valid(marker, sidecar_sig, audio_sig):
    """Проверяет, что закэшированная обложка соответствует текущим файлам."""
    if marker.get("version") != _COVER_MARKER_VERSION:
        return False
    if marker.get("sidecar") != sidecar_sig:
        return False
    source = marker.get("source")
    if source == "embedded":
        return marker.get("audio") == audio_sig
    return source == "sidecar"


def _save_cover_file(cover_file, data):
    """Атомарно пишет обложку: UI никогда не увидит недописанный файл."""
    tmp_file = ""
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_file = tempfile.mkstemp(
            prefix=f".{cover_file.stem}.",
            suffix=".tmp",
            dir=str(COVERS_DIR),
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_file, cover_file)
        return True
    except Exception as e:
        print(f"[metadata] cover save failed: {e}")
        if tmp_file:
            try:
                os.unlink(tmp_file)
            except OSError:
                pass
        return False


def _usable_cover_path(value):
    """Путь к картинке, которую UI действительно сможет показать."""
    if not value:
        return None
    try:
        from cover_provider import _displayable_cover_path

        return _displayable_cover_path(value)
    except Exception:
        try:
            path = Path(str(value))
        except (TypeError, ValueError):
            return None
        return str(path) if path.is_file() else None


def _stored_track_cover(track_id):
    """Обложка, привязанная к треку в SQLite (переживает перезапуск)."""
    if track_id is None:
        return None
    try:
        import db

        row = db.get_track_by_id(track_id)
    except Exception as e:
        print(f"[metadata] stored cover lookup failed: {e}")
        return None
    if not row:
        return None
    try:
        value = row["cover_path"]
    except (KeyError, IndexError, TypeError):
        return None
    return _usable_cover_path(value)


def extract_cover(file_path, track_id):
    """Возвращает путь к обложке трека, кэшируя её в COVERS_DIR.

    Приоритет (строго):
    1. sidecar-картинка рядом с аудиофайлом;
    2. встроенная обложка (ID3 APIC / MP4 ``covr``), которую вшил SomeDL;
    3. обложка, привязанная к треку в SQLite (для старых записей).

    Рядом с ``{track_id}.jpg`` хранится маркер ``{track_id}.cover.json``.
    Если в папке появилась sidecar-картинка, сигнатура в маркере перестаёт
    совпадать и обложка пересобирается — даже если старая уже была
    закэширована.
    """
    playback_trace.log("cover.extract.start", track=track_id, path=file_path)
    cover_file = COVERS_DIR / f"{track_id}.jpg"
    marker_file = COVERS_DIR / f"{track_id}.cover.json"

    sidecar = find_sidecar_image(file_path)
    sidecar_sig = _file_signature(sidecar)
    audio_sig = _file_signature(file_path)

    if cover_file.exists() and cover_file.stat().st_size > 0:
        marker = _read_cover_marker(marker_file)
        if marker is None:
            # Старый кэш без маркера. Если sidecar нет — оставляем как есть,
            # чтобы не перечитывать mutagen для всей библиотеки. Если sidecar
            # есть — старый кэш мог быть сделан из встроенной/онлайн-обложки,
            # поэтому пересобираем.
            if sidecar_sig is None:
                playback_trace.log("cover.extract.done", track=track_id, source="cache", path=cover_file)
                return str(cover_file)
        elif _cover_cache_is_valid(marker, sidecar_sig, audio_sig):
            playback_trace.log("cover.extract.done", track=track_id, source="cache", path=cover_file)
            return str(cover_file)
        else:
            playback_trace.log("cover.extract.stale", track=track_id, source=marker.get("source"))

    # Удалённый/перемещённый файл не должен доходить до mutagen: он
    # печатает ошибку на каждый вызов при перерисовке списка. None —
    # делегат нарисует placeholder без чтения с диска.
    if not file_path or not os.path.isfile(file_path):
        playback_trace.log("cover.extract.skip", track=track_id, reason="missing_path", path=file_path)
        return None

    # 1. Sidecar-картинка рядом с треком — наивысший приоритет.
    if sidecar:
        try:
            data = Path(sidecar).read_bytes()
        except OSError as e:
            print(f"[metadata] sidecar cover read failed for {sidecar}: {e}")
            data = None
        if data and _save_cover_file(cover_file, data):
            _write_cover_marker(marker_file, {
                "version": _COVER_MARKER_VERSION,
                "source": "sidecar",
                "sidecar": sidecar_sig,
                "audio": audio_sig,
            })
            playback_trace.log(
                "cover.extract.done", track=track_id, source="sidecar",
                bytes=len(data), path=cover_file,
            )
            return str(cover_file)

    # 2. Встроенная обложка.
    data = read_embedded_cover(file_path)
    if data and _save_cover_file(cover_file, data):
        _write_cover_marker(marker_file, {
            "version": _COVER_MARKER_VERSION,
            "source": "embedded",
            "sidecar": sidecar_sig,
            "audio": audio_sig,
        })
        playback_trace.log("cover.extract.done", track=track_id, source="embedded", bytes=len(data), path=cover_file)
        return str(cover_file)

    # 3. Обложка, привязанная к треку в SQLite. Нужна, когда запись
    # метаданных в кэше недоступна (истекла/перезаписана), но картинка
    # уже была скачана ранее. Без этого .webm снова показывал бы нотку
    # после перезапуска.
    cover = _stored_track_cover(track_id)
    playback_trace.log("cover.extract.done", track=track_id, source="db", path=cover)
    return cover



def format_track(track, fallback_path=None, with_duration=True):
    """Строка для отображения в списке: 'Artist — Title [m:ss]'.
    with_duration=False — убрать хвост с длительностью."""
    title = track["title"]
    artist = track["artist"]
    dur = track["duration"]

    if title and artist:
        display = f"{artist} — {title}"
    elif title:
        display = title
    elif fallback_path:
        display = Path(fallback_path).name
    else:
        display = "(unknown)"

    if dur and with_duration:
        m, s = divmod(dur, 60)
        display += f"  [{m}:{s:02d}]"

    return display
