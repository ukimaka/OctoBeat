//! C ABI for the OctoBeat Qt 6 application.
//!
//! The Qt side owns the UI and libVLC; this crate owns SQLite, metadata,
//! covers and the library scanner. All functions are synchronous and
//! thread-safe; the UI may call them from a worker thread.

pub mod db;
pub mod metadata;
pub mod scan;

use std::ffi::{CStr, CString, c_char, c_void};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use rusqlite::Connection;

pub struct Core {
    conn: Mutex<Connection>,
    music_dir: Mutex<PathBuf>,
    covers_dir: PathBuf,
    last_error: Mutex<Option<CString>>,
}

impl Core {
    fn open(
        data_dir: &str,
        db_path: &str,
        music_dir: &str,
        cache_dir: &str,
    ) -> Result<Self, String> {
        fs::create_dir_all(data_dir).map_err(|e| format!("data dir: {e}"))?;
        fs::create_dir_all(cache_dir).map_err(|e| format!("cache dir: {e}"))?;

        let conn = Self::open_database(db_path)?;
        let missing = db::remove_missing_tracks(&conn)?;
        if missing > 0 {
            eprintln!("[octobeat-core] removed missing tracks: {missing}");
        }

        let covers_dir = PathBuf::from(cache_dir).join("covers");
        fs::create_dir_all(&covers_dir).map_err(|e| format!("covers dir: {e}"))?;

        Ok(Self {
            conn: Mutex::new(conn),
            music_dir: Mutex::new(PathBuf::from(music_dir)),
            covers_dir,
            last_error: Mutex::new(None),
        })
    }

    fn open_database(db_path: &str) -> Result<Connection, String> {
        let mut last_error = String::new();
        for attempt in 0..2 {
            let result = (|| -> Result<Connection, String> {
                let conn = Connection::open(db_path).map_err(|e| format!("open database: {e}"))?;
                conn.busy_timeout(std::time::Duration::from_millis(5000))
                    .map_err(|e| format!("busy_timeout: {e}"))?;
                conn.execute_batch("PRAGMA foreign_keys = ON; PRAGMA journal_mode=WAL;")
                    .map_err(|e| format!("pragma: {e}"))?;
                {
                    let mut check = conn
                        .prepare("PRAGMA quick_check")
                        .map_err(|e| format!("quick_check: {e}"))?;
                    let rows = check
                        .query_map([], |row| row.get::<_, String>(0))
                        .map_err(|e| format!("quick_check query: {e}"))?;
                    for row in rows {
                        let status = row.map_err(|e| format!("quick_check row: {e}"))?;
                        if status != "ok" {
                            return Err(format!("database integrity: {status}"));
                        }
                    }
                }
                db::init_db(&conn)?;
                Ok(conn)
            })();
            match result {
                Ok(conn) => return Ok(conn),
                Err(error) => {
                    last_error = error.clone();
                    let corrupted = error.contains("malformed")
                        || error.contains("not a database")
                        || error.contains("database integrity");
                    if attempt == 0 && corrupted {
                        let stamp = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .map(|value| value.as_secs())
                            .unwrap_or(0);
                        let backup = format!("{db_path}.corrupt-{stamp}");
                        let backup = if fs::metadata(&backup).is_ok() {
                            format!("{backup}-{attempt}")
                        } else {
                            backup
                        };
                        let _ = fs::rename(db_path, &backup);
                        let _ = fs::remove_file(format!("{db_path}-wal"));
                        let _ = fs::remove_file(format!("{db_path}-shm"));
                        eprintln!("[octobeat-core] database is corrupted; moved to {backup}");
                        continue;
                    }
                    break;
                }
            }
        }
        Err(last_error)
    }

    fn set_error(&self, message: impl Into<String>) {
        let message = message.into();
        eprintln!("[octobeat-core] {message}");
        if let Ok(mut error) = self.last_error.lock() {
            *error = CString::new(message).ok();
        }
    }

    fn lock_db(&self) -> Result<std::sync::MutexGuard<'_, Connection>, String> {
        self.conn
            .lock()
            .map_err(|_| "database lock poisoned".to_string())
    }
}

fn c_string(value: *const c_char, fallback: &str) -> Result<String, String> {
    if value.is_null() {
        return Ok(fallback.to_string());
    }
    let text = unsafe { CStr::from_ptr(value) }
        .to_str()
        .map_err(|e| format!("invalid UTF-8: {e}"))?;
    Ok(text.to_string())
}

fn into_c_string(value: String) -> *mut c_char {
    match CString::new(value) {
        Ok(value) => value.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_new(
    data_dir: *const c_char,
    db_path: *const c_char,
    music_dir: *const c_char,
    cache_dir: *const c_char,
) -> *mut Core {
    let result = (|| -> Result<Core, String> {
        let data_dir = c_string(data_dir, "")?;
        let db_path = c_string(db_path, "")?;
        let music_dir = c_string(music_dir, "")?;
        let cache_dir = c_string(cache_dir, "")?;
        if data_dir.is_empty() || db_path.is_empty() || music_dir.is_empty() || cache_dir.is_empty()
        {
            return Err("data_dir, db_path, music_dir and cache_dir are required".to_string());
        }
        Core::open(&data_dir, &db_path, &music_dir, &cache_dir)
    })();

    match result {
        Ok(core) => Box::into_raw(Box::new(core)),
        Err(error) => {
            eprintln!("[octobeat-core] init failed: {error}");
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_free(core: *mut Core) {
    if core.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(core));
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_tracks_json(core: *mut Core) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    match core
        .lock_db()
        .and_then(|conn| db::get_all_tracks(&conn))
        .and_then(|tracks| serde_json::to_string(&tracks).map_err(|e| e.to_string()))
    {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_playlists_json(core: *mut Core) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    match core
        .lock_db()
        .and_then(|conn| db::get_all_playlists(&conn))
        .and_then(|playlists| serde_json::to_string(&playlists).map_err(|e| e.to_string()))
    {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_playlist_tracks_json(
    core: *mut Core,
    playlist_id: i64,
) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    match core
        .lock_db()
        .and_then(|conn| db::get_tracks_in_playlist(&conn, playlist_id))
        .and_then(|tracks| serde_json::to_string(&tracks).map_err(|e| e.to_string()))
    {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_create_playlist(core: *mut Core, name: *const c_char) -> i64 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return 0;
    };
    let result = c_string(name, "").and_then(|name| {
        core.lock_db()
            .and_then(|conn| db::create_playlist(&conn, &name))
    });
    match result {
        Ok(Some(id)) => id,
        Ok(None) => 0,
        Err(error) => {
            core.set_error(error);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_update_playlist_description(
    core: *mut Core,
    playlist_id: i64,
    description: *const c_char,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = c_string(description, "").and_then(|description| {
        core.lock_db()
            .and_then(|conn| db::update_playlist_description(&conn, playlist_id, &description))
    });
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_update_playlist_cover(
    core: *mut Core,
    playlist_id: i64,
    cover_path: *const c_char,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = c_string(cover_path, "").and_then(|cover_path| {
        core.lock_db()
            .and_then(|conn| db::update_playlist_cover(&conn, playlist_id, &cover_path))
    });
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_delete_playlist(core: *mut Core, playlist_id: i64) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::delete_playlist(&conn, playlist_id))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_add_track_to_playlist(
    core: *mut Core,
    playlist_id: i64,
    track_id: i64,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::add_track_to_playlist(&conn, playlist_id, track_id))
    {
        Ok(true) => 0,
        Ok(false) => -1,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_remove_track_from_playlist(
    core: *mut Core,
    playlist_id: i64,
    track_id: i64,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::remove_track_from_playlist(&conn, playlist_id, track_id))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_track_path(core: *mut Core, track_id: i64) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    match core
        .lock_db()
        .and_then(|conn| db::track_path(&conn, track_id))
    {
        Ok(Some(path)) => into_c_string(path),
        Ok(None) => std::ptr::null_mut(),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_scan(
    core: *mut Core,
    progress: Option<extern "C" fn(i32, i32, *mut c_void)>,
    user_data: *mut c_void,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };

    let music_dir = match core.music_dir.lock() {
        Ok(directory) => directory.clone(),
        Err(_) => {
            core.set_error("music directory lock poisoned");
            return -1;
        }
    };
    let result = scan::scan_library(&core.conn, &music_dir, &core.covers_dir, |done, total| {
        if let Some(callback) = progress {
            callback(done as i32, total as i32, user_data);
        }
    });

    match result {
        Ok(result) => {
            eprintln!(
                "[octobeat-core] scan: added={}, updated={}, total={}",
                result.added, result.updated, result.total
            );
            0
        }
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_set_music_dir(core: *mut Core, music_dir: *const c_char) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let Ok(directory) = c_string(music_dir, "") else {
        return -1;
    };
    if directory.is_empty() {
        return -1;
    }
    match core.music_dir.lock() {
        Ok(mut current) => {
            *current = PathBuf::from(directory);
            0
        }
        Err(_) => {
            core.set_error("music directory lock poisoned");
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_folders_json(core: *mut Core) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    let result = core
        .lock_db()
        .and_then(|conn| db::get_all_folders(&conn))
        .and_then(|folders| serde_json::to_string(&folders).map_err(|e| e.to_string()));
    match result {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_create_folder(core: *mut Core, name: *const c_char) -> i64 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return 0;
    };
    let result = c_string(name, "").and_then(|name| {
        core.lock_db()
            .and_then(|conn| db::create_folder(&conn, &name))
    });
    match result {
        Ok(id) => id,
        Err(error) => {
            core.set_error(error);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_move_track_to_folder(
    core: *mut Core,
    track_id: i64,
    folder_id: i64,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let folder = if folder_id > 0 { Some(folder_id) } else { None };
    match core
        .lock_db()
        .and_then(|conn| db::move_track_to_folder(&conn, track_id, folder))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_track_lyrics_json(core: *mut Core, track_id: i64) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    let result = core
        .lock_db()
        .and_then(|conn| db::get_track_lyrics(&conn, track_id))
        .and_then(|lyrics| serde_json::to_string(&lyrics).map_err(|e| e.to_string()));
    match result {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_update_track_lyrics(
    core: *mut Core,
    track_id: i64,
    synced: *const c_char,
    plain: *const c_char,
    manual: i32,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = (|| -> Result<(), String> {
        let synced = c_string(synced, "")?;
        let plain = c_string(plain, "")?;
        let conn = core.lock_db()?;
        db::update_track_lyrics(
            &conn,
            track_id,
            if synced.is_empty() {
                None
            } else {
                Some(&synced)
            },
            if plain.is_empty() { None } else { Some(&plain) },
            manual != 0,
        )
    })();
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_profile_json(core: *mut Core) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    let result = (|| -> Result<String, String> {
        let conn = core.lock_db()?;
        let profile = db::get_profile(&conn)?;
        let tracks_count = db::get_tracks_count(&conn)?;
        let playlists_count = db::get_playlists_count(&conn)?;
        let app_age_days = db::get_app_age_days(&conn)?;
        let favorite = match profile.favorite_track_id {
            Some(id) => db::get_track_by_id(&conn, id)?,
            None => None,
        };
        let top_tracks = db::get_top_tracks(&conn, 5)?;
        let playlists = db::get_all_playlists(&conn)?;
        serde_json::to_string(&serde_json::json!({
            "profile": profile,
            "tracks": tracks_count,
            "playlists_count": playlists_count,
            "app_age_days": app_age_days,
            "favorite": favorite,
            "top_tracks": top_tracks,
            "playlists": playlists,
        }))
        .map_err(|e| e.to_string())
    })();
    match result {
        Ok(json) => into_c_string(json),
        Err(error) => {
            core.set_error(error);
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_set_profile_field(
    core: *mut Core,
    field: *const c_char,
    value: *const c_char,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = (|| -> Result<(), String> {
        let field = c_string(field, "")?;
        let value = c_string(value, "")?;
        let conn = core.lock_db()?;
        if field == "favorite_track_id" {
            let id = if value.is_empty() {
                None
            } else {
                Some(value.parse::<i64>().map_err(|e| e.to_string())?)
            };
            db::set_favorite_track(&conn, id)
        } else {
            db::update_profile_field(&conn, &field, &value)
        }
    })();
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_log_play(core: *mut Core, track_id: i64) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::log_play(&conn, track_id))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_add_listening_time(core: *mut Core, seconds: i64) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::add_listening_time(&conn, seconds))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_delete_track(core: *mut Core, track_id: i64) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::delete_track(&conn, track_id))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_update_track_metadata(
    core: *mut Core,
    track_id: i64,
    title: *const c_char,
    artist: *const c_char,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = (|| -> Result<(), String> {
        let title = c_string(title, "")?;
        let artist = c_string(artist, "")?;
        if title.trim().is_empty() {
            return Err("empty title".to_string());
        }
        let conn = core.lock_db()?;
        let track =
            db::get_track_by_id(&conn, track_id)?.ok_or_else(|| "track not found".to_string())?;
        metadata::write_tags(
            std::path::Path::new(&track.file_path),
            title.trim(),
            artist.trim(),
        )?;
        db::update_track_metadata(
            &conn,
            track_id,
            Some(title.trim()),
            Some(artist.trim()),
            track.album.as_deref(),
            track.duration,
        )
    })();
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_set_track_cover(
    core: *mut Core,
    track_id: i64,
    source_path: *const c_char,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = (|| -> Result<(), String> {
        let source = c_string(source_path, "")?;
        if source.is_empty() {
            return Err("empty cover path".to_string());
        }
        let extension = std::path::Path::new(&source)
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("jpg")
            .to_lowercase();
        let destination = core.covers_dir.join(format!("{track_id}.{extension}"));
        fs::copy(&source, &destination).map_err(|e| format!("copy cover: {e}"))?;
        let conn = core.lock_db()?;
        db::set_track_cover(&conn, track_id, Some(&destination.to_string_lossy()), true)
    })();
    match result {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_set_lyrics_offset(
    core: *mut Core,
    track_id: i64,
    offset_ms: i64,
) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    match core
        .lock_db()
        .and_then(|conn| db::set_track_lyrics_offset(&conn, track_id, offset_ms))
    {
        Ok(()) => 0,
        Err(error) => {
            core.set_error(error);
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_clear_covers(core: *mut Core) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = core
        .lock_db()
        .and_then(|conn| db::clear_track_covers(&conn));
    if let Err(error) = result {
        core.set_error(error);
        return -1;
    }
    let _ = fs::remove_dir_all(&core.covers_dir);
    let _ = fs::create_dir_all(&core.covers_dir);
    0
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_clear_all_cache(core: *mut Core) -> i32 {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return -1;
    };
    let result = core
        .lock_db()
        .and_then(|conn| db::clear_track_covers(&conn));
    if let Err(error) = result {
        core.set_error(error);
        return -1;
    }
    if let Some(parent) = core.covers_dir.parent() {
        let _ = fs::remove_dir_all(parent);
        let _ = fs::create_dir_all(parent);
    }
    0
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_core_last_error(core: *mut Core) -> *mut c_char {
    let Some(core) = (unsafe { core.as_ref() }) else {
        return std::ptr::null_mut();
    };
    match core.last_error.lock() {
        Ok(error) => error
            .as_ref()
            .map(|value| into_c_string(value.to_string_lossy().into_owned()))
            .unwrap_or(std::ptr::null_mut()),
        Err(_) => std::ptr::null_mut(),
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_string_free(value: *mut c_char) {
    if value.is_null() {
        return;
    }
    unsafe {
        drop(CString::from_raw(value));
    }
}
