use std::fs::File;
use std::path::Path;
use std::sync::atomic::Ordering;
use std::sync::mpsc::{Sender, SyncSender};
use std::sync::Arc;
use std::thread;

use symphonia::core::codecs::audio::AudioDecoderOptions;
use symphonia::core::codecs::registry::CodecRegistry;
use symphonia::core::common::Tier;
use symphonia::core::errors::Error;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, SeekMode, SeekTo, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::units::{Duration as SymphoniaDuration, Time};
use symphonia_opus::OpusDecoder;

use crate::engine::{EngineEvent, SharedSlot};

type Prepared = Result<(u32, usize, i64), String>;

fn registry() -> CodecRegistry {
    let mut codecs = CodecRegistry::new();
    symphonia::default::register_enabled_codecs(&mut codecs);
    codecs.register_audio_decoder_at_tier::<OpusDecoder>(Tier::Fallback);
    codecs
}

fn duration_ms(track: &symphonia::core::formats::Track) -> i64 {
    if let (Some(duration), Some(time_base)) = (track.duration, track.time_base) {
        if let Some(time) = time_base.calc_duration(duration) {
            return time.as_millis().max(0) as i64;
        }
    }
    if let (Some(frames), Some(params)) = (track.num_frames, track.codec_params.as_ref()) {
        if let Some(audio) = params.audio() {
            if let Some(rate) = audio.sample_rate {
                if rate > 0 {
                    return ((frames as u128 * 1000) / rate as u128) as i64;
                }
            }
        }
    }
    0
}

pub fn spawn(
    slot: usize,
    generation: u64,
    path: String,
    start_ms: i64,
    shared: Arc<SharedSlot>,
    sample_tx: SyncSender<EngineEvent>,
    prepare_tx: Sender<Prepared>,
) {
    let _ = thread::Builder::new()
        .name(format!("octobeat-decode-{slot}"))
        .spawn(move || {
            if let Err(message) = run(
                slot,
                generation,
                &path,
                start_ms,
                &shared,
                &sample_tx,
                &prepare_tx,
            ) {
                let _ = prepare_tx.send(Err(message.clone()));
                let _ = sample_tx.send(EngineEvent::Error {
                    slot,
                    generation,
                    message,
                });
            }
        });
}

fn run(
    slot: usize,
    generation: u64,
    path: &str,
    start_ms: i64,
    shared: &SharedSlot,
    sample_tx: &SyncSender<EngineEvent>,
    prepare_tx: &Sender<Prepared>,
) -> Result<(), String> {
    let file = File::open(Path::new(path)).map_err(|e| format!("open {path}: {e}"))?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(extension) = Path::new(path).extension().and_then(|e| e.to_str()) {
        hint.with_extension(extension);
    }
    let mut format = symphonia::default::get_probe()
        .probe(
            &hint,
            mss,
            FormatOptions::default().seek_index_fill_period_ms(200),
            MetadataOptions::default(),
        )
        .map_err(|e| format!("probe {path}: {e}"))?;

    if start_ms > 0 {
        // FIFOs and live ADTS streams are not seekable; they simply start at
        // the beginning, which is what the streaming cache path expects.
        let _ = format.seek(
            SeekMode::Accurate,
            SeekTo::Time {
                time: Time::from_millis(start_ms.max(0)),
                track_id: None,
            },
        );
    }

    let (track_id, mut duration, params) = {
        let track = format
            .default_track(TrackType::Audio)
            .ok_or_else(|| "no audio track".to_string())?;
        let params = track
            .codec_params
            .as_ref()
            .and_then(|params| params.audio())
            .cloned()
            .ok_or_else(|| "no audio codec parameters".to_string())?;
        (track.id, duration_ms(track), params)
    };

    // Matroska/WebM usually has no total duration in the track header. Use a
    // separate reader so the main format stays at the beginning; FIFOs and
    // other live streams are skipped because they cannot be rewound.
    if duration == 0
        && start_ms == 0
        && std::path::Path::new(path)
            .metadata()
            .map(|metadata| metadata.is_file())
            .unwrap_or(false)
    {
        duration = scan_duration(path).unwrap_or(0);
    }

    let mut decoder = registry()
        .make_audio_decoder(&params, &AudioDecoderOptions::default())
        .map_err(|e| format!("decoder: {e}"))?;

    let mut prepared = false;

    loop {
        if shared.generation.load(Ordering::Relaxed) != generation {
            return Ok(());
        }
        let packet = match format.next_packet() {
            Ok(Some(packet)) => packet,
            Ok(None) => break,
            Err(Error::IoError(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {
                break;
            }
            Err(Error::ResetRequired) => break,
            Err(error) => return Err(format!("read: {error}")),
        };
        if packet.track_id != track_id {
            continue;
        }
        match decoder.decode(&packet) {
            Ok(buffer) => {
                let buffer_rate = buffer.spec().rate();
                let buffer_channels = buffer.spec().channels().count();
                if !prepared {
                    let _ = prepare_tx.send(Ok((buffer_rate, buffer_channels, duration)));
                    prepared = true;
                }
                if buffer_channels == 0 {
                    continue;
                }
                let mut raw = vec![0.0f32; buffer.samples_interleaved()];
                buffer.copy_to_slice_interleaved(&mut raw);
                let samples = stereo_samples(&raw, buffer_channels);
                if sample_tx
                    .send(EngineEvent::Samples {
                        slot,
                        generation,
                        samples,
                    })
                    .is_err()
                {
                    return Ok(());
                }
            }
            Err(Error::DecodeError(_)) => continue,
            Err(Error::IoError(error)) if error.kind() == std::io::ErrorKind::UnexpectedEof => {
                break;
            }
            Err(error) => return Err(format!("decode: {error}")),
        }
    }

    if !prepared {
        return Err("decoder produced no audio".to_string());
    }
    let _ = sample_tx.send(EngineEvent::Finished { slot, generation });
    Ok(())
}

fn scan_duration(path: &str) -> Option<i64> {
    let file = File::open(Path::new(path)).ok()?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(extension) = Path::new(path).extension().and_then(|e| e.to_str()) {
        hint.with_extension(extension);
    }
    let mut format = symphonia::default::get_probe()
        .probe(
            &hint,
            mss,
            FormatOptions::default(),
            MetadataOptions::default(),
        )
        .ok()?;
    let track = format.default_track(TrackType::Audio)?;
    let track_id = track.id;
    let time_base = track.time_base?;
    let mut end = 0u64;
    while let Ok(Some(packet)) = format.next_packet() {
        if packet.track_id == track_id {
            let packet_end = packet
                .pts
                .get()
                .max(0)
                .saturating_add(packet.dur.get() as i64)
                .max(0) as u64;
            end = end.max(packet_end);
        }
    }
    if end == 0 {
        return None;
    }
    time_base
        .calc_duration(SymphoniaDuration::new(end))
        .map(|time| time.as_millis().max(0) as i64)
}

fn stereo_samples(raw: &[f32], channels: usize) -> Vec<f32> {
    let frames = raw.len() / channels.max(1);
    let mut out = Vec::with_capacity(frames * 2);
    match channels {
        1 => {
            for &sample in raw {
                out.push(sample);
                out.push(sample);
            }
        }
        2 => out.extend_from_slice(raw),
        _ => {
            for frame in raw.chunks_exact(channels) {
                out.push(frame[0]);
                out.push(frame[1]);
            }
        }
    }
    out
}
