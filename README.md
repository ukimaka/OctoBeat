# OctoBeat

A lightweight, native desktop music player for people who are tired of Electron bloat and streaming subscriptions. Built entirely in Python (PyQt5) and SQLite.

## 💡 Why OctoBeat?
Most modern players either eat 500MB of RAM or force you into a streaming ecosystem. **OctoBeat** is built for those who prefer local MP3/FLAC files, care about performance, and want modern features without the bloat.

## ✨ Features
- **Blazing fast:** Native PyQt5 UI, zero web views.
- **Local-first:** Advanced folder management, custom playlists, and smart sorting.
- **MusicBrainz Metadata:** Official metadata and covers (Cover Art Archive), with YouTube as a fallback.
- **YouTube Integration:** Search and download tracks with `yt-dlp`.
- **Synced Lyrics:** Beautiful full-screen karaoke mode powered by LRCLIB.
- **Audio Engineering:** Crossfade (equal-power curve), loudness normalization.
- **Social (Optional):** Sync your stats and share playlists with friends via a self-hosted FastAPI backend.
- **Customizable:** Light/Dark themes, RU/EN localization, interface scaling.

## 📋 Prerequisites
- **Python 3.10+** and `pip`.
- **Linux:** install the VLC runtime with your distribution's package manager.
  OctoBeat uses libVLC and the Linux build does not bundle it:
  - Debian/Ubuntu: `sudo apt install vlc`
  - Fedora: `sudo dnf install vlc`
  - Arch: `sudo pacman -S vlc`
- **Windows:** install **64-bit VLC** matching your 64-bit Python installation.
  The Windows PyInstaller build copies `libvlc.dll`, `libvlccore.dll`, the
  required VLC runtime DLLs, and the `plugins` folder into
  `dist\OctoBeat\_internal\vlc`.
  If VLC is installed in a non-standard location, set `OCTOBEAT_VLC_DIR` to
  that directory before building.
- Install the Python dependencies from `requirements.txt` (this includes
  `python-vlc`, the Python bindings for libVLC).

## 🚀 Installation (Linux)
1. Clone the repository: `git clone https://github.com/zak2007asdas20071-rgb/OctoBeat.git`
2. Go to the folder: `cd OctoBeat`
3. Create virtual environment: `python -m venv .venv`
4. Activate it: `source .venv/bin/activate`
5. Install dependencies: `pip install -r requirements.txt`
6. Run: `python main.py`

## 📦 Building a Standalone App
PyInstaller is configured for an **onedir** build. The application is written to
`dist/OctoBeat/` with the icons, themes, and license notices included.

- **Linux:** `./build.sh`
- **Windows:** `build.bat`

The Linux build expects libVLC to be installed on the target system. The
Windows build bundles libVLC from the installed 64-bit VLC and stops with a
clear error if VLC cannot be found.

## 🛠️ Tech Stack
- **Language:** Python 3.10+
- **GUI:** PyQt5
- **Database:** SQLite
- **Downloader:** yt-dlp
- **Backend (Optional):** FastAPI
