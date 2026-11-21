#!/usr/bin/env bash
# Builds the Linux release tarball, including the frozen SomeDL/Python helper,
# yt-dlp, Deno and ffmpeg.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build-release}"
DIST="${DIST_DIR:-$ROOT/dist}"

"$ROOT/packaging/tools/build-linux.sh"
cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j "${JOBS:-$(nproc)}"
mkdir -p "$DIST"
(
    cd "$BUILD"
    cpack --config CPackConfig.cmake
)
cp "$BUILD"/OctoBeat-*-Linux-*.tar.gz "$DIST"/
echo "Package: $DIST/$(basename "$BUILD"/OctoBeat-*-Linux-*.tar.gz)"
