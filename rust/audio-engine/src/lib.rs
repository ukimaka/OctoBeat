//! C ABI for the native OctoBeat audio engine.

#![allow(clippy::not_unsafe_ptr_arg_deref)]

mod decoder;
mod engine;

pub use engine::{AudioEngine, EngineEvent, SharedSlot};

use std::ffi::{c_char, c_int, CStr};

fn c_string(value: *const c_char, fallback: &str) -> Result<String, String> {
    if value.is_null() {
        return Ok(fallback.to_string());
    }
    let text = unsafe { CStr::from_ptr(value) }
        .to_str()
        .map_err(|error| format!("invalid UTF-8 path: {error}"))?;
    Ok(text.to_string())
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_new() -> *mut AudioEngine {
    match AudioEngine::new() {
        Ok(engine) => Box::into_raw(Box::new(engine)),
        Err(error) => {
            eprintln!("[octobeat-audio] init failed: {error:#}");
            std::ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_free(engine: *mut AudioEngine) {
    if engine.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(engine));
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_play(
    engine: *mut AudioEngine,
    path: *const c_char,
    start_ms: i64,
) -> c_int {
    if engine.is_null() {
        return 0;
    }
    let engine = unsafe { &*engine };
    let path = match c_string(path, "") {
        Ok(path) => path,
        Err(error) => {
            engine.set_error(error);
            return 0;
        }
    };
    if path.is_empty() {
        engine.set_error("Empty audio path.");
        return 0;
    }
    if engine.play(path, start_ms) {
        1
    } else {
        0
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_crossfade(engine: *mut AudioEngine, path: *const c_char) -> c_int {
    if engine.is_null() {
        return 0;
    }
    let engine = unsafe { &*engine };
    let path = match c_string(path, "") {
        Ok(path) => path,
        Err(error) => {
            engine.set_error(error);
            return 0;
        }
    };
    if path.is_empty() {
        engine.set_error("Empty audio path.");
        return 0;
    }
    match engine.crossfade(path) {
        Ok(()) => 1,
        Err(error) => {
            engine.set_error(error);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_finish_crossfade(engine: *mut AudioEngine) {
    if !engine.is_null() {
        unsafe { &*engine }.finish_crossfade();
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_cancel_crossfade(engine: *mut AudioEngine) {
    if !engine.is_null() {
        unsafe { &*engine }.cancel_crossfade();
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_stop(engine: *mut AudioEngine) {
    if !engine.is_null() {
        unsafe { &*engine }.stop();
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_pause(engine: *mut AudioEngine) {
    if !engine.is_null() {
        unsafe { &*engine }.pause();
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_resume(engine: *mut AudioEngine) {
    if !engine.is_null() {
        unsafe { &*engine }.resume();
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_seek(engine: *mut AudioEngine, position_ms: i64) {
    if !engine.is_null() {
        unsafe { &*engine }.seek(position_ms.max(0));
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_set_volume(engine: *mut AudioEngine, volume: c_int) {
    if !engine.is_null() {
        unsafe { &*engine }.set_volume(volume.clamp(0, 100) as f32 / 100.0);
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_set_slot_volume(
    engine: *mut AudioEngine,
    slot: c_int,
    volume: c_int,
) {
    if !engine.is_null() && (0..2).contains(&slot) {
        unsafe { &*engine }.set_slot_volume(slot as usize, volume.clamp(0, 100) as f32 / 100.0);
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_set_duration_hint(engine: *mut AudioEngine, duration_ms: i64) {
    if !engine.is_null() {
        unsafe { &*engine }.set_duration_hint(duration_ms);
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_position(engine: *mut AudioEngine) -> i64 {
    if engine.is_null() {
        0
    } else {
        unsafe { &*engine }.position()
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_duration(engine: *mut AudioEngine) -> i64 {
    if engine.is_null() {
        0
    } else {
        unsafe { &*engine }.duration()
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_is_playing(engine: *mut AudioEngine) -> c_int {
    if engine.is_null() {
        0
    } else if unsafe { &*engine }.is_playing() {
        1
    } else {
        0
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_active_slot(engine: *mut AudioEngine) -> c_int {
    if engine.is_null() {
        0
    } else {
        unsafe { &*engine }.active_slot() as c_int
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_has_ended(engine: *mut AudioEngine) -> c_int {
    if engine.is_null() {
        0
    } else if unsafe { &*engine }.has_ended() {
        1
    } else {
        0
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_underruns(engine: *mut AudioEngine) -> u64 {
    if engine.is_null() {
        0
    } else {
        unsafe { &*engine }.underruns()
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn octobeat_audio_take_error(
    engine: *mut AudioEngine,
    buffer: *mut c_char,
    buffer_len: c_int,
) -> c_int {
    if engine.is_null() || buffer.is_null() || buffer_len <= 0 {
        return -1;
    }
    let engine = unsafe { &*engine };
    let Some(message) = engine.take_error() else {
        return 0;
    };
    let bytes = message.as_bytes();
    let limit = (buffer_len as usize).saturating_sub(1);
    let count = bytes.len().min(limit);
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr() as *const c_char, buffer, count);
        *buffer.add(count) = 0;
    }
    count as c_int
}
