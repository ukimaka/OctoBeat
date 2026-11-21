//! Recursive music-folder scanner.

use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use rusqlite::Connection;
use walkdir::WalkDir;

use crate::db::{self, AUDIO_EXTENSIONS};
use crate::metadata;

#[derive(Debug, Default, Clone, Copy)]
pub struct ScanResult {
    pub added: usize,
    pub updated: usize,
    pub total: usize,
}

pub fn scan_library(
    conn: &Mutex<Connection>,
    music_dir: &Path,
    covers_dir: &Path,
    cancel: &AtomicBool,
    mut progress: impl FnMut(usize, usize),
) -> Result<ScanResult, String> {
    {
        let conn = conn
            .lock()
            .map_err(|_| "database lock poisoned".to_string())?;
        db::remove_missing_tracks(&conn)?;
    }

    let mut files = Vec::new();
    for entry in WalkDir::new(music_dir)
        .follow_links(false)
        .into_iter()
        .filter_map(Result::ok)
    {
        if cancel.load(Ordering::Relaxed) {
            return Err("scan canceled".to_string());
        }
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        let extension = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.to_ascii_lowercase());
        if extension
            .as_deref()
            .is_some_and(|e| AUDIO_EXTENSIONS.contains(&e))
        {
            files.push(path.to_path_buf());
        }
    }
    files.sort();

    let total = files.len();
    let mut result = ScanResult {
        total,
        ..Default::default()
    };

    for (index, path) in files.iter().enumerate() {
        if cancel.load(Ordering::Relaxed) {
            return Err("scan canceled".to_string());
        }
        let normalized = db::normalize_path(&path.to_string_lossy());
        let meta = metadata::read(path);

        let (track_id, added) = {
            let conn = conn
                .lock()
                .map_err(|_| "database lock poisoned".to_string())?;
            if let Some(track) = db::get_track_by_path(&conn, &normalized)? {
                (track.id, false)
            } else {
                match db::add_track(&conn, &normalized)? {
                    Some(id) => (id, true),
                    None => continue,
                }
            }
        };

        {
            let conn = conn
                .lock()
                .map_err(|_| "database lock poisoned".to_string())?;
            db::update_track_metadata(
                &conn,
                track_id,
                meta.title.as_deref(),
                meta.artist.as_deref(),
                meta.album.as_deref(),
                meta.duration,
            )?;
        }

        let manual_cover = {
            let conn = conn
                .lock()
                .map_err(|_| "database lock poisoned".to_string())?;
            db::is_cover_manual(&conn, track_id)?
        };
        if !manual_cover {
            if let Some(cover) = metadata::extract_cover(path, covers_dir, track_id) {
                let conn = conn
                    .lock()
                    .map_err(|_| "database lock poisoned".to_string())?;
                db::update_track_cover(&conn, track_id, Some(&cover))?;
            }
        }

        if added {
            result.added += 1;
        } else {
            result.updated += 1;
        }
        progress(index + 1, total);
    }

    Ok(result)
}
