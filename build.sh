#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

pyinstaller --clean --noconfirm OctoBeat.spec
chmod +x dist/OctoBeat/OctoBeat
