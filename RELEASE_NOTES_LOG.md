# OctoBeat — Bug Fix Log

Running list of fixes for GitHub release notes (newest first).

## Unreleased

- Tuned the libVLC instance for a faster audio device wake-up. Added
  `--file-caching=1500` and `--network-caching=1500` to `_INSTANCE_OPTIONS`
  so VLC reads a little ahead before playback, giving a suspended audio
  device (PipeWire + USB headset) time to resume and fill its buffer, and
  `--aout=pulse` to talk to PulseAudio/pipewire-pulse directly instead of
  probing every audio driver on start. Verified offscreen: the app starts,
  plays and seeks with the new flags and no tracebacks; a seek to 30 s is
  applied in ~46 ms, so the larger cache does not slow seeking down.
- Stopped redundant libVLC volume calls. `VlcAudioPlayer` now remembers the
  last successfully applied volume (`_last_applied_volume`) and
  `_apply_volume()` returns immediately (logged as `volume.apply.skip`) when
  the value is unchanged, instead of rebuilding the audio chain with a
  pointless `audio_set_volume()`. The value is reset when new media is
  loaded/released and set to 0 when the output is muted for a seek, so the
  real volume is always restored after seeking. A pending volume that fails
  to apply on the Playing event is now retried on `TimeChanged` events
  (~70 ms) rather than waiting for the 5 s safety poll. Verified offscreen:
  only the two necessary `audio_set_volume()` calls per play+seek remain, the
  terminal no longer spams volume changes, and pause/resume still work.

- Fixed first-play stutter caused by position polling: the UI clock is now
  driven by libVLC `TimeChanged` events instead of a manual `get_time()` call
  every 100 ms. The manual poll was taking the libVLC lock while the PipeWire
  output was still warming up and broke the audio buffer. The safety poll is
  now a single-shot 5 s delayed start followed by a 700 ms interval, and it
  skips `get_time()` entirely while `TimeChanged` events keep arriving (they
  are the primary source). Seek still works: `safe_seek()` keeps its forced
  position update and restarts the poll immediately after a successful seek
  (no start delay), so the slider is never frozen. Verified offscreen with a
  real track: 0 `get_time()` calls during playback, seek to 30 s landed at
  31.9 s, pause/resume toggled state correctly.
- Fixed first-play stutter caused by cover extraction in the GUI thread:
  `LibraryTab._refresh_next_track()` used to call `metadata.extract_cover()`
  synchronously right when playback started, so reading tags and image data
  from disk blocked the main thread during audio warm-up. The Next-in-queue
  island now shows its text immediately and defers the cover extraction by
  2500 ms (`_NEXT_COVER_DELAY_MS`); a token check discards stale results when
  the next track changes. `NextTrackIsland.set_cover()` applies the deferred
  image. Tracing shows `ui.next_track.cover_deferred` at playback start and
  the actual `cover.extract.start` ~2.5 s later.

- Added A/B test flag `OCTOBEAT_DISABLE_LYRICS=1` to completely disable
  lyrics background worker startup. With this flag set, `set_track()` only
  renders cached lyrics (if any) and never spawns a network thread, allowing
  clean comparison of first-track stutter with/without lyrics activity.
- Removed the delayed lyrics start again: the lyrics worker is launched
  immediately on `set_track()`, as before. The first-play stutter turned out
  to come from VLC instance settings and redundant volume calls, not from the
  GIL during parsing, so the 6 s delay bought nothing and only made lyrics
  appear late. `_FIRST_TRACK_LYRICS_DELAY_MS` and the `QTimer` deferral are
  gone; the `OCTOBEAT_DISABLE_LYRICS=1` A/B flag is kept.
- Added `time.sleep(0)` yields in `parse_lrc()` and `_parse_lrc_words()`
  loops so long LRC files release the GIL more frequently, reducing the
  chance of blocking the audio thread during parsing.
- Verified with offscreen runs: no tracebacks, `lyrics.delayed_start`
  appears in trace at ~17 ms and `lyrics.worker.start` follows at ~6 s;
  with `OCTOBEAT_DISABLE_LYRICS=1` the worker is never created.

- Fixed `TypeError: log() got multiple values for argument 'event'` in the
  temporary first-play trace. `playback_trace.log()` declared `event` as its
  first parameter, while the VLC event hook passed `event=` as a data field
  in the same call. The parameter is now positional-only (`name`), so event
  names and every other keyword field are logged without collisions. Also
  audited all 89 trace calls (VLC events, poll ticks, volume, lyrics, cover)
  for the same conflict. Verified with an offscreen run using a real track:
  `vlc.event`, poll, volume, lyrics and cover lines are written to
  `first-play-trace.log` and no tracebacks appear in the console.

- Added temporary first-play diagnostics (no playback changes). With
  `OCTOBEAT_TRACE_FIRST_PLAY=1`, the app writes an ordered trace of the
  first track after launch to `first-play-trace.log` in the data directory:
  raw VLC events (LengthChanged/Playing/TimeChanged), every position-poll
  tick, every volume application, `lyrics_checked` plus saved-lyrics state,
  lyrics fetch start/finish, and cover extraction/network start/finish.
  Tracing stops on track end, stop, crossfade, or the next track. The log
  path can be overridden with `OCTOBEAT_TRACE_FIRST_PLAY_LOG`.

- Fixed the YouTube download progress dialog hanging at 0%. `_on_download()`
  called `self.hide()` on the search dialog, and `QDialog::setVisible(False)`
  exits the nested `exec_()` loop. The import flow then treated the dialog as
  cancelled and dropped its reference, so the worker's `progress`/`finished`
  signals no longer reached the dialog. The search window now stays under the
  modal progress dialog; progress reaches 100% and the dialog closes itself.
- Ctrl+C no longer hangs the app on a stuck background thread. `main.py`
  installs SIGINT/SIGTERM handlers with a Python tick timer, closes modal
  windows, and starts a 6-second watchdog that logs and exits with code 130.
  `wait_for_background()` is now bounded (10 s total, 2 s second chance on a
  normal close), logs every unfinished thread/pool, and reports whether
  anything was left running; `main.py` then uses `os._exit()` instead of
  letting Qt destroy a live QThread and abort.
- Added `cookiesfrombrowser` support. Settings → YouTube now has a browser
  selector (Firefox, Chrome, Chromium, Brave, Edge, Opera, Vivaldi, Safari);
  the choice is passed to yt-dlp for search and download, including CSV
  import and cover lookup. yt-dlp console output is silenced through a quiet
  logger, and bot-check / unreadable-cookie errors are shown as a readable
  dialog with instructions instead of raw console errors.
- Restored the missing `note` import in workers.py. RescanWorker called it on
  its first line, so every rescan died with NameError before touching the
  library. The module now imports note from qt_diagnostics, and the rescan
  path was re-run against the real library.
- Added a thread-to-worker strong registry (qt_diagnostics.hold_worker) and
  wired it into every moveToThread() site: import/rescan/remote-playlist,
  YouTube search/download, and trim waveform/audio. A moved QObject worker
  now stays alive until its QThread emits finished, even after the owning
  widget drops its attribute or retire_thread() detaches a slow thread.
- shutdown_diagnostics() is now called after the Qt event loop returns in
  main.py, so faulthandler is flushed/disabled and the thread/pool/worker
  registries are cleared on a normal exit.
- Made deliberate shutdown waits visible in qt-fatal.log: when
  wait_for_background() blocks on a running QThread or QThreadPool it writes
  an [WARN] line before waiting and the elapsed time afterwards.
- Gave every moved worker its own objectName (import-files-worker,
  rescan-worker, import-csv-worker, remote-playlist-worker,
  trim-audio-worker, trim-waveform-loader, yt-search-worker,
  yt-download-worker). QThread subclasses were already named by
  track_thread(); fatal reports now also print worker='...'.
- Removed the widget parent from the YouTube thumbnail QThreadPool. The pool
  is now named yt-thumb-pool, prevents new thumbnail jobs during shutdown,
  and is waited for fully with QThreadPool.waitForDone() when the dialog
  closes and on QApplication.aboutToQuit. No timeout-based deletion is used;
  waits longer than 2 seconds are recorded in the diagnostics log.
- Added objectNames to every background QThread and QThreadPool
  (yt-search, yt-download, yt-thumb-pool, cover-loader, lyrics, rescan,
  import-*, trim-*, update-*, profile-*, friends-request, token-check, auth)
  so fatal reports and thread dumps identify the responsible worker.
- Added qt_diagnostics: a Qt message handler for fatal thread messages,
  faulthandler.enable(), wrapped sys.excepthook, a 120-action ring buffer,
  and a separate qt-fatal.log containing the thread name, live threads/pools,
  last actions, and Python stacks.
- Hardened background-thread ownership: QThread objects are kept in a strong
  registry while running, all remaining local QThread creations are tracked,
  and no QThread is parented to a widget. MainWindow shutdown now
  waits fully for all tracked QThreads and QThreadPools (slow waits logged).
  The downloaded-track metadata fetch stays inside the detached yt-download
  thread; automatic metadata tagging is unchanged.
- Fixed regression from the deferred progress-dialog cleanup: the deferred
  completion callback lost the worker's finished() arguments. Rescan needs
  meta_updated, loudness_processed, and loudness_failed, so the delayed call
  raised TypeError and PyQt aborted with SIGABRT. The deferred closure now
  captures the original signal arguments and forwards them to on_finished();
  the update and trim delayed callbacks were audited for the same mismatch.
- Applied the safe thread-retirement mechanism to both YouTube dialog
  QThreads (search and download): they are no longer parented to the widget
  and are retired through qt_lifecycle.retire_thread(). Audited every QThread
  creation in the project (profile, account, friends, lyrics, auth, updates,
  import flow, trim): no remaining QThread is created with a widget parent.
- Fixed SIGSEGV in the import/rescan/update/trim progress dialogs: a queued
  progress event could run while QProgressDialog::setValue() was pumping
  events, and the finished handler deleted the dialog inside that call.
  Progress slots now ignore stale or already-deleted dialogs and defer the
  final cleanup until the outermost setValue() returns.
- Fixed "QThread: Destroyed while thread is still running": added
  qt_lifecycle.retire_thread() and removed widget parents from background
  network/cover threads. A thread that misses the shutdown wait is detached
  and kept alive until it actually finishes instead of being deleted with
  its page or dialog.
- Fixed trimming closing before its worker thread finished: the dialog now
  accepts only after thread.finished, while error/cancel paths detach a
  still-running thread safely.
- Fixed QPixmap creation in CoverLoader's background thread: the loader now
  emits QImage, and the profile slot creates QPixmap on the GUI thread.
- Extended the modal backdrop to file and folder pickers: choosing music
  files, covers, cookies, avatars, banners, or the download folder now dims
  the main window with the same 40% layer and restores it when the picker
  closes.
- Added a premium modal backdrop: all custom dialogs and standard progress
  dialogs now dim the window behind them with a 40% black layer (alpha 102)
  and fade it out smoothly on close. Dialogs keep an opaque theme
  background, stay fully interactive, and nested dialogs share one dim
  layer without flicker.
- Fixed Settings dropdowns: language, zoom, and theme combo boxes now open
  on mouse release and stay open until an item is picked, instead of
  closing as soon as the button is released.
- Reworked the YouTube download progress window into a frameless custom
  dialog with a fully opaque dark background: no system title bar, white
  frame, or OS buttons — only the title, progress bar, and Cancel button.
- Fixed main tab text clipping: 14px tab font, 6px 16px padding, and
  natural (non-expanding) tab widths with the tab bar font matching the tabs.
- Fixed Settings navigation clicks: standard single-row selection with mouse
  tracking, no context menu or drag behavior, and only currentRowChanged
  driving the settings stack.
- Fixed first-play audio stutter: position polling now starts only after
  MediaPlayerLengthChanged, and the initial gain volume is deferred to
  MediaPlayerPlaying.
- Restored the full-size YouTube search dialog and moved downloads into a
  separate compact 250×150 progress dialog with Cancel.
- Fixed Settings navigation clicks: disabled context-menu behavior and
  enforced normal single-selection/currentRowChanged navigation.
- Hardened loudness normalization: Playing event applies the gain once,
  log confirms the actual VLC volume, and missing loudness defaults to 1.0.
- Enlarged main tab labels (8px 20px padding, 15px font).
- Reorganized Friends into Variant A: friends list on top, requests section
  at the bottom behind a divider that disappears when there are no requests.
- Moved Settings out of the main tab bar: it now opens from the avatar
  dropdown menu as a hidden page.
- Restyled the Friends list as osu!-style cards: 48px circular avatar,
  bold nickname with @username, green/gray presence dot, and a
  "View Profile" button via setItemWidget().
- Fixed deleted-file spam: cover extraction and delegates skip missing paths
  and show a placeholder; startup sync now purges missing tracks from the DB.
- Fixed phantom playlist row: empty playlists no longer add a fake
  "Unknown Title"/"Nothing added" item.
- Fixed Random ignoring the selected folder: it now filters tracks by the
  current download_dir exactly like the library.
- Fixed yt-dlp "Unknown Title": downloaded/renamed files are tagged, read
  back via read_metadata(), and saved to the DB immediately.
- Fixed loudness normalization: loudness values are normalized from the DB,
  VLC volume is clamped to 0–200 and re-applied after playback starts.
- Fixed BBCode editor white background on dark themes: the app palette now
  provides theme-aware Base/Text roles, and QDialog/QTextEdit resolve
  palette(window)/palette(base) from the active theme.
- Fixed black text on dark dialogs: populated WindowText/Text/ButtonText
  palette roles from each theme's QSS; removed hardcoded white tab text.
- Fixed playlist detail gradient on light themes: gradient now uses
  palette(window) as its bottom color and derives lightness from the actual
  palette, with a smooth cover-to-background blend in both themes.
- Fixed unclickable dropdowns at 125–150% zoom: settings rows let the text
  column shrink, combos have bounded widths, and pages scroll vertically.
- Fixed overly tall YouTube dialog: compact layout with 640×360 default size
  and a 400 px height cap.
- Removed redundant `QSizeGrip` that rendered as a black square overlapping
  the player bar; window edge resizing is handled natively.
- Fixed crash when deleting a playlist: corrected `CustomConfirmDialog`
  argument order (parent first).
- Fixed SIGSEGV after metadata rescan: release libVLC media on the GUI thread
  before the worker rewrites tags/renames files, and removed the unsafe
  blocking cross-thread release signal.
- Fixed rescan completion race: worker thread and progress dialog are now
  cleaned up before the completion dialog opens its modal event loop.
- Fixed cyclic playback freezing after timeline seek: poll timer state is
  restored from the seek snapshot, seeks are re-entrancy guarded, and stale
  Paused/Stopped events can no longer leave the player stuck.
- Hardened the VLC event queue: bounded per-tick draining prevents event
  floods from blocking the Qt event loop.
