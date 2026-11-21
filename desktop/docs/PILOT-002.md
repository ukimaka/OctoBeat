# Pilot 002: `cover_provider.py` → Rust

- **Date:** 2026-11-19
- **Unit:** `cover_provider.py`
- **Crate:** `rust/cover-provider-rs`
- **Bridge:** PyO3
- **Function:** `get_cached_source_for_path`

## Why this unit

- Small (47 lines of executable Python), one public function, no Qt or database.
- Reads real audio tags, so it exercises the metadata stack we need for the library.
- The app's 114-track library is entirely Opus, making this the first test against real files.

## Recorded behavior

- 240 cases:
  - generated edge cases (random strings, non-audio paths, empty strings);
  - curated fixtures in `rust/cover-provider-rs/fixtures/`.
- 0 cases threw.

Fixtures cover:

- Opus: no tags, title only, artist+title, album+artist+title, MusicBrainz artist ID, `website`, `description` (not `comment`), Cyrillic/Japanese tags, empty file;
- MP3: album+artist+title, WOAS, `TXXX:MusicBrainz Artist Id`, comment/website/mbid-only files;
- FLAC: MusicBrainz artist ID, `comment` (written as `DESCRIPTION` by ffmpeg), `description`, `website`, no tags;
- M4A: `©cmt` comment, freeform MusicBrainz Artist Id, website/mbid-only files;
- non-audio text, missing path, directory path, empty string.

## Result

```
240/240 cases match
gate passed: fmt, clippy, cargo test, unsafe, ported, size,
             error cases, panics, build, api, behavior
```

## Metadata stack decision

`lofty` was evaluated first, but it **drops unknown Vorbis comments** such as
`website` and cannot distinguish every case the Python code sees through
mutagen's `easy=True` view. `symphonia` 0.6 preserves raw keys and maps
standard tags:

- `StandardTag::Album`, `Artist`, `TrackTitle`, `Comment`;
- `StandardTag::MusicBrainzArtistId`, `MusicBrainzAlbumId`,
  `MusicBrainzRecordingId`, `MusicBrainzTrackId`;
- raw `website` / `comment` for Vorbis comments;
- `Description` is deliberately **not** treated as `Comment`;
- WOAS maps to `UrlSource`, which mutagen's `easy=True` view does not expose
  as `website`, so it is not counted as a website marker.

The Rust port therefore uses **symphonia for reading metadata**. `lofty` can
still be used later for writing tags where it has the better API.

## Commands

```sh
rust-anything bridge . cover_provider.py
rust-anything record rust/cover-provider-rs \
  --inputs rust/cover-provider-rs/custom_cases.jsonl
rust-anything build rust/cover-provider-rs
rust-anything diff rust/cover-provider-rs
rust-anything gate rust/cover-provider-rs
rust-anything map . --write
```

## Next units

- `metadata_cache.py` (disk JSON cache; needs temp directories and TTL cases).
- `path_utils.py` (path normalization; keep subprocess/file-mutating functions
  in Python if the generated cases cannot be made safe).
- `db.py` (SQLite schema and migrations; needs a temp database and custom
  recorded cases from `test_db.py`).
