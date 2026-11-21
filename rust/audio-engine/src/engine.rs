use anyhow::{anyhow, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use rtrb::{Consumer, Producer, RingBuffer};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU32, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, Sender, SyncSender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crate::decoder;

const RING_CAPACITY: usize = 1 << 20;
const OUTPUT_CHANNELS: usize = 2;
const SAMPLE_CHANNEL_CAPACITY: usize = 128;

fn load_f32(value: &AtomicU32) -> f32 {
    f32::from_bits(value.load(Ordering::Relaxed))
}

fn store_f32(value: &AtomicU32, sample: f32) {
    value.store(sample.to_bits(), Ordering::Relaxed);
}

#[derive(Default)]
pub struct SharedSlot {
    pub volume: AtomicU32,
    pub base_ms: AtomicI64,
    pub played_frames: AtomicU64,
    pub rate: AtomicU32,
    pub duration_ms: AtomicI64,
    pub finished: AtomicBool,
    pub ended: AtomicBool,
    pub generation: AtomicU64,
}

impl SharedSlot {
    pub fn new() -> Self {
        Self {
            volume: AtomicU32::new(1.0f32.to_bits()),
            ..Self::default()
        }
    }

    pub fn reset(&self) {
        self.base_ms.store(0, Ordering::Relaxed);
        self.played_frames.store(0, Ordering::Relaxed);
        self.rate.store(0, Ordering::Relaxed);
        self.duration_ms.store(0, Ordering::Relaxed);
        self.finished.store(false, Ordering::Relaxed);
        self.ended.store(false, Ordering::Relaxed);
        store_f32(&self.volume, 1.0);
    }
}

pub struct Shared {
    pub slots: [Arc<SharedSlot>; 2],
    pub active: AtomicUsize,
    pub playing: AtomicBool,
    pub paused: AtomicBool,
    pub master_volume: AtomicU32,
    pub duration_hint_ms: AtomicI64,
    pub underruns: AtomicU64,
    pub shutdown: AtomicBool,
    pub cancel_request: AtomicU64,
    pub error: Mutex<Option<String>>,
}

impl Shared {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            slots: [Arc::new(SharedSlot::new()), Arc::new(SharedSlot::new())],
            active: AtomicUsize::new(0),
            playing: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            master_volume: AtomicU32::new(0.7f32.to_bits()),
            duration_hint_ms: AtomicI64::new(0),
            underruns: AtomicU64::new(0),
            shutdown: AtomicBool::new(false),
            cancel_request: AtomicU64::new(0),
            error: Mutex::new(None),
        })
    }

    pub fn set_error(&self, message: impl Into<String>) {
        let message = message.into();
        eprintln!("[octobeat-audio] {message}");
        if let Ok(mut error) = self.error.lock() {
            if error.is_none() {
                *error = Some(message);
            }
        }
    }

    fn take_error(&self) -> Option<String> {
        self.error.lock().ok().and_then(|mut error| error.take())
    }
}

pub enum EngineEvent {
    Samples {
        slot: usize,
        generation: u64,
        samples: Vec<f32>,
    },
    Finished {
        slot: usize,
        generation: u64,
    },
    Error {
        slot: usize,
        generation: u64,
        message: String,
    },
}

pub enum Command {
    Play {
        path: String,
        start_ms: i64,
    },
    Crossfade {
        path: String,
        reply: Sender<Result<(), String>>,
    },
    FinishCrossfade,
    CancelCrossfade,
    Stop,
    Seek {
        position_ms: i64,
    },
    Shutdown,
}

pub struct AudioEngine {
    shared: Arc<Shared>,
    tx: Sender<Command>,
    thread: Mutex<Option<thread::JoinHandle<()>>>,
}

impl AudioEngine {
    pub fn new() -> Result<Self> {
        let shared = Shared::new();
        let (tx, rx) = std::sync::mpsc::channel();
        let thread_shared = shared.clone();
        let handle = thread::Builder::new()
            .name(String::from("octobeat-audio-engine"))
            .spawn(move || engine_thread(thread_shared, rx))
            .context("spawn audio engine thread")?;
        Ok(Self {
            shared,
            tx,
            thread: Mutex::new(Some(handle)),
        })
    }

    pub fn play(&self, path: String, start_ms: i64) -> bool {
        self.tx.send(Command::Play { path, start_ms }).is_ok()
    }

    pub fn crossfade(&self, path: String) -> Result<(), String> {
        let (reply_tx, reply_rx) = std::sync::mpsc::channel();
        if self
            .tx
            .send(Command::Crossfade {
                path,
                reply: reply_tx,
            })
            .is_err()
        {
            return Err("Audio engine is not running.".to_string());
        }
        match reply_rx.recv_timeout(Duration::from_secs(3)) {
            Ok(result) => result,
            Err(_) => {
                let _ = self.tx.send(Command::CancelCrossfade);
                Err("The next track did not become ready in time.".to_string())
            }
        }
    }

    pub fn finish_crossfade(&self) {
        let _ = self.tx.send(Command::FinishCrossfade);
    }

    pub fn cancel_crossfade(&self) {
        let _ = self.tx.send(Command::CancelCrossfade);
    }

    pub fn stop(&self) {
        self.shared.cancel_request.fetch_add(1, Ordering::Relaxed);
        let _ = self.tx.send(Command::Stop);
    }

    pub fn pause(&self) {
        self.shared.paused.store(true, Ordering::Relaxed);
    }

    pub fn resume(&self) {
        self.shared.paused.store(false, Ordering::Relaxed);
    }

    pub fn seek(&self, position_ms: i64) {
        let _ = self.tx.send(Command::Seek { position_ms });
    }

    pub fn set_volume(&self, volume: f32) {
        store_f32(&self.shared.master_volume, volume.clamp(0.0, 1.0));
    }

    pub fn set_slot_volume(&self, slot: usize, volume: f32) {
        if slot < 2 {
            store_f32(&self.shared.slots[slot].volume, volume.clamp(0.0, 1.0));
        }
    }

    pub fn position(&self) -> i64 {
        let slot = &self.shared.slots[self.shared.active.load(Ordering::Relaxed)];
        let rate = slot.rate.load(Ordering::Relaxed) as u64;
        let frames = slot.played_frames.load(Ordering::Relaxed);
        if rate == 0 {
            return slot.base_ms.load(Ordering::Relaxed);
        }
        slot.base_ms.load(Ordering::Relaxed) + ((frames * 1000) / rate) as i64
    }

    pub fn duration(&self) -> i64 {
        let slot = &self.shared.slots[self.shared.active.load(Ordering::Relaxed)];
        let duration = slot.duration_ms.load(Ordering::Relaxed);
        if duration > 0 {
            duration
        } else {
            self.shared.duration_hint_ms.load(Ordering::Relaxed)
        }
    }

    pub fn is_playing(&self) -> bool {
        let slot = &self.shared.slots[self.shared.active.load(Ordering::Relaxed)];
        self.shared.playing.load(Ordering::Relaxed)
            && !self.shared.paused.load(Ordering::Relaxed)
            && !slot.ended.load(Ordering::Relaxed)
    }

    pub fn active_slot(&self) -> usize {
        self.shared.active.load(Ordering::Relaxed)
    }

    pub fn duration_hint(&self) -> i64 {
        self.shared.duration_hint_ms.load(Ordering::Relaxed)
    }

    pub fn set_duration_hint(&self, duration_ms: i64) {
        self.shared
            .duration_hint_ms
            .store(duration_ms.max(0), Ordering::Relaxed);
    }

    pub fn take_error(&self) -> Option<String> {
        self.shared.take_error()
    }

    pub fn set_error(&self, message: impl Into<String>) {
        self.shared.set_error(message);
    }

    pub fn has_ended(&self) -> bool {
        let slot = &self.shared.slots[self.shared.active.load(Ordering::Relaxed)];
        slot.ended.load(Ordering::Relaxed)
    }

    pub fn underruns(&self) -> u64 {
        self.shared.underruns.load(Ordering::Relaxed)
    }
}

impl Drop for AudioEngine {
    fn drop(&mut self) {
        self.shared.shutdown.store(true, Ordering::Relaxed);
        let _ = self.tx.send(Command::Shutdown);
        if let Ok(mut guard) = self.thread.lock() {
            if let Some(handle) = guard.take() {
                let _ = handle.join();
            }
        }
    }
}

#[derive(Default)]
struct SlotQueue {
    chunks: VecDeque<Vec<f32>>,
    offset: usize,
}

impl SlotQueue {
    fn new() -> Self {
        Self {
            chunks: VecDeque::new(),
            offset: 0,
        }
    }

    fn clear(&mut self) {
        self.chunks.clear();
        self.offset = 0;
    }

    fn push_chunk(&mut self, samples: Vec<f32>) {
        if !samples.is_empty() {
            self.chunks.push_back(samples);
        }
    }

    fn write_to(&mut self, producer: &mut Producer<f32>) {
        while let Some(front) = self.chunks.front() {
            let remaining = &front[self.offset..];
            if remaining.is_empty() {
                self.chunks.pop_front();
                self.offset = 0;
                continue;
            }
            let (pushed, rest) = producer.push_partial_slice(remaining);
            self.offset += pushed.len();
            if !rest.is_empty() {
                break;
            }
            self.chunks.pop_front();
            self.offset = 0;
        }
    }
}

struct Resampler {
    source_rate: u32,
    target_rate: u32,
    phase: f64,
    last: [f32; 2],
    primed: bool,
    output: Vec<f32>,
}

impl Resampler {
    fn new(source_rate: u32, target_rate: u32) -> Self {
        Self {
            source_rate,
            target_rate,
            phase: 1.0,
            last: [0.0; 2],
            primed: false,
            output: Vec::new(),
        }
    }

    fn reset(&mut self) {
        self.phase = 1.0;
        self.last = [0.0; 2];
        self.primed = false;
        self.output.clear();
    }

    fn process(&mut self, input: &[f32]) -> Vec<f32> {
        if self.source_rate == 0 || self.target_rate == 0 {
            return input.to_vec();
        }
        if self.source_rate == self.target_rate {
            return input.to_vec();
        }
        let step = self.source_rate as f64 / self.target_rate as f64;
        let mut out = std::mem::take(&mut self.output);
        out.clear();
        for frame in input.as_chunks::<2>().0 {
            let current = [frame[0], frame[1]];
            if !self.primed {
                self.last = current;
                self.primed = true;
                self.phase = 1.0;
                out.extend_from_slice(&current);
                self.phase -= 1.0;
                self.phase += step;
                while self.phase < 1.0 {
                    out.extend_from_slice(&current);
                    self.phase += step;
                }
                self.phase -= 1.0;
                continue;
            }
            while self.phase < 1.0 {
                let p = self.phase as f32;
                out.push(self.last[0] * (1.0 - p) + current[0] * p);
                out.push(self.last[1] * (1.0 - p) + current[1] * p);
                self.phase += step;
            }
            self.phase -= 1.0;
            self.last = current;
        }
        self.output = out;
        self.output.clone()
    }
}

struct EngineThread {
    shared: Arc<Shared>,
    producers: [Producer<f32>; 2],
    consumers: [Arc<Mutex<Option<Consumer<f32>>>>; 2],
    queues: [SlotQueue; 2],
    resamplers: [Option<Resampler>; 2],
    output: Option<cpal::Stream>,
    output_rate: u32,
    decoders_generation: [u64; 2],
    paths: [Option<String>; 2],
    pending_finished: [bool; 2],
}

impl EngineThread {
    fn new(shared: Arc<Shared>) -> Self {
        let (p0, c0) = RingBuffer::new(RING_CAPACITY);
        let (p1, c1) = RingBuffer::new(RING_CAPACITY);
        Self {
            shared,
            producers: [p0, p1],
            consumers: [
                Arc::new(Mutex::new(Some(c0))),
                Arc::new(Mutex::new(Some(c1))),
            ],
            queues: [SlotQueue::new(), SlotQueue::new()],
            resamplers: [None, None],
            output: None,
            output_rate: 0,
            decoders_generation: [0, 0],
            paths: [None, None],
            pending_finished: [false, false],
        }
    }

    fn stop_output(&mut self) {
        self.shared.playing.store(false, Ordering::Relaxed);
        self.shared.paused.store(false, Ordering::Relaxed);
        self.output = None;
    }

    fn drain_consumers(&mut self) {
        for slot in 0..2 {
            if let Ok(mut guard) = self.consumers[slot].lock() {
                if let Some(consumer) = guard.as_mut() {
                    while consumer.pop().is_ok() {}
                }
            }
            self.queues[slot].clear();
        }
    }

    fn stop_decoders(&mut self) {
        for slot in 0..2 {
            self.shared.slots[slot]
                .generation
                .fetch_add(1, Ordering::Relaxed);
            self.shared.slots[slot]
                .finished
                .store(true, Ordering::Relaxed);
        }
    }

    fn reset_slot(&mut self, slot: usize) {
        self.shared.slots[slot].reset();
        self.queues[slot].clear();
        self.resamplers[slot] = None;
        self.pending_finished[slot] = false;
    }

    fn spawn_decoder(
        &mut self,
        slot: usize,
        path: String,
        start_ms: i64,
        sample_tx: SyncSender<EngineEvent>,
        wait: bool,
    ) -> Result<(u32, usize, i64), String> {
        let shared_slot = self.shared.slots[slot].clone();
        let generation = shared_slot.generation.load(Ordering::Relaxed);
        let cancel_snapshot = self.shared.cancel_request.load(Ordering::Relaxed);
        let (prepare_tx, prepare_rx) = std::sync::mpsc::channel();
        decoder::spawn(
            slot,
            generation,
            path,
            start_ms,
            shared_slot,
            sample_tx,
            prepare_tx,
        );
        self.decoders_generation[slot] = generation;
        if !wait {
            return Ok((0, 0, 0));
        }

        let deadline = Instant::now() + Duration::from_secs(8);
        loop {
            if self.shared.shutdown.load(Ordering::Relaxed) {
                return Err("Audio engine is shutting down.".to_string());
            }
            if self.shared.cancel_request.load(Ordering::Relaxed) != cancel_snapshot {
                self.shared.slots[slot]
                    .generation
                    .fetch_add(1, Ordering::Relaxed);
                return Err("cancelled".to_string());
            }
            match prepare_rx.recv_timeout(Duration::from_millis(100)) {
                Ok(Ok((rate, channels, duration_ms))) => {
                    return Ok((rate, channels, duration_ms));
                }
                Ok(Err(message)) => return Err(message),
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                    if Instant::now() >= deadline {
                        return Err("The track did not become ready in time.".to_string());
                    }
                }
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                    return Err("The decoder stopped before the track was ready.".to_string());
                }
            }
        }
    }

    fn choose_output(
        &self,
        requested_rate: u32,
    ) -> Result<(cpal::SupportedStreamConfig, u32, bool)> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or_else(|| anyhow!("no audio output device"))?;
        let mut fallback: Option<cpal::SupportedStreamConfig> = None;
        if let Ok(configs) = device.supported_output_configs() {
            for config in configs {
                if config.channels() as usize != OUTPUT_CHANNELS {
                    continue;
                }
                if config.min_sample_rate().0 <= requested_rate
                    && config.max_sample_rate().0 >= requested_rate
                {
                    let supported = config.with_sample_rate(cpal::SampleRate(requested_rate));
                    if supported.sample_format() == cpal::SampleFormat::F32 {
                        return Ok((supported, requested_rate, false));
                    }
                    if fallback.is_none() {
                        fallback = Some(supported);
                    }
                }
            }
        }
        if let Some(config) = fallback {
            return Ok((config, requested_rate, false));
        }
        let default = device
            .default_output_config()
            .context("default output configuration")?;
        if default.channels() as usize != OUTPUT_CHANNELS {
            return Err(anyhow!(
                "output device does not expose a stereo configuration (got {} channels)",
                default.channels()
            ));
        }
        let rate = default.sample_rate().0;
        let resample = rate != requested_rate;
        Ok((default, rate, resample))
    }

    fn build_output(&mut self, requested_rate: u32) -> Result<(u32, bool)> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or_else(|| anyhow!("no audio output device"))?;
        let (supported, output_rate, resample) = self.choose_output(requested_rate)?;
        let sample_format = supported.sample_format();
        let config = supported.config();
        let shared = self.shared.clone();
        let consumers = [self.consumers[0].clone(), self.consumers[1].clone()];
        let error_shared = self.shared.clone();
        let error_callback = move |error| {
            error_shared.playing.store(false, Ordering::Relaxed);
            error_shared.set_error(format!("audio output error: {error}"));
        };
        let stream = match sample_format {
            cpal::SampleFormat::F32 => device
                .build_output_stream(
                    &config,
                    move |data: &mut [f32], _| {
                        render_f32(data, &consumers, &shared, config.channels as usize)
                    },
                    error_callback,
                    None,
                )
                .context("build F32 output stream")?,
            cpal::SampleFormat::I16 => {
                let mut scratch: Vec<f32> = Vec::new();
                let consumers = consumers.clone();
                let shared = shared.clone();
                device
                    .build_output_stream(
                        &config,
                        move |data: &mut [i16], _| {
                            if scratch.len() < data.len() {
                                scratch.resize(data.len(), 0.0);
                            }
                            let mix = &mut scratch[..data.len()];
                            render_f32(mix, &consumers, &shared, config.channels as usize);
                            for (out, sample) in data.iter_mut().zip(mix.iter()) {
                                *out = (sample.clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
                            }
                        },
                        error_callback,
                        None,
                    )
                    .context("build I16 output stream")?
            }
            cpal::SampleFormat::I32 => {
                let mut scratch: Vec<f32> = Vec::new();
                let consumers = consumers.clone();
                let shared = shared.clone();
                device
                    .build_output_stream(
                        &config,
                        move |data: &mut [i32], _| {
                            if scratch.len() < data.len() {
                                scratch.resize(data.len(), 0.0);
                            }
                            let mix = &mut scratch[..data.len()];
                            render_f32(mix, &consumers, &shared, config.channels as usize);
                            for (out, sample) in data.iter_mut().zip(mix.iter()) {
                                *out = (sample.clamp(-1.0, 1.0) * i32::MAX as f32) as i32;
                            }
                        },
                        error_callback,
                        None,
                    )
                    .context("build I32 output stream")?
            }
            other => {
                return Err(anyhow!(
                    "unsupported output sample format {other:?}; expected F32, I16 or I32"
                ));
            }
        };
        stream.play().context("start output stream")?;
        self.output = Some(stream);
        self.output_rate = output_rate;
        self.shared.playing.store(true, Ordering::Relaxed);
        if std::env::var_os("OCTOBEAT_TRACE_AUDIO").is_some() {
            eprintln!(
                "[octobeat-audio] output: source={requested_rate} Hz, engine={output_rate} Hz, resample={resample}, format={sample_format:?}"
            );
        }
        Ok((output_rate, resample))
    }

    fn pump(&mut self, sample_rx: &Receiver<EngineEvent>) {
        loop {
            match sample_rx.try_recv() {
                Ok(EngineEvent::Samples {
                    slot,
                    generation,
                    samples,
                }) => {
                    if generation == self.shared.slots[slot].generation.load(Ordering::Relaxed) {
                        let samples = match self.resamplers[slot].as_mut() {
                            Some(resampler) => resampler.process(&samples),
                            None => samples,
                        };
                        self.queues[slot].push_chunk(samples);
                    }
                }
                Ok(EngineEvent::Finished { slot, generation }) => {
                    if generation == self.shared.slots[slot].generation.load(Ordering::Relaxed) {
                        self.pending_finished[slot] = true;
                    }
                }
                Ok(EngineEvent::Error {
                    slot,
                    generation,
                    message,
                }) => {
                    if generation == self.shared.slots[slot].generation.load(Ordering::Relaxed) {
                        self.pending_finished[slot] = true;
                        self.shared.set_error(message);
                    }
                }
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => break,
            }
        }

        for slot in 0..2 {
            if !self.queues[slot].chunks.is_empty() {
                let mut chunks = std::mem::take(&mut self.queues[slot]);
                chunks.write_to(&mut self.producers[slot]);
                self.queues[slot] = chunks;
            }
            // Only publish "finished" after every decoded sample has reached
            // the ring buffer. Otherwise the audio callback could mark the
            // track ended while the engine thread still holds its last chunk.
            if self.pending_finished[slot] && self.queues[slot].chunks.is_empty() {
                self.shared.slots[slot]
                    .finished
                    .store(true, Ordering::Relaxed);
                self.pending_finished[slot] = false;
            }
        }
    }

    fn prepare_slot(
        &mut self,
        slot: usize,
        path: String,
        start_ms: i64,
        sample_tx: SyncSender<EngineEvent>,
    ) -> Result<(u32, usize, i64), String> {
        self.reset_slot(slot);
        self.shared.slots[slot]
            .base_ms
            .store(start_ms, Ordering::Relaxed);
        self.shared.slots[slot]
            .generation
            .fetch_add(1, Ordering::Relaxed);
        self.paths[slot] = Some(path.clone());
        self.spawn_decoder(slot, path, start_ms, sample_tx, true)
    }

    fn configure_resampler(&mut self, slot: usize, source_rate: u32, output_rate: u32) {
        self.shared.slots[slot]
            .rate
            .store(output_rate, Ordering::Relaxed);
        self.resamplers[slot] = if source_rate != output_rate {
            Some(Resampler::new(source_rate, output_rate))
        } else {
            None
        };
    }

    fn active_slot(&self) -> usize {
        self.shared.active.load(Ordering::Relaxed)
    }
}

fn render_f32(
    data: &mut [f32],
    consumers: &[Arc<Mutex<Option<Consumer<f32>>>>; 2],
    shared: &Shared,
    channels: usize,
) {
    if shared.paused.load(Ordering::Relaxed) {
        data.fill(0.0);
        return;
    }
    let master = load_f32(&shared.master_volume);
    let volumes = [
        load_f32(&shared.slots[0].volume),
        load_f32(&shared.slots[1].volume),
    ];
    let mut guard0 = consumers[0].lock().ok();
    let mut guard1 = consumers[1].lock().ok();
    let mut played = [0u64; 2];

    for frame in data.chunks_mut(channels.max(1)) {
        let mut mixed = [0.0f32; 2];
        let mut got = [false; 2];
        for slot in 0..2 {
            let consumer = match slot {
                0 => guard0.as_mut().and_then(|guard| guard.as_mut()),
                _ => guard1.as_mut().and_then(|guard| guard.as_mut()),
            };
            if let Some(consumer) = consumer {
                if consumer.slots() >= 2 {
                    let left = consumer.pop().unwrap_or(0.0);
                    let right = consumer.pop().unwrap_or(0.0);
                    mixed[0] += left * volumes[slot];
                    mixed[1] += right * volumes[slot];
                    played[slot] += 1;
                    got[slot] = true;
                } else if shared.slots[slot].finished.load(Ordering::Relaxed) {
                    shared.slots[slot].ended.store(true, Ordering::Relaxed);
                }
            }
        }
        if !got[shared.active.load(Ordering::Relaxed)]
            && !shared.slots[shared.active.load(Ordering::Relaxed)]
                .finished
                .load(Ordering::Relaxed)
        {
            shared.underruns.fetch_add(1, Ordering::Relaxed);
        }
        for ch in 0..channels.max(1) {
            frame[ch] = mixed[ch.min(1)] * master;
        }
    }

    for (slot, &count) in played.iter().enumerate() {
        if count > 0 {
            shared.slots[slot]
                .played_frames
                .fetch_add(count, Ordering::Relaxed);
        }
    }
}

fn trace_audio() -> bool {
    std::env::var_os("OCTOBEAT_TRACE_AUDIO").is_some()
}

fn engine_thread(shared: Arc<Shared>, rx: Receiver<Command>) {
    let mut engine = EngineThread::new(shared.clone());
    let (sample_tx, sample_rx) = std::sync::mpsc::sync_channel(SAMPLE_CHANNEL_CAPACITY);

    loop {
        engine.pump(&sample_rx);
        if shared.shutdown.load(Ordering::Relaxed) {
            engine.stop_decoders();
            engine.stop_output();
            break;
        }
        match rx.recv_timeout(Duration::from_millis(2)) {
            Ok(Command::Play { path, start_ms }) => {
                if trace_audio() {
                    eprintln!("[octobeat-audio] play slot=0 start_ms={start_ms} path={path}");
                }
                engine.stop_decoders();
                engine.stop_output();
                engine.drain_consumers();
                engine.reset_slot(0);
                engine.reset_slot(1);
                shared.active.store(0, Ordering::Relaxed);
                shared.paused.store(false, Ordering::Relaxed);
                match engine.prepare_slot(0, path, start_ms, sample_tx.clone()) {
                    Ok((rate, _channels, duration_ms)) => {
                        shared.slots[0]
                            .duration_ms
                            .store(duration_ms, Ordering::Relaxed);
                        match engine.build_output(rate) {
                            Ok((output_rate, resample)) => {
                                engine.configure_resampler(0, rate, output_rate);
                                if resample {
                                    engine.resamplers[0] = Some(Resampler::new(rate, output_rate));
                                }
                            }
                            Err(error) => {
                                shared.set_error(format!("{error:#}"));
                                engine.stop_decoders();
                            }
                        }
                    }
                    Err(error) => {
                        if error != "cancelled" {
                            shared.set_error(error);
                        }
                    }
                }
            }
            Ok(Command::Crossfade { path, reply }) => {
                let active = engine.active_slot();
                let standby = 1 - active;
                if trace_audio() {
                    eprintln!("[octobeat-audio] crossfade active={active} standby={standby} path={path}");
                }
                if engine.output.is_none() {
                    let _ = reply.send(Err("No active playback.".to_string()));
                    continue;
                }
                engine.shared.slots[standby]
                    .generation
                    .fetch_add(1, Ordering::Relaxed);
                engine.reset_slot(standby);
                match engine.prepare_slot(standby, path, 0, sample_tx.clone()) {
                    Ok((rate, _channels, duration_ms)) => {
                        shared.slots[standby]
                            .duration_ms
                            .store(duration_ms, Ordering::Relaxed);
                        engine.configure_resampler(standby, rate, engine.output_rate);
                        if engine.resamplers[standby].is_none() {
                            // configure_resampler already handles the exact case.
                        }
                        store_f32(&shared.slots[standby].volume, 0.0);
                        let _ = reply.send(Ok(()));
                    }
                    Err(error) => {
                        shared.slots[standby]
                            .finished
                            .store(true, Ordering::Relaxed);
                        let _ = reply.send(Err(error));
                    }
                }
            }
            Ok(Command::FinishCrossfade) => {
                let active = engine.active_slot();
                let standby = 1 - active;
                if trace_audio() {
                    eprintln!("[octobeat-audio] finish crossfade active={active} -> {standby}");
                }
                shared.slots[active]
                    .generation
                    .fetch_add(1, Ordering::Relaxed);
                shared.slots[active].finished.store(true, Ordering::Relaxed);
                shared.slots[active].ended.store(true, Ordering::Relaxed);
                store_f32(&shared.slots[active].volume, 0.0);
                engine.queues[active].clear();
                shared.active.store(standby, Ordering::Relaxed);
                shared.slots[standby].ended.store(false, Ordering::Relaxed);
                store_f32(&shared.slots[standby].volume, 1.0);
            }
            Ok(Command::CancelCrossfade) => {
                let active = engine.active_slot();
                let standby = 1 - active;
                if trace_audio() {
                    eprintln!("[octobeat-audio] cancel crossfade active={active} standby={standby}");
                }
                shared.slots[standby]
                    .generation
                    .fetch_add(1, Ordering::Relaxed);
                shared.slots[standby]
                    .finished
                    .store(true, Ordering::Relaxed);
                engine.queues[standby].clear();
                store_f32(&shared.slots[standby].volume, 0.0);
            }
            Ok(Command::Stop) => {
                if trace_audio() {
                    eprintln!("[octobeat-audio] stop");
                }
                engine.stop_decoders();
                engine.stop_output();
                engine.drain_consumers();
                engine.reset_slot(0);
                engine.reset_slot(1);
                shared.active.store(0, Ordering::Relaxed);
                shared.duration_hint_ms.store(0, Ordering::Relaxed);
                shared.paused.store(false, Ordering::Relaxed);
            }
            Ok(Command::Seek { position_ms }) => {
                let active = engine.active_slot();
                if engine.output.is_none() {
                    continue;
                }
                if let Some(path) = engine.paths[active].clone() {
                    shared.slots[active]
                        .generation
                        .fetch_add(1, Ordering::Relaxed);
                    shared.slots[active]
                        .finished
                        .store(false, Ordering::Relaxed);
                    shared.slots[active].ended.store(false, Ordering::Relaxed);
                    if let Ok(mut guard) = engine.consumers[active].lock() {
                        if let Some(consumer) = guard.as_mut() {
                            while consumer.pop().is_ok() {}
                        }
                    }
                    engine.queues[active].clear();
                    engine.pending_finished[active] = false;
                    if let Some(resampler) = engine.resamplers[active].as_mut() {
                        resampler.reset();
                    }
                    shared.slots[active]
                        .base_ms
                        .store(position_ms.max(0), Ordering::Relaxed);
                    shared.slots[active]
                        .played_frames
                        .store(0, Ordering::Relaxed);
                    let _ = engine.spawn_decoder(
                        active,
                        path,
                        position_ms.max(0),
                        sample_tx.clone(),
                        false,
                    );
                }
            }
            Ok(Command::Shutdown) => {
                engine.stop_decoders();
                engine.stop_output();
                break;
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    shared.playing.store(false, Ordering::Relaxed);
}
