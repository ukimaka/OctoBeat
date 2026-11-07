# OctoBeat Flatpak

[`io.github.ukimaka.OctoBeat.yml`](../io.github.ukimaka.OctoBeat.yml) builds
OctoBeat as a self-contained Flatpak: PyQt5, Python packages, VLC/libvlc and
the application sources.  FFmpeg is taken from the runtime (see below).

## Runtime choice

OctoBeat uses **PyQt5**, so the manifest uses the KDE **Qt5** runtime:

* `org.kde.Platform` / `org.kde.Sdk` **5.15-25.08**
* `com.riverbankcomputing.PyQt.BaseApp` **5.15-25.08**

`org.kde.Platform//6.7` is a **Qt6-only** runtime.  The
`com.riverbankcomputing.PyQt.BaseApp` branches are `5.15-23.08`,
`5.15-24.08` and `5.15-25.08`; there is no PyQt5 BaseApp for 6.7.  Using 6.7
would require building Qt5 and PyQt5 from source, so the supported Qt5 branch
is used instead.  If the application is ported to PyQt6, switch both the
runtime and base app to a matching 6.x branch.

## Modules

| Module | Contents |
| --- | --- |
| `python3-build-modules.json` | `meson-python` (PEP 517 backend for pycairo/PyGObject) |
| `python3-pycairo.json` | pycairo (built first; PyGObject needs its headers) |
| `python3-pygobject.json` | PyGObject (needed by `pydbus`/MPRIS) |
| `python3-modules.json` | requests, yt-dlp, SomeDL, ytmusicapi, Flask, waitress, rich, mutagen, pydub, numpy, audioop-lts, python-vlc |
| `python3-mpris-server.json` | `mpris-server`, `pydbus`, `emoji`, `StrEnum`, `unidecode` |
| `vlc` | VLC 3.0.24, audio-only build, linked against the runtime FFmpeg |
| `octobeat` | application sources, launcher, `.desktop`, AppStream metadata, icon |

`PyQt5` is deliberately **not** in `requirements.txt`: it is provided by the
PyQt BaseApp.

### FFmpeg

The KDE 5.15-25.08 runtime already ships **FFmpeg 7.1** (`/usr/bin/ffmpeg`,
`/usr/bin/ffprobe`) and `libavcodec`/`libavformat`.  The runtime also enables
`org.freedesktop.Platform.codecs-extra` automatically for extra codecs.  A
separate FFmpeg module would duplicate ~100 MB and risk an ABI mismatch with
VLC, so VLC is linked against the runtime FFmpeg instead.  `dependencies.py`
finds `/usr/bin/ffmpeg` and does not need to download a static build.

### VLC

VLC is built from the official 3.0.24 tarball with Qt, X11/Wayland video
outputs, network access modules, Lua, D-Bus and the extra demuxers disabled.
Audio decoding goes through FFmpeg (`avcodec`/`avformat`) and output through
PulseAudio.  The build produces `libvlc.so.5`, `libvlccore.so.9` and 240
plugins under `/app/lib/vlc/plugins`.

The plugin cache is not shipped: flatpak-builder strips the plugins after the
build, which invalidates `plugins.dat`; the directory is read-only at runtime,
so libVLC simply scans it on startup.

VLC's own **libopus** decoder is enabled (`--enable-opus`).  The `avcodec`
decoder from the runtime FFmpeg 7.1 rejects the Opus extradata produced by
VLC 3.0.24's Ogg demuxer (`Extradata version 97 is not implemented`), which
made every `.opus` track fail with `Codec not supported`.  With the libopus
plugin present, `.opus` files decode normally alongside MP3/FLAC/M4A/OGG/WAV
(which are handled by `avcodec`).

## Library migration from the native installation

The native build stores its database in `~/.local/share/OctoBeat/music.db`;
inside Flatpak `XDG_DATA_HOME` points to
`~/.var/app/io.github.ukimaka.OctoBeat/data`, so the sandbox has its own copy.
On the first Flatpak launch `migrate_old_data()` copies the native data
directory (database, WAL files, profile, SomeDL data) into the sandbox.
`--filesystem=home` makes the native paths readable, so the imported
`/home/<user>/Music/...` entries keep working unchanged.  The native
`~/.config/MusicPlayer/MusicPlayer.conf` is copied as well, so preferences such
as a custom `download_dir`, theme and language survive the move.

The copy never overwrites files that already exist in the sandbox.  For users
who ran an older Flatpak build (which imported files as bare paths without
tags), the startup sync now re-reads metadata for rows with a missing
title/artist and stores it with `update_track_metadata()`.  New files found in
the music folder are inserted through `add_tracks_with_metadata()` instead of
`add_track()`, so they get tags immediately.

## Diagnostics

The app installs a sandbox-side diagnostic command:

```sh
flatpak run --command=octobeat-diagnose io.github.ukimaka.OctoBeat
```

It prints the sandbox paths (`HOME`, `XDG_DATA_HOME`), checks access to
`~/Music`, verifies FFmpeg and the Opus/avcodec/PulseAudio VLC plugins, reports
the database location, counts tracks with missing tags or invisible files, and
plays a sample track through libVLC with the dummy audio output.

## Build

Requirements: `flatpak`, `flatpak-builder`, and the Flathub remote.

```sh
# once, if Flathub is not configured for the user installation
flatpak remote-add --user --if-not-exists flathub \
    https://flathub.org/repo/flathub.flatpakrepo

./build-flatpak.sh
```

The script runs the equivalent of:

```sh
flatpak-builder --user --force-clean --install-deps-from=flathub \
    --repo=flatpak-repo build-dir io.github.ukimaka.OctoBeat.yml
flatpak build-bundle flatpak-repo OctoBeat.flatpak io.github.ukimaka.OctoBeat
```

If your runtimes live in the system installation, run with
`FLATPAK_SYSTEM=1 ./build-flatpak.sh`.

Install the result:

```sh
flatpak install --user ./OctoBeat.flatpak
flatpak run io.github.ukimaka.OctoBeat
```

## Regenerating the Python modules

The JSON files are generated with
[`flatpak-pip-generator`](https://github.com/flatpak/flatpak-builder-tools/tree/master/pip)
using the SDK's Python 3.13, so wheels match the runtime:

```sh
python3 flatpak-pip-generator.py \
    --runtime org.kde.Sdk//5.15-25.08 \
    -r flatpak/requirements.txt \
    -o flatpak/python3-modules

python3 flatpak-pip-generator.py \
    --runtime org.kde.Sdk//5.15-25.08 \
    -r flatpak/requirements-build.txt \
    -o flatpak/python3-build-modules

python3 flatpak-pip-generator.py \
    --runtime org.kde.Sdk//5.15-25.08 \
    pycairo -o flatpak/python3-pycairo
```

`pygobject` and `mpris-server` are split manually: PyGObject must see the
installed pycairo headers, and the `mpris-server` module installs only the
pure-Python wheels with `--no-deps`.  Keep the build order from the manifest
(`pycairo` → `pygobject` → `mpris-server`).

## Permissions

* `--share=network` — YouTube search/download.
* `--socket=pulseaudio` — audio output.
* `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc` — display.
* `--filesystem=home` — the player can add any music folder; narrow this to
  `xdg-music`/`xdg-download` if you prefer a stricter sandbox.
* `--own-name=org.mpris.MediaPlayer2.MusicPlayer` — media keys.
* `--talk-name=org.kde.StatusNotifierWatcher`,
  `--talk-name=org.freedesktop.Notifications` — tray icon and notifications.

## Verified

The manifest was built and installed locally:

* `flatpak-builder` completed, including VLC 3.0.24 and PyGObject.
* `flatpak run io.github.ukimaka.OctoBeat` starts; MPRIS registers.
* `flatpak run io.github.ukimaka.OctoBeat --somedl-cli --help` works.
* libVLC plays WAV/MP3/FLAC/M4A/OGG and Opus files with the `dummy` audio
  output (Opus previously failed with `Codec not supported`).
* A fresh sandbox imports the native `~/.local/share/OctoBeat/music.db` with
  titles, artists and playlists intact; a sandbox database created by the
  older build is repaired on startup (113/113 tracks got metadata back).
* `flatpak build-bundle` produced `OctoBeat.flatpak` (~87 MB).
* YAML, AppStream metadata and the `.desktop` file validate.
