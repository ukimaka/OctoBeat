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

"""Shared python-yt-dlp integration.

All YouTube requests go through the Python library instead of CLI
subprocesses.  The library can be interrupted from a Qt worker and raises
catchable exceptions instead of blocking on stdout/stderr pipes.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from PyQt5.QtCore import QSettings

from qt_diagnostics import note

# YouTube's web clients currently work best with these player clients.
# Equivalent CLI option:
#   --extractor-args "youtube:player_client=web_safari,tv"
YOUTUBE_EXTRACTOR_ARGS = {
    "youtube": {"player_client": ["web_safari", "tv"]},
}
# Some networks reject the clients above with "page needs to be reloaded".
# Retry once with yt-dlp's own client selection instead of failing the task.
YOUTUBE_FALLBACK_EXTRACTOR_ARGS = {
    "youtube": {"player_client": ["default"]},
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# yt-dlp can download DASH/HLS fragments in parallel. YouTube audio often
# comes as fragmented streams, so this is the main throughput knob.
FRAGMENT_CONCURRENCY = 4
_MB = 1024.0 * 1024.0

DOWNLOAD_MODE_SETTING = "youtube_download_mode"
DOWNLOAD_MODE_NATIVE = "native"
DOWNLOAD_MODE_MP3 = "mp3"
DEFAULT_DOWNLOAD_MODE = DOWNLOAD_MODE_NATIVE
DOWNLOAD_MODES = (DOWNLOAD_MODE_NATIVE, DOWNLOAD_MODE_MP3)
_BOT_MARKERS = (
    "sign in to confirm you're not a bot",
    "confirm you're not a bot",
    "please sign in",
    "bot check",
)
_COOKIE_MARKERS = (
    "cookies database",
    "failed to decrypt",
)
_RETRY_MARKERS = (
    "page needs to be reloaded",
    "no video formats found",
    "unable to extract",
    "failed to extract",
    *_BOT_MARKERS,
)

class _QuietYtDlpLogger:
    """Глушит служебный вывод yt-dlp.

    Ошибки всё равно приходят исключением и показываются в диалоге, а
    консоль не засоряется внутренними повторами yt-dlp.
    """

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


_QUIET_LOGGER = _QuietYtDlpLogger()


class YtDlpUnavailable(RuntimeError):
    """Raised when the yt-dlp Python package cannot be imported."""


def is_youtube_url(value: str) -> bool:
    """True для прямой http(s)-ссылки на YouTube (youtube.com или youtu.be)."""
    text = (value or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(text).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
        or host.endswith(".youtu.be")
    )


def normalize_download_mode(mode: str | None) -> str:
    """Приводит режим из настроек к native/mp3."""
    value = str(mode or "").strip().lower()
    return value if value in DOWNLOAD_MODES else DEFAULT_DOWNLOAD_MODE


def current_download_mode() -> str:
    """Режим скачивания из QSettings (native по умолчанию)."""
    try:
        value = QSettings("MusicPlayer", "MusicPlayer").value(
            DOWNLOAD_MODE_SETTING, DEFAULT_DOWNLOAD_MODE
        )
    except Exception:
        value = DEFAULT_DOWNLOAD_MODE
    return normalize_download_mode(value)


class DownloadCancelled(Exception):
    """Internal signal used to abort yt-dlp from a progress hook."""


def load_ytdlp():
    """Import yt-dlp lazily and turn import failures into a clean error."""
    try:
        import yt_dlp
    except Exception as exc:  # ImportError or a broken optional dependency
        raise YtDlpUnavailable(
            "yt-dlp не установлен или не загружается. "
            "Установите его командой: pip install -U yt-dlp"
        ) from exc
    return yt_dlp


def build_options(
    cookies_path=None,
    *,
    extra: dict[str, Any] | None = None,
    extractor_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return common YoutubeDL options, including the required clients."""
    clients = (extractor_args or YOUTUBE_EXTRACTOR_ARGS)["youtube"][
        "player_client"
    ]
    options: dict[str, Any] = {
        "extractor_args": {
            "youtube": {"player_client": list(clients)}
        },
        # Keep the GUI clean; errors still arrive as exceptions.
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "no_color": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": FRAGMENT_CONCURRENCY,
        "logger": _QUIET_LOGGER,
    }
    if cookies_path:
        options["cookiefile"] = str(cookies_path)
    if extra:
        options.update(extra)
    return options


def format_error(exc: BaseException) -> str:
    """Make a yt-dlp exception readable in a Qt message box."""
    text = str(exc).strip() or exc.__class__.__name__
    text = _ANSI_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 12:
        lines = lines[:12] + ["..."]
    message = "\n".join(lines)
    lowered = message.lower()
    if any(marker in lowered for marker in _BOT_MARKERS):
        message = (
            "YouTube требует входа (bot check).\n"
            "Откройте Настройки → YouTube и импортируйте cookies.txt "
            "из браузера, где выполнен вход в YouTube.\n\n" + message
        )
    elif (
        any(marker in lowered for marker in _COOKIE_MARKERS)
        or ("could not find" in lowered and "cookies" in lowered)
    ):
        message = (
            "Не удалось прочитать cookies.txt.\n"
            "Проверьте, что файл существует и экспортирован в формате "
            "Netscape, либо импортируйте его заново в настройках YouTube.\n\n"
            + message
        )
    return message


def search_videos(
    query: str,
    limit: int = 5,
    cookies_path=None,
) -> list[dict[str, Any]]:
    """Search YouTube with yt-dlp and return flat video dictionaries.

    A direct ``youtube.com``/``youtu.be`` URL is extracted as-is; any other
    text is sent through yt-dlp's ``ytsearch`` prefix.
    """
    query = (query or "").strip()
    if not query:
        return []

    yt_dlp = load_ytdlp()
    direct_url = is_youtube_url(query)

    def attempt(extractor_args):
        options = build_options(
            cookies_path,
            extra={"extract_flat": True, "skip_download": True},
            extractor_args=extractor_args,
        )
        # Прямую ссылку отдаём yt-dlp как есть, без префикса ytsearch.
        target = query if direct_url else (
            f"ytsearch{max(1, int(limit))}:{query}"
        )
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(target, download=False)

    try:
        info = attempt(YOUTUBE_EXTRACTOR_ARGS)
    except Exception as first_exc:
        if not should_retry_with_default(first_exc):
            raise
        note(
            "[youtube] primary clients failed, retrying default: "
            + format_error(first_exc).splitlines()[0]
        )
        info = attempt(YOUTUBE_FALLBACK_EXTRACTOR_ARGS)

    if not isinstance(info, dict):
        return []
    entries = info.get("entries")
    if entries is not None:
        return [entry for entry in entries if isinstance(entry, dict)]
    return [info] if info.get("id") else []


def _log_download(message: str) -> None:
    """Пишет измерение скорости и в терминал, и в диагностический лог."""
    print(message, flush=True)
    note(message)


def download_audio(
    source: str,
    outtmpl: str,
    cookies_path=None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    mode: str | None = None,
) -> str:
    """Download one YouTube source and return the final (native or MP3) path."""
    mode = normalize_download_mode(mode or current_download_mode())
    yt_dlp = load_ytdlp()
    conversion = "none (native)" if mode == DOWNLOAD_MODE_NATIVE else "MP3 320 kbps"
    _log_download(
        "[youtube] download options: format=bestaudio/best, "
        f"conversion={conversion}, "
        f"concurrent_fragment_downloads={FRAGMENT_CONCURRENCY}"
    )

    def attempt(extractor_args):
        return _download_with_options(
            yt_dlp,
            source,
            outtmpl,
            cookies_path,
            progress_callback,
            cancel_check,
            extractor_args,
            mode,
        )

    try:
        return attempt(YOUTUBE_EXTRACTOR_ARGS)
    except DownloadCancelled:
        raise
    except Exception as first_exc:
        if cancel_check and cancel_check():
            raise DownloadCancelled() from first_exc
        if not should_retry_with_default(first_exc):
            raise
        note(
            "[youtube] primary clients failed, retrying default: "
            + format_error(first_exc).splitlines()[0]
        )
        return attempt(YOUTUBE_FALLBACK_EXTRACTOR_ARGS)


def _download_with_options(
    yt_dlp,
    source: str,
    outtmpl: str,
    cookies_path,
    progress_callback,
    cancel_check,
    extractor_args,
    mode: str,
) -> str:
    """Run one download attempt with a specific set of player clients."""
    now = time.monotonic()
    captured = {
        "filepath": None,
        "last_percent": -1,
        "started": now,
        "last_speed_log": now,
        "last_speed_bytes": 0,
        "peak_speed": 0.0,
        "summary_logged": False,
    }

    def is_cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def progress_hook(status: dict[str, Any]) -> None:
        if is_cancelled():
            raise DownloadCancelled()

        current = time.monotonic()
        finished = status.get("status") == "finished"
        downloaded = max(0, int(status.get("downloaded_bytes") or 0))
        total = status.get("total_bytes") or status.get(
            "total_bytes_estimate"
        )
        percent = None
        if total:
            percent = int(downloaded * 100 / int(total))
            percent = max(0, min(99, percent))

        if finished:
            if not captured["summary_logged"]:
                elapsed = max(current - captured["started"], 0.001)
                average = downloaded / elapsed / _MB
                peak = max(captured["peak_speed"] / _MB, average)
                _log_download(
                    "[youtube] download done: "
                    f"{downloaded / _MB:.2f} MB in {elapsed:.1f}s, "
                    f"avg {average:.2f} MB/s, "
                    f"peak {peak:.2f} MB/s"
                )
                captured["summary_logged"] = True
            percent = 99
        else:
            # Считаем скорость сами за последний интервал: yt-dlp иногда
            # отдаёт мгновенный speed 150+ MB/s после буферизации, из-за чего
            # такие значения бесполезны для сравнения.
            elapsed_since_log = current - captured["last_speed_log"]
            if elapsed_since_log >= 2.0:
                speed = max(
                    0.0,
                    (downloaded - captured["last_speed_bytes"])
                    / elapsed_since_log,
                )
                captured["last_speed_log"] = current
                captured["last_speed_bytes"] = downloaded
                if speed >= 0.01 * _MB:
                    captured["peak_speed"] = max(
                        captured["peak_speed"], speed
                    )
                    suffix = (
                        f", {percent}%" if percent is not None else ""
                    )
                    _log_download(
                        "[youtube] download speed: "
                        f"{speed / _MB:.2f} MB/s "
                        f"({downloaded / _MB:.2f} MB{suffix})"
                    )

        if percent is None or progress_callback is None:
            return
        if percent != captured["last_percent"]:
            captured["last_percent"] = percent
            progress_callback(percent)

    def postprocessor_hook(status: dict[str, Any]) -> None:
        if is_cancelled():
            raise DownloadCancelled()
        if status.get("status") != "finished":
            return
        info = status.get("info_dict") or {}
        filepath = info.get("filepath")
        if filepath:
            captured["filepath"] = str(filepath)

    # Обложки скачивает только cover_provider и кладёт их в кэш приложения.
    # yt-dlp не должен создавать .jpg рядом с аудио: иначе такие файлы
    # выглядят как пользовательский sidecar и перебивают MusicBrainz.
    postprocessors = []
    if mode == DOWNLOAD_MODE_MP3:
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        })

    options = build_options(
        cookies_path,
        extractor_args=extractor_args,
        extra={
            # Only the audio stream is requested: no video download at all.
            "format": "bestaudio/best",
            "outtmpl": str(outtmpl),
            # Ни превью, ни его конвертации: только аудио.
            "writethumbnail": False,
            "postprocessors": postprocessors,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        },
    )

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=True)
        final_path = resolve_download_path(
            info, ydl, captured["filepath"]
        )

    if not final_path:
        raise RuntimeError("yt-dlp завершился, но файл не найден")
    return final_path


def should_retry_with_default(exc: BaseException) -> bool:
    """Whether a failed request is worth retrying with yt-dlp defaults."""
    message = format_error(exc).lower()
    return any(marker in message for marker in _RETRY_MARKERS)


def resolve_download_path(info, ydl=None, captured_path=None) -> str | None:
    """Find the post-processed file produced by yt-dlp."""
    candidates: list[str] = []

    def add(value) -> None:
        if value:
            text = str(value)
            if text not in candidates:
                candidates.append(text)

    stack = [info]
    entries: list[Any] = []
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        for key in ("filepath", "_filename", "filename"):
            add(item.get(key))
        for download in item.get("requested_downloads") or []:
            if isinstance(download, dict):
                for key in ("filepath", "_filename", "filename"):
                    add(download.get(key))
        nested = item.get("entries")
        if nested:
            nested = list(nested)
            entries.extend(nested)
            stack.extend(nested)

    if ydl is not None:
        for item in [info, *entries]:
            if not isinstance(item, dict):
                continue
            try:
                add(ydl.prepare_filename(item))
            except Exception:
                continue

    # Hook may report the pre-conversion filename; use it only as fallback.
    add(captured_path)

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
        if path.suffix.lower() != ".mp3":
            converted = path.with_suffix(".mp3")
            if converted.is_file():
                return str(converted)
    return None
