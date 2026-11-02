# OctoBeat — Bug Fix Log

Running list of fixes for GitHub release notes (newest first).

## Unreleased

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
