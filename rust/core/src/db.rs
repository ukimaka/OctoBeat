//! SQLite layer, ported from the original `db.py`.
//!
//! The schema and the additive migrations are kept compatible with the
//! Python application so an existing `music.db` can be opened and upgraded
//! without data loss.

use std::path::{Path, PathBuf};

use rusqlite::{Connection, OptionalExtension, params};
use serde::Serialize;

pub const AUDIO_EXTENSIONS: &[&str] = &["mp3", "flac", "ogg", "m4a", "wav", "webm", "opus"];

#[derive(Debug, Clone, Serialize)]
pub struct Track {
    pub id: i64,
    pub file_path: String,
    pub title: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub duration: Option<i64>,
    pub loudness: Option<f64>,
    pub cover_path: Option<String>,
    pub folder_id: Option<i64>,
    pub added_at: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Playlist {
    pub id: i64,
    pub name: String,
    pub cover_path: Option<String>,
    pub description: Option<String>,
    pub is_pinned: i64,
    pub position: i64,
}

/// Python's `os.path.abspath(os.fspath(path))`: make the path absolute and
/// remove `.`/`..` components without resolving symlinks (unlike
/// `canonicalize`). On Windows the comparison should be case-insensitive;
/// that is handled by the platform layer in a later port step.
pub fn normalize_path(value: &str) -> String {
    let path = Path::new(value);
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf())
    };
    absolute.to_string_lossy().into_owned()
}

pub fn init_db(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS folders (
            id     INTEGER PRIMARY KEY,
            name   TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id            INTEGER PRIMARY KEY,
            file_path     TEXT UNIQUE NOT NULL,
            title         TEXT,
            artist        TEXT,
            album         TEXT,
            duration      INTEGER,
            loudness      REAL,
            cover_path    TEXT,
            cover_manual  INTEGER DEFAULT 0,
            folder_id     INTEGER REFERENCES folders(id) ON DELETE SET NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            lyrics_synced TEXT,
            lyrics_plain  TEXT,
            lyrics_checked INTEGER DEFAULT 0,
            lyrics_manual INTEGER DEFAULT 0,
            lyrics_offset_ms INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id           INTEGER PRIMARY KEY,
            name         TEXT UNIQUE NOT NULL,
            cover_path   TEXT,
            description  TEXT,
            is_pinned    INTEGER DEFAULT 0,
            position     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id  INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
            track_id     INTEGER NOT NULL REFERENCES tracks(id)    ON DELETE CASCADE,
            added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (playlist_id, track_id)
        );

        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            nickname TEXT DEFAULT 'Music Lover',
            avatar_path TEXT,
            banner_path TEXT,
            description TEXT,
            favorite_track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
            listening_seconds INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY,
            track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS playlist_visibility (
            playlist_id INTEGER PRIMARY KEY,
            is_public   INTEGER DEFAULT 0
        );
        "#,
    )
    .map_err(|e| format!("schema: {e}"))?;

    // Additive migrations, in the same order as db.py.
    let mut cols = table_columns(conn, "tracks")?;
    for (name, sql) in [
        ("loudness", "ALTER TABLE tracks ADD COLUMN loudness REAL"),
        (
            "cover_path",
            "ALTER TABLE tracks ADD COLUMN cover_path TEXT",
        ),
        (
            "cover_manual",
            "ALTER TABLE tracks ADD COLUMN cover_manual INTEGER DEFAULT 0",
        ),
        (
            "lyrics_offset_ms",
            "ALTER TABLE tracks ADD COLUMN lyrics_offset_ms INTEGER DEFAULT 0",
        ),
        (
            "folder_id",
            "ALTER TABLE tracks ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL",
        ),
        (
            "lyrics_synced",
            "ALTER TABLE tracks ADD COLUMN lyrics_synced TEXT",
        ),
        (
            "lyrics_plain",
            "ALTER TABLE tracks ADD COLUMN lyrics_plain TEXT",
        ),
        (
            "lyrics_checked",
            "ALTER TABLE tracks ADD COLUMN lyrics_checked INTEGER DEFAULT 0",
        ),
        (
            "lyrics_manual",
            "ALTER TABLE tracks ADD COLUMN lyrics_manual INTEGER DEFAULT 0",
        ),
    ] {
        if !cols.iter().any(|c| c == name) {
            conn.execute(sql, [])
                .map_err(|e| format!("migration {name}: {e}"))?;
            cols.push(name.to_string());
        }
    }
    if !cols.iter().any(|c| c == "created_at") {
        conn.execute("ALTER TABLE tracks ADD COLUMN created_at TIMESTAMP", [])
            .map_err(|e| format!("migration created_at: {e}"))?;
        conn.execute(
            "UPDATE tracks SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL",
            [],
        )
        .map_err(|e| format!("migration created_at fill: {e}"))?;
    }

    let mut playlist_cols = table_columns(conn, "playlist_tracks")?;
    if !playlist_cols.iter().any(|c| c == "added_at") {
        conn.execute(
            "ALTER TABLE playlist_tracks ADD COLUMN added_at TIMESTAMP",
            [],
        )
        .map_err(|e| format!("migration added_at: {e}"))?;
        conn.execute(
            "UPDATE playlist_tracks SET added_at = CURRENT_TIMESTAMP WHERE added_at IS NULL",
            [],
        )
        .map_err(|e| format!("migration added_at fill: {e}"))?;
        playlist_cols.push("added_at".to_string());
    }
    let _ = playlist_cols;

    let mut pl_cols = table_columns(conn, "playlists")?;
    for (name, sql) in [
        (
            "cover_path",
            "ALTER TABLE playlists ADD COLUMN cover_path TEXT",
        ),
        (
            "description",
            "ALTER TABLE playlists ADD COLUMN description TEXT",
        ),
        (
            "is_pinned",
            "ALTER TABLE playlists ADD COLUMN is_pinned INTEGER DEFAULT 0",
        ),
        (
            "position",
            "ALTER TABLE playlists ADD COLUMN position INTEGER DEFAULT 0",
        ),
    ] {
        if !pl_cols.iter().any(|c| c == name) {
            conn.execute(sql, [])
                .map_err(|e| format!("migration playlist {name}: {e}"))?;
            pl_cols.push(name.to_string());
        }
    }

    let mut profile_cols = table_columns(conn, "profile")?;
    if !profile_cols.iter().any(|c| c == "favorite_track_id") {
        conn.execute(
            "ALTER TABLE profile ADD COLUMN favorite_track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL",
            [],
        )
        .map_err(|e| format!("migration profile favorite: {e}"))?;
        profile_cols.push("favorite_track_id".to_string());
    }
    if !profile_cols.iter().any(|c| c == "listening_seconds") {
        conn.execute(
            "ALTER TABLE profile ADD COLUMN listening_seconds INTEGER DEFAULT 0",
            [],
        )
        .map_err(|e| format!("migration profile listening: {e}"))?;
        conn.execute(
            "UPDATE profile SET listening_seconds = COALESCE((
                SELECT SUM(t.duration) FROM play_history ph
                JOIN tracks t ON t.id = ph.track_id
            ), 0) WHERE id = 1",
            [],
        )
        .map_err(|e| format!("migration profile listening fill: {e}"))?;
    }

    conn.execute_batch(
        r#"
        CREATE INDEX IF NOT EXISTS idx_tracks_folder ON tracks(folder_id);
        CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks(playlist_id);
        CREATE INDEX IF NOT EXISTS idx_play_history_track ON play_history(track_id);
        "#,
    )
    .map_err(|e| format!("indexes: {e}"))?;

    // The original code creates the profile row lazily; keep a row available
    // for later profile work and for compatibility.
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)", [])
        .map_err(|e| format!("profile row: {e}"))?;

    Ok(())
}

fn table_columns(conn: &Connection, table: &str) -> Result<Vec<String>, String> {
    let mut stmt = conn
        .prepare(&format!("PRAGMA table_info({table})"))
        .map_err(|e| format!("pragma {table}: {e}"))?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|e| format!("pragma rows {table}: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("pragma value {table}: {e}"))?);
    }
    Ok(out)
}

fn row_to_track(row: &rusqlite::Row<'_>) -> rusqlite::Result<Track> {
    Ok(Track {
        id: row.get(0)?,
        file_path: row.get(1)?,
        title: row.get(2)?,
        artist: row.get(3)?,
        album: row.get(4)?,
        duration: row.get(5)?,
        loudness: row.get(6)?,
        cover_path: row.get(7)?,
        folder_id: row.get(8)?,
        added_at: None,
    })
}

/// Remove rows whose files no longer exist. The Python app does this on
/// startup so the library and playlists do not show phantom tracks.
pub fn remove_missing_tracks(conn: &Connection) -> Result<usize, String> {
    let mut stmt = conn
        .prepare("SELECT id, file_path FROM tracks")
        .map_err(|e| format!("missing tracks prepare: {e}"))?;
    let rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(|e| format!("missing tracks query: {e}"))?;
    let mut missing = Vec::new();
    for row in rows {
        let (id, path) = row.map_err(|e| format!("missing tracks row: {e}"))?;
        if !Path::new(&path).is_file() {
            missing.push(id);
        }
    }
    drop(stmt);

    for id in &missing {
        conn.execute("DELETE FROM tracks WHERE id = ?1", params![id])
            .map_err(|e| format!("delete missing track: {e}"))?;
    }
    Ok(missing.len())
}

pub fn get_all_tracks(conn: &Connection) -> Result<Vec<Track>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, file_path, title, artist, album, duration, loudness, \
             cover_path, folder_id FROM tracks ORDER BY id",
        )
        .map_err(|e| format!("tracks prepare: {e}"))?;
    let rows = stmt
        .query_map([], row_to_track)
        .map_err(|e| format!("tracks query: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("tracks row: {e}"))?);
    }
    Ok(out)
}

pub fn get_track_by_id(conn: &Connection, id: i64) -> Result<Option<Track>, String> {
    conn.query_row(
        "SELECT id, file_path, title, artist, album, duration, loudness, \
         cover_path, folder_id FROM tracks WHERE id = ?1",
        params![id],
        row_to_track,
    )
    .optional()
    .map_err(|e| format!("track by id: {e}"))
}

pub fn get_track_by_path(conn: &Connection, file_path: &str) -> Result<Option<Track>, String> {
    let normalized = normalize_path(file_path);
    conn.query_row(
        "SELECT id, file_path, title, artist, album, duration, loudness, \
         cover_path, folder_id FROM tracks WHERE file_path = ?1",
        params![normalized],
        row_to_track,
    )
    .optional()
    .map_err(|e| format!("track by path: {e}"))
}

pub fn add_track(conn: &Connection, file_path: &str) -> Result<Option<i64>, String> {
    let normalized = normalize_path(file_path);
    let changed = conn
        .execute(
            "INSERT OR IGNORE INTO tracks (file_path) VALUES (?1)",
            params![normalized],
        )
        .map_err(|e| format!("add track: {e}"))?;
    if changed == 0 {
        return Ok(None);
    }
    Ok(Some(conn.last_insert_rowid()))
}

pub fn update_track_metadata(
    conn: &Connection,
    track_id: i64,
    title: Option<&str>,
    artist: Option<&str>,
    album: Option<&str>,
    duration: Option<i64>,
) -> Result<(), String> {
    conn.execute(
        "UPDATE tracks SET title = ?1, artist = ?2, album = ?3, duration = ?4 WHERE id = ?5",
        params![title, artist, album, duration, track_id],
    )
    .map_err(|e| format!("update metadata: {e}"))?;
    Ok(())
}

pub fn update_track_cover(
    conn: &Connection,
    track_id: i64,
    cover_path: Option<&str>,
) -> Result<(), String> {
    conn.execute(
        "UPDATE tracks SET cover_path = ?1 WHERE id = ?2",
        params![cover_path, track_id],
    )
    .map_err(|e| format!("update cover: {e}"))?;
    Ok(())
}

pub fn is_cover_manual(conn: &Connection, track_id: i64) -> Result<bool, String> {
    conn.query_row(
        "SELECT COALESCE(cover_manual, 0) FROM tracks WHERE id = ?1",
        params![track_id],
        |row| Ok(row.get::<_, i64>(0)? != 0),
    )
    .optional()
    .map_err(|e| format!("cover manual: {e}"))
    .map(|value| value.unwrap_or(false))
}

pub fn set_track_cover(
    conn: &Connection,
    track_id: i64,
    cover_path: Option<&str>,
    manual: bool,
) -> Result<(), String> {
    conn.execute(
        "UPDATE tracks SET cover_path = ?1, cover_manual = ?2 WHERE id = ?3",
        params![cover_path, if manual { 1 } else { 0 }, track_id],
    )
    .map_err(|e| format!("set cover: {e}"))?;
    Ok(())
}

pub fn delete_track(conn: &Connection, track_id: i64) -> Result<(), String> {
    conn.execute("DELETE FROM tracks WHERE id = ?1", params![track_id])
        .map_err(|e| format!("delete track: {e}"))?;
    Ok(())
}

pub fn clear_track_covers(conn: &Connection) -> Result<(), String> {
    conn.execute("UPDATE tracks SET cover_path = NULL, cover_manual = 0", [])
        .map_err(|e| format!("clear covers: {e}"))?;
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
pub struct Profile {
    pub id: i64,
    pub nickname: String,
    pub avatar_path: Option<String>,
    pub banner_path: Option<String>,
    pub description: Option<String>,
    pub favorite_track_id: Option<i64>,
    pub listening_seconds: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TopTrack {
    pub track: Track,
    pub play_count: i64,
}

pub fn get_profile(conn: &Connection) -> Result<Profile, String> {
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)", [])
        .map_err(|e| format!("profile row: {e}"))?;
    conn.query_row(
        "SELECT id, nickname, avatar_path, banner_path, description, \
         favorite_track_id, COALESCE(listening_seconds, 0) FROM profile WHERE id = 1",
        [],
        |row| {
            Ok(Profile {
                id: row.get(0)?,
                nickname: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                avatar_path: row.get(2)?,
                banner_path: row.get(3)?,
                description: row.get(4)?,
                favorite_track_id: row.get(5)?,
                listening_seconds: row.get(6)?,
            })
        },
    )
    .map_err(|e| format!("profile: {e}"))
}

pub fn update_profile_field(conn: &Connection, field: &str, value: &str) -> Result<(), String> {
    let column = match field {
        "nickname" | "avatar_path" | "banner_path" | "description" => field,
        _ => return Err(format!("unknown profile field: {field}")),
    };
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)", [])
        .map_err(|e| format!("profile row: {e}"))?;
    conn.execute(
        &format!("UPDATE profile SET {column} = ?1 WHERE id = 1"),
        params![value],
    )
    .map_err(|e| format!("update profile {column}: {e}"))?;
    Ok(())
}

pub fn set_favorite_track(conn: &Connection, track_id: Option<i64>) -> Result<(), String> {
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)", [])
        .map_err(|e| format!("profile row: {e}"))?;
    conn.execute(
        "UPDATE profile SET favorite_track_id = ?1 WHERE id = 1",
        params![track_id],
    )
    .map_err(|e| format!("favorite track: {e}"))?;
    Ok(())
}

pub fn log_play(conn: &Connection, track_id: i64) -> Result<(), String> {
    conn.execute(
        "INSERT INTO play_history (track_id) VALUES (?1)",
        params![track_id],
    )
    .map_err(|e| format!("log play: {e}"))?;
    Ok(())
}

pub fn add_listening_time(conn: &Connection, seconds: i64) -> Result<(), String> {
    if seconds <= 0 {
        return Ok(());
    }
    conn.execute("INSERT OR IGNORE INTO profile (id) VALUES (1)", [])
        .map_err(|e| format!("profile row: {e}"))?;
    conn.execute(
        "UPDATE profile SET listening_seconds = \
         COALESCE(listening_seconds, 0) + ?1 WHERE id = 1",
        params![seconds],
    )
    .map_err(|e| format!("add listening time: {e}"))?;
    Ok(())
}

pub fn get_tracks_count(conn: &Connection) -> Result<i64, String> {
    conn.query_row("SELECT COUNT(*) FROM tracks", [], |row| row.get(0))
        .map_err(|e| format!("tracks count: {e}"))
}

pub fn get_playlists_count(conn: &Connection) -> Result<i64, String> {
    conn.query_row("SELECT COUNT(*) FROM playlists", [], |row| row.get(0))
        .map_err(|e| format!("playlists count: {e}"))
}

pub fn get_app_age_days(conn: &Connection) -> Result<i64, String> {
    let first: Option<String> = conn
        .query_row("SELECT MIN(created_at) FROM tracks", [], |row| row.get(0))
        .map_err(|e| format!("app age: {e}"))?;
    let Some(first) = first else {
        return Ok(0);
    };
    let days: i64 = conn
        .query_row(
            "SELECT CAST(julianday('now') - julianday(?1) AS INTEGER)",
            params![first],
            |row| row.get(0),
        )
        .map_err(|e| format!("app age days: {e}"))?;
    Ok(days.max(0))
}

pub fn get_top_tracks(conn: &Connection, limit: i64) -> Result<Vec<TopTrack>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT t.id, t.file_path, t.title, t.artist, t.album, t.duration, \
             t.loudness, t.cover_path, t.folder_id, COUNT(ph.id) AS play_count
             FROM play_history ph JOIN tracks t ON t.id = ph.track_id
             GROUP BY t.id
             ORDER BY play_count DESC, MAX(ph.played_at) DESC
             LIMIT ?1",
        )
        .map_err(|e| format!("top tracks prepare: {e}"))?;
    let rows = stmt
        .query_map(params![limit], |row| {
            Ok(TopTrack {
                track: row_to_track(row)?,
                play_count: row.get(9)?,
            })
        })
        .map_err(|e| format!("top tracks query: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("top tracks row: {e}"))?);
    }
    Ok(out)
}

#[derive(Debug, Clone, Serialize)]
pub struct Folder {
    pub id: i64,
    pub name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TrackLyrics {
    pub synced: Option<String>,
    pub plain: Option<String>,
    pub checked: bool,
    pub manual: bool,
    pub offset_ms: i64,
}

pub fn get_all_folders(conn: &Connection) -> Result<Vec<Folder>, String> {
    let mut stmt = conn
        .prepare("SELECT id, name FROM folders ORDER BY name")
        .map_err(|e| format!("folders prepare: {e}"))?;
    let rows = stmt
        .query_map([], |row| {
            Ok(Folder {
                id: row.get(0)?,
                name: row.get(1)?,
            })
        })
        .map_err(|e| format!("folders query: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("folders row: {e}"))?);
    }
    Ok(out)
}

pub fn create_folder(conn: &Connection, name: &str) -> Result<i64, String> {
    conn.execute("INSERT INTO folders (name) VALUES (?1)", params![name])
        .map_err(|e| format!("create folder: {e}"))?;
    Ok(conn.last_insert_rowid())
}

pub fn move_track_to_folder(
    conn: &Connection,
    track_id: i64,
    folder_id: Option<i64>,
) -> Result<(), String> {
    conn.execute(
        "UPDATE tracks SET folder_id = ?1 WHERE id = ?2",
        params![folder_id, track_id],
    )
    .map_err(|e| format!("move track to folder: {e}"))?;
    Ok(())
}

pub fn get_track_lyrics(conn: &Connection, track_id: i64) -> Result<TrackLyrics, String> {
    conn.query_row(
        "SELECT lyrics_synced, lyrics_plain, COALESCE(lyrics_checked, 0), \
         COALESCE(lyrics_manual, 0), COALESCE(lyrics_offset_ms, 0) \
         FROM tracks WHERE id = ?1",
        params![track_id],
        |row| {
            Ok(TrackLyrics {
                synced: row.get(0)?,
                plain: row.get(1)?,
                checked: row.get::<_, i64>(2)? != 0,
                manual: row.get::<_, i64>(3)? != 0,
                offset_ms: row.get(4)?,
            })
        },
    )
    .optional()
    .map_err(|e| format!("track lyrics: {e}"))
    .map(|row| {
        row.unwrap_or(TrackLyrics {
            synced: None,
            plain: None,
            checked: true,
            manual: false,
            offset_ms: 0,
        })
    })
}

pub fn update_track_lyrics(
    conn: &Connection,
    track_id: i64,
    synced: Option<&str>,
    plain: Option<&str>,
    manual: bool,
) -> Result<(), String> {
    if manual {
        conn.execute(
            "UPDATE tracks SET lyrics_synced = ?1, lyrics_plain = ?2, \
             lyrics_checked = 1, lyrics_manual = 1 WHERE id = ?3",
            params![synced, plain, track_id],
        )
        .map_err(|e| format!("save manual lyrics: {e}"))?;
    } else {
        conn.execute(
            "UPDATE tracks SET lyrics_synced = ?1, lyrics_plain = ?2, \
             lyrics_checked = 1 WHERE id = ?3 AND COALESCE(lyrics_manual, 0) = 0",
            params![synced, plain, track_id],
        )
        .map_err(|e| format!("save track lyrics: {e}"))?;
    }
    Ok(())
}

pub fn set_track_lyrics_offset(
    conn: &Connection,
    track_id: i64,
    offset_ms: i64,
) -> Result<(), String> {
    conn.execute(
        "UPDATE tracks SET lyrics_offset_ms = ?1 WHERE id = ?2",
        params![offset_ms, track_id],
    )
    .map_err(|e| format!("lyrics offset: {e}"))?;
    Ok(())
}

pub fn get_all_playlists(conn: &Connection) -> Result<Vec<Playlist>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT id, name, cover_path, description, is_pinned, position \
             FROM playlists ORDER BY is_pinned DESC, position ASC, id ASC",
        )
        .map_err(|e| format!("playlists prepare: {e}"))?;
    let rows = stmt
        .query_map([], |row| {
            Ok(Playlist {
                id: row.get(0)?,
                name: row.get(1)?,
                cover_path: row.get(2)?,
                description: row.get(3)?,
                is_pinned: row.get(4)?,
                position: row.get(5)?,
            })
        })
        .map_err(|e| format!("playlists query: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("playlists row: {e}"))?);
    }
    Ok(out)
}

pub fn create_playlist(conn: &Connection, name: &str) -> Result<Option<i64>, String> {
    let name = name.trim();
    if name.is_empty() {
        return Ok(None);
    }
    let changed = conn
        .execute(
            "INSERT OR IGNORE INTO playlists (name, position) \
             VALUES (?1, (SELECT COALESCE(MAX(position), 0) + 1 FROM playlists))",
            params![name],
        )
        .map_err(|e| format!("create playlist: {e}"))?;
    if changed == 0 {
        return Ok(None);
    }
    Ok(Some(conn.last_insert_rowid()))
}

pub fn update_playlist_cover(
    conn: &Connection,
    playlist_id: i64,
    cover_path: &str,
) -> Result<(), String> {
    conn.execute(
        "UPDATE playlists SET cover_path = ?1 WHERE id = ?2",
        params![cover_path, playlist_id],
    )
    .map_err(|e| format!("update playlist cover: {e}"))?;
    Ok(())
}

pub fn update_playlist_description(
    conn: &Connection,
    playlist_id: i64,
    description: &str,
) -> Result<(), String> {
    conn.execute(
        "UPDATE playlists SET description = ?1 WHERE id = ?2",
        params![description, playlist_id],
    )
    .map_err(|e| format!("update playlist description: {e}"))?;
    Ok(())
}

pub fn delete_playlist(conn: &Connection, playlist_id: i64) -> Result<(), String> {
    conn.execute("DELETE FROM playlists WHERE id = ?1", params![playlist_id])
        .map_err(|e| format!("delete playlist: {e}"))?;
    Ok(())
}

pub fn add_track_to_playlist(
    conn: &Connection,
    playlist_id: i64,
    track_id: i64,
) -> Result<bool, String> {
    let changed = conn
        .execute(
            "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id) \
             VALUES (?1, ?2)",
            params![playlist_id, track_id],
        )
        .map_err(|e| format!("add to playlist: {e}"))?;
    Ok(changed > 0)
}

pub fn remove_track_from_playlist(
    conn: &Connection,
    playlist_id: i64,
    track_id: i64,
) -> Result<(), String> {
    conn.execute(
        "DELETE FROM playlist_tracks WHERE playlist_id = ?1 AND track_id = ?2",
        params![playlist_id, track_id],
    )
    .map_err(|e| format!("remove from playlist: {e}"))?;
    Ok(())
}

pub fn get_tracks_in_playlist(conn: &Connection, playlist_id: i64) -> Result<Vec<Track>, String> {
    let mut stmt = conn
        .prepare(
            "SELECT t.id, t.file_path, t.title, t.artist, t.album, t.duration, \
             t.loudness, t.cover_path, t.folder_id, pt.added_at
             FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
             WHERE pt.playlist_id = ?1
             ORDER BY pt.added_at, t.id",
        )
        .map_err(|e| format!("playlist tracks prepare: {e}"))?;
    let rows = stmt
        .query_map(params![playlist_id], |row| {
            let mut track = row_to_track(row)?;
            track.added_at = row.get(9)?;
            Ok(track)
        })
        .map_err(|e| format!("playlist tracks query: {e}"))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| format!("playlist tracks row: {e}"))?);
    }
    Ok(out)
}

pub fn track_path(conn: &Connection, track_id: i64) -> Result<Option<String>, String> {
    conn.query_row(
        "SELECT file_path FROM tracks WHERE id = ?1",
        params![track_id],
        |row| row.get::<_, String>(0),
    )
    .optional()
    .map_err(|e| format!("track path: {e}"))
}

pub fn _pathbuf_to_string(path: &PathBuf) -> String {
    path.to_string_lossy().into_owned()
}
