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

"""Фоновые воркеры: длинные операции, которые нельзя делать в главном потоке."""

import csv
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError
from PyQt5.QtCore import QObject, QThread, pyqtSignal

import db
import metadata
import somedl_integration
from cookies_store import find_cookies_file
from paths import MUSIC_DIR
from qt_diagnostics import note
from path_utils import (
    find_tool,
    normalize_track_path,
    safe_replace,
    subprocess_creationflags,
    subprocess_env,
    unique_path,
)
from ytdlp_support import (
    DOWNLOAD_MODE_MP3,
    current_download_mode,
)

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".webm", ".opus"}

MUSIC_FOLDER = MUSIC_DIR


def find_audio_files(folder):
    """Возвращает список путей ко всем аудиофайлам в папке (рекурсивно)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    # Чистим .jpg, оставшиеся от старых версий yt-dlp, до того как UI
    # увидит их как пользовательские sidecar.
    try:
        metadata.cleanup_ytdlp_thumbnails(folder)
    except Exception as exc:
        print(f"[cleanup] thumbnail scan failed {folder}: {exc}")
    return [
        str(p) for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    ]


def get_mean_volume(path):
    """Запускает ffmpeg volumedetect и парсит mean_volume в dB.
    Возвращает float или None."""
    exe = find_tool("ffmpeg")
    if exe is None:
        print("[loudness] ffmpeg not found")
        return None
    try:
        result = subprocess.run(
            [exe, "-hide_banner", "-i", path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            env=subprocess_env(),
            creationflags=subprocess_creationflags(),
        )
    except FileNotFoundError:
        print("[loudness] ffmpeg not found")
        return None
    except subprocess.TimeoutExpired:
        print(f"[loudness] ffmpeg timeout on {path}")
        return None

    m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
    if m:
        return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
#  ImportWorker — импорт файлов в ~/Music
# ---------------------------------------------------------------------------

class ImportWorker(QObject):
    """Копирует выбранные файлы в ~/Music, добавляет в БД, читает теги."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, int, int, list)
    #               added, already, name_taken, failed, conflicts
    error = pyqtSignal(str)

    def __init__(self, files, target_folder):
        super().__init__()
        self.setObjectName("import-files-worker")
        self.files = files
        self.target_folder = Path(target_folder)
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            self.finished.emit(0, 0, 0, 0, [])
            return

        total = len(self.files)
        name_taken = failed = 0
        conflicts = []
        pending = []

        for i, src in enumerate(self.files, 1):
            if self._stopped or QThread.currentThread().isInterruptionRequested():
                break
            try:
                status, target = self._copy_to_library(src)

                if status == "name_taken":
                    name_taken += 1
                    conflicts.append(Path(src).name)
                elif status == "failed":
                    failed += 1
                elif status in ("copied", "same_path"):
                    try:
                        md = metadata.read_metadata(target)
                    except Exception as e:
                        print(f"[import] metadata error with {target}: {e}")
                        md = {
                            "title": Path(target).stem,
                            "artist": "Unknown Artist",
                            "album": None,
                            "duration": 0,
                        }
                    pending.append((
                        target,
                        md["title"],
                        md["artist"],
                        md["album"],
                        md["duration"],
                    ))
            except Exception as e:
                failed += 1
                print(f"[import] error with {src}: {e}")

            if i % 5 == 0 or i == total:
                self.progress.emit(i, total)

        added = already = 0
        if pending:
            try:
                added, already = db.add_tracks_with_metadata(pending)
            except Exception as e:
                failed += len(pending)
                print(f"[import] batch DB insert failed: {e}")

        self.finished.emit(added, already, name_taken, failed, conflicts)

    def _copy_to_library(self, src):
        src = Path(src)
        target = self.target_folder / src.name

        try:
            if src.resolve() == target.resolve():
                return ("same_path", str(target))
        except Exception:
            pass

        if target.exists():
            return ("name_taken", str(target))

        try:
            shutil.copy2(str(src), str(target))
        except Exception as e:
            print(f"[import] copy failed {src}: {e}")
            return ("failed", None)

        return ("copied", str(target))


# ---------------------------------------------------------------------------
#  RescanWorker — обновить метаданные + добить loudness у треков без неё
# ---------------------------------------------------------------------------

class RescanWorker(QObject):
    """Перечитывает метаданные + измеряет громкость у треков без loudness."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, int)
    #               metadata_updated, loudness_processed, loudness_failed

    def __init__(self):
        super().__init__()
        self.setObjectName("rescan-worker")
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _interrupted(self):
        return (
            self._stopped
            or QThread.currentThread().isInterruptionRequested()
        )

    def _reset_cover_cache(self, track_id):
        """Сбрасывает старую обложку, чтобы UI прочитал новую из тегов."""
        for name in (f"{track_id}.jpg", f"{track_id}.cover.json"):
            try:
                path = metadata.COVERS_DIR / name
                if path.exists():
                    path.unlink()
            except OSError as exc:
                print(f"[rescan] cover cache reset failed {name}: {exc}")
        try:
            db.update_track_cover(track_id, None)
        except Exception as exc:
            print(f"[rescan] cover DB reset failed {track_id}: {exc}")

    def run(self):
        # SomeDL Import обновляет теги и встроенные обложки на месте,
        # не перекачивая аудио. Выполняем один раз на всю библиотеку.
        if db.get_all_tracks() and not self._interrupted():
            try:
                note("rescan: somedl import start")
                somedl_integration.update_library_metadata(
                    MUSIC_FOLDER, cancel_check=self._interrupted
                )
                note("rescan: somedl import finished")
            except somedl_integration.SomedlCancelled:
                return
            except Exception as exc:
                print(f"[rescan] somedl import failed: {exc}")

        # Шаг 1: метаданные (быстро)
        meta_rows = db.get_all_tracks()
        meta_total = len(meta_rows)
        note(f"rescan start: {meta_total} tracks")
        for row in meta_rows:
            if self._interrupted():
                break
            try:
                path = row["file_path"]
                # Старые yt-dlp-превью удаляем до чтения обложки. SomeDL
                # не создаёт .jpg рядом с музыкой, а пользовательские
                # sidecar'ы этот метод не трогает.
                try:
                    metadata.cleanup_ytdlp_thumbnail(path)
                except Exception as exc:
                    print(f"[rescan] thumbnail cleanup failed {path}: {exc}")

                current = metadata.read_metadata(path)
                artist = str(current["artist"] or "Unknown Artist")
                clean_title = str(current["title"] or Path(path).stem)

                # При необходимости переименовываем файл по свежим тегам.
                new_path = path
                if artist != "Unknown Artist" and clean_title:
                    ext = Path(path).suffix or ".mp3"
                    safe_name = re.sub(
                        r'[\\/:*?"<>|]', "_", f"{artist} - {clean_title}"
                    ).strip()
                    candidate = str(Path(path).with_name(safe_name + ext))
                    if candidate != path:
                        # os.rename молча перезаписывает файл на Linux,
                        # поэтому сначала подбираем свободное имя. Проверяем
                        # и диск, и БД: иначе UPDATE упрётся в UNIQUE.
                        candidate = unique_path(
                            candidate,
                            current_path=path,
                            is_taken=lambda value: (
                                db.get_track_by_path(value) is not None
                            ),
                        )
                        # Плеер уже освобождён в главном потоке перед
                        # запуском воркера (ImportFlow.rescan), поэтому
                        # переименование безопасно и не трогает libVLC.
                        try:
                            os.rename(path, candidate)
                        except Exception as e:
                            print(f"[rescan] rename failed {path}: {e}")
                            new_path = path
                        else:
                            new_path = candidate
                            try:
                                metadata.rename_sidecar_image(path, candidate)
                            except Exception as e:
                                print(f"[rescan] sidecar rename failed: {e}")

                if new_path != path:
                    db.update_track_path(row["id"], new_path)

                # SomeDL только что вшил новую обложку. Старый кэш мог
                # содержать YouTube-превью или .webp, поэтому его сбрасываем.
                self._reset_cover_cache(row["id"])

                md = metadata.read_metadata(new_path)
                db.update_track_metadata(
                    row["id"],
                    title=md["title"],
                    artist=md["artist"],
                    album=md["album"],
                    duration=md["duration"],
                )
            except Exception as e:
                print(f"[rescan] failed {row['file_path']}: {e}")

        if self._interrupted():
            self.progress.emit(1, 1)
            self.finished.emit(0, 0, 0)
            return

        # Шаг 2: громкость для треков без loudness
        loud_rows = db.get_tracks_without_loudness()
        loud_total = len(loud_rows)
        processed = failed = 0

        grand_total = meta_total + loud_total

        if grand_total == 0:
            self.progress.emit(1, 1)
            self.finished.emit(0, 0, 0)
            return

        # Прогресс после первой фазы
        self.progress.emit(meta_total, grand_total)

        for i, row in enumerate(loud_rows, 1):
            if self._interrupted():
                break
            try:
                loudness = get_mean_volume(row["file_path"])
                if loudness is not None:
                    db.update_track_loudness(row["id"], loudness)
                    processed += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"[loudness] error with {row['file_path']}: {e}")

            if i % 2 == 0 or i == loud_total:
                self.progress.emit(meta_total + i, grand_total)

        note(
            f"rescan finished: meta={meta_total} "
            f"loudness={processed} failed={failed}"
        )
        self.finished.emit(meta_total, processed, failed)


# ---------------------------------------------------------------------------
#  FolderScanWorker — точечный авто-скан папок после File Watcher
# ---------------------------------------------------------------------------

class FolderScanWorker(QObject):
    """Добавляет в БД аудиофайлы из конкретных папок/файлов.

    В отличие от ``RescanWorker`` не перечитывает всю библиотеку и не
    переименовывает файлы: только находит новые треки, читает их теги и
    пакетно вставляет в SQLite. Уже известные пути пропускаются, поэтому
    повторный вызов после лишнего события watcher'а почти ничего не стоит.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, list)
    #               added, failed, added_paths

    def __init__(self, folders=(), files=()):
        super().__init__()
        self.setObjectName("folder-scan-worker")
        self.folders = [str(path) for path in folders]
        self.files = [str(path) for path in files]
        self._stopped = False

    def stop(self):
        self._stopped = True

    def _interrupted(self):
        return (
            self._stopped
            or QThread.currentThread().isInterruptionRequested()
        )

    def _collect_audio_files(self):
        found = {}

        for raw in self.files:
            path = Path(raw)
            if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
                found[normalize_track_path(path)] = str(path)

        for raw in self.folders:
            for path in find_audio_files(raw):
                found[normalize_track_path(path)] = path

        return [found[key] for key in sorted(found, key=str.casefold)]

    def run(self):
        try:
            audio_files = self._collect_audio_files()
        except Exception as exc:
            print(f"[watch-scan] file collection failed: {exc}")
            self.finished.emit(0, 1, [])
            return

        total = len(audio_files)
        if total == 0:
            self.progress.emit(1, 1)
            self.finished.emit(0, 0, [])
            return

        # Один запрос вместо get_track_by_path() на каждый файл.
        existing = {
            normalize_track_path(row["file_path"])
            for row in db.get_all_tracks()
        }

        pending = []
        failed = 0
        for index, path in enumerate(audio_files, 1):
            if self._interrupted():
                break
            if normalize_track_path(path) in existing:
                continue
            try:
                md = metadata.read_metadata(path)
            except Exception as exc:
                failed += 1
                print(f"[watch-scan] metadata error with {path}: {exc}")
                md = {
                    "title": Path(path).stem,
                    "artist": "Unknown Artist",
                    "album": None,
                    "duration": 0,
                }
            pending.append((
                path,
                md["title"],
                md["artist"],
                md["album"],
                md["duration"],
            ))
            if index % 5 == 0 or index == total:
                self.progress.emit(index, total)

        added = 0
        if pending:
            try:
                added, _duplicates = db.add_tracks_with_metadata(pending)
            except Exception as exc:
                failed += len(pending)
                print(f"[watch-scan] batch DB insert failed: {exc}")
                self.finished.emit(0, failed, [])
                return

        added_paths = [entry[0] for entry in pending]
        self.progress.emit(total, total)
        self.finished.emit(added, failed, added_paths)


# ---------------------------------------------------------------------------
#  CsvImportWorker — импорт плейлиста Exportify (Spotify CSV)
# ---------------------------------------------------------------------------

class CsvImportWorker(QObject):
    """Читает CSV из Exportify, скачивает треки с YouTube и вшивает теги/обложки.

    CSV должен содержать колонки «Track Name» и «Artist Name(s)».
    """

    progress = pyqtSignal(int, int)   # обработано, всего
    finished = pyqtSignal(int, int)   # успешно, ошибок
    error = pyqtSignal(str)

    def __init__(self, csv_path, target_folder=MUSIC_FOLDER):
        super().__init__()
        self.setObjectName("import-csv-worker")
        self.csv_path = Path(csv_path)
        self.target_folder = Path(target_folder)
        self._stopped = False

    # ------------------------------------------------------------------
    #  Основной поток
    # ------------------------------------------------------------------
    def run(self):
        try:
            rows = self._read_rows()
        except Exception as e:
            self.error.emit(f"Не могу прочитать CSV {self.csv_path}: {e}")
            self.finished.emit(0, 0)
            return

        if not rows:
            self.progress.emit(1, 1)
            self.finished.emit(0, 0)
            return

        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            self.finished.emit(0, 0)
            return

        # Проверяем SomeDL один раз, чтобы не повторять одну и ту же
        # ошибку для каждой строки CSV.
        if not somedl_integration.somedl_available():
            self.error.emit(
                "SomeDL не установлен. Установите зависимость: pip install somedl"
            )
            self.finished.emit(0, 0)
            return

        total = len(rows)
        added = failed = 0

        for i, (artist, track_name) in enumerate(rows, 1):
            if self._stopped or QThread.currentThread().isInterruptionRequested():
                break

            try:
                path = self._import_track(artist, track_name)
                if path:
                    added += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f"[csv-import] {artist} - {track_name}: {e}")

            self.progress.emit(i, total)

        self.finished.emit(added, failed)

    def _import_track(self, artist, track_name):
        """Скачивает трек через SomeDL и добавляет его в БД.

        SomeDL сам скачивает аудио с YouTube, подтягивает метаданные и
        вшивает обложку 544x544. Нам остаётся только добавить готовый файл
        в библиотеку.
        """
        try:
            final_path = somedl_integration.download_track(
                f"{artist} - {track_name}",
                self.target_folder,
                audio_format=(
                    "mp3"
                    if current_download_mode() == DOWNLOAD_MODE_MP3
                    else "best"
                ),
                cookies_path=find_cookies_file(self.target_folder),
                cancel_check=lambda: self._stopped,
            )
        except somedl_integration.SomedlCancelled:
            return None
        if self._stopped:
            return None

        track_id = db.add_track(final_path)
        if track_id is not None:
            try:
                md = metadata.read_metadata(final_path)
                db.update_track_metadata(
                    track_id,
                    title=md["title"] or track_name,
                    artist=md["artist"] or artist,
                    album=md["album"],
                    duration=md["duration"],
                )
            except Exception as e:
                print(f"[csv-import] Не удалось обновить метаданные в БД: {e}")
        return final_path

    # ------------------------------------------------------------------
    #  CSV
    # ------------------------------------------------------------------
    def _read_rows(self):
        """Возвращает список пар (artist, track_name) из CSV."""
        rows = []
        with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            # Ищем колонки без учёта регистра/пробелов
            keys = {name.strip().lower(): name for name in fields if name}
            track_key = keys.get("track name")
            artist_key = keys.get("artist name(s)") or keys.get("artist name")
            if not track_key or not artist_key:
                raise ValueError(
                    "нет колонок 'Track Name' и 'Artist Name(s)'"
                )

            for raw in reader:
                track_name = (raw.get(track_key) or "").strip()
                artist = (raw.get(artist_key) or "").strip()
                if track_name and artist:
                    rows.append((artist, track_name))
        return rows

    # ------------------------------------------------------------------
    #  Остановка
    # ------------------------------------------------------------------
    def stop(self):
        """Просит SomeDL завершить текущее скачивание."""
        self._stopped = True


# ---------------------------------------------------------------------------
#  TrimWorker — интерактивная обрезка выбранного фрагмента
# ---------------------------------------------------------------------------

class TrimWorker(QObject):
    """CHANGED: обрезает файл по маркерам и атомарно заменяет оригинал.

    pydub.export пересоздаёт контейнер и теряет ID3/APIC и теги других
    форматов, поэтому перед ``os.replace`` они переносятся через mutagen.
    """

    progress = pyqtSignal(int)        # 0..100
    finished = pyqtSignal(float)      # новая длительность, сек
    error = pyqtSignal(str)
    cancelled = pyqtSignal()
    warning = pyqtSignal(str)

    _FORMATS = {
        ".mp3": "mp3",
        ".flac": "flac",
        ".ogg": "ogg",
        ".m4a": "mp4",
        ".webm": "webm",
        ".opus": "opus",
        ".wav": "wav",
    }

    def __init__(self, file_path, start_ms, end_ms):
        super().__init__()
        self.setObjectName("trim-audio-worker")
        self.file_path = file_path
        self.start_ms = int(start_ms)
        self.end_ms = int(end_ms)

    def _interrupted(self):
        thread = QThread.currentThread()
        return thread is not None and thread.isInterruptionRequested()

    @staticmethod
    def _remove_temp(path):
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass

    @staticmethod
    def _copy_tags(src, dst):
        """Переносит теги и обложку. True — успех, False — ошибка, None — тегов нет."""
        ext = Path(src).suffix.lower()

        try:
            if ext == ".mp3":
                try:
                    tags = ID3(src)
                except ID3NoHeaderError:
                    return None
                tags.save(dst, v2_version=3)
                return True

            from mutagen import File as MutagenFile
            from mutagen.flac import FLAC

            old = MutagenFile(src)
            if old is None:
                return None

            old_pictures = (
                list(old.pictures)
                if isinstance(old, FLAC) and getattr(old, "pictures", None)
                else []
            )
            if not old.tags and not old_pictures:
                return None

            new = MutagenFile(dst)
            if new is None:
                return False

            if old.tags:
                if new.tags is None:
                    try:
                        new.add_tags()
                    except Exception:
                        pass
                if new.tags is None:
                    return False
                new.tags.update(old.tags)

            if isinstance(old, FLAC) and isinstance(new, FLAC):
                new.clear_pictures()
                for picture in old_pictures:
                    new.add_picture(picture)

            new.save()
            return True
        except Exception as e:
            print(f"[trim] tag copy failed: {e}")
            return False

    def run(self):
        # Ленивый импорт: pydub — необязательная зависимость.
        try:
            from pydub import AudioSegment
        except ImportError:
            self.error.emit(
                "pydub is not installed. Install it with: pip install pydub"
            )
            return

        if not os.path.isfile(self.file_path):
            self.error.emit(f"File not found: {self.file_path}")
            return

        ext = os.path.splitext(self.file_path)[1].lower()
        export_format = self._FORMATS.get(ext)
        if export_format is None:
            self.error.emit(f"Unsupported audio format: {ext}")
            return

        # WAV pydub умеет читать/писать без ffmpeg, остальные форматы — нет.
        if ext != ".wav" and find_tool("ffmpeg") is None:
            self.error.emit(
                "FFmpeg is not installed. Install it with your package "
                "manager (e.g. sudo apt install ffmpeg)."
            )
            return

        temp_path = None
        try:
            self.progress.emit(5)
            audio = AudioSegment.from_file(self.file_path)
            if self._interrupted():
                self.cancelled.emit()
                return

            total = len(audio)
            if total <= 0:
                self.error.emit("Audio file is empty.")
                return

            start = max(0, min(self.start_ms, total))
            end = max(0, min(self.end_ms, total))
            if end <= start:
                self.error.emit("The selection is empty.")
                return

            # Файл не менялся — не перекодируем его зря.
            if start == 0 and end >= total:
                self.finished.emit(total / 1000.0)
                return

            self.progress.emit(35)
            trimmed = audio[start:end]
            self.progress.emit(60)

            if self._interrupted():
                self.cancelled.emit()
                return

            # Временный файл создаём рядом с оригиналом: os.replace должен
            # работать в пределах одной файловой системы.
            fd, temp_path = tempfile.mkstemp(
                prefix=".trim-",
                suffix=ext,
                dir=os.path.dirname(os.path.abspath(self.file_path)),
            )
            os.close(fd)

            trimmed.export(temp_path, format=export_format)
            self.progress.emit(80)

            if self._interrupted():
                self._remove_temp(temp_path)
                self.cancelled.emit()
                return

            tags_result = self._copy_tags(self.file_path, temp_path)
            if tags_result is False:
                self.warning.emit("Tags and cover could not be preserved.")

            self.progress.emit(95)

            if self._interrupted():
                self._remove_temp(temp_path)
                self.cancelled.emit()
                return

            # Сохраняем права доступа оригинала (mkstemp создаёт 0600).
            try:
                os.chmod(
                    temp_path,
                    stat.S_IMODE(os.stat(self.file_path).st_mode),
                )
            except OSError:
                pass

            safe_replace(temp_path, self.file_path)
            temp_path = None
            self.progress.emit(100)
            self.finished.emit(len(trimmed) / 1000.0)

        except Exception as e:
            self._remove_temp(temp_path)
            if self._interrupted():
                self.cancelled.emit()
            else:
                self.error.emit(str(e))
