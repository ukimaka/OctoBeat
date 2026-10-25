"""Фоновые воркеры: длинные операции, которые нельзя делать в главном потоке."""

import csv
import os
import re
import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError

import db
import metadata


AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".wav"}

MUSIC_FOLDER = Path.home() / "Music"

# Небезопасные для файловой системы символы (+ '%' — служебный в yt-dlp)
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|%\x00-\x1f]')


def find_audio_files(folder):
    """Возвращает список путей ко всем аудиофайлам в папке (рекурсивно)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [
        str(p) for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    ]


def get_mean_volume(path):
    """Запускает ffmpeg volumedetect и парсит mean_volume в dB.
    Возвращает float или None."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
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
        self.files = files
        self.target_folder = Path(target_folder)

    def run(self):
        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            self.finished.emit(0, 0, 0, 0, [])
            return

        total = len(self.files)
        added = already = name_taken = failed = 0
        conflicts = []

        for i, src in enumerate(self.files, 1):
            try:
                status, target = self._copy_to_library(src)

                if status == "name_taken":
                    name_taken += 1
                    conflicts.append(Path(src).name)
                elif status == "failed":
                    failed += 1
                elif status in ("copied", "same_path"):
                    track_id = db.add_track(target)
                    if track_id is None:
                        already += 1
                    else:
                        md = metadata.read_metadata(target)
                        db.update_track_metadata(
                            track_id,
                            title=md["title"],
                            artist=md["artist"],
                            album=md["album"],
                            duration=md["duration"],
                        )
                        added += 1
            except Exception as e:
                failed += 1
                print(f"[import] error with {src}: {e}")

            if i % 5 == 0 or i == total:
                self.progress.emit(i, total)

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

    def run(self):
        # Шаг 1: метаданные (быстро)
        meta_rows = db.get_all_tracks()
        meta_total = len(meta_rows)
        for row in meta_rows:
            try:
                path = row["file_path"]

                # Чистим название YouTube и при необходимости переименовываем файл
                artist, clean_title = metadata.clean_youtube_title(Path(path).stem)
                new_path = path
                if artist != "Unknown Artist" and clean_title:
                    ext = Path(path).suffix or ".mp3"
                    safe_name = re.sub(
                        r'[\\/:*?"<>|]', "_", f"{artist} - {clean_title}"
                    ).strip()
                    candidate = str(Path(path).with_name(safe_name + ext))
                    if candidate != path:
                        try:
                            os.rename(path, candidate)
                            new_path = candidate
                        except Exception as e:
                            print(f"[rescan] rename failed {path}: {e}")
                            new_path = path

                if new_path != path:
                    db.update_track_path(row["id"], new_path)

                # Записываем новые теги
                if artist != "Unknown Artist":
                    try:
                        try:
                            audio = EasyID3(new_path)
                        except Exception:
                            audio = EasyID3()
                        audio["artist"] = artist
                        audio["title"] = clean_title
                        audio.save(new_path, v2_version=3)
                    except Exception as e:
                        print(f"[rescan] tag write failed {new_path}: {e}")

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

        self.finished.emit(meta_total, processed, failed)


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
        self.csv_path = Path(csv_path)
        self.target_folder = Path(target_folder)
        self._proc = None
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
        """Скачивает один трек, вшивает обложку/теги и добавляет его в БД.

        Возвращает путь к файлу или None, если скачать не удалось.
        """
        output_base = self._unique_output_base(artist, track_name)
        final_path = self._download(artist, track_name, output_base)
        if not final_path:
            return None

        # --- Обложка: jpg рядом с mp3 -> APIC -> удалить jpg ---
        self._embed_cover(final_path)

        # --- Теги из CSV, чтобы в плеере были красивые artist/title ---
        self._write_tags(final_path, artist, track_name)

        # --- БД ---
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
    #  Скачивание
    # ------------------------------------------------------------------
    def _download(self, artist, track_name, output_base):
        exe = shutil.which("yt-dlp")
        if exe is None:
            raise RuntimeError("yt-dlp не найден в PATH")

        from youtube_worker import _find_cookies_file

        query = f"{artist} - {track_name}"
        cmd = [
            exe,
            "--no-playlist",
            "--no-warnings",
            "--newline",
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "-o", str(self.target_folder / (output_base + ".%(ext)s")),
            "--print", "after_move:filepath",
        ]
        cookies_path = _find_cookies_file(self.target_folder)
        if cookies_path is not None:
            cmd += ["--cookies", str(cookies_path)]
        cmd.append(f"ytsearch1:{query}")

        final_path = None
        last_lines = []
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in self._proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                if "Sign in to confirm you're not a bot" in line:
                    raise RuntimeError(
                        "YouTube требует авторизации (нужен cookies.txt)"
                    )
                if not line.startswith("[") and line.lower().endswith(".mp3"):
                    final_path = line.strip()
                    continue
                last_lines.append(line)
                if len(last_lines) > 10:
                    last_lines.pop(0)
            self._proc.wait()
        except Exception:
            self._terminate_proc()
            raise

        if self._stopped:
            return None

        if self._proc.returncode != 0:
            raise RuntimeError(
                "yt-dlp error: " + " | ".join(last_lines[-3:])
            )

        if not (final_path and Path(final_path).exists()):
            candidate = self.target_folder / (output_base + ".mp3")
            if candidate.exists():
                final_path = str(candidate)
            else:
                raise RuntimeError("не удалось определить путь к mp3")

        return final_path

    def _unique_output_base(self, artist, track_name):
        """Безопасное уникальное имя файла без расширения."""
        raw = f"{artist} - {track_name}"
        safe = _UNSAFE_FILENAME_RE.sub("_", raw)
        safe = re.sub(r"\s+", " ", safe).strip(" .")
        if not safe:
            safe = "track"
        # Ограничиваем по байтам, а не символам: длинные кириллические
        # названия иначе легко превышают лимит имени файла (255 байт).
        safe = safe.encode("utf-8")[:180].decode("utf-8", "ignore").strip(" .")
        if not safe:
            safe = "track"

        base = safe
        counter = 2
        while any(
            (self.target_folder / f"{base}{ext}").exists()
            for ext in (".mp3", ".jpg", ".webp", ".png", ".part")
        ):
            base = f"{safe} ({counter})"
            counter += 1
        return base

    def _terminate_proc(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------
    #  Обложка и теги
    # ------------------------------------------------------------------
    @staticmethod
    def _embed_cover(final_path):
        base_path = os.path.splitext(final_path)[0]
        img_path = None
        for ext in (".jpg", ".webp", ".png"):
            if os.path.exists(base_path + ext):
                img_path = base_path + ext
                break
        if not img_path:
            return

        try:
            try:
                audio = ID3(final_path)
            except ID3NoHeaderError:
                audio = ID3()

            if img_path.endswith(".jpg"):
                mime = "image/jpeg"
            elif img_path.endswith(".png"):
                mime = "image/png"
            else:
                mime = "image/webp"

            with open(img_path, "rb") as img:
                audio.add(APIC(
                    encoding=3,
                    mime=mime,
                    type=3,
                    desc="Cover",
                    data=img.read(),
                ))

            audio.save(final_path, v2_version=3)
            os.remove(img_path)
            print(f"[csv-import] Обложка вшита: {mime}")
        except Exception as e:
            print(f"[csv-import] Ошибка вшивания обложки: {e}")

    @staticmethod
    def _write_tags(final_path, artist, title):
        try:
            try:
                audio = EasyID3(final_path)
            except Exception:
                audio = EasyID3()

            audio["artist"] = artist
            audio["title"] = title
            audio.save(final_path, v2_version=3)
            print(f"[csv-import] Теги: Artist='{artist}', Title='{title}'")
        except Exception as e:
            print(f"[csv-import] Не удалось записать теги: {e}")

    # ------------------------------------------------------------------
    #  Остановка
    # ------------------------------------------------------------------
    def stop(self):
        """Прерывает текущее скачивание (при отмене прогресс-диалога)."""
        self._stopped = True
        self._terminate_proc()
