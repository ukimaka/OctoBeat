# OctoBeat Rust Port Plan

## Status

- Branch: `rust-port` (worktree).
- Python `main` remains stable.
- M0 is in progress.
- Two core units are ported and gated:
  - `metadata_normalize.py` — 1,316/1,316 cases (`PILOT-001.md`);
  - `cover_provider.py` — 240/240 cases (`PILOT-002.md`).
- Core code lives in `rust/`; the C++/Qt UI and packaging live in `desktop/`.
- The generated port map is in `rust/PORT_MAP.md` (2 of 67 units).

## Milestones

| Milestone | Duration | Deliverables | Done when |
|---|---:|---|---|
| **M0. Baseline & harness** | 1 week | Branch/worktree, ADR, plan, tooling notes, baseline metrics, reference screenshots, DB/audio fixtures, CI skeleton | Docs and fixtures are reproducible; baseline recorded |
| **M1. Core foundation** | 2 weeks | Rust workspace, `db`, `paths`, migrations, config snapshot, logging, cxx bridge skeleton | Opens old `music.db`, migrates, tests pass |
| **M2. Library data** | 3 weeks | `lofty`, covers, normalization, scanner, watcher, import/rescan, CLI | 114 Opus + synthetic formats read correctly |
| **M3. Playback** | 3 weeks | C++ VlcEngine, Rust controller, crossfade, loudness, queue/repeat/shuffle, session, MPRIS | Headless tests; Opus/M4A/WebM; crossfade boundaries |
| **M4. UI base + Library** | 4 weeks | Qt6 shell, QSS, icons, library, delegates, search/sort, context menu, DnD, Next in queue | Screenshots at 100/125/150%, 6 themes, EN/RU |
| **M5. Playlists + PlayerBar + Settings** | 3–4 weeks | Playlist grid/detail, covers, descriptions, bulk add, player bar, all settings, zoom, language | Create/delete/reorder; settings persist |
| **M6. Lyrics + Profile** | 3–4 weeks | LRCLIB, panel, editor, fullscreen, karaoke, offset; profile, BBCode, achievements, top tracks | Lyrics and profile match the Python app |
| **M7. Downloads + Import** | 3–4 weeks | yt-dlp search, SomeDL, formats, cookies, progress/cancel, CSV, rescan, ffmpeg dialog | Mock tests + one real download; cancellation/errors |
| **M8. Mini/Tray/Trim/Updater** | 3–4 weeks | Mini-player, tray, trim/waveform, updater, About/licenses | All windows and flows present |
| **M9. Packaging/QA/Beta** | 4–6 weeks | Flatpak, AppImage, Windows Inno, auto-update, CI, migration, performance, bugfix | Clean install Linux/Windows; old library migrates; no Python needed |

Estimated total: **6–7 months full-time** for 1.0; MVP after M5 is **~13–16 weeks**; beta after M7.

## Module map

| Domain | Python now | Target | Notes |
|---|---|---|---|
| Data | `db.py`, `paths.py`, `path_utils.py` | Rust `db`, `paths` | Schema/migrations 1:1, backup, WAL |
| Metadata | `metadata.py`, `metadata_normalize.py`, `audio_tags.py`, `cover_provider.py`, `metadata_cache.py` | Rust `tags`, `normalize`, `covers` | `lofty`; Opus/ID3/MP4/Vorbis; sidecar covers; badges |
| Scanner | `workers.py` (Import/Rescan/FolderScan), `music_watcher.py` | Rust `scan`, `watch` | `notify` + 2.5 s debounce |
| Playback | `vlc_backend.py`, `player.py`, `controller.py`, `session.py` | C++ `VlcEngine` + Rust `playback` | Crossfade, queue, repeat/shuffle, restore |
| Lyrics | `lyrics_api.py`, `lyrics_manager.py` | Rust `lyrics` | LRCLIB, LRC parser, offset, cache |
| Downloads | `somedl_integration.py`, `ytdlp_support.py`, `youtube_worker.py`, `cookies_store.py` | Rust `downloads` | CLI sidecars, progress, cancel, CSV |
| Profile/stats | `db.py` profile functions, `profile_ui.py` stats | Rust `profile` + C++ UI | Achievements, top tracks, listening time |
| Settings | `settings_page.py`, QSettings, `paths.py` | C++ `Settings` + Rust snapshot | QSettings stays for v1 |
| UI shell | `main.py`, `main_window.py`, `title_bar.py`, `appearance.py`, `styles.py`, `ui_common.py`, `pixmap_utils.py` | C++ | 1:1 port, reuse QSS |
| Library | `library_tab.py`, `library_tree.py`, `delegates.py`, `next_track_island.py` | C++ | Custom delegates, DnD |
| Playlists | `playlists_ui.py`, `playlist_widgets.py`, `bulk_dialogs.py`, `dialogs.py`, `track_menu.py`, `track_actions.py` | C++ UI + Rust mutations | Covers, descriptions, DnD |
| Player bar | `player_bar.py` | C++ | Timeline, controls, volume |
| Lyrics UI | `lyrics_panel.py`, `lyrics_overlay.py`, `karaoke_overlay.py`, `lyrics_dialog.py` | C++ | Fullscreen, karaoke |
| Profile UI | `profile_ui.py`, `profile_widgets.py`, `profile_assets.py`, `account_menu.py` | C++ | BBCode, avatar/banner |
| Settings UI | `settings_page.py`, `settings_dialog.py`, `dependency_dialog.py` | C++ | Sections, themes, zoom, language |
| Downloads UI | `youtube_dialog.py`, `import_flow.py` | C++ + Rust | Search, progress, cancel |
| Mini/tray/hotkeys | `mini_player.py`, `tray_icon.py`, `hotkeys.py` | C++ | Frameless, tray, shortcuts |
| Trim | `trim_dialog.py`, `trim_waveform.py`, `workers.py` (TrimWorker) | C++ UI + Rust audio | `symphonia` peaks, ffmpeg export |
| MPRIS | `mpris_integration.py` | C++ QtDBus for v1 | Logic in Rust; can move later |
| Updater | `updater.py` | Rust + C++ UI | GitHub releases, AppImage/EXE |
| Dependencies | `dependencies.py`, `dependency_dialog.py` | Rust + C++ UI | ffmpeg check/install |
| Diagnostics | `qt_diagnostics.py`, `qt_lifecycle.py`, `playback_trace.py` | C++ + Rust logging | Unified log |
| Translations | `translations.py` | C++ JSON map | Keys preserved, RU/EN |
| Themes/icons | `styles.py`, `themes/*.qss`, `icons/*.svg` | C++ | QSS + SVG recoloring |
| Packaging | `OctoBeat.spec`, `installer.iss`, Flatpak, CI | CMake/Cargo/Flatpak/Inno | Replace Python packaging |

## Testing strategy

- **Oracle:** the Python app stays runnable until cutover.
- **Core units:** `rust-anything record` + `diff` + `gate` for every migrated Python module.
- **Real inputs:** 114 Opus files from `/home/baka/Music/` locally; synthetic MP3/FLAC/OGG/M4A/WebM/WAV generated with ffmpeg in CI.
- **Database:** copies of `music.db` (including the old schema without `cover_path`/`lyrics_manual`); never touch the live DB.
- **Lyrics:** recorded LRCLIB responses and LRC fixtures; no network in unit tests.
- **Controller:** deterministic sequences for queue, repeat, shuffle and crossfade with a mock player.
- **Downloads:** recorded `somedl`/`yt-dlp` output; one optional network integration test.
- **UI:** side-by-side screenshots at 100/125/150%, six themes, EN/RU; only documented visual differences allowed.
- **Performance:** startup, RSS, scan time for 120 and 10,000 tracks.
- **CI:** Linux (fmt/clippy/tests + Flatpak), Windows (build/tests + Inno Setup), Qt offscreen tests.

## Definition of done (v1)

- Opens and migrates an existing `music.db` and QSettings with no data loss.
- All user-facing features from the current README are present.
- Opus and the other supported formats play; crossfade and loudness work.
- Library/playlists/search/sort/DnD; covers/descriptions; queue/repeat/shuffle.
- Lyrics, karaoke, profile/BBCode/achievements, downloads/CSV, mini-player, tray, trim, updater.
- Flatpak, AppImage and Windows installer build from CI.
- No Python runtime is required; `yt-dlp`/SomeDL are self-contained sidecars.
- The port map shows every core unit ported and gated; screenshot differences are documented.

## Next actions

1. Finish M0: baseline metrics, fixtures, CI skeleton, docs committed.
2. M1: Rust workspace + `db`/`paths`; record and port `path_utils.py` and `db.py`.
3. M2: `metadata.py`, covers, scanner.
4. M3: playback engine + controller.
