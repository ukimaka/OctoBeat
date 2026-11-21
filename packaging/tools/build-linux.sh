#!/usr/bin/env bash
# Builds the relocatable helper binaries for the Linux package:
#   - SomeDL frozen with PyInstaller (Python runtime is inside the binary)
#   - yt-dlp standalone
#   - Deno (used by yt-dlp for YouTube challenges)
#   - static ffmpeg/ffprobe
#
# Usage:
#   packaging/tools/build-linux.sh
# Output:
#   packaging/tools/runtime/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS="$ROOT/packaging/tools"
OUT="$TOOLS/runtime"
BUILD="$TOOLS/.build"
mkdir -p "$OUT" "$BUILD"

YTDLP_URL="${YTDLP_URL:-https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux}"
DENO_URL="${DENO_URL:-https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip}"
FFMPEG_URL="${FFMPEG_URL:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz}"

echo "[tools] yt-dlp"
curl -L --fail --silent --show-error -o "$OUT/yt-dlp" "$YTDLP_URL"
chmod +x "$OUT/yt-dlp"

if [ ! -x "$OUT/deno" ]; then
    echo "[tools] deno"
    curl -L --fail --silent --show-error -o "$BUILD/deno.zip" "$DENO_URL"
    unzip -q -o "$BUILD/deno.zip" -d "$BUILD/deno"
    cp "$BUILD/deno/deno" "$OUT/deno"
    chmod +x "$OUT/deno"
fi

if [ ! -x "$OUT/ffmpeg" ]; then
    echo "[tools] ffmpeg"
    curl -L --fail --silent --show-error -o "$BUILD/ffmpeg.tar.xz" "$FFMPEG_URL"
    rm -rf "$BUILD/ffmpeg"
    mkdir -p "$BUILD/ffmpeg"
    tar -xf "$BUILD/ffmpeg.tar.xz" -C "$BUILD/ffmpeg" --strip-components=1
    cp "$BUILD/ffmpeg/bin/ffmpeg" "$OUT/ffmpeg"
    cp "$BUILD/ffmpeg/bin/ffprobe" "$OUT/ffprobe"
    cp "$BUILD/ffmpeg/LICENSE.txt" "$OUT/FFMPEG-LICENSE.txt" 2>/dev/null || true
    chmod +x "$OUT/ffmpeg" "$OUT/ffprobe"
fi

if [ ! -x "$OUT/somedl" ]; then
    echo "[tools] SomeDL (PyInstaller)"
    VENV="$BUILD/venv"
    if [ ! -x "$VENV/bin/python" ]; then
        python3 -m venv "$VENV"
    fi
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet somedl pyinstaller
    rm -rf "$BUILD/somedl"
    mkdir -p "$BUILD/somedl"
    (
        cd "$BUILD/somedl"
        "$VENV/bin/pyinstaller" --onefile --noconfirm --name somedl \
            --collect-all SomeDL --collect-all ytmusicapi \
            --collect-all yt_dlp "$ROOT/packaging/tools/somedl_entry.py" >/dev/null
    )
    cp "$BUILD/somedl/dist/somedl" "$OUT/somedl"
    chmod +x "$OUT/somedl"
fi

echo "[tools] done: $OUT"
ls -lh "$OUT"
