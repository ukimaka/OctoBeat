## Unreleased

- Tooltips now appear after a global 1000 ms delay (`SH_ToolTip_WakeUpDelay`).
  The delay is installed through a QProxyStyle at application startup.
- Glass style extended to the settings/profile pages and all frameless dialogs
  (YouTube search, trim audio, confirm/input dialogs): the content capsule uses
  rgba background (alpha 0.78), translucent child surfaces and a 1 px border.
  Settings and profile pages use a lighter rgba panel (alpha 0.70).
- YouTube download modes in Settings → YouTube:
  - **Speed (original format)** is the default: yt-dlp downloads
    `bestaudio/best` and does not convert the audio. Output is M4A or WebM.
  - **Compatibility (MP3 320 kbps)** uses `FFmpegExtractAudio` at 320 kbps.
  - The choice is stored as `youtube_download_mode` and passed to yt-dlp for
    every download, including CSV import.
  - Native M4A tags and cover art are written with `mutagen.mp4` (`©nam`,
    `©ART`, `©alb`, `covr`); MP3 continues to use ID3/EasyID3.
  - WebM/Opus files are accepted by the library, but mutagen cannot embed tags
    in WebM; those files fall back to filename metadata and the sidecar cover.
- Browser-cookie selection was removed completely. The app now discovers
  `cookies.txt` automatically in the app data folder, `~/Music/` and the
  configured download folder. Settings → YouTube has **Import cookies.txt**
  (copies to `~/.local/share/OctoBeat/cookies.txt`, mode 0600) and
  **Delete cookies** (removes all discovered copies). Search, downloads, CSV
  import and cover lookup all pass the discovered file as `cookiefile`.

- YouTube download tuning: yt-dlp now requests only the audio stream
  (`bestaudio/best`) and uses `concurrent_fragment_downloads=4`. Every download
  prints its options, live speed in MB/s (at most one line per 2 seconds), and a
  final summary with size, elapsed time, average speed and peak speed. The
  4-way setting applies to fragmented/HLS streams; progressive YouTube audio is
  a single HTTP stream, so the log is the source of truth for actual throughput.
- UI/navigation:
  - Settings is back in the main tab bar next to Library and Playlists.
  - Left-clicking the avatar opens the profile; right-clicking opens a context
    menu with "Change avatar" and "Exit".
  - Added a system tray icon from `icons/OctoBeat.svg` with Open/Exit actions.
    The window's X button hides the app to the tray, or minimizes it to the
    taskbar when no tray is available. The tray icon's left click restores the
    window.
- Glassmorphism: menus, tooltips, the settings sidebar and the Next in queue
  card now use translucent QSS layers (alpha 0.72–0.85), 1 px borders and
  rounded corners. Standard QToolTip windows are switched to translucent
  surfaces so their rgba background is visible. Qt QSS has no true
  `backdrop-filter`; the effect uses alpha, borders and the existing menu shadow
  instead of blurring text.
- Frameless window corners are now genuinely transparent: the main window uses
  `Qt.WA_TranslucentBackground`, the central surface has an 18 px radius and an
  8 px inner inset for child widgets. When maximized, the radius/inset are
  removed so the surface fills the screen.

- Fixed cover art search for tracks with popular names (e.g. "After Dark", "Pattern Recognition", "Birdbrain").
  Previously the MusicBrainz search would first try `recording:"Title" AND artist:"Artist"` with `strict=True`,
  and if that returned no results, it would fall back to a **title-only search** (`recording:"Title"` with no artist).
  This caused tracks like "Pattern Recognition" (Neuro-sama & ODDEEO) to incorrectly match unrelated artists
  (Byzantine, Allen Ginsberg, etc.) because the title-only search has no artist context.

  The fix changes the fallback strategy:
  1. **Strict search** with both `recording` and `artist` fields (`strict=True`)
  2. **Relaxed search** with both `recording` and `artist` fields (`strict=False`) — keeps artist in query
  3. **Title-only search** only if the artist is genuinely empty/unknown

  This ensures the artist field is always passed to MusicBrainz when available, preventing wrong matches
  for popular track names. Also fixed `_artist_credit()` to properly handle MusicBrainz's joinphrase format
  (bare strings in the artist-credit array), so multi-artist credits like "Neuro-sama & ODDEEO" display correctly.

- Removed the optional server backend (ONREZA) completely. OctoBeat is now fully local:
  - `profile_ui.py` keeps only local logic: nickname, About Me (BBCode), avatar and banner
    are read from and written to `db.py` and copied by `profile_assets.py`. Removed
    `ApiClient`, `AuthDialog`, `_ProfileSyncWorker`, `_FriendProfileWorker`,
    `_sync_profile_to_server()` and every server-side profile/statistics sync.
  - `account_menu.py` no longer stores or checks auth tokens and no longer runs
    notification/statistics timers. The avatar now opens Profile on a left click and
    shows only "Change avatar" / "Exit" on a right click.
  - `settings_page.py` no longer has the Account page, login/logout actions or auth state.
  - Deleted `friends_ui.py`; removed the Friends page, the menu entry, its signals and
    friend-profile loading. `appearance.py` no longer updates that page.
  - `import_flow.py` no longer downloads someone else's playlist through the API;
    local file import, CSV import, rescan and YouTube download remain.
  - After the last `ApiClient`/`auth_ui` references were gone, deleted `api_client.py`
    and `auth_ui.py`.
  - Updated README: the profile is local, and the account/server/friends sections are gone.
- Merged `_musicbrainz_search_relaxed()` into `_musicbrainz_search(..., strict=...)`
  (one search helper instead of two) and removed trailing whitespace in
  `musicbrainz_client.py`.
- Fixed the mini-play button in library and playlist track lists: clicking the
  currently playing track now toggles pause/resume instead of restarting it from
  the beginning. Clicking another track still starts that track normally.
- YouTube search now accepts a direct video URL. A link on `youtube.com` or
  `youtu.be` is passed to yt-dlp as-is instead of being wrapped in `ytsearch`;
  plain text still uses the regular YouTube search.
- Removed the last account/auth leftovers from the UI styling (stale
  `#profileAuthButton` selector). The Account settings page and Friends tab/menu
  entry are gone; the translation dictionaries contain no account, friends or
  authorization strings.
- Removed 53 obsolete translation keys from both the English and Russian
  dictionaries: leftover friends/account strings, old playlist-dialog strings and
  unused trim/crop labels. The `en` and `ru` key sets are now identical, and every
  remaining key is referenced by the code.
