"""Фоновый воркер: скачивание аудио с YouTube через yt-dlp (subprocess)."""

import json
import os
import re
import shutil
import subprocess
import requests
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtCore import QSettings

from metadata import clean_youtube_title

MUSIC_FOLDER = Path.home() / "Music"

# Пример строки: "[download]  45.3% of 3.42MiB at 1.20MiB/s ETA 00:02"
PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

# Группы в скобках: ( ... ) или [ ... ]
_BRACKET_RE = re.compile(r"[\\(\[]([^\\)\]]*)[\\)\]]")
# Мусорные ключевые слова внутри скобок (без учёта регистра)
_NOISE_KEYWORDS_RE = re.compile(
    r"official\s+(?:music\s+)?video|official\s+audio"
    r"|official|lyric|visuali[sz]er|\bm/?v\b|prod\b|explicit|audio",
    re.IGNORECASE,
)
# Небезопасные для файловой системы символы
_UNSAFE_FS_RE = re.compile(r'[\\/:*?"<>|]')

# ID видео в ссылках YouTube: ?v=ID, youtu.be/ID, /shorts/ID, /embed/ID
_VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/v/)([A-Za-z0-9_-]{11})"
)


def _find_cookies_file(extra_folder=None):
    """Ищет cookies.txt: сначала в настройках, затем в стандартных местах."""
    settings = QSettings("MusicPlayer", "MusicPlayer")
    cookies_path_str = settings.value("youtube_cookies", "")
    cookies_path = Path(cookies_path_str) if cookies_path_str else None
    if cookies_path and cookies_path.is_file():
        return cookies_path

    candidates = []
    if extra_folder is not None:
        candidates.append(Path(extra_folder) / "cookies.txt")
    candidates.append(MUSIC_FOLDER / "cookies.txt")
    candidates.append(Path(__file__).resolve().parent / "cookies.txt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class YoutubeWorker(QObject):
    """Качает аудио через yt-dlp. Живёт в отдельном QThread."""

    progress = pyqtSignal(int)      # 0..100
    finished = pyqtSignal(str)      # путь к скачанному mp3
    error = pyqtSignal(str)

    def __init__(self, query, target_folder=None):
        super().__init__()
        self.query = (query or "").strip()
        self.target_folder = Path(target_folder) if target_folder else MUSIC_FOLDER
        self._proc = None
        self._stopped = False

    def run(self):
        if not self.query:
            self.error.emit("Пустой запрос")
            return

        exe = shutil.which("yt-dlp")
        if exe is None:
            self.error.emit("yt-dlp не найден в PATH")
            return

        try:
            self.target_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Не могу создать папку {self.target_folder}: {e}")
            return

        source = (
            self.query
            if self._looks_like_url(self.query)
            else f"ytsearch1:{self.query}"
        )

        cookies_path = _find_cookies_file(self.target_folder)

        cmd = [
            exe,
            "--no-playlist",
            "--no-warnings",
            "--newline",
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "-o", str(self.target_folder / "%(title)s.%(ext)s"),
            "--print", "after_move:filepath",
        ]
        if cookies_path is not None:
            cmd += ["--cookies", str(cookies_path)]
        cmd.append(source)

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
                m = PROGRESS_RE.search(line)
                if m:
                    self.progress.emit(min(100, int(float(m.group(1)))))
                    continue
                if "Sign in to confirm you're not a bot" in line:
                    self.error.emit(
                        "YouTube требует авторизации. Пожалуйста, "
                        "скачайте файл cookies.txt (инструкция в README) "
                        "и положите его в папку с музыкой"
                    )
                    return
                if line and not line.startswith("[") and ".mp3" in line:
                    final_path = line.strip()
                last_lines.append(line)
                if len(last_lines) > 10:
                    last_lines.pop(0)
            self._proc.wait()
        except Exception as e:
            self.error.emit(str(e))
            return

        if self._stopped:
            return

        if self._proc.returncode != 0:
            error_text = "\n".join(last_lines)
            self.error.emit(f"yt-dlp error:\n{error_text}")
            return

        if not (final_path and Path(final_path).exists()):
            self.error.emit("Загрузка прошла, но не удалось определить путь к файлу")
            return

        # --- Вшиваем обложку из скачанного jpg файла ---
        base_path = os.path.splitext(final_path)[0]
        img_path = None
        for ext in (".jpg", ".webp", ".png"):
            if os.path.exists(base_path + ext):
                img_path = base_path + ext
                break

        if img_path:
            try:
                try:
                    audio = ID3(final_path)
                except ID3NoHeaderError:
                    audio = ID3()

                # Определяем mime по расширению
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
                print(f"[yt-dlp] Обложка вшита: {mime}")
            except Exception as e:
                print(f"[yt-dlp] Ошибка вшивания обложки: {e}")

        # --- ЧИСТИМ НАЗВАНИЕ И ВШИВАЕМ ТЕГИ ---
        raw_title = Path(final_path).stem
        artist, clean_title = clean_youtube_title(raw_title)

        if artist != "Unknown Artist":
            from mutagen.easyid3 import EasyID3
            try:
                audio = EasyID3(final_path)
            except Exception:
                audio = EasyID3()

            try:
                audio["artist"] = artist
                audio["title"] = clean_title
                audio.save(final_path, v2_version=3)
                print(f"[tags] Set Artist='{artist}', Title='{clean_title}'")
            except Exception as e:
                print(f"[tags] Cannot write tags: {e}")

            new_name = f"{artist} - {clean_title}.mp3"
            new_path = os.path.join(os.path.dirname(final_path), new_name)
            try:
                if final_path != new_path:
                    os.rename(final_path, new_path)
                    final_path = new_path
                    print(f"[rename] Renamed to {new_name}")
            except Exception as e:
                print(f"[rename] Failed to rename: {e}")

        self.progress.emit(100)
        self.finished.emit(final_path)

    def stop(self):
        """Прерывает запущенный yt-dlp (вызывается при закрытии окна)."""
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    @staticmethod
    def _looks_like_url(text):
        return text.startswith(("http://", "https://", "www."))


def _extract_video_id(value):
    """Достаёт ID видео из ссылки YouTube (или принимает готовый ID)."""
    if not value:
        return ""
    text = str(value).strip()
    match = _VIDEO_ID_RE.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return ""


def _pick_thumbnail(entry):
    """Выбирает превью ~320px шириной из списка thumbnails."""
    thumbs = entry.get("thumbnails")
    if not isinstance(thumbs, list):
        return ""

    best = None
    for thumb in thumbs:
        if not isinstance(thumb, dict) or not thumb.get("url"):
            continue
        if best is None:
            best = thumb
            continue
        width = thumb.get("width") or 0
        best_width = best.get("width") or 0
        if abs(width - 320) < abs(best_width - 320):
            best = thumb
    return best.get("url", "") if best else ""


def _entry_to_result(entry):
    """Преобразует запись yt-dlp в словарь результата поиска."""
    raw_url = entry.get("webpage_url") or entry.get("url") or ""
    video_id = _extract_video_id(raw_url) or _extract_video_id(entry.get("id"))
    if str(raw_url).startswith("http"):
        url = raw_url
    elif video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
    else:
        url = str(raw_url)

    try:
        duration = int(entry["duration"]) if entry.get("duration") is not None else 0
    except (TypeError, ValueError):
        duration = 0

    uploader = (
        entry.get("uploader")
        or entry.get("channel")
        or entry.get("uploader_id")
        or ""
    )

    thumbnail = entry.get("thumbnail") or _pick_thumbnail(entry)
    if not thumbnail and video_id:
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

    return {
        "id": url,
        "video_id": video_id,
        "title": entry.get("title") or "Unknown",
        "uploader": uploader,
        "duration": duration,
        "thumbnail": thumbnail or "",
    }


class YoutubeSearchWorker(QObject):
    """Ищет видео на YouTube через yt-dlp — без скачивания."""

    finished = pyqtSignal(list)     # список словарей с метаданными
    error = pyqtSignal(str)

    RESULT_LIMIT = 5

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = (query or "").strip()
        self._proc = None
        self._stopped = False

    def run(self):
        if not self.query:
            self.error.emit("Пустой запрос")
            return

        exe = shutil.which("yt-dlp")
        if exe is None:
            self.error.emit("yt-dlp не найден в PATH")
            return

        cmd = [
            exe,
            "--no-warnings",
            "--flat-playlist",
            "--dump-json",
            f"ytsearch{self.RESULT_LIMIT}:{self.query}",
        ]
        cookies_path = _find_cookies_file()
        if cookies_path is not None:
            cmd += ["--cookies", str(cookies_path)]

        results = []
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
                line = line.strip()
                if not line:
                    continue
                if not line.startswith("{"):
                    last_lines.append(line)
                    if len(last_lines) > 10:
                        last_lines.pop(0)
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                results.append(_entry_to_result(entry))
            self._proc.wait()
        except Exception as e:
            self.error.emit(str(e))
            return

        if self._stopped:
            return

        if not results:
            if self._proc.returncode != 0:
                self.error.emit(
                    "yt-dlp error:\n" + "\n".join(last_lines)
                )
            else:
                self.error.emit("Ничего не найдено")
            return

        self.finished.emit(results)

    def stop(self):
        """Прерывает запущенный yt-dlp."""
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
