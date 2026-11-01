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
from pathlib import Path
from typing import Any, Callable

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
_BOT_MARKERS = (
    "sign in to confirm you're not a bot",
    "confirm you're not a bot",
    "please sign in",
    "bot check",
)
_RETRY_MARKERS = (
    "page needs to be reloaded",
    "no video formats found",
    "unable to extract",
    "failed to extract",
    *_BOT_MARKERS,
)


class YtDlpUnavailable(RuntimeError):
    """Raised when the yt-dlp Python package cannot be imported."""


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
            "YouTube требует авторизации (bot check). "
            "Добавьте cookies.txt в настройках.\n" + message
        )
    return message


def search_videos(
    query: str,
    limit: int = 5,
    cookies_path=None,
) -> list[dict[str, Any]]:
    """Search YouTube with yt-dlp and return flat video dictionaries."""
    query = (query or "").strip()
    if not query:
        return []

    yt_dlp = load_ytdlp()

    def attempt(extractor_args):
        options = build_options(
            cookies_path,
            extra={"extract_flat": True, "skip_download": True},
            extractor_args=extractor_args,
        )
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(
                f"ytsearch{max(1, int(limit))}:{query}",
                download=False,
            )

    try:
        info = attempt(YOUTUBE_EXTRACTOR_ARGS)
    except Exception as first_exc:
        if not should_retry_with_default(first_exc):
            raise
        print(
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


def download_audio(
    source: str,
    outtmpl: str,
    cookies_path=None,
    progress_callback: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    """Download one YouTube source as MP3 and return the final path."""
    yt_dlp = load_ytdlp()

    def attempt(extractor_args):
        return _download_with_options(
            yt_dlp,
            source,
            outtmpl,
            cookies_path,
            progress_callback,
            cancel_check,
            extractor_args,
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
        print(
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
) -> str:
    """Run one download attempt with a specific set of player clients."""
    captured = {"filepath": None, "last_percent": -1}

    def is_cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def progress_hook(status: dict[str, Any]) -> None:
        if is_cancelled():
            raise DownloadCancelled()
        if progress_callback is None:
            return
        if status.get("status") == "finished":
            percent = 99
        else:
            total = status.get("total_bytes") or status.get(
                "total_bytes_estimate"
            )
            if not total:
                return
            percent = int(
                (status.get("downloaded_bytes") or 0) * 100 / int(total)
            )
            percent = max(0, min(99, percent))
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

    options = build_options(
        cookies_path,
        extractor_args=extractor_args,
        extra={
            "format": "bestaudio/best",
            "outtmpl": str(outtmpl),
            "writethumbnail": True,
            "postprocessors": [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": "jpg",
                    "when": "before_dl",
                },
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                },
            ],
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
