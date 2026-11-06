# OctoBeat: расследование обложки для `.webm`

**Дата:** 2026-11-04  
**Трек в артефакте QA:** `LIFE - Neuro-sama (Official Video)` → после переименования `LIFE - Neuro-sama.webm`  
**Статус:** только расследование. Логика приложения не изменялась. Временное логирование выполнялось отдельным harness-скриптом (monkeypatch транспорта `musicbrainzngs`), после снятия логов скрипт и временные каталоги удалены.

---

## TL;DR

1. **MusicBrainz ответил `HTTP 200 OK`, но с нулём записей.** Это не `404`, не `429` и не `403`. Для поиска «не найдено» в MusicBrainz — это `200` + пустой `recording-list`; `404` относится к Cover Art Archive, а не к поиску.
2. **`.jpg` в папке музыки создал yt-dlp**, а не наш код: `writethumbnail: True` + постпроцессор `FFmpegThumbnailsConvertor` (`format: jpg`). Файл появился в `12:26:54`, то есть **за 4 секунды до** окончания скачивания аудио (`12:26:58`); наш код начинает работу только после возврата `download_audio`.
3. **Для `.webm` обложка не вшивается и временное превью не удаляется:** `audio_tags.embed_cover` поддерживает только `.mp3`/`.m4a`/`.mp4`, для `.webm` возвращает `False`. Поэтому `.jpg` остаётся рядом с аудио, а затем `rename_sidecar_image` переименовывает его под новое имя трека.
4. **UI ставит sidecar выше всего остального.** `metadata.extract_cover` сначала берёт `<трек>.jpg`, поэтому даже если бы MusicBrainz дал обложку, на экране всё равно был бы YouTube-кадр. Это вторая независимая причина, которую нужно учитывать при фиксе.
5. Сохранённый кэш QA (`source: youtube`, `cover_source: youtube`, `album: null`) — это ровно ветка **«MusicBrainz 200 + нет совпадений»**, а не ветка ошибки/лимита. Если бы **обе** попытки упали с `429/403/503`, код вернул бы заглушку без обложки, а не YouTube-обложку (проверено матрицей сценариев). Если бы упала только одна попытка, а вторая вернула `200/0`, результат был бы тем же, что и в кэше QA, но причина всё равно — отсутствие совпадения, а не бан.

---

## 1. HTTP-ответ MusicBrainz

### 1.1. Что именно отправляет приложение

`YoutubeWorker` получает имя файла `LIFE - Neuro-sama (Official Video).webm`, чистит его через `clean_youtube_title` и передаёт в пайплайн:

```text
raw_title        = "LIFE - Neuro-sama (Official Video)"
artist           = "LIFE"
title            = "Neuro-sama"
```

`search_musicbrainz("LIFE", "Neuro-sama")` делает два запроса (`musicbrainz_client.py:277-347`):

| # | `strict` | Lucene-запрос | `limit` |
|---|---|---|---|
| 1 | `True` | `recording:"Neuro\-sama" AND artist:"LIFE"` | 5 |
| 2 | `False` | `recording:(neuro\-sama) artist:(life)` | 5 |

Точные URL (URL-encoded):

```text
strict:
https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%22Neuro%5C-sama%22+AND+artist%3A%22LIFE%22

relaxed:
https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%28neuro%5C-sama%29+artist%3A%28life%29
```

User-Agent: `OctoBeat/1.0 ( https://github.com/ukimaka/OctoBeat )`  
Формат ответа: XML (по умолчанию в `musicbrainzngs`).

### 1.2. Реальный ответ (воспроизведение)

Логи временного harness-скрипта:

```text
[MB] request GET /ws/2/recording/ args={'query': 'recording:"Neuro\\-sama" AND artist:"LIFE"', 'limit': '5'}
[HTTP] 200  https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%22Neuro%5C-sama%22+AND+artist%3A%22LIFE%22
[MB] response recording-list=0

[MB] request GET /ws/2/recording/ args={'query': 'recording:(neuro\\-sama) artist:(life)', 'limit': '5'}
[HTTP] 200  https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%28neuro%5C-sama%29+artist%3A%28life%29
[MB] response recording-list=5
[RESULT] search_musicbrainz -> None
```

Сырой ответ на строгий запрос:

```http
HTTP/1.1 200 OK

<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<metadata ...>
  <recording-list count="0" offset="0"/>
</metadata>
```

То есть **строгий запрос: HTTP 200, `count="0"`**.

Мягкий запрос вернул 5 записей из общего `count=27085` (сервер отдаёт только `limit=5`). Все 5 отброшены локальной проверкой — см. §4.

### 1.3. Про 404 / 429 / 403

- **404** в поиске записей не используется для «не найдено». `200` + пустой `recording-list` — это штатный «not found». `404` приходит от Cover Art Archive, когда у релиза нет картинки; `get_cover_art` его перехватывает и пробует release-group/другие изображения (`cover_provider.py:165-238`).
- **429/403** в этом прогоне не наблюдались. Если бы они были, `musicbrainzngs._safe_read` ретраит 8 раз (паузы 2, 4, … 14 с), затем бросает `NetworkError` → `MusicBrainzLookupError`. Код в этом случае **не уходит на YouTube**, а возвращает заглушку без обложки (`musicbrainz_client.py:559-566`). Это проверено матрицей в §5.
- **503** — единственная нестабильность, которую мы увидели: при повторных одинаковых запросах MusicBrainz иногда отвечал:

```http
HTTP/1.1 503 Service Unavailable

{"error": "The MusicBrainz web server is currently busy. Please try again later."}
```

Это не бан и не 429. `musicbrainzngs` считает 503 временной ошибкой и ретраит. Если все ретраи исчерпаны — снова `MusicBrainzLookupError` → заглушка, не YouTube.

> **Важная оговорка.** Точный HTTP-статус в момент прогона QA (12:26) нигде не сохраняется: приложение логирует только исключения, а успешный `200` с нулём результатов — молча. Мы воспроизвели тот же запрос в 12:38 и получили `200/0`. Сохранённый кэш QA доказывает, что эффективный поиск завершился **без фатальной ошибки** (иначе была бы заглушка), но не позволяет отличить «200 на оба запроса» от «503 на strict + 200 на relaxed». На вывод это не влияет: в обоих случаях причина — отсутствие совпадения в MusicBrainz, а не бан.

---

## 2. Откуда `.jpg` в папке музыки

### 2.1. Это yt-dlp

Точные места:

- `ytdlp_support.py:433` — `"writethumbnail": True`
- `ytdlp_support.py:412-418` — постпроцессор:

```python
postprocessors = [
    {
        "key": "FFmpegThumbnailsConvertor",
        "format": "jpg",
        "when": "before_dl",
    },
]
```

- `ytdlp_support.py:432` — `"outtmpl": str(outtmpl)`
- `youtube_worker.py:116` — `str(self.target_folder / "%(title)s.%(ext)s")`

То есть yt-dlp сначала скачивает превью (обычно `.webp`), конвертирует его в `.jpg` через ffmpeg **до** скачивания аудио (`when: before_dl`) и кладёт рядом с будущим аудиофайлом.

### 2.2. Доказательства по артефактам

Таймстемпы (`stat`):

```text
2026-11-04 12:26:54.395  47296    /home/baka/Music/LIFE - Neuro-sama.jpg
2026-11-04 12:26:58.728  3645405  /home/baka/Music/LIFE - Neuro-sama.webm
2026-11-04 12:27:01.454  47296    /home/baka/.cache/OctoBeat/youtube_covers/ce8275f1....jpg
2026-11-04 12:27:01.502  47296    /home/baka/.cache/OctoBeat/covers/1.jpg
```

`.jpg` создан **до** аудио. Наш пайплайн стартует только после возврата `download_audio` (`youtube_worker.py:114-133`), то есть после `12:26:58`. Следовательно, файл в Music создал не наш код.

Дополнительно:

```text
$ file "LIFE - Neuro-sama.jpg"
JPEG image data, JFIF standard 1.01, ... comment: "Lavc63.1.102", baseline,
precision 8, 1280x720, components 3
```

- `Lavc63.1.102` — след ffmpeg (Libav), то есть `FFmpegThumbnailsConvertor`.
- `1280x720` — 16:9 кадр YouTube, а не квадратная обложка альбома.
- Все три файла побайтово совпадают:

```text
2af3fba98887c8cacefeaf20ad13b22750d3deb1696c322029d56fe24b8c603e  /home/baka/Music/LIFE - Neuro-sama.jpg
2af3fba98887c8cacefeaf20ad13b22750d3deb1696c322029d56fe24b8c603e  /home/baka/.cache/OctoBeat/youtube_covers/ce8275f1....jpg
2af3fba98887c8cacefeaf20ad13b22750d3deb1696c322029d56fe24b8c603e  /home/baka/.cache/OctoBeat/covers/1.jpg
```

`youtube_covers/...jpg` — это копия, сделанная нашим `_copy_cover_file_to_cache` из уже скачанного превью (`cover_provider.py:285-297`, `351-362`), а `covers/1.jpg` — копия, сделанная UI из sidecar (`metadata.py:669-687`).

### 2.3. Наш код в Music не пишет

Наши функции сохранения обложек пишут только в кэш:

- `cover_provider.py:245-256` — `COVER_DIR` (`<cache>/musicbrainz_covers`) и `YOUTUBE_COVER_DIR` (`<cache>/youtube_covers`);
- `metadata.py:588-603` — `COVERS_DIR` (`<cache>/covers`).

В коде нет записи изображений в `MUSIC_DIR`/`target_folder`. Единственные операции с папкой музыки — сам yt-dlp (`writethumbnail`), переименование аудио и `rename_sidecar_image`.

### 2.4. Почему `.jpg` не удалился после вшивания

`audio_tags.embed_cover` (`audio_tags.py:55-98`) поддерживает **только**:

- `.mp3` — ID3/APIC;
- `.m4a`/`.mp4` — MP4 `covr`.

Для `.webm` функция сразу возвращает `False` (`audio_tags.py:98`). `write_tags` (`audio_tags.py:101-146`) для `.webm` тоже возвращает `False`.

В `youtube_worker.py:189-194` удаление временного превью обусловлено успешным вшиванием:

```python
if embedded_ok and img_path and os.path.exists(img_path):
    os.remove(img_path)
```

Для `.webm` `embedded_ok = False`, поэтому удаление не выполняется. Затем `rename_sidecar_image` (`metadata.py:409-484`) переименовывает `LIFE - Neuro-sama (Official Video).jpg` → `LIFE - Neuro-sama.jpg` (`youtube_worker.py:230-232`).

---

## 3. Приоритет для `.webm`: пошаговый разбор

1. **Скачивание.** `download_audio` с `writethumbnail` + `FFmpegThumbnailsConvertor` создаёт `<title>.webm` и `<title>.jpg` в папке музыки.
2. **Разбор имени.** `youtube_worker.py:133-134`: `raw_title = Path(final_path).stem` → `clean_youtube_title` → `("LIFE", "Neuro-sama")`.
3. **Поиск превью.** `youtube_worker.py:136-142`: находит `img_path = ...jpg` и передаёт его как `youtube_thumbnail_path`.
4. **Локальная обложка.** `musicbrainz_client.py:462-475`: `find_local_cover(..., exclude=(youtube_thumbnail_path,))`. Превью yt-dlp исключено; у `.webm` нет встроенной обложки; другого sidecar нет → `local_cover = None`.
5. **MusicBrainz.** `musicbrainz_client.py:487-501`: strict `200/0`, relaxed `200/5` (все отброшены) → `None`; исключения нет, `mb_unavailable = False`.
6. **Ветка ошибки не срабатывает.** `musicbrainz_client.py:559-566` пропускается, потому что `mb_unavailable` = `False`.
7. **YouTube-фолбэк.** `musicbrainz_client.py:578-600` → `_youtube_fallback`. Внутри (`cover_provider.py:429-446`) сначала используется уже скачанное превью:
   - `_youtube_cover` (`cover_provider.py:351-362`) → `_copy_cover_file_to_cache` → `<cache>/youtube_covers/<sha1>.jpg`;
   - результат получает `source="youtube"`, `cover_source="youtube"`, `is_default_cover=False`.
8. **Кэш.** `musicbrainz_client.py:595-600` сохраняет результат на 30 дней (`CACHE_TTL`).
9. **Вшивание.** `youtube_worker.py:169-187`: `audio_tags.embed_cover(.webm, .jpg)` → `False`; временный `.jpg` остаётся.
10. **Переименование.** `youtube_worker.py:215-236`: аудио → `LIFE - Neuro-sama.webm`, sidecar → `LIFE - Neuro-sama.jpg`.
11. **UI.** `metadata.extract_cover` (`metadata.py:625-705`) сначала ищет sidecar (`metadata.py:642`, `669-687`) и копирует его в `<cache>/covers/1.jpg` с маркером `source=sidecar`. Только потом — встроенную обложку и кэш MusicBrainz/YouTube.

### Почему это две независимые проблемы

- **Проблема A (метаданные):** MusicBrainz реально не знает этот трек, поэтому пайплайн штатно ушёл на YouTube.
- **Проблема B (UI/sidecar):** yt-dlp оставил `.jpg` в папке музыки; UI считает его пользовательским sidecar и ставит выше любой другой обложки.

Мы проверили B отдельно: подложили в кэш «фейковую обложку MusicBrainz» с другим хешем и вызвали `extract_cover`:

```text
sidecar    2af3fba98887c8ca
fake MB    abf83c776211f6cf
extract with sidecar    -> 2af3fba98887c8ca  => sidecar
extract without sidecar -> abf83c776211f6cf  => fake MB
```

То есть **даже при наличии обложки MusicBrainz sidecar от yt-dlp выигрывает**. Фикс только в MusicBrainz-поиске не уберёт YouTube-кадр с экрана, пока `.jpg` лежит рядом с `.webm`.

---

## 4. Строгий поиск: параметры и ответ сервера

### 4.1. Что отправили

| Параметр | Значение |
|---|---|
| `artist` | `LIFE` |
| `recording` (title) | `Neuro-sama` |
| `duration` | **не отправлялся** |
| `limit` | `5` |
| `strict` | сначала `True`, затем `False` |
| Endpoint | `https://musicbrainz.org/ws/2/recording/` |
| User-Agent | `OctoBeat/1.0 ( https://github.com/ukimaka/OctoBeat )` |

`duration` в MusicBrainz-поиске не используется вообще: в `musicbrainz_client.py`, `cover_provider.py` и `metadata_normalize.py` нет ни `duration`, ни `qdur`, ни `dur` применительно к запросу/сравнению. Это не причина текущего бага, но полезно знать: матчинг идёт только по title/artist.

### 4.2. Что ответил сервер

**Strict:** `HTTP 200`, `recording-list count="0"`.

**Relaxed:** `HTTP 200`, `count=27085`, вернулось 5 записей:

| # | score | artist | title | release | почему отброшено |
|---|---|---|---|---|---|
| 1 | 100 | Narcune | Unloved (Neuro-Sama) | Single «Unloved (Neuro-Sama)» | artist не `LIFE`; `_titles_match` = False (ratio 0.714 < 0.9) |
| 2 | 69 | 14-K | Sama Sama | Album «Yesterday's Dream» | title не совпадает (ratio 0.526) |
| 3 | 69 | Silent Sanctuary | Sama-sama | Album «Monodramatic» | title не совпадает |
| 4 | 69 | Rocksteddy | Sama-sama | EP «Instadramatic» | title не совпадает |
| 5 | 69 | Macha | Sama Sama | Album «Macha» | title не совпадает |

`_choose_recording` (`musicbrainz_client.py:197-235`) требует:

- `_titles_match` — `_fold` + `difflib.SequenceMatcher(...).ratio() >= 0.9` (`metadata_normalize.py:241-256`);
- `_artists_match` — точное/подстрочное совпадение или ≥50% общих токенов (`metadata_normalize.py:259-270`).

Ни одна запись не проходит. Единственное «похожее» — `Narcune — Unloved (Neuro-Sama)`: это **другая песня другого исполнителя**, и отбрасывать её правильно. Если ослабить матчинг, можно приклеить чужую обложку.

### 4.3. Если бы MusicBrainz нашёл релиз, но без обложки

Тогда сработала бы ветка `musicbrainz_client.py:533-557`: метаданные остаются `source="musicbrainz"`, но `cover_source="youtube"`, и в результате были бы заполнены `album`/`release_id`. В кэше QA `album=null`, `release_id` отсутствует, `source="youtube"` — значит, это **не** ветка «нашли релиз без обложки».

---

## 5. Проверка гипотезы 429/403

Мы прогнали три сценария с одинаковым файлом и аргументами, подменив только ответ MusicBrainz/CAA:

| Сценарий | `source` | `cover_source` | `cover_path` | `album` |
|---|---|---|---|---|
| A. `MusicBrainzLookupError` (429/403/503 после ретраев) | `fallback` | `None` | `None` | `None` |
| B. `200` + нет совпадений | `youtube` | `youtube` | `<cache>/youtube_covers/...jpg` | `None` |
| C. `200` + запись есть, CAA пуст | `musicbrainz` | `youtube` | `<cache>/youtube_covers/...jpg` | `Some Album` |

Реальный кэш QA:

```json
{
  "title": "Neuro-sama",
  "artist": "LIFE",
  "album": null,
  "cover_path": "/home/baka/.cache/OctoBeat/youtube_covers/ce8275f140f8f1242b1820fa4afe636cb5862619.jpg",
  "cover_source": "youtube",
  "is_default_cover": false,
  "source": "youtube",
  "file_path": "/home/baka/Music/LIFE - Neuro-sama (Official Video).webm"
}
```

Это **ровно сценарий B**. Сценарий A (бан/лимит на обеих попытках) дал бы `source=fallback`, `cover_path=None` — обложки не было бы вообще. Сценарий C дал бы `source=musicbrainz` и заполненный `album`.

Если бы `429/403` был только на одной из двух попыток, а вторая вернула `200/0`, результат тоже был бы B — но и тогда причина в отсутствии совпадения, а не в бане: сам трек в MusicBrainz не находится (см. §4).

Вывод: **гипотеза «429/403 и молчаливый fallback на YouTube» не подтверждается.** При 429/403 код не идёт на YouTube, а возвращает заглушку. Наблюдаемый YouTube-результат — следствие штатного `200` без совпадений.

Отдельный риск: 429/503 заставляют `musicbrainzngs` делать до 8 ретраев с паузами 2…14 с. При массовом импорте это может выглядеть как «зависание» на метаданных, а после исчерпания — давать заглушки. Это стоит логировать и, возможно, ограничивать.

---

## 6. Что рекомендуется исправить (не реализовано)

1. **Не оставлять превью yt-dlp в папке музыки.**
   - Либо отключить `writethumbnail` и брать YouTube-превью через `_youtube_fallback` по URL (но это лишний сетевой запрос).
   - Либо после скачивания перемещать/удалять `<title>.jpg` для контейнеров, которые не поддерживают вшивание (`.webm`, `.opus` и т.п.), а не полагаться на `embedded_ok`.
   - Либо настроить yt-dlp так, чтобы thumbnail писался сразу в отдельный каталог кэша (через отдельный `outtmpl`/постпроцессор), а не рядом с аудио.
2. **Не считать превью yt-dlp пользовательским sidecar.** Нужен признак происхождения (маркер/каталог/суффикс), иначе `extract_cover` всегда будет ставить его выше MusicBrainz. Это критично: без этого фикса даже успешный MusicBrainz-ответ не изменит картинку для `.webm`.
3. **Не ослаблять матчинг MusicBrainz ради этого трека.** В MusicBrainz нет `LIFE — Neuro-sama`; единственное совпадение `Narcune — Unloved (Neuro-Sama)` — другая песня. Ослабление `_artists_match`/`_titles_match` приведёт к чужим обложкам.
4. **Добавить постоянное логирование статусов.** Сейчас `200` + пустой результат не логируется вообще; видны только исключения. Минимально полезно:
   - query, strict, limit;
   - HTTP-код и `recording-list count`;
   - топ-3 `score/artist/title`;
   - какой источник обложки победил и почему.
   Это позволит QA отличать «нет в MB» от «MB недоступен» без раскопок кэша.
5. **Проверить `RescanWorker`.** Он тоже передаёт `find_sidecar_image(...)` как `youtube_thumbnail_path` (`workers.py:498-504`), то есть пользовательский sidecar может быть ошибочно классифицирован как YouTube-превью при рескане. Это родственный риск, стоит отдельной проверки.

---

## 7. Как воспроизвести

MusicBrainz (не чаще 1 запроса в секунду):

```bash
curl -sS -A 'OctoBeat/1.0 ( https://github.com/ukimaka/OctoBeat )' \
  'https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%22Neuro%5C-sama%22+AND+artist%3A%22LIFE%22'

curl -sS -A 'OctoBeat/1.0 ( https://github.com/ukimaka/OctoBeat )' \
  'https://musicbrainz.org/ws/2/recording/?limit=5&query=recording%3A%28neuro%5C-sama%29+artist%3A%28life%29'
```

Ожидаемо: первый — `200` + `<recording-list count="0"/>`; второй — `200` + 5 нерелевантных записей.

Проверка правила «`.jpg` — от yt-dlp»:

```bash
stat -c '%y %s %n' "$HOME/Music/LIFE - Neuro-sama.jpg" "$HOME/Music/LIFE - Neuro-sama.webm"
sha256sum "$HOME/Music/LIFE - Neuro-sama.jpg" \
          "$HOME/.cache/OctoBeat/youtube_covers/"*.jpg \
          "$HOME/.cache/OctoBeat/covers/1.jpg"
```

Ожидаемо: `.jpg` старше `.webm`; хеши совпадают.

Проверка приоритета sidecar:

1. Положить рядом с `.webm` файл `<имя>.jpg`.
2. Вызвать `metadata.extract_cover(path, track_id)`.
3. Убедиться, что в `<cache>/covers/<track_id>.cover.json` стоит `"source": "sidecar"`, а картинка совпадает с sidecar, даже если в `metadata_cache.json` указана другая обложка.

---

## Приложение: артефакты QA

### Кэш метаданных

`~/.cache/OctoBeat/metadata_cache.json`:

```json
{
  "version": 1,
  "entries": {
    "life|neuro-sama": {
      "expires_at": 1796376421.4792895,
      "data": {
        "title": "Neuro-sama",
        "artist": "LIFE",
        "album": null,
        "date": null,
        "cover_path": "/home/baka/.cache/OctoBeat/youtube_covers/ce8275f140f8f1242b1820fa4afe636cb5862619.jpg",
        "cover_url": null,
        "cover_source": "youtube",
        "is_default_cover": false,
        "source": "youtube",
        "file_path": "/home/baka/Music/LIFE - Neuro-sama (Official Video).webm",
        "file_name": "LIFE - Neuro-sama (Official Video).webm"
      }
    }
  }
}
```

### Маркер UI-кэша

`~/.cache/OctoBeat/covers/1.cover.json`:

```json
{
  "audio": {
    "mtime_ns": 1793784418728583804,
    "path": "/home/baka/Music/LIFE - Neuro-sama.webm",
    "size": 3645405
  },
  "sidecar": {
    "mtime_ns": 1793784414395566463,
    "path": "/home/baka/Music/LIFE - Neuro-sama.jpg",
    "size": 47296
  },
  "source": "sidecar",
  "version": 1
}
```

### Строка в БД

```text
id=1
file_path=/home/baka/Music/LIFE - Neuro-sama.webm
title=Neuro-sama
artist=LIFE
album=None
duration=213
created_at=2026-11-04 09:27:01 (UTC)
```

### Медиафайл

```text
format_name=matroska,webm
duration=213.661000
size=3645405
```

Тегов title/artist/album в `.webm` нет; всё, что видно в UI, взято из имени файла/метаданных, а не из тегов контейнера.
