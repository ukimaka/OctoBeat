# OctoBeat native audio engine

Rust playback backend for the Qt application. No libVLC.

- **Decode:** Symphonia 0.6 with `symphonia-opus` (Ogg/WebM Opus).
  FLAC (including 24-bit/192 kHz), MP3, AAC/M4A, AAC/ADTS, Ogg/Vorbis,
  WAV, ALAC, AIFF and CAF are enabled.
- **Output:** cpal/ALSA. The stream is opened at the source sample rate
  when the device supports it; 192 kHz output was verified through PipeWire.
- **Threading:** one engine thread owns cpal and the ring buffers, one
  decoder thread per active/standby slot. The real-time callback only mixes
  two lock-free slots. UI calls use the C ABI from `src/audio/audio_engine.h`.
- **Transport:** play, pause/resume, stop, seek, volume, duration hint,
  two-slot crossfade with per-slot volumes and end detection.
- **Streaming:** the ffmpeg ADTS FIFO is decoded directly by Symphonia.

## Smoke test

```sh
cargo run --release --bin audio-smoke -- /path/track.flac 3
```

The binary prints position/duration/playing and seeks to 60 s.

## Notes

- Only F32 output configurations are used for now. On Linux, ALSA/PipeWire
  exposes F32 at 44.1–384 kHz. If the exact rate is unavailable, a simple
  linear resampler is used; a high-quality resampler should be added before
  shipping on Windows shared mode.
- The engine intentionally has no video, HLS demuxer or network code.
  ffmpeg owns the YouTube HLS transport and writes ADTS into a FIFO.
