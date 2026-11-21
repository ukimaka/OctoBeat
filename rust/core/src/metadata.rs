//! Tag, duration and embedded-cover reading for the library scanner.

use std::fs;
use std::path::{Path, PathBuf};

use lofty::config::WriteOptions;
use lofty::file::{AudioFile, TaggedFileExt};
use lofty::tag::Accessor;

#[derive(Debug, Clone, Default)]
pub struct Metadata {
    pub title: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub duration: Option<i64>,
}

pub fn read(path: &Path) -> Metadata {
    let mut result = Metadata::default();

    if let Ok(tagged) = lofty::read_from_path(path) {
        if let Some(tag) = tagged.primary_tag().or_else(|| tagged.first_tag()) {
            result.title = tag.title().map(|v| v.to_string());
            result.artist = tag.artist().map(|v| v.to_string());
            result.album = tag.album().map(|v| v.to_string());
        }
        let seconds = tagged.properties().duration().as_secs();
        if seconds > 0 {
            result.duration = Some(seconds as i64);
        }
    }

    if result.title.is_none() || result.artist.is_none() {
        let (file_title, file_artist) = parse_filename(path);
        if result.title.is_none() {
            result.title = file_title;
        }
        if result.artist.is_none() {
            result.artist = file_artist;
        }
    }

    result
}

/// The original app falls back to `Artist - Title` from the filename.
fn parse_filename(path: &Path) -> (Option<String>, Option<String>) {
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().trim().to_string())
        .unwrap_or_default();
    if stem.is_empty() {
        return (None, None);
    }

    if let Some((artist, title)) = stem.split_once(" - ") {
        let artist = artist.trim();
        let title = title.trim();
        if !artist.is_empty() && !title.is_empty() {
            return (Some(title.to_string()), Some(artist.to_string()));
        }
    }

    (Some(stem), None)
}

/// Write title/artist tags back to the audio file.
pub fn write_tags(path: &Path, title: &str, artist: &str) -> Result<(), String> {
    let mut tagged = lofty::read_from_path(path).map_err(|e| format!("read tags: {e}"))?;
    let tag = match tagged.primary_tag_mut() {
        Some(tag) => tag,
        None => tagged
            .first_tag_mut()
            .ok_or_else(|| "no writable tag".to_string())?,
    };
    tag.set_title(title.to_string());
    tag.set_artist(artist.to_string());
    tagged
        .save_to_path(path, WriteOptions::default())
        .map_err(|e| format!("save tags: {e}"))
}

/// Extract the first embedded picture, or use a same-named image file next
/// to the track (Artist - Title.flac + Artist - Title.jpg). The source file
/// is never modified; the image is copied into the cover cache.
pub fn extract_cover(path: &Path, dest_dir: &Path, track_id: i64) -> Option<String> {
    extract_embedded_cover(path, dest_dir, track_id)
        .or_else(|| extract_sidecar_cover(path, dest_dir, track_id))
}

fn extract_embedded_cover(path: &Path, dest_dir: &Path, track_id: i64) -> Option<String> {
    let tagged = lofty::read_from_path(path).ok()?;
    let tag = tagged.primary_tag().or_else(|| tagged.first_tag())?;
    let picture = tag.pictures().first()?;
    let data = picture.data();
    if data.is_empty() {
        return None;
    }

    let extension = if data.starts_with(&[0xFF, 0xD8]) {
        "jpg"
    } else if data.starts_with(&[0x89, b'P', b'N', b'G']) {
        "png"
    } else {
        "jpg"
    };

    if fs::create_dir_all(dest_dir).is_err() {
        return None;
    }
    let output: PathBuf = dest_dir.join(format!("{track_id}.{extension}"));
    fs::write(&output, data).ok()?;
    Some(output.to_string_lossy().into_owned())
}

fn extract_sidecar_cover(path: &Path, dest_dir: &Path, track_id: i64) -> Option<String> {
    let directory = path.parent()?;
    let stem = path.file_stem()?.to_string_lossy();
    let mut candidates = Vec::new();
    for entry in fs::read_dir(directory).ok()?.flatten() {
        let candidate = entry.path();
        if !candidate.is_file() {
            continue;
        }
        let extension = candidate
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if !matches!(extension.as_str(), "jpg" | "jpeg" | "png" | "webp") {
            continue;
        }
        let candidate_stem = candidate
            .file_stem()
            .map(|value| value.to_string_lossy())
            .unwrap_or_default();
        if candidate_stem.eq_ignore_ascii_case(&stem) {
            candidates.push(candidate);
        }
    }
    candidates.sort_by_key(|candidate| {
        let extension = candidate
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        match extension.as_str() {
            "jpg" | "jpeg" => 0,
            "png" => 1,
            _ => 2,
        }
    });
    let source = candidates.into_iter().next()?;
    let extension = source
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("jpg")
        .to_ascii_lowercase();
    if fs::create_dir_all(dest_dir).is_err() {
        return None;
    }
    let output: PathBuf = dest_dir.join(format!("{track_id}.{extension}"));
    fs::copy(&source, &output).ok()?;
    Some(output.to_string_lossy().into_owned())
}
