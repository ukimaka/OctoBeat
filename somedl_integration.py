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

"""Интеграция с SomeDL.

SomeDL скачивает аудио с YouTube и сам подтягивает метаданные и обложки из
YouTube Music, MusicBrainz, Genius и Deezer. Мы не дублируем этот пайплайн:
приложение вызывает CLI ``somedl`` и забирает готовый файл с уже вшитыми
тегами и обложкой (544x544). Для существующей библиотеки используется
``somedl import`` в режиме update — он обновляет теги на месте, не трогая
аудио и не создавая sidecar-картинок рядом с музыкой.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from paths import CACHE_DIR, DATA_DIR
from path_utils import (
    subprocess_creationflags,
    subprocess_env,
    unique_path,
)

# Форматы, которые умеет отдавать SomeDL.
AUDIO_FORMATS = {
    "best", "best/opus", "best/m4a", "opus", "m4a", "mp3", "vorbis", "flac",
}

# Форматы, которые SomeDL Import умеет обновлять на месте.
IMPORT_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".opus"}

_AUDIO_EXTS = IMPORT_EXTS | {".webm", ".wav"}

_STAGING_ROOT = CACHE_DIR / "somedl_staging"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Строка, которую ``somedl import`` печатает перед обработкой файла:
# ``--- File Nr. 12 ---...``. По ней считается реальный прогресс импорта.
_FILE_NR_RE = re.compile(r"File Nr\.\s*(\d+)", re.IGNORECASE)

_COMMAND: list[str] | None = None


class SomedlError(RuntimeError):
    """SomeDL завершился с ошибкой или не смог скачать трек."""


class SomedlNotFoundError(SomedlError):
    """CLI ``somedl`` не установлен или недоступен."""


class SomedlCancelled(SomedlError):
    """Операция отменена пользователем."""


# ---------------------------------------------------------------------------
#  Поиск CLI и изолированная конфигурация
# ---------------------------------------------------------------------------

def _find_command() -> list[str] | None:
    """Возвращает команду запуска SomeDL для текущего окружения."""
    global _COMMAND
    if _COMMAND is not None:
        return _COMMAND

    # В первую очередь — somedl из того же virtualenv, что и приложение.
    sibling = Path(sys.executable).with_name(
        "somedl.exe" if sys.platform == "win32" else "somedl"
    )
    if sibling.is_file():
        _COMMAND = [str(sibling)]
        return _COMMAND

    executable = shutil.which("somedl")
    if executable:
        _COMMAND = [executable]
        return _COMMAND

    # Frozen-сборка: отдельного python.exe нет, поэтому SomeDL запускается
    # этим же exe с внутренним флагом (обрабатывается в main.py).
    if getattr(sys, "frozen", False):
        _COMMAND = [sys.executable, "--somedl-cli"]
        return _COMMAND

    # Последний шанс: запускаем пакет тем же интерпретатором.
    try:
        import importlib.util

        if importlib.util.find_spec("SomeDL") is not None:
            _COMMAND = [sys.executable, "-m", "SomeDL.main"]
            return _COMMAND
    except Exception:
        pass
    return None


def somedl_available() -> bool:
    """True, если SomeDL установлен и его можно вызвать."""
    return _find_command() is not None


def _command() -> list[str]:
    command = _find_command()
    if command is None:
        raise SomedlNotFoundError(
            "SomeDL не установлен. Установите зависимость командой: "
            "pip install somedl"
        )
    return command


def _config_home() -> Path:
    """Каталог, в котором SomeDL ищет свой somedl_config.toml."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home()))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _config_path() -> Path:
    return _config_home() / "SomeDL" / "somedl_config.toml"


def _environment() -> dict[str, str]:
    """Окружение subprocess с отдельным конфигом SomeDL для приложения.

    Изолированный конфиг гарантирует, что настройки пользовательского
    SomeDL не добавят ``cover.jpg`` рядом с музыкой и не создадут HTML-отчёт
    в папке библиотеки.
    """
    env = subprocess_env()
    base = DATA_DIR / "somedl"
    if sys.platform == "win32":
        env["APPDATA"] = str(base)
    elif sys.platform != "darwin":
        env["XDG_CONFIG_HOME"] = str(base)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _replace_config_value(text: str, key: str, value: str) -> str:
    pattern = re.compile(
        rf"(?m)^(\s*){re.escape(key)}\s*=.*$"
    )
    return pattern.sub(lambda match: match.group(1) + f"{key} = {value}", text)


def _ensure_config() -> None:
    """Создаёт/чинит приватный конфиг SomeDL без sidecar-обложек и отчётов."""
    path = _config_path()
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
    else:
        try:
            from importlib.resources import files

            text = files("SomeDL").joinpath(
                "new_somedl_config.toml"
            ).read_text(encoding="utf-8")
        except Exception:
            # Если пакет установлен нестандартно, SomeDL сгенерирует
            # конфиг сам при первом запуске.
            return

    updated = text
    # Обложка живёт только внутри файла; никаких .jpg в папке с музыкой.
    updated = _replace_config_value(updated, "cover_art_file", "false")
    updated = _replace_config_value(updated, "cover_art_size", '"l"')
    updated = _replace_config_value(updated, "lrc_file", "false")
    # Имя файла без подпапок: путь к результату легко перехватить.
    updated = _replace_config_value(updated, "output", '"{artist} - {song}"')
    # SomeDL Import создаёт HTML-отчёт в source-папке после 2+ файлов.
    updated = _replace_config_value(updated, "download_report", "1000000")

    if updated == text and path.is_file():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        print(f"[somedl] cannot write config {path}: {exc}")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def _tail(text: str, lines: int = 12) -> str:
    cleaned = [
        line.strip()
        for line in _strip_ansi(text).splitlines()
        if line.strip()
    ]
    return "\n".join(cleaned[-lines:])


# ---------------------------------------------------------------------------
#  Запуск CLI с отменой и перехватом вывода
# ---------------------------------------------------------------------------

def _run_cli(
    args: list[str],
    *,
    stdin_text: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float | None = None,
    stall_timeout: float | None = None,
    output_callback: Callable[[str], None] | None = None,
    tick_callback: Callable[[float], None] | None = None,
) -> tuple[int, str]:
    """Запускает somedl, не блокируя Qt-поток на чтении пайпа.

    Вывод пишется во временный файл: так дочерний процесс не зависает,
    если его лог окажется больше буфера pipe. Пока процесс работает, файл
    дочитывается порциями, а новые строки передаются в ``output_callback``
    (по ним UI строит прогресс). ``tick_callback`` вызывается с числом
    секунд с момента запуска, чтобы UI мог показывать «живой» прогресс даже
    между сообщениями SomeDL. ``stall_timeout`` завершает процесс, если он
    молчит слишком долго (например, завис на сетевом запросе).
    """
    command = _command() + args
    # Отдельный файл и отдельный читающий дескриптор: чтение прогресса не
    # двигает файловый offset дочернего процесса (это важно на Windows, где
    # нет os.pread, и защищает от гонки на POSIX).
    stderr_file = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
    output_path = stderr_file.name
    reader = None
    stdin = subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL

    try:
        process = subprocess.Popen(
            command,
            stdin=stdin,
            stdout=stderr_file,
            stderr=subprocess.STDOUT,
            env=_environment(),
            creationflags=subprocess_creationflags(),
        )
    except FileNotFoundError as exc:
        stderr_file.close()
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise SomedlNotFoundError(
            "Не удалось запустить somedl. Проверьте установку SomeDL."
        ) from exc

    output_position = 0
    pending_line = ""

    def drain_output() -> None:
        """Дочитывает новые строки вывода и отдаёт их в колбэк."""
        nonlocal output_position, pending_line
        if reader is None:
            return
        chunks = []
        while True:
            reader.seek(output_position)
            chunk = reader.read(65536)
            if not chunk:
                break
            output_position += len(chunk)
            chunks.append(chunk)
        if not chunks or output_callback is None:
            return
        text = pending_line + b"".join(chunks).decode(
            "utf-8", errors="replace"
        )
        pending_line = ""
        for part in text.splitlines(keepends=True):
            if not part.endswith(("\n", "\r")):
                # Неполная строка: дождёмся следующей порции вывода.
                pending_line = part
                continue
            line = _strip_ansi(part.rstrip("\r\n"))
            if line.strip():
                output_callback(line)

    try:
        reader = open(output_path, "rb")
        if stdin_text is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_text.encode("utf-8"))
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        started = time.monotonic()
        last_output = started
        while process.poll() is None:
            before = output_position
            drain_output()
            if output_position != before:
                last_output = time.monotonic()

            if cancel_check is not None and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise SomedlCancelled("Операция SomeDL отменена")
            elapsed = time.monotonic() - started
            if timeout is not None and elapsed > timeout:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise SomedlError(
                    "SomeDL не завершился за отведённое время"
                )
            if (
                stall_timeout is not None
                and time.monotonic() - last_output > stall_timeout
            ):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise SomedlError(
                    "SomeDL не отвечает уже "
                    f"{int(stall_timeout)} с; обновление прервано. "
                    "Проверьте подключение к интернету."
                )
            if tick_callback is not None:
                tick_callback(elapsed)
            time.sleep(0.2)

        # Забираем вывод, который SomeDL успел написать перед выходом.
        drain_output()

        code = process.returncode
        reader.seek(0)
        output = reader.read().decode("utf-8", errors="replace")
        return code, output
    finally:
        # Если вышли по исключению (например, из колбэка прогресса),
        # не оставляем дочерний процесс работать в фоне.
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if reader is not None:
            reader.close()
        stderr_file.close()
        try:
            os.unlink(output_path)
        except OSError:
            pass


def _find_audio_files(folder: Path) -> list[Path]:
    try:
        files = [
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.casefold() in _AUDIO_EXTS
        ]
    except OSError:
        return []
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _remove_import_junk(folder: Path) -> None:
    """Убирает служебные файлы, которые оставляет ``somedl import``."""
    for name in ("somedl_import_cache",):
        try:
            (folder / name).unlink()
        except OSError:
            pass
    for report in folder.glob("Download Report *.html"):
        try:
            report.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
#  Публичный API
# ---------------------------------------------------------------------------

def download_track(
    query: str,
    target_folder: str | Path,
    *,
    audio_format: str = "best",
    cookies_path: str | Path | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float | None = 1800,
    stall_timeout: float | None = 300,
) -> str:
    """Скачивает один трек через SomeDL и возвращает путь к файлу.

    Скачивание идёт во временный каталог, поэтому SomeDL не может
    перезаписать существующий файл или оставить рядом с музыкой
    ``cover.jpg``/``.part``/HTML-отчёт. Готовый аудиофайл переносится в
    ``target_folder`` под свободным именем.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        raise SomedlError("Пустой запрос для SomeDL")

    audio_format = (audio_format or "best").casefold()
    if audio_format not in AUDIO_FORMATS:
        audio_format = "best"

    target = Path(target_folder)
    try:
        target.mkdir(parents=True, exist_ok=True)
        _STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SomedlError(f"Не могу создать папку для загрузки: {exc}") from exc

    _ensure_config()
    staging = Path(
        tempfile.mkdtemp(prefix="download-", dir=str(_STAGING_ROOT))
    )

    args = [
        clean_query,
        "-o", str(staging),
        "-f", audio_format,
        "--disable-report",
        "--no-album",
        "--get-song",
    ]
    if cookies_path:
        cookie_file = Path(cookies_path)
        if cookie_file.is_file():
            args.extend(["--cookies", str(cookie_file)])

    try:
        code, output = _run_cli(
            args,
            cancel_check=cancel_check,
            timeout=timeout,
            stall_timeout=stall_timeout,
        )
        files = _find_audio_files(staging)
        if code != 0 or not files:
            message = _tail(output) or (
                f"SomeDL завершился с кодом {code}, файл не создан"
            )
            raise SomedlError(message)

        moved: list[str] = []
        for source in files:
            destination = unique_path(target / source.name)
            shutil.move(str(source), str(destination))
            moved.append(str(destination))

            # Некоторые настройки SomeDL могут создать .lrc. Переносим его
            # вместе с треком, но картинки и отчёты не трогаем.
            lrc = source.with_suffix(".lrc")
            if lrc.is_file():
                lrc_target = Path(destination).with_suffix(".lrc")
                lrc_target = Path(unique_path(lrc_target))
                shutil.move(str(lrc), str(lrc_target))

        print(f"[somedl] downloaded: {moved[0]}")
        return moved[0]
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def update_library_metadata(
    folder: str | Path,
    *,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float | None = 3600,
    stall_timeout: float | None = 300,
    progress_callback: (
        Callable[[int, int, str], None] | None
    ) = None,
    tick_callback: Callable[[float], None] | None = None,
) -> str:
    """Обновляет теги и обложки существующих файлов через ``somedl import``.

    Используется режим ``update``: SomeDL перезаписывает метаданные и
    встроенную обложку на месте, не перекачивая аудио и не переименовывая
    файлы. Возвращает хвост вывода SomeDL (для логов).

    ``progress_callback(done, total, line)`` вызывается по мере вывода
    SomeDL: ``done`` — номер текущего файла (если его удалось разобрать),
    ``total`` — количество поддерживаемых файлов, ``line`` — строка вывода.
    ``tick_callback`` вызывается несколько раз в секунду, чтобы UI мог
    обновлять прогресс, даже когда SomeDL молчит.
    """
    root = Path(folder)
    if not root.is_dir():
        return ""

    supported = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMPORT_EXTS
    ]
    if not supported:
        print(f"[somedl] no supported files for import in {root}")
        return ""

    total = len(supported)
    done = 0

    def on_output(line: str) -> None:
        nonlocal done
        match = _FILE_NR_RE.search(line)
        if match:
            done = min(total, max(done, int(match.group(1))))
        if progress_callback is not None:
            progress_callback(done, total, line)

    _ensure_config()
    _remove_import_junk(root)

    # 1/6 source, 2/6 destination (та же папка), 3/6 шаблон, 4/6 рекурсивно,
    # 5/6 режим update, 6/6 yt-id → нет, имя файла "Artist - Song" → да,
    # подтверждение запуска.
    answers = "\n".join([
        str(root),
        str(root),
        "{artist} - {song}",
        "y",
        "u",
        "n",
        "y",
        "y",
        "",
    ])

    try:
        code, output = _run_cli(
            ["import"],
            stdin_text=answers,
            cancel_check=cancel_check,
            timeout=timeout,
            stall_timeout=stall_timeout,
            output_callback=on_output,
            tick_callback=tick_callback,
        )
    finally:
        _remove_import_junk(root)

    if progress_callback is not None:
        progress_callback(total, total, "")

    if code != 0:
        message = _tail(output) or f"somedl import завершился с кодом {code}"
        raise SomedlError(message)

    print(f"[somedl] import updated: {root}")
    return _tail(output)
