# OctoBeat

A lightweight, native desktop music player for people who are tired of Electron bloat and streaming subscriptions. Built entirely in Python (PyQt5) and SQLite.

## 💡 Why OctoBeat?
Most modern players either eat 500MB of RAM or force you into a streaming ecosystem. **OctoBeat** is built for those who prefer local MP3/FLAC files, care about performance, and want modern features without the bloat.

## ✨ Features
- **Blazing fast:** Native PyQt5 UI, zero web views.
- **Local-first:** Advanced folder management, custom playlists, and smart sorting.
- **YouTube Integration:** Search, download, and smartly embed metadata & covers (via `yt-dlp`).
- **Synced Lyrics:** Beautiful full-screen karaoke mode powered by LRCLIB.
- **Audio Engineering:** Crossfade (equal-power curve), loudness normalization.
- **Social (Optional):** Sync your stats and share playlists with friends via a self-hosted FastAPI backend.
- **Customizable:** Light/Dark themes, RU/EN localization, interface scaling.

## 🚀 Installation (Linux)
1. Clone the repository: `git clone https://github.com/zak2007asdas20071-rgb/OctoBeat.git`
2. Go to the folder: `cd OctoBeat`
3. Create virtual environment: `python -m venv .venv`
4. Activate it: `source .venv/bin/activate.fish`
5. Install dependencies: `pip install -r requirements.txt`
6. Run: `python main.py`

## 🛠️ Tech Stack
- **Language:** Python 3.10+
- **GUI:** PyQt5
- **Database:** SQLite
- **Downloader:** yt-dlp
- **Backend (Optional):** FastAPI
