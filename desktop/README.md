# OctoBeat (Rust + Qt 6) — developer notes

This directory contains the Qt 6 developer build. Public packages are built
from the repository root; see the top-level README.

## Requirements

- CMake 3.24+, a C++20 compiler, Rust/cargo
- Qt 6.5+ with Widgets, Svg, Network and DBus (Linux MPRIS)
- ALSA development files (`alsa-lib`) and PipeWire or PulseAudio
- ffmpeg
- `yt-dlp`, Deno and `somedl` for streaming/downloads in a source build
  (release packages bundle all of them)

On Arch:

```sh
sudo pacman -S cmake qt6-base qt6-svg qt6-declarative alsa-lib pipewire ffmpeg yt-dlp deno python-pip
pip install --user somedl
```

## Build

```sh
cmake -S desktop -B desktop/build -DCMAKE_BUILD_TYPE=Release
cmake --build desktop/build -j
```

The Rust core and the native audio engine (`rust/audio-engine`) are built
automatically by CMake and linked into `desktop/build/octobeat`. The binary
does not link against libVLC.

## Run

```sh
./desktop/build/octobeat
```

Default paths match the Python application:

- data: `~/.local/share/OctoBeat`
- database: `~/.local/share/OctoBeat/music.db`
- cache/covers: `~/.cache/OctoBeat`
- music: `~/Music` (`QStandardPaths::MusicLocation`)
- QSettings: organization `MusicPlayer`, application `MusicPlayer`

Make a backup of `music.db` before the first run. The core removes tracks whose
files no longer exist and creates an upward-compatible schema migration.

### Test with a copy

```sh
mkdir -p /tmp/octobeat-dev
cp ~/.local/share/OctoBeat/music.db /tmp/octobeat-dev/music.db
./desktop/build/octobeat \
  --data-dir /tmp/octobeat-dev \
  --db /tmp/octobeat-dev/music.db \
  --cache-dir /tmp/octobeat-dev/cache \
  --music-dir "$HOME/Music"
```

## Native audio engine

Playback is handled by `rust/audio-engine`:

- Symphonia 0.6 for FLAC, MP3, AAC/M4A, AAC/ADTS, Ogg/Vorbis, WAV, ALAC,
  AIFF and CAF;
- `symphonia-opus` for Ogg/WebM Opus;
- cpal output at the source sample rate (including 24-bit/192 kHz content);
- a dedicated decoder thread, a lock-free ring buffer and a cpal callback
  for each of the two crossfade slots, so the UI thread never touches audio;
- the streaming ADTS FIFO is decoded directly, without VLC.

The engine is behind `desktop/src/audio/AudioEngine.cpp`; the Qt side keeps
the same signals and transport semantics as before.

## What works in this build

- Rust core: SQLite schema/migrations, missing-track cleanup, metadata,
  embedded covers, recursive scanner.
- Qt 6 Widgets shell: custom title bar, frameless window, single-instance,
  system tray.
- Library: folder tree (create folders, drag tracks between folders),
  local file import, scan, search, reversible sort with arrows, cached covers,
  hover play, hover trash, track context menu.
- Playback: native Rust engine (Symphonia + Opus + cpal), play/pause,
  previous/next, seek, volume, repeat
  off/all/one, shuffle, end-of-track handling.
- Playlists: single-click grid with hover play overlay, black page, gradient
  detail page with search/sort, glass Add Tracks dialog with existing-track
  checkmarks, remove with Delete/trash/context menu.
- Streaming home: recently played, music-only recommendations built from
  YouTube Music (no related news/politics), recent artists and playlists;
  right-click a card to remove it from home. The scrollbar is suppressed
  while the home page is rebuilt, the extra greeting/subtitle block was
  removed, and the currently playing card keeps a brand-coloured Pause
  button visible (other cards show Play on hover).
- Streaming search: Spotify-style glass suggestion panel with mixed music
  tracks, artists, albums and playlists, keyboard navigation, search history
  and a full search page with All/Tracks/Artists/Playlists filters. Search
  uses YouTube Music results, so reactions, podcasts and gameplay are filtered
  out; a regular YouTube search is used only as a fallback.
- Streaming artist/playlist pages: music-only tracks from YouTube Music,
  plus albums/playlists. Tracks are matched by channel id, so artists with
  the same name are not mixed; " - Topic" is stripped. The artist page has
  Play artist and a Show all tracks button that lazy-loads every album track
  (first 20 stay visible until expanded); playlist pages/cards have Play all.
  Channel uploads and junk playlists are filtered; entities with a known
  popularity below 1000 plays/subscribers are hidden.
- Extended search is artist-first: artists with matching tracks/albums
  indented under them (up to 20), an exact artist query adds the whole
  discography. Back/result text sits on the same row as the search field;
  search and browse results are cached for 24 h and Clear ALL Cache removes
  them.
- All streaming covers are cropped to their slot without blurred side bars;
  the library and playlist covers use the same crop.
- Streaming track context menu: Download and Add to queue. The queue has a
  visible panel from the header button (play, remove, clear) and starts the
  next track when the current one ends.
- Streaming transport: the timeline uses a separate playback clock (the
  FIFO stream has no container duration), so it moves even for live streams;
  the real duration comes from yt-dlp. Play/pause, next, previous, seeking
  and the mini-player work during streaming. Seeking waits for the new FIFO
  to prebuffer before switching; the old audio keeps playing meanwhile.
- Streaming queue preload: the next queued track is resolved and buffered
  ~10 s before the end, then crossfaded when Crossfade is enabled. A manual
  track switch also keeps the old stream until the new one is ready.
- Streaming shuffle/repeat: shuffle applies to artist/playlist queues,
  repeat-one loops the current stream, repeat-all restarts the collection.
- Streaming status messages hide after 500 ms. The mini-player loads the
  stream cover asynchronously after playback starts.
- Mini-player stays compact (390×188) and shows the current streaming track,
  artist, elapsed time and playback state. The full Streaming search list
  uses larger 80 px rows, 56 px covers and 16/13 px title/subtitle fonts.
- MPRIS on Linux: `playerctl`, media keys and desktop widgets can read the
  current local track or stream, play/pause/stop, go next/previous, seek, set
  volume and change shuffle/loop. The bus name is
  `org.mpris.MediaPlayer2.octobeat`.
- Profile statistics: local plays are written to `play_history`, actual
  listening seconds are accumulated once per second and flushed every five
  seconds, so the Profile tab shows live top tracks and total listening time.
- Profile achievements: four badges (tracks, playlists, listening time,
  library age) with Bronze/Silver/Gold/Diamond levels and progress tooltips.
- CSV import: Settings → Import from CSV reads Exportify files
  (`Track Name`, `Artist Name(s)`), downloads one track at a time through
  SomeDL (Opus with embedded tags/cover) into the music folder, shows
  overall progress, lists failures and scans the library once at the end.
  Cancel stops the current download and keeps already imported tracks.
- Crossfade (off by default): Settings → Enable Crossfade blends the end of a
  local track into the next one over about three seconds using two native
  playback slots. Queue jumps and streams stay hard cuts. Crossfade uses the same
  repeat/shuffle context and is skipped for tracks shorter than half a second.
- Streaming and downloads: direct YouTube search; audio-only HLS via
  `android_music`, remuxed by ffmpeg into a local ADTS AAC FIFO and decoded
  by the native Rust engine. Right-click a result or use the hover download icon to save it with
  SomeDL into the music folder (Opus, full tags and embedded cover); the
  library rescans after download. Streaming falls back to a full yt-dlp cache
  if the fast path is unavailable. Loading states use a spinner
  with optional percentage instead of progress bars.
- Covers: square album art is unchanged; rectangular YouTube thumbnails keep
  their full frame over a blurred, darkened backdrop instead of being stretched.
- Settings: Python-style aligned rows, scrollable pages, interface zoom
  (100/125/150 via `QT_SCALE_FACTOR`, 125 default), QSS theme switching,
  music folder picker, cookies import, download format, cache clearing.
- Profile: banner, avatar, stats, About Me (basic BBCode), favorite/top tracks,
  public playlist covers; avatar button in the tab-bar corner.
- Mini-player: frameless, always-on-top, `startSystemMove()` for Wayland
  dragging, expand/close, track cover.
- Player bar matches the Python layout: current track/context, full-width
  timeline, centered transport controls, accent-coloured repeat/shuffle.
- Smooth wheel scrolling with cached covers, hover mini-play, "Next in queue".
- Karaoke: LRCLIB lyrics, synced LRC (line and word highlighting), bottom
  lyrics panel, per-track ±0.5 s offset persisted in SQLite, fullscreen lyrics
  and karaoke overlays.
- Russian UI translation (`resources/translations/ru.json`) with restart.
- Rounded translucent window corners and the OctoBeat logo in the title bar.

## Known gaps (next iterations)

- Crossfade is not implemented yet.
- MPRIS is not implemented yet.
- QML surfaces (mini-player/karaoke/cat) are planned; the current mini-player
  is a Qt Widget.
- SomeDL is required for downloads; without the CLI the download action
  shows an installation error and does not fall back to a lower-quality file.
  metadata/thumbnail.
- Profile achievements, trim editor, title-bar cat and updater are not in this
  build.
- Flatpak and Windows packaging are not in this build.

## Smoke tests

```sh
# core + database
./desktop/build/octobeat --data-dir /tmp/octobeat-dev --music-dir "$HOME/Music" --scan --smoke-test

# window screenshot
./desktop/build/octobeat --data-dir /tmp/octobeat-dev --music-dir "$HOME/Music" \
  --play-first --screenshot /tmp/octobeat-dev/window.png

# mini-player screenshot
./desktop/build/octobeat --data-dir /tmp/octobeat-dev --music-dir "$HOME/Music" \
  --play-first --mini --screenshot /tmp/octobeat-dev/mini.png

# direct search + fast HLS/FIFO streaming
./desktop/build/octobeat --smoke-fast-stream "Neurotoxin Evil"

# yt-dlp search + stream resolve (legacy smoke)
./desktop/build/octobeat --data-dir /tmp/octobeat-dev --music-dir "$HOME/Music" \
  --smoke-stream "Rick Astley Never Gonna Give You Up"
```
