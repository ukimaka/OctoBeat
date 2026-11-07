#!/bin/sh
# Диагностика Flatpak-версии OctoBeat.
#
# Запуск:
#   flatpak run --command=octobeat-diagnose io.github.ukimaka.OctoBeat
#
# Скрипт показывает, какие пути видит песочница, где лежит база, сколько в
# ней треков без тегов/недоступных файлов, и пробует проиграть один трек
# через libVLC (dummy audio, без звука).

set -u

echo "== Flatpak sandbox =="
echo "FLATPAK_ID=${FLATPAK_ID:-<none>}"
echo "HOME=$HOME"
echo "XDG_DATA_HOME=${XDG_DATA_HOME:-<unset>}"
echo "XDG_CACHE_HOME=${XDG_CACHE_HOME:-<unset>}"
echo

echo "== Filesystem access =="
for d in "$HOME" "$HOME/Music" "$HOME/.local/share/OctoBeat"; do
    if [ -d "$d" ]; then
        echo "OK       $d"
    else
        echo "MISSING  $d"
    fi
done
if [ -d "$HOME/Music" ]; then
    count=$(find "$HOME/Music" -type f 2>/dev/null | wc -l)
    echo "files in ~/Music: $count"
    find "$HOME/Music" -maxdepth 1 -type f 2>/dev/null | head -3 |
    while IFS= read -r f; do
        if [ -r "$f" ]; then
            echo "readable:     $f"
        else
            echo "NOT readable: $f"
        fi
    done
fi
echo

echo "== FFmpeg =="
if command -v ffmpeg >/dev/null 2>&1; then
    command -v ffmpeg
    ffmpeg -version 2>/dev/null | head -1
else
    echo "ffmpeg not found in PATH"
fi
echo

echo "== VLC decoders =="
for plugin in libopus_plugin.so libavcodec_plugin.so libpulse_plugin.so; do
    if [ -e "/app/lib/vlc/plugins/codec/$plugin" ] ||
       [ -e "/app/lib/vlc/plugins/audio_output/$plugin" ]; then
        echo "OK       $plugin"
    else
        echo "MISSING  $plugin"
    fi
done
echo

echo "== Database, paths, playback =="
python3 - <<'PY'
import os
import sqlite3
import time
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QStandardPaths

QCoreApplication.setApplicationName("OctoBeat")
data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
db_file = data_dir / "music.db"
host_db = Path.home() / ".local" / "share" / "OctoBeat" / "music.db"

print(f"flatpak data dir: {data_dir}")
print(f"flatpak database: {db_file} (exists: {db_file.is_file()})")
print(f"native database:  {host_db} (exists: {host_db.is_file()})")

if not db_file.is_file():
    print("no database yet: launch the application once")
    raise SystemExit(0)

conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, file_path, title, artist FROM tracks ORDER BY id"
).fetchall()
print(f"tracks: {len(rows)}")
print(
    "tracks without title/artist: "
    f"{sum(1 for r in rows if not (r['title'] and r['artist']))}"
)

missing = [r for r in rows if not r["file_path"] or not Path(r["file_path"]).is_file()]
print(f"tracks whose file is not visible: {len(missing)}")
for row in missing[:5]:
    print(f"  missing: {row['file_path']}")

try:
    playlists = conn.execute("SELECT count(*) FROM playlists").fetchone()[0]
    print(f"playlists: {playlists}")
except sqlite3.Error as exc:
    print(f"playlists: error: {exc}")

sample = next(
    (r for r in rows if r["file_path"] and Path(r["file_path"]).is_file()),
    None,
)
if sample is None:
    print("no playable sample track found")
    raise SystemExit(0)

print(f"playback sample: {sample['file_path']}")
try:
    import vlc

    instance = vlc.Instance("--aout=dummy", "--no-video", "--quiet")
    player = instance.media_player_new()
    player.set_media(instance.media_new_path(sample["file_path"]))
    player.play()
    time.sleep(1.5)
    print(
        "  state: "
        f"{player.get_state()} length_ms: {player.get_length()} "
        f"time_ms: {player.get_time()}"
    )
    player.stop()
except Exception as exc:
    print(f"  VLC error: {exc}")
PY
