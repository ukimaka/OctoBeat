# Port map: rust-port

2 of 67 units have a Rust port; no original changed since it was recorded.

## Ports

| Unit | Crate | In Rust | Kept in the original | Cases | Last diff | Original |
| --- | --- | --- | --- | ---: | ---: | --- |
| `cover_provider.py` | `rust/cover-provider-rs` | `get_cached_source_for_path` | - | 240 | 240/240 | unchanged |
| `metadata_normalize.py` | `rust/metadata-normalize-rs` | `normalize_track_query`, `normalize_artist_name`, `split_featured_artists`, `clean_featured_title`, `metadata_needs_refresh` | - | 1316 | 1316/1316 | unchanged |

## Not ported yet

In the order `analyze` suggests.

| Unit | Lines | Exports | Readiness |
| --- | ---: | ---: | ---: |
| `session.py` | 100 | 2 | 89 |
| `cookies_store.py` | 90 | 4 | 85 |
| `metadata_cache.py` | 130 | 1 | 93 |
| `lyrics_dialog.py` | 148 | 2 | 90 |
| `updater.py` | 207 | 3 | 81 |
| `tray_icon.py` | 109 | 2 | 90 |
| `path_utils.py` | 106 | 7 | 80 |
| `audio_tags.py` | 129 | 2 | 86 |
| `paths.py` | 148 | 1 | 74 |
| `tools/` | 79 | 1 | 90 |
| `settings_dialog.py` | 183 | 1 | 88 |
| `karaoke_overlay.py` | 184 | 1 | 85 |
| `lyrics_overlay.py` | 182 | 1 | 85 |
| `appearance.py` | 93 | 1 | 91 |
| `lyrics_panel.py` | 183 | 1 | 86 |
| `track_menu.py` | 234 | 1 | 82 |
| `hotkeys.py` | 134 | 1 | 86 |
| `next_track_island.py` | 100 | 1 | 89 |
| `profile_assets.py` | 157 | 0 | 86 |
| `account_menu.py` | 132 | 1 | 88 |
| `dependency_dialog.py` | 187 | 1 | 85 |
| `title_bar.py` | 123 | 1 | 88 |
| `library_tree.py` | 227 | 1 | 76 |
| `music_watcher.py` | 241 | 1 | 73 |
| `ui.py` | 17 | 0 | 100 |
| `version.py` | 17 | 0 | 100 |
| `bulk_dialogs.py` | 284 | 1 | 80 |
| `main.py` | 207 | 1 | 75 |
| `playback_trace.py` | 152 | 6 | 76 |
| `player_bar.py` | 306 | 1 | 80 |
| `dialogs.py` | 41 | 0 | 88 |
| `player.py` | 383 | 1 | 72 |
| `youtube_worker.py` | 267 | 2 | 73 |
| `mpris_integration.py` | 221 | 4 | 76 |
| `qt_lifecycle.py` | 95 | 2 | 77 |
| `db.py` | 620 | 50 | 63 |
| `import_flow.py` | 362 | 1 | 73 |
| `lyrics_api.py` | 316 | 2 | 71 |
| `trim_dialog.py` | 568 | 1 | 72 |
| `controller.py` | 447 | 1 | 64 |
| `dependencies.py` | 492 | 14 | 61 |
| `library_tab.py` | 556 | 1 | 63 |
| `qt_diagnostics.py` | 401 | 11 | 64 |
| `ytdlp_support.py` | 444 | 12 | 61 |
| `pixmap_utils.py` | 295 | 15 | 64 |
| `lyrics_manager.py` | 415 | 3 | 59 |
| `somedl_integration.py` | 499 | 6 | 60 |
| `track_actions.py` | 415 | 1 | 64 |
| `trim_waveform.py` | 431 | 2 | 56 |
| `ui_common.py` | 329 | 11 | 59 |
| `settings_page.py` | 725 | 2 | 68 |
| `translations.py` | 615 | 1 | 72 |
| `delegates.py` | 557 | 1 | 58 |
| `playlist_widgets.py` | 498 | 2 | 54 |
| `playlists_ui.py` | 653 | 1 | 62 |
| `mini_player.py` | 725 | 1 | 61 |
| `profile_ui.py` | 723 | 2 | 56 |
| `dialog_base.py` | 690 | 6 | 55 |
| `profile_widgets.py` | 661 | 5 | 53 |
| `youtube_dialog.py` | 749 | 3 | 47 |
| `styles.py` | 686 | 10 | 40 |
| `vlc_backend.py` | 1075 | 6 | 41 |
| `main_window.py` | 1094 | 2 | 37 |
| `metadata.py` | 785 | 12 | 28 |
| `workers.py` | 810 | 7 | 29 |

Regenerate with `rust-anything map --write`. Commit this file: when the original changes upstream, the next map marks every port whose recording it outdated.
