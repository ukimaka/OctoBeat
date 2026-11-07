#!/usr/bin/env bash
# Build the OctoBeat Flatpak and bundle it as OctoBeat.flatpak.
#
# Requirements:
#   flatpak, flatpak-builder, and the Flathub remote.
#
# The build uses the user-wide Flatpak installation by default. If your
# runtimes are installed system-wide, run with FLATPAK_SYSTEM=1.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MANIFEST="io.github.ukimaka.OctoBeat.yml"
BUILD_DIR="${BUILD_DIR:-build-dir}"
REPO_DIR="${REPO_DIR:-flatpak-repo}"
BUNDLE="${BUNDLE:-OctoBeat.flatpak}"
STATE_DIR="${STATE_DIR:-$ROOT_DIR/.flatpak-builder}"
REMOTE="${FLATPAK_REMOTE:-flathub}"

FB_ARGS=(
  --force-clean
  --disable-rofiles-fuse
  --state-dir="$STATE_DIR"
  --repo="$REPO_DIR"
  --install-deps-from="$REMOTE"
)
if [[ "${FLATPAK_SYSTEM:-0}" != "1" ]]; then
  FB_ARGS+=(--user)
fi

echo "==> Building $MANIFEST"
flatpak-builder "${FB_ARGS[@]}" "$BUILD_DIR" "$MANIFEST"

echo "==> Exporting $BUNDLE"
flatpak build-bundle "$REPO_DIR" "$BUNDLE" io.github.ukimaka.OctoBeat

if [[ "$BUNDLE" = /* ]]; then
  INSTALL_PATH="$BUNDLE"
else
  INSTALL_PATH="./$BUNDLE"
fi

echo
echo "Built: $BUNDLE"
echo "Install with: flatpak install --user $INSTALL_PATH"
