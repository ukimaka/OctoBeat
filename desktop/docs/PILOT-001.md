# Pilot 001: `metadata_normalize.py` → Rust

- **Date:** 2026-11-19
- **Unit:** `metadata_normalize.py`
- **Crate:** `rust/metadata-normalize-rs`
- **Bridge:** PyO3 (transition; the same `port.rs` can later be reused by the Rust core)
- **Functions:** `normalize_track_query`, `normalize_artist_name`, `split_featured_artists`, `clean_featured_title`, `metadata_needs_refresh`

## Why this unit

- Pure Python (only `re`), no Qt or I/O.
- Small (196 lines) but non-trivial: Unicode, regex, case folding, tuples.
- Used by lyrics matching and metadata refresh, so correctness matters.
- Ideal for validating the `record → port → diff → gate` loop before touching the database or the UI.

## Recorded behavior

- 1,316 cases total:
  - generated edge cases (emoji, CJK, combining marks, BOM, newlines, tabs, regex traps);
  - 130+ real-world YouTube/feat/`Topic` patterns in `custom_cases.jsonl`.
- 0 cases threw after removing one malformed custom input.
- The recording is committed as `cases.jsonl`.

## Result

```
1316/1316 cases match
gate passed: fmt, clippy, cargo test, unsafe, ported, size,
             error cases, panics, build, api, behavior
```

The Rust port uses:

- `regex` for the Python regular expressions;
- `unicode-casefold` for `str.casefold()` (`ß` → `ss`, `İ` → `i̇`, etc.);
- a lookaround-free rewrite of the `feat.` trailing regex, because the `regex` crate does not support lookahead.

## Commands

```sh
rust-anything bridge . metadata_normalize.py
rust-anything record rust/metadata-normalize-rs \
  --inputs rust/metadata-normalize-rs/custom_cases.jsonl
rust-anything build rust/metadata-normalize-rs
rust-anything diff rust/metadata-normalize-rs
rust-anything gate rust/metadata-normalize-rs
rust-anything map .
```

## Notes for the next units

- Add real-world inputs for every unit; generated cases alone miss domain cases.
- Use `unicode-casefold` wherever the Python code calls `.casefold()`.
- The `regex` crate has no lookaround: rewrite or use `fancy-regex` only where necessary.
- Keep generated `src/lib.rs` and `python/` untouched; edit `src/port.rs`.
- The PyO3 crate is a transition artifact; the eventual C++/Qt app links the Rust core directly, without Python.
