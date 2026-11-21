#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARBALL="$ROOT/dist/OctoBeat-1.0.0-Linux-x86_64.tar.gz"
if [ ! -f "$TARBALL" ]; then
    echo "Build the tarball first: packaging/linux/build-tarball.sh" >&2
    exit 1
fi
cp "$TARBALL" "$ROOT/packaging/arch/"
cd "$ROOT/packaging/arch"
sha256sums="$(sha256sum OctoBeat-1.0.0-Linux-x86_64.tar.gz | cut -d' ' -f1)"
sed -i "s/^sha256sums=.*/sha256sums=('$sha256sums')/" PKGBUILD
makepkg -f
cp octobeat-bin-*.pkg.tar.zst "$ROOT/dist/"
