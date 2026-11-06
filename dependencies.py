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

"""Внешние зависимости: поиск и авто-установка FFmpeg.

FFmpeg нужен SomeDL, yt-dlp и измерению громкости. Ищем его в двух местах:

1. локальная папка приложения ``<data>/bin`` (сюда же складывается
   автоматически скачанный статический бинарник);
2. системный ``PATH``.

Локальная папка важнее системной: если пользователь один раз согласился на
авто-установку, приложение продолжает использовать проверенную сборку даже
при наличии другой версии в системе.

Скачивание и распаковка выполняются в фоновом ``QThread``, поэтому
интерфейс не замирает даже на медленном соединении.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal

from paths import DATA_DIR
from path_utils import subprocess_creationflags
from qt_diagnostics import note, track_thread
from qt_lifecycle import retire_thread, widget_alive

# Сюда складываются скачанные бинарники. Путь совпадает с тем, что
# пользователь видит в диалоге: ~/.local/share/OctoBeat/bin,
# %APPDATA%\OctoBeat\bin или ~/Library/Application Support/OctoBeat/bin.
BIN_DIR = DATA_DIR / "bin"

TOOL_NAMES = ("ffmpeg", "ffprobe")

# Официальные статические сборки.
LINUX_RELEASE_URL = (
    "https://johnvansickle.com/ffmpeg/releases/"
    "ffmpeg-release-{arch}-static.tar.xz"
)
WINDOWS_RELEASE_URL = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

# Размер блока при скачивании: прогресс обновляется достаточно часто, но
# сигналы в GUI не летят на каждый килобайт.
_CHUNK_SIZE = 256 * 1024
_DOWNLOAD_TIMEOUT = 30


class DependencyError(RuntimeError):
    """Понятная пользователю ошибка установки зависимости."""


class DependencyCancelled(DependencyError):
    """Скачивание отменено (закрытие приложения или кнопка «Отмена»)."""


# ---------------------------------------------------------------------------
#  Поиск
# ---------------------------------------------------------------------------

def tool_filename(name):
    """Имя исполняемого файла для текущей платформы."""
    return f"{name}.exe" if sys.platform == "win32" else name


def local_tool_path(name):
    """Путь к бинарнику в локальной папке приложения, если он там есть."""
    path = BIN_DIR / tool_filename(name)
    return path if path.is_file() else None


def system_tool_path(name):
    """Путь к бинарнику в системном PATH (или None)."""
    return shutil.which(name)


def find_dependency(name):
    """Локальная копия приоритетнее системной."""
    local = local_tool_path(name)
    return str(local) if local is not None else system_tool_path(name)


def check_dependencies():
    """Возвращает состояние ffmpeg/ffprobe для главного потока.

    ``tools`` — найденные пути, ``missing`` — имена ненайденных,
    ``bin_dir`` — куда будет установлена локальная копия.
    """
    tools = {name: find_dependency(name) for name in TOOL_NAMES}
    missing = [name for name in TOOL_NAMES if not tools[name]]
    return {
        "tools": tools,
        "missing": missing,
        "bin_dir": str(BIN_DIR),
        "local": {
            name: bool(local_tool_path(name)) for name in TOOL_NAMES
        },
    }


def ffmpeg_location():
    """Папка для опции yt-dlp ``ffmpeg_location`` (только если есть локально)."""
    if any(local_tool_path(name) for name in TOOL_NAMES):
        return str(BIN_DIR)
    return None


def augment_environment(env):
    """Добавляет локальную папку bin в начало PATH процесса.

    Так SomeDL (и запускаемый им yt-dlp CLI) находит именно нашу сборку.
    """
    if not any(local_tool_path(name) for name in TOOL_NAMES):
        return env
    binary_dir = str(BIN_DIR)
    current = env.get("PATH", "")
    parts = [
        part for part in current.split(os.pathsep)
        if part and os.path.normcase(part) != os.path.normcase(binary_dir)
    ]
    env["PATH"] = os.pathsep.join([binary_dir, *parts])
    return env


# ---------------------------------------------------------------------------
#  Скачивание и установка
# ---------------------------------------------------------------------------

def release_url():
    """URL статической сборки FFmpeg для текущей платформы."""
    if sys.platform == "win32":
        return WINDOWS_RELEASE_URL
    if sys.platform == "darwin":
        raise DependencyError(
            "Automatic FFmpeg installation is not available on macOS. "
            "Install it with Homebrew: brew install ffmpeg"
        )

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine.startswith("armv7") or machine.startswith("armhf"):
        arch = "armhf"
    else:
        raise DependencyError(
            f"No static FFmpeg build is available for architecture "
            f"'{machine}'."
        )
    return LINUX_RELEASE_URL.format(arch=arch)


def _download_file(url, destination, progress=None, cancel_check=None):
    """Скачивает URL в файл, сообщая прогресс в байтах."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OctoBeat ffmpeg installer"},
    )
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as source:
        try:
            total = int(source.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        downloaded = 0
        with open(destination, "wb") as target:
            while True:
                if cancel_check is not None and cancel_check():
                    raise DependencyCancelled("Download cancelled")
                chunk = source.read(_CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
    return destination


def _safe_tar_members(archive, destination):
    root = Path(destination).resolve()
    for member in archive.getmembers():
        target = (root / member.name).resolve()
        if target != root and root not in target.parents:
            raise DependencyError(
                f"Archive contains an unsafe path: {member.name}"
            )
        yield member


def _extract_archive(archive_path, destination):
    """Распаковывает tar.xz/zip, отбрасывая небезопасные пути."""
    suffix = Path(archive_path).suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            root = Path(destination).resolve()
            for member in archive.infolist():
                target = (root / member.filename).resolve()
                if target != root and root not in target.parents:
                    raise DependencyError(
                        "Archive contains an unsafe path: "
                        f"{member.filename}"
                    )
            archive.extractall(destination)
        return

    with tarfile.open(archive_path, "r:*") as archive:
        members = list(_safe_tar_members(archive, destination))
        try:
            archive.extractall(destination, members=members, filter="data")
        except TypeError:
            # Python < 3.12 не знает параметр filter.
            archive.extractall(destination, members=members)


def _locate_tool(root, name):
    """Ищет исполняемый файл внутри распакованного архива."""
    filename = tool_filename(name)
    candidates = [
        path
        for path in Path(root).rglob(filename)
        if path.is_file() and path.stat().st_size > 0
    ]
    if not candidates:
        raise DependencyError(
            f"The downloaded archive does not contain {filename}."
        )
    # В архивах gyan.dev/johnvansickle бинарники лежат в подпапке bin/.
    candidates.sort(
        key=lambda path: (path.parent.name != "bin", len(path.parts))
    )
    return candidates[0]


def _install_binary(source, destination):
    """Атомарно копирует бинарник и выставляет права на запуск."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        if sys.platform != "win32":
            os.chmod(
                temporary,
                os.stat(temporary).st_mode | stat.S_IXUSR | stat.S_IXGRP
                | stat.S_IXOTH,
            )
        os.replace(temporary, destination)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _verify_tool(path):
    """Проверяет, что скачанный бинарник действительно запускается."""
    try:
        result = subprocess.run(
            [str(path), "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=subprocess_creationflags(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DependencyError(
            f"{Path(path).name} cannot be executed: {exc}"
        ) from exc
    if result.returncode != 0:
        raise DependencyError(
            f"{Path(path).name} exited with code {result.returncode}."
        )


def install_ffmpeg(progress=None, cancel_check=None):
    """Скачивает и устанавливает ffmpeg/ffprobe в ``BIN_DIR``.

    ``progress(downloaded, total)`` вызывается из рабочего потока.
    Возвращает результат ``check_dependencies()``.
    """
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    url = release_url()
    note(f"ffmpeg install: downloading {url}")

    workdir = Path(tempfile.mkdtemp(prefix="ffmpeg-", dir=str(DATA_DIR)))
    try:
        archive_name = "ffmpeg-archive" + (
            ".zip" if url.endswith(".zip") else ".tar.xz"
        )
        archive_path = workdir / archive_name
        _download_file(
            url,
            archive_path,
            progress=progress,
            cancel_check=cancel_check,
        )
        if cancel_check is not None and cancel_check():
            raise DependencyCancelled("Download cancelled")

        unpacked = workdir / "unpacked"
        unpacked.mkdir()
        _extract_archive(archive_path, unpacked)

        for name in TOOL_NAMES:
            source = _locate_tool(unpacked, name)
            destination = BIN_DIR / tool_filename(name)
            _install_binary(source, destination)
            _verify_tool(destination)
            note(f"ffmpeg install: installed {destination}")

        return check_dependencies()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  Фоновые воркеры
# ---------------------------------------------------------------------------

class DependencyCheckWorker(QObject):
    """Проверяет зависимости в фоне, чтобы не трогать главный поток."""

    finished = pyqtSignal(object)

    def run(self):
        try:
            result = check_dependencies()
        except Exception as exc:  # pragma: no cover - защитный путь
            print(f"[deps] dependency check failed: {exc}")
            result = {
                "tools": {},
                "missing": list(TOOL_NAMES),
                "bin_dir": str(BIN_DIR),
                "local": {},
            }
        self.finished.emit(result)


class DependencyDownloadWorker(QObject):
    """Скачивает/распаковывает FFmpeg и сообщает прогресс."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object, str)
    #               результат, текст ошибки

    def __init__(self):
        super().__init__()
        self.setObjectName("ffmpeg-download-worker")
        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def _cancelled_now(self):
        return (
            self._cancelled
            or QThread.currentThread().isInterruptionRequested()
        )

    def run(self):
        try:
            result = install_ffmpeg(
                progress=self.progress.emit,
                cancel_check=self._cancelled_now,
            )
        except DependencyCancelled:
            self.progress.emit(0, 0)
            self.finished.emit({}, "cancelled")
        except Exception as exc:
            print(f"[deps] ffmpeg install failed: {exc}")
            self.finished.emit({}, str(exc))
        else:
            self.finished.emit(result, "")


# ---------------------------------------------------------------------------
#  Менеджер: старт проверки и диалог
# ---------------------------------------------------------------------------

class DependencyManager(QObject):
    """Проверяет зависимости после старта и предлагает авто-установку."""

    def __init__(self, parent=None, check_delay_ms=1200):
        super().__init__(parent)
        self._check_delay = max(0, int(check_delay_ms))
        self._check_thread = None
        self._check_worker = None
        self._download_thread = None
        self._download_worker = None
        self._dialog = None
        self._prompted = False
        self._shutting_down = False

    # ------------------------------------------------------------------
    #  Проверка
    # ------------------------------------------------------------------
    def start(self):
        QTimer.singleShot(self._check_delay, self._run_check)

    def _run_check(self):
        if self._shutting_down or self._check_thread is not None:
            return
        worker = DependencyCheckWorker()
        thread = QThread(self)
        thread.setObjectName("ffmpeg-check")
        worker.moveToThread(thread)
        track_thread(thread, "ffmpeg-check")
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_check_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._check_thread = thread
        self._check_worker = worker
        thread.start()

    def _on_check_finished(self, result):
        self._check_thread = None
        self._check_worker = None
        if not isinstance(result, dict):
            return
        note(
            "ffmpeg check: "
            + ", ".join(
                f"{name}={path or 'missing'}"
                for name, path in (result.get("tools") or {}).items()
            )
        )
        if result.get("missing") and not self._prompted:
            self._show_dialog(result)

    # ------------------------------------------------------------------
    #  Диалог
    # ------------------------------------------------------------------
    def _show_dialog(self, result):
        if self._shutting_down:
            return
        self._prompted = True
        # Импорт внутри метода: dependencies.py используют и фоновые
        # модули, которым не нужен QtWidgets.
        from dependency_dialog import DependencyDialog

        dialog = DependencyDialog(
            self.parent(),
            result.get("missing") or list(TOOL_NAMES),
            result.get("bin_dir") or str(BIN_DIR),
        )
        dialog.download_requested.connect(self._start_download)
        dialog.finished.connect(self._on_dialog_closed)
        self._dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_dialog_closed(self, _result=None):
        dialog = self._dialog
        self._dialog = None
        if widget_alive(dialog):
            dialog.deleteLater()
        # Закрытие диалога во время скачивания отменяет загрузку.
        if self._download_worker is not None:
            self._stop_download()

    # ------------------------------------------------------------------
    #  Скачивание
    # ------------------------------------------------------------------
    def _start_download(self):
        if self._shutting_down or self._download_thread is not None:
            return
        dialog = self._dialog
        if widget_alive(dialog):
            dialog.set_downloading()

        worker = DependencyDownloadWorker()
        thread = QThread(self)
        thread.setObjectName("ffmpeg-download")
        worker.moveToThread(thread)
        track_thread(thread, "ffmpeg-download")
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)

        self._download_thread = thread
        self._download_worker = worker
        thread.start()

    def _on_download_progress(self, downloaded, total):
        dialog = self._dialog
        if widget_alive(dialog):
            dialog.set_progress(downloaded, total)

    def _on_download_finished(self, result, error):
        thread = self._download_thread
        self._download_thread = None
        self._download_worker = None
        if thread is not None:
            retire_thread(thread, 3000)

        dialog = self._dialog
        if not widget_alive(dialog):
            return
        if error == "cancelled":
            dialog.set_cancelled()
            return
        if error:
            dialog.set_error(error)
            return
        dialog.set_success((result or {}).get("tools") or {})
        if not self._shutting_down:
            self._after_install(result or {})

    def _after_install(self, result):
        """Локальная папка уже видна через PATH; пишем это в лог."""
        note(
            "ffmpeg install finished: "
            + ", ".join(
                f"{name}={path or 'missing'}"
                for name, path in (result.get("tools") or {}).items()
            )
        )

    def _stop_download(self):
        worker = self._download_worker
        thread = self._download_thread
        self._download_worker = None
        self._download_thread = None
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            retire_thread(thread, 2000)

    # ------------------------------------------------------------------
    #  Завершение приложения
    # ------------------------------------------------------------------
    def shutdown(self):
        self._shutting_down = True
        dialog = self._dialog
        self._dialog = None
        if widget_alive(dialog):
            try:
                dialog.close()
            except RuntimeError:
                pass
        self._stop_download()
        thread = self._check_thread
        self._check_thread = None
        self._check_worker = None
        if thread is not None:
            retire_thread(thread, 1500)
