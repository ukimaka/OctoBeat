#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"$ROOT/packaging/tools/build-linux.sh"
flatpak run org.flatpak.Builder \
  --user --force-clean --install-deps-from=flathub \
  --repo="$ROOT/packaging/flatpak/repo" \
  "$ROOT/packaging/flatpak/build-dir" \
  "$ROOT/packaging/flatpak/io.github.ukimaka.OctoBeat.yml"

flatpak build-bundle "$ROOT/packaging/flatpak/repo" \
  "$ROOT/dist/OctoBeat-1.0.0.flatpak" io.github.ukimaka.OctoBeat
