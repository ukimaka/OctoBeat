#!/usr/bin/env bash
set -euo pipefail
cd /work/packaging/arch
cp /work/dist/OctoBeat-1.0.0-Linux-x86_64.tar.gz .
sum="$(sha256sum OctoBeat-1.0.0-Linux-x86_64.tar.gz | cut -d' ' -f1)"
sed -i "s/^sha256sums=.*/sha256sums=('$sum')/" PKGBUILD
makepkg -f --nodeps
