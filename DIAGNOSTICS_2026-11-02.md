# OctoBeat — диагностика 2026-11-02

Статус: только диагностика. Правок в коде нет, `RELEASE_NOTES_LOG.md` не изменялся.

Проверены кодовая база и локальные core-дампы (`coredumpctl`) на этой машине. Главный вывод: зафиксированный SIGSEGV при сканировании — не падение внутри `RescanWorker`, а **use-after-free QProgressDialog** при доставке queued-сигнала прогресса. Отдельно подтверждён второй класс падений — **QThread destroyed while running**.

---

## 1. Подтверждённый по core-дампам root cause SIGSEGV

### 1.1. Что именно падает

Три SIGSEGV с одинаковым стеком:

- PID 964983, 2026-11-01 20:49:24, `.venv/bin/python main.py`
- PID 1324472, 2026-11-02 00:08:48, `.venv/bin/python main.py`
- PID 1360610, 2026-11-02 00:23:45, `.venv/bin/python main.py`

Сигнал: `SIGSEGV`, `si_code: SI_KERNEL`/`SEGV_MAPERR`. В регистре на момент падения: `r12 = 100` — обрабатывался прогресс **100%**.

Точный стек (PID 1360610; в остальных дампах отличается только адрес/номер Python-кадра):

```text
#0  QProgressBar::maximum() const                 libQt5Widgets.so.5 + 0x305638
#1  QProgressDialog::setValue(int)                libQt5Widgets.so.5 + 0x3bf98b
#2  ??                                            PyQt5/QtWidgets.abi3.so + 0x15c0d5
#3  ??                                            libpython3.14.so.1.0 + 0x1d61b0
#4  ??                                            libpython3.14.so.1.0 + 0x1a4eca
#5  ??                                            libpython3.14.so.1.0 + 0x68c07
#6  ??                                            libpython3.14.so.1.0 + 0x2b6ced
#7  ??                                            PyQt5/QtCore.abi3.so + 0x1ad0b7
#8  ??                                            PyQt5/QtCore.abi3.so + 0x1b18c9
#9  QObject::event(QEvent*)                       libQt5Core.so.5 + 0x30417f
#10 QApplicationPrivate::notify_helper            libQt5Widgets.so.5 + 0x1583a7
#11 ??                                            PyQt5/QtWidgets.abi3.so + 0x2dad27
#12 QCoreApplication::notifyInternal2             libQt5Core.so.5 + 0x2d8068
#13 QCoreApplicationPrivate::sendPostedEvents    libQt5Core.so.5 + 0x2dd7ce
#14 ??                                            libQt5Core.so.5 + 0x330890
#15 ??                                            libglib-2.0.so.0 + 0x6175e
#16 ??                                            libglib-2.0.so.0 + 0x6ac50
#17 g_main_context_iteration                      libglib-2.0.so.0 + 0x6adb5
#18 QEventDispatcherGlib::processEvents           libQt5Core.so.5 + 0x32dea9
#19 QEventLoop::exec                              libQt5Core.so.5 + 0x2d60eb
#20 QCoreApplication::exec                        libQt5Core.so.5 + 0x2d8240
#21 ??                                            PyQt5/QtWidgets.abi3.so + 0x2dbdd3
#22-30 Py_RunMain / Py_BytesMain / libc
#31 Py_RunMain                                    libpython3.14.so.1.0
#32 Py_BytesMain                                  libpython3.14.so.1.0
#33/34 libc
#35 _start
```

Ключевой факт: это **не** кадр внутри `RescanWorker`, `mutagen`, `libvlc` или image-плагина. Это queued-вызов `QProgressDialog::setValue` на уже уничтоженном C++-объекте. `QProgressBar::maximum()` разыменовывает освобождённую память, потому что `QProgressDialog` уже прошёл через `deleteLater`/уничтожение.

### 1.2. Подтверждённый root cause

**Подтверждено:** SIGSEGV вызван использованием разрушенного `QProgressDialog` в queued-слоте прогресса. Значение 100 в регистре и стек `QObject::event → sendPostedEvents → QCoreApplication::exec` показывают, что последний сигнал прогресса был доставлен после того, как диалог уже был удалён.

Наиболее вероятный сценарий в текущем коде:

1. `ImportFlow._run_worker_with_progress()` создаёт `DimmedProgressDialog` (`import_flow.py:356-364`).
2. `_on_progress()` проверяет `self._progress_dialog is not None` и вызывает `setValue()` (`import_flow.py:369-372`).
3. `_cleanup()` по `worker.finished` вызывает `close()` и `deleteLater()`, затем обнуляет ссылку (`import_flow.py:374-390`).
4. `_on_rescan_finished()` печатает `[rescan] metadata: ...` и сразу открывает модальный `CustomConfirmDialog.information(...)` (`import_flow.py:280-299`), то есть входит во вложенный event loop.
5. `deleteLater()` выполняется уже внутри этого вложенного цикла. `progress` и `finished` идут через разные Python-прокси/очереди, поэтому порядок доставки финального `progress(100)` относительно `finished → cleanup` не гарантирован жёстко. Если `setValue(100)` приходит после уничтожения C++-объекта, получаем ровно этот SIGSEGV.

Дополнительно: не все прогресс-диалоги имеют такую проверку. В `main_window._start_update_download()` сигнал `progress` подключён напрямую к `self._update_progress.setValue` (`main_window.py:290`), а в `trim_dialog.py:399` — напрямую к `self._progress.setValue`. После `close()`/`deleteLater()` там нет проверки, жив ли объект. Если конкретный core относился к одному из этих сценариев, класс ошибки тот же.

**Что ещё не доказано:** какая именно ветка оставила указатель живым в конкретном запуске — `ImportFlow`, update-download или trim. Это следующий шаг диагностики; сам класс ошибки подтверждён стеком.

---

## 2. Второй подтверждённый класс падений: QThread destroyed while running

### 2.1. Дампы

SIGABRT, PID 1449684, 2026-11-02 01:14:31, `.venv/bin/python main.py`. Аналогичные SIGABRT: 1452350, 1468240, 1504144, 1508428, 1513319, 1514098, 1515024.

Сигнал: `SIGABRT`, `si_code: SI_TKILL`.

Точный стек:

```text
#0  ??                                            libc.so.6 + 0x9a11c
#1  raise                                         libc.so.6 + 0x3e5d0
#2  abort                                         libc.so.6 + 0x25685
#3  QMessageLogger::fatal(char const*, ...)       libQt5Core.so.5 + 0x9846a
#4  ??                                            libQt5Core.so.5 + 0x9a07e
#5  ??                                            PyQt5/QtCore.abi3.so
#6  QObjectPrivate::deleteChildren()              libQt5Core.so.5
#7  QWidget::~QWidget()                           libQt5Widgets.so.5 + 0x386d85
#8  ??                                            PyQt5/QtWidgets.abi3.so
#9  QObject::event(QEvent*)                       libQt5Core.so.5 + 0x30417f
#10 QApplicationPrivate::notify_helper            libQt5Widgets.so.5
#11 ??                                            PyQt5/QtWidgets.abi3.so
#12 QCoreApplication::notifyInternal2             libQt5Core.so.5 + 0x2d8068
#13 QCoreApplicationPrivate::sendPostedEvents    libQt5Core.so.5 + 0x2dd7ce
#14 ??                                            libQt5Core.so.5 + 0x330890
#15-17 glib main context
#18 QEventDispatcherGlib::processEvents           libQt5Core.so.5
#19 QEventLoop::exec                              libQt5Core.so.5
#20 QCoreApplication::exec                        libQt5Core.so.5
#21-31 PyQt/QtWidgets, libpython3.14, Py_RunMain, Py_BytesMain, libc
```

В строках core-дампа найдена строка:

```text
QThread: Destroyed while thread is still running
```

### 2.2. Подтверждённый root cause

**Подтверждено:** QThread был дочерним QObject виджета и ещё работал в момент уничтожения родительского виджета. `QObjectPrivate::deleteChildren()` в `QWidget::~QWidget()` уничтожает дочерний QThread, а Qt вызывает `qFatal()`.

Кандидаты в коде:

- `CoverLoader(track_id, query, self)` — родитель `ProfilePage` (`profile_ui.py:904-920`);
- `_FriendProfileWorker(..., self)` — родитель `ProfilePage` (`profile_ui.py:206-280`, `:628`);
- `_ProfileSyncWorker(..., self)` — родитель `ProfilePage` (`profile_ui.py:1276`);
- `QThread(self)` в YouTube-диалоге для поиска и скачивания (`youtube_dialog.py:553-556`, `:675-678`);
- `_TokenCheckWorker(token, self)` — QThread с родителем-QObject (`account_menu.py:31-80`).

В `ProfilePage.shutdown()` (`profile_ui.py:1158+`) и `AccountMenu.shutdown()` (`account_menu.py:158+`) используется `wait(2000)`, после чего всё равно вызывается `deleteLater()`. Если поток не завершился за 2 секунды (сеть, yt-dlp, TLS), родительский виджет может быть уничтожен раньше потока → qFatal/SIGABRT.

Это отдельный класс падений, не совпадающий с SIGSEGV из раздела 1, но он тоже подтверждён дампами и должен учитываться в требовании «0 вылетов».

---

## 3. Подтверждённое нарушение Qt: QPixmap в фоновом потоке

**Подтверждено по коду:** `profile_ui.CoverLoader` — `QThread`, который создаёт GUI-ресурс `QPixmap` в `run()`:

- `profile_ui.py:127-204` — класс `CoverLoader`;
- `profile_ui.py:130` — `loaded = pyqtSignal(int, QPixmap)`;
- `profile_ui.py:173-182` — `QImage` создаётся в фоне (это допустимо), затем вызывается `QPixmap.fromImage(image)` (это недопустимо в не-GUI потоке);
- `profile_ui.py:904-920` — `CoverLoader(..., self)`, родитель — `ProfilePage`;
- `profile_ui.py:321` — `ProfilePage.__init__()` вызывает `reload_stats()`;
- `profile_ui.py:952-1005`, `:1083`, `:1100`, `:1115` — `reload_stats()`/`_track_row()` могут запустить loader для треков без обложки.

`QPixmap` привязан к GUI-потоку и дисплейному серверу. Создание `QPixmap` в QThread и передача его через queued signal может портить внутренние ресурсы Qt/XCB/Wayland. Падение часто отложенное: при следующей перерисовке, смене темы, открытии/закрытии диалога или перерисовке библиотеки после rescan.

**Подтверждено:** нарушение правил Qt. **Гипотеза:** именно этот loader мог дать один из поздних SIGSEGV, если он был активен во время/после сканирования. Сам `RescanWorker` QPixmap/QIcon не создаёт.

---

## 4. Остальные гипотезы по SIGSEGV

Все пункты ниже — `гипотеза`, если не указано иное.

| № | Гипотеза | Статус | Почему рассматривается |
|---|---|---|---|
| 1 | Use-after-free `QProgressDialog` при queued `setValue(100)` | **подтверждено core-дампом** | Точный стек из раздела 1, значение 100, `QObject::event` + `sendPostedEvents`. |
| 2 | QThread destroyed while running | **подтверждено core-дампом** | Стек SIGABRT из раздела 2 и строка `QThread: Destroyed while thread is still running`. |
| 3 | `RescanWorker`/`QThread` удалены до фактического завершения `run()` | гипотеза | `_cleanup()` делает `wait(2000)`, затем безусловно `worker.deleteLater()`/`thread.deleteLater()` (`import_flow.py:374-390`). При зависании в ID3/rename/DB/ffmpeg/сети 2 секунды может не хватить. |
| 4 | libVLC не полностью отпустил файл до перезаписи mutagen | гипотеза | `release_media()` делает `stop()`/`set_media(None)`/`media.release()` (`vlc_backend.py:974-1010`), но не ждёт завершения input/decoder/aout-потоков. Сразу после этого worker делает `os.rename` и `ID3.save()`/`EasyID3.save()` (`workers.py:300-337`). In-place запись в файл, который ещё читает VLC, — риск нативного падения. |
| 5 | VLC снова стартует во время сканирования через MPRIS/очередь | гипотеза | `release()` не очищает контекст контроллера. Во время модального прогресса всё ещё работают queued-сигналы MPRIS (`mpris_integration.py:50-67`, `:248-256`), медиа-клавиши и `trackFinished`/next. `controller.toggle_play()`/`_play_current()` могут открыть файл, который worker переименовывает/перезаписывает. |
| 6 | `ID3`/`EasyID3` применяются ко всем аудиоформатам | гипотеза | `AUDIO_EXTS` включает mp3/flac/ogg/m4a/wav (`workers.py:54`), а `CsvImportWorker._embed_cover()` всегда использует `ID3()` (`workers.py:606-651`), теги — `EasyID3` (`:325-337`). Для FLAC/OGG/M4A/WAV это порча контейнера; позже VLC/мутаген/Qt-декодер могут получить повреждённый файл. В текущей библиотеке все 4 трека — MP3, поэтому здесь риск ниже. |
| 7 | Гонка файлов обложек: неатомарная запись/удаление и чтение QImageReader | гипотеза | `metadata.extract_cover()` пишет `write_bytes()` без temp+replace (`metadata.py:135-180`); worker удаляет старую обложку (`workers.py:315-322`); `CoverLoader` копирует через `shutil.copyfile()` (`profile_ui.py:164-165`); `cached_cover()` читает через `QImageReader` (`pixmap_utils.py:209-266`). Усечённый/перезаписываемый файл может дать SIGBUS/SIGSEGV в image-плагине. |
| 8 | Повреждённая/огромная скачанная обложка | гипотеза | `cover_provider._download_image()` проверяет только magic bytes и лимит 20 МБ (`:135-155`), но не декодируемость и не размеры в пикселях. `_embed_cover()` может вшить такой файл; позже Qt-декодер падает или упирается в OOM. |
| 9 | Конкуренция SQLite/`PRAGMA journal_mode=WAL` | гипотеза | `db.get_connection()` открывает новое соединение при каждом вызове и каждый раз выполняет `PRAGMA journal_mode=WAL` (`db.py:26-34`). Worker пишет row-by-row, UI/MPRIS читают. WAL обычно безопасен, но возможны `database is locked`, а необработанное исключение в Qt-слоте/`reload()` может привести к аварийному завершению. `with get_connection()` не закрывает соединение. |
| 10 | `musicbrainzngs`/yt-dlp/requests одновременно из нескольких потоков | гипотеза | `RescanWorker` и `CoverLoader` могут одновременно вызывать `get_track_metadata_with_fallback()` (`musicbrainz_client.py:350-475`). `metadata_cache` защищён lock (`metadata_cache.py:35-37`, `:99-147`), но у `musicbrainzngs` и yt-dlp есть глобальное состояние; параллельные `YoutubeDL`/SSL-вызовы не гарантированно безопасны. |
| 11 | Необработанные исключения в `reload()`/paint после scan | гипотеза | `library_changed` синхронно вызывает `LibraryTab.reload()` (`library_tab.py:231-318`), для каждой строки — `metadata.extract_cover()` (`:324`). В `extract_cover()` есть TOCTOU `exists()`+`stat()` (`metadata.py:138-140`) и запись файла (`:175-177`). Исключение в Qt-слоте/виртуальном методе может привести к abort. |
| 12 | Гонка `event_detach()` при release | гипотеза | `release_media()` вызывает `_detach_events()` до `stop()` (`vlc_backend.py:974-983`). python-vlc удаляет Python-callback из словаря, пока libVLC может ещё находиться в обработке события. Редкий нативный use-after-free/поздний вызов. |
| 13 | Удаление диалогов/overlay во вложенном event loop | гипотеза | `_cleanup()` делает `deleteLater()` прогресс-диалога, а `_on_rescan_finished()` сразу открывает `CustomConfirmDialog.information()` с `exec_()`. Вложенный цикл обрабатывает отложенные удаления и анимации `_WindowDimOverlay` (`dialog_base.py:260-345`). Возможен use-after-free overlay/диалога. |
| 14 | Устаревшие QModelIndex/hover после `clear()` дерева | гипотеза | `LibraryTab.reload()` делает `clear()`, но `LibraryTreeWidget` хранит `_last_hovered_index`/`_last_row_rect` (`library_tree.py:48-51`), а делегат — `hovered_trash_index`/`hovered_trash_rect` (`delegates.py:104-108`). После перестройки старые индексы могут указывать на удалённые узлы. |
| 15 | `QSettings` создаётся в фоновом потоке | гипотеза | `youtube_worker._find_cookies_file()` создаёт `QSettings` в `RescanWorker` (`youtube_worker.py:62-68`). QSettings реентерабелен, но не потокобезопасен при одновременном доступе к одному файлу из GUI. |
| 16 | `os.rename` и обновление пути в БД не атомарны | гипотеза | Worker сначала делает `os.rename`, затем `db.update_track_path` (`workers.py:300-308`). UI/MPRIS может прочитать старый путь между операциями и получить missing file; каскад ошибок в `extract_cover`/`reload`. Не прямой SIGSEGV, но источник нестабильности. |

---

## 5. Гипотезы по заиканию звука при первом проигрывании

Все пункты — `гипотеза` о причине, если не указано иное. Для некоторых подтверждён сам код-факт, но не его causal-связь с аудиопровалом.

| № | Гипотеза | Статус | Почему рассматривается |
|---|---|---|---|
| 1 | Опрос позиции стартует по `LengthChanged`, хотя audio output ещё не готов | **код-факт подтверждён**, причинность — гипотеза | `play()` выставляет `PLAYING` до `player.play()` (`vlc_backend.py:771-777`). `LengthChanged` запускает `_poll_timer` (`:431-445`). `_poll_position()` каждые 100 мс вызывает `get_time()`/`get_length()` (`:501-537`), которые берут внутренние блокировки input/demux. На первом play буфер ещё наполняется; на повторном файл/aout уже прогреты. |
| 2 | Громкость применяется по `Playing`, но `Playing` не гарантирует готовность aout; `_pending_volume` повторяется каждые 100 мс | **код-факт подтверждён**, причинность — гипотеза | `_handle_event()` ставит `_volume_ready=True` и вызывает `_apply_volume()` (`:446-462`). Если `audio_set_volume()` вернул не 0, `_pending_volume` остаётся (`:588-611`), и `_poll_position()` снова вызывает `_apply_volume()` (`:532-533`). Повторные вызовы во время стабилизации aout могут давать щелчки/провалы. |
| 3 | Первый play каждого трека запускает `LyricsWorker`; Python-callback’и VLC конкурируют за GIL | **код-факт подтверждён**, причинность — гипотеза | `controller._play_current()` сначала играет, затем испускает `track_changed` (`controller.py:162-184`); `MainWindow._on_track_changed()` вызывает `lyrics_manager.set_track()`. При `lyrics_checked=0` запускается `LyricsWorker` (`lyrics_manager.py:139-183`), `syncedlyrics` опрашивает несколько провайдеров и LRCLIB с таймаутом 10 с (`lyrics_api.py:100-131`). Event-callback’и python-vlc (`vlc_backend.py:372-385`) — Python-функции и требуют GIL; конкуренция может затормозить input/event-поток. При повторном play воркер уже не запускается. В локальной БД у 3 из 4 треков `lyrics_checked=0`. |
| 4 | Первый play запускает извлечение обложки следующего трека в GUI-потоке | **код-факт подтверждён**, причинность — гипотеза | `_emit_next_track()` → `LibraryTab._refresh_next_track()` → `metadata.extract_cover()` (`library_tab.py:557-573`). Если обложки нет в кэше, mutagen читает аудиофайл/APIC и может писать кэш (`metadata.py:135-180`). Это происходит сразу после `play()` и первый раз для каждого «следующего» трека. |
| 5 | Инициализация аудиовыхода/устройства: USB-гарнитура + PulseAudio на PipeWire | **среда подтверждена**, причинность — гипотеза | В `_INSTANCE_OPTIONS` нет `--aout`, `--audio-resampler`, `--file-caching` (`vlc_backend.py:58-64`). На машине используется USB G435 через PulseAudio на PipeWire; возможны suspend/resume sink’а, согласование sample rate/format и недобор буфера при первом stream. |
| 6 | Каждый `play()` останавливает оба плеера и пересоздаёт media/aout | **код-факт подтверждён**, причинность — гипотеза | `CrossfadePlayer.play()` делает `p.stop()` для обоих (`player.py:181-201`), затем `set_media()` ещё раз вызывает `stop()`, `set_media(None)`, освобождает старый `Media` и создаёт новый (`vlc_backend.py:700-759`). Первый play платит за пересоздание input/возможно aout; повторный — warmer. |
| 7 | Холодный page cache, ID3/APIC и VBR-разбор | гипотеза | `media_new_path()` ленив; VLC читает файл только в `play()`. Первый раз возможен cold read, разбор ID3v2/APIC, проход по VBR MP3 для длительности. После первого play файл/обложка в page cache, повтор идеален. На NVMe менее вероятно, но после rescan файлы перезаписаны. |
| 8 | Прогрев плагинов/декодеров VLC | гипотеза | `_load_vlc()`/`get_instance()` создают инстанс при построении окна (`vlc_backend.py:231-248`), но codec/demux/aout-плагины подгружаются при первом открытии медиа. Если заикается только самый первый трек сессии — это скорее этот пункт, чем логика плеера. |
| 9 | Event-таймер 40 мс и Python-callback’и создают нагрузку в первые секунды | **код-факт подтверждён**, причинность — гипотеза | `_event_timer` каждые 40 мс вызывает `_drain_events()` и разбирает до 256 событий (`:344-347`, `:405-420`). На старте трека идёт пачка `Opening/Buffering/LengthChanged/Playing/TimeChanged`, плюс lyrics/cover/UI. Каждый callback — вход в Python/GIL. |
| 10 | `_length_known` не сбрасывается в `stop()`, а `PLAYING` выставляется оптимистично | **код-факт подтверждён**, причинность — гипотеза | `stop()` (`:844-857`) не сбрасывает `_length_known`/`_volume_ready`; это делают только `set_media()`/`release_media()`. В сценарии `stop()` → `play()` без `set_media()` poll может стартовать до фактического `player.play()`. |
| 11 | Loudness-нормализация выставляет громкость выше 100 в первый момент | **код-факт подтверждён**, причинность — гипотеза | `_compute_gain()` даёт до 4x (`player.py:359-369`), итоговый clamp — 200 (`player.py:197-199`, `vlc_backend.py:591-593`). Для тихого трека первый `audio_set_volume()` может сразу поставить 150–200, что перестраивает software amplification/filter chain. |
| 12 | Первый play дополнительно делает `log_play`, чтение БД и запуск lyrics-записи | гипотеза | `db.log_play()` и чтение `loudness` идут при каждом play, но первый play трека дополнительно запускает lyrics-воркер, который позже пишет в БД. На фоне WAL это не должно влиять на аудио, но при медленном/сетевом диске возможна I/O-конкуренция. |
| 13 | MPRIS/DBus/UI-задачи первого play | гипотеза | `track_changed` одновременно обновляет PlayerBar, Playlists, Library, MPRIS и lyrics. Часть работы одноразовая для трека; при больших списках/медленных дисках может совпасть со стартом аудио. |
| 14 | Внешние CPU/IO-факторы | гипотеза | UI остаётся отзывчивым, значит аудиопровал может быть на уровне PipeWire/USB/CPU governor. Проверить на другом аудиовыходе и с уже активным потоком. |

---

## 6. Файлы и строки, на которые опирается диагностика

### Ядро плеера и VLC

- `vlc_backend.py`: 58-64 (опции инстанса), 231-248 (get_instance), 272-290 (создание плеера), 301-313 (состояние/volume), 324-347 (таймеры), 354-403 (attach/detach событий), 405-420 (drain), 422-462 (Length/Playing), 464-499 (Paused/Stopped/End/Error), 501-537 (_poll_position), 542-562 (_set_state), 588-611 (_apply_volume), 700-759 (set_media), 761-791 (play), 793-836 (pause/resume), 844-857 (stop), 956-969 (set_volume), 974-1010 (release_media).
- `player.py`: 36-65 (создание двух VLC-плееров), 79-99 (crossfade duration/swap), 115-123 (stateChanged/volume), 181-201 (play), 203-220 (set_media), 222-272 (crossfade), 274-293 (fade tick), 340-357 (volume), 359-369 (gain).
- `controller.py`: 145-184 (_play_current), 200-236 (_emit_next_track), 238-264 (_next_in_context), 307-325 (_play_from_queue), 373-395 (toggle_play), 433-459 (prepare_crossfade).
- `session.py`: 23-89 (restore/save volume/context).
- `main.py`: 61-77 (High-DPI/QPixmapCache).

### Сканирование и метаданные

- `import_flow.py`: 120-126 (поля), 168-184 (rescan/release), 280-299 (_on_rescan_finished), 331-354 (shutdown), 356-413 (_run_worker_with_progress, _on_progress, _cleanup).
- `workers.py`: 54 (AUDIO_EXTS), 62-70 (find_audio_files), 83-113 (get_mean_volume), 222-388 (RescanWorker), 300-308 (rename), 310-337 (embed/tags), 355-387 (loudness), 606-651 (_embed_cover).
- `metadata.py`: 88-121 (read_metadata), 135-180 (extract_cover).
- `metadata_cache.py`: 35-37 (lock/globals), 99-147 (_cache_get/_cache_set).
- `cover_provider.py`: 135-155 (_download_image), 236-273 (_save_cover_bytes), 276-288 (_copy_cover_file_to_cache), 301-335 (_youtube_first_result), 372-473 (_youtube_fallback).
- `musicbrainz_client.py`: 350-475 (get_track_metadata_with_fallback).
- `db.py`: 26-34 (get_connection/PRAGMA), 244-249 (get_all_tracks), 279-311 (update path/metadata/loudness), 313-327 (lyrics update), 352-393 (folders), 565-589 (log_play/listening).
- `ytdlp_support.py`: 126-166 (search_videos), 169-284 (download_audio).
- `youtube_worker.py`: 62-68 (_find_cookies_file/QSettings).

### GUI, прогресс-диалоги, QPixmap

- `main_window.py`: 276-290 (update progress), 381-391 (library signals), 444-458 (media signals), 551-575 (_on_track_changed), 619-640 (startup sync), 682 (_on_library_changed), 852-878 (listening/position/duration).
- `trim_dialog.py`: 380-410 (progress dialog + direct `setValue`), 399.
- `dialog_base.py`: 260-345 (_WindowDimOverlay), 431-433 (DimmedProgressDialog).
- `profile_ui.py`: 127-204 (CoverLoader), 206-280 (_FriendProfileWorker), 321 (ProfilePage init/reload_stats), 628 (_ProfileSyncWorker connect), 904-928 (_start_cover_loader), 952-1005 (reload_stats), 1083/1100/1115/1194 (extract_cover в профиле), 1158+ (shutdown).
- `pixmap_utils.py`: 209-266 (cached_cover/QImageReader/QPixmapCache).
- `delegates.py`: 104-108 (hovered_trash_index), 572-590 (_draw_cover/cached_cover).
- `library_tab.py`: 231-343 (reload/_make_track_item), 557-573 (_refresh_next_track).
- `library_tree.py`: 48-51 (hover-состояние), 218-255 (_sync_item).
- `youtube_dialog.py`: 553-556 (search QThread(self)), 675-678 (download QThread(self)), 730-780 (cleanup/lingering threads).
- `account_menu.py`: 31-80 (_TokenCheckWorker), 158-178 (shutdown).
- `mpris_integration.py`: 50-67 (command bridge), 80-118 (metadata/cover), 248-256 (bridge connections).
- `hotkeys.py`: 65-100 (фокус/хоткеи; в модальном диалоге не срабатывают, но MPRIS — да).

### Ранее заявленные фиксы, которые нужно учитывать

- `RELEASE_NOTES_LOG.md`: 27-29 — первый фикс первого play (poll после LengthChanged, volume после Playing).
- `RELEASE_NOTES_LOG.md`: 70-74 — фикс SIGSEGV после rescan (release VLC на GUI-потоке, cleanup до completion dialog).

---

## 7. Итоговая приоритизация диагностики

1. **SIGSEGV:** первым делом проверять жизненный цикл `QProgressDialog` и queued `progress(100)`, а не `RescanWorker`. Core-дампы уже указывают на этот слой.
2. **Второй класс:** QThread, дочерний виджету, уничтожается до завершения — отдельный подтверждённый источник abort’ов.
3. **QPixmap в `CoverLoader`** — подтверждённое нарушение Qt; проверить, был ли loader активен в момент падения.
4. **VLC/mutagen file lock** и **MPRIS/повторный play во время scan** — следующие по опасности гипотезы для SIGSEGV.
5. **Заикание:** сначала проверить корреляцию с `lyrics_checked=0` (LyricsWorker/GIL), затем порядок `LengthChanged`/`Playing` и повторные `audio_set_volume`, затем аудиовыход PipeWire/USB и холодный кэш.

---

## 8. Ограничения диагностики

- Точная ветка, из-за которой `QProgressDialog` остался в памяти после удаления, по core-дампу не восстановлена: подтверждён класс use-after-free, но не конкретный прогресс-диалог.
- Причинная связь «lyrics/GIL → заикание» пока не доказана экспериментом; подтверждены только код-факты и наличие `lyrics_checked=0` у большинства треков.
- `QPixmap` в фоне подтверждён как нарушение Qt, но не доказано, что именно он дал конкретный SIGSEGV.
- Core-дампы могли быть сняты до последних изменений в `import_flow.py`/`vlc_backend.py`; перед выводами о текущей сборке нужно воспроизвести падение заново.
