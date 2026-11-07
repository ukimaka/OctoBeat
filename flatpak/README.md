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
* libVLC plays a WAV file (`State.Ended`, correct 1000 ms length) with the
  `dummy` audio output.
* `flatpak build-bundle` produced `OctoBeat.flatpak` (~87 MB).
* YAML, AppStream metadata and the `.desktop` file validate.
