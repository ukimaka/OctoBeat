//! Pure-Rust Opus Interactive Audio Codec decoder (`symphonia-opus`).
//!
//! This crate implements a 100% safe Rust (`#![forbid(unsafe_code)]`, zero C dependencies, zero
//! per-packet heap allocations) decoder for the Opus audio codec as standardized in:
//!
//! - [RFC 6716](<https://datatracker.ietf.org/doc/html/rfc6716>): Definition of the Opus Audio
//!   Codec (range coder, SILK LP layer, CELT MDCT layer, Hybrid mode, packet framing, and PLC).
//! - [RFC 7845](<https://datatracker.ietf.org/doc/html/rfc7845>): Ogg Encapsulation for the Opus
//!   Audio Codec (`OpusHead` identification header, pre-skip, Q7.8 output gain, and Vorbis
//!   multi-stream surround mapping).
//! - [RFC 8251](<https://datatracker.ietf.org/doc/html/rfc8251>): Updates to the Opus Audio Codec
//!   (normative stereo/mono downmix, SILK/CELT errata fixes, and updated conformance vectors).
//!
//! It integrates directly into the [Symphonia](<https://github.com/pdeljanov/Symphonia>) (`0.6`)
//! multimedia framework via [`OpusDecoder`].
//!
//! # Quick Start: Registering with Symphonia
//!
//! Register [`OpusDecoder`] on a [`CodecRegistry`](symphonia_core::codecs::registry::CodecRegistry).
//! Registering at [`Tier::Fallback`](symphonia_core::common::Tier::Fallback) allows a future
//! first-party Symphonia Opus release to supersede this crate automatically without code changes:
//!
//! ```rust
//! use symphonia_core::audio::Audio;
//! use symphonia_core::codecs::audio::AudioDecoderOptions;
//! use symphonia_core::codecs::audio::well_known::CODEC_ID_OPUS;
//! use symphonia_core::codecs::registry::CodecRegistry;
//! use symphonia_core::common::Tier;
//! use symphonia_core::codecs::audio::AudioCodecParameters;
//! use symphonia_core::packet::PacketRef;
//! use symphonia_core::units::{Duration, Timestamp};
//! use symphonia_opus::OpusDecoder;
//!
//! // 1. Register OpusDecoder in Symphonia's CodecRegistry:
//! let mut registry = CodecRegistry::new();
//! registry.register_audio_decoder_at_tier::<OpusDecoder>(Tier::Fallback);
//!
//! // 2. Build AudioCodecParameters with a 19-byte RFC 7845 stereo OpusHead:
//! let opus_head: [u8; 19] = [
//!     b'O', b'p', b'u', b's', b'H', b'e', b'a', b'd', // Magic signature
//!     1,                                              // Version 1
//!     2,                                              // 2 channels (stereo)
//!     0x38, 0x01,                                     // Pre-skip = 312 samples (LE)
//!     0x80, 0xBB, 0x00, 0x00,                         // Input rate = 48000 Hz (LE)
//!     0x00, 0x00,                                     // Output gain = 0.0 dB (Q7.8 LE)
//!     0,                                              // Mapping family 0 (RTP stereo)
//! ];
//! let mut params = AudioCodecParameters::new();
//! params.for_codec(CODEC_ID_OPUS).with_extra_data(Box::new(opus_head));
//!
//! // 3. Instantiate via CodecRegistry and decode a 20 ms Fullband stereo CELT frame:
//! let mut decoder = registry
//!     .make_audio_decoder(&params, &AudioDecoderOptions::default())
//!     .unwrap();
//! let packet_bytes = [0xFC, 0xFF, 0xFE]; // TOC = CELT FB stereo 20 ms, payload = silence
//! let packet = PacketRef::new(0, Timestamp::from(0u32), Duration::from(960u64), &packet_bytes);
//! let decoded = decoder.decode_ref(&packet).unwrap();
//! assert_eq!(decoded.frames(), 960);
//! ```
//!
//! # End-to-End File Demuxing & Decoding (`symphonia 0.6`)
//!
//! When demuxing `.opus`, `.ogg`, or `.webm`/`.mkv` containers with `symphonia`, register default
//! codecs alongside [`OpusDecoder`] and feed demuxed packets to the instantiated decoder:
//!
//! ```rust,no_run
//! use std::fs::File;
//! use symphonia::core::codecs::audio::AudioDecoderOptions;
//! use symphonia::core::codecs::registry::CodecRegistry;
//! use symphonia::core::common::Tier;
//! use symphonia::core::errors::Error;
//! use symphonia::core::formats::probe::Hint;
//! use symphonia::core::formats::{FormatOptions, TrackType};
//! use symphonia::core::io::MediaSourceStream;
//! use symphonia::core::meta::MetadataOptions;
//! use symphonia_opus::OpusDecoder;
//!
//! fn decode_file(path: &str) -> symphonia::core::errors::Result<()> {
//!     let mut codecs = CodecRegistry::new();
//!     symphonia::default::register_enabled_codecs(&mut codecs);
//!     codecs.register_audio_decoder_at_tier::<OpusDecoder>(Tier::Fallback);
//!
//!     let file = File::open(path)?;
//!     let mss = MediaSourceStream::new(Box::new(file), Default::default());
//!     let mut format = symphonia::default::get_probe().probe(
//!         &Hint::new(),
//!         mss,
//!         FormatOptions::default(),
//!         MetadataOptions::default(),
//!     )?;
//!
//!     let track = format
//!         .default_track(TrackType::Audio)
//!         .ok_or(Error::Unsupported("no audio track found"))?;
//!     let track_id = track.id;
//!     let codec_params = track
//!         .codec_params
//!         .as_ref()
//!         .and_then(|p| p.audio())
//!         .ok_or(Error::Unsupported("track does not carry audio codec parameters"))?
//!         .clone();
//!
//!     let mut decoder = codecs.make_audio_decoder(&codec_params, &AudioDecoderOptions::default())?;
//!
//!     while let Some(packet) = format.next_packet()? {
//!         if packet.track_id != track_id {
//!             continue;
//!         }
//!         let _audio_buf = decoder.decode(&packet)?;
//!     }
//!     Ok(())
//! }
//! ```
//!
//! # Codec Capabilities & Container Support
//!
//! | Mode | TOC Configs | Bandwidths | Frame Durations | Active Layers |
//! | :--- | :--- | :--- | :--- | :--- |
//! | **SILK-only** | `0..=11` | NB (8 kHz), MB (12 kHz), WB (16 kHz) | 10, 20, 40, 60 ms | [`silk`] (`0..8 kHz` fixed-point LPC/LTP) |
//! | **Hybrid** | `12..=15` | SWB (24 kHz), FB (48 kHz) | 10, 20 ms | [`silk`] (`0..8 kHz`) + [`celt`] (bands `17..21`) |
//! | **CELT-only** | `16..=31` | NB (8 kHz), WB (16 kHz), SWB (24 kHz), FB (48 kHz) | 2.5, 5, 10, 20 ms | [`celt`] (MDCT + PVQ bands `0..end_band`) |
//!
//! - **Output Sample Rates**: `48_000` Hz default, plus native decimation/resampling to `24_000`,
//!   `16_000`, `12_000`, and `8_000` Hz ([RFC 6716 Section 2](<https://datatracker.ietf.org/doc/html/rfc6716#section-2>)).
//! - **Channel Layouts**: Mapping Family `0` (mono / stereo RTP) and Mapping Family `1` (`1..=8`
//!   channel Vorbis surround with coupled 2-channel and uncoupled 1-channel elementary streams,
//!   [RFC 7845 Section 5.1.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1.1>)).
//! - **Error Resilience**: In-band SILK LBRR, DTX comfort noise generation, per-layer packet loss
//!   concealment ([`OpusDecoder::decode_lost_packet`]), and 5 ms redundant CELT mode transitions
//!   ([RFC 6716 Section 4.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.5>)).
//! - **Containers (`symphonia 0.6.1`)**: Full out-of-the-box support for **Ogg Opus** (`ogg`) and
//!   **Matroska / WebM** (`mkv`). Note that `symphonia-format-isomp4 0.6.1` has a known upstream
//!   endianness issue on `dOps` `PreSkip` and `OutputGain` fields (fixed in
//!   [pdeljanov/Symphonia#398](<https://github.com/pdeljanov/Symphonia/pull/398>)).
//!
//! # Accuracy & RFC Conformance
//!
//! Passes all **120 official IETF conformance runs** (`12` [RFC 8251](<https://datatracker.ietf.org/doc/html/rfc8251>)
//! test vectors across `8, 12, 16, 24, and 48 kHz` in `mono` and `stereo`) calibrated against the
//! patched RFC 6716 Appendix A C reference decoder (`opus_demo -d`):
//!
//! - **Range Coder (`100%` exact)**: Every checked packet across all 120 runs matches the
//!   reference encoder's 32-bit [`OpusDecoder::final_range`] state (`0` mismatches).
//! - **SILK Speech Layer (`100.00%` bit-exact, `0` LSB)**: Integer fixed-point synthesis matches
//!   `opus_demo -d` bit-for-bit on every 16-bit PCM sample (`testvector02..04`).
//! - **CELT & Hybrid Layers (`99.41%..100.00%` identical, `<= 1` LSB)**: Over `99.4%` of stereo
//!   16-bit PCM samples match `opus_demo -d` to `0` LSB; the remaining `< 0.6%` sit on `.5`
//!   half-integer rounding boundaries within `1` LSB (`-90.3 dBFS`).
//! - **Psychoacoustic Quality (`99.8..100.0 / 100`)**: Scores `99.8` to `100.0` at 48 kHz stereo
//!   on the official `opus_compare` metric (where `0` passes and `> 90` is recommended).
//!
//! # Architecture ([RFC 6716 Section 4](<https://datatracker.ietf.org/doc/html/rfc6716#section-4>))
//!
//! ```text
//!                             +---------+    +------------+
//!                             |  SILK   |    |   Sample   |
//!                          +->| Decoder |--->|    Rate    |----+
//!    Bit-    +---------+   |  |         |    | Conversion |    v
//!    stream  |  Range  |---+  +---------+    +------------+  /---\  Audio
//!    ------->| Decoder |                                     | + |------>
//!            |         |---+  +---------+    +------------+  \---/
//!            +---------+   |  |  CELT   |    | Decimation |    ^
//!                          +->| Decoder |--->| (Optional) |----+
//!                             |         |    |            |
//!                             +---------+    +------------+
//! ```
//!
//! Internal modules (rendered on `docs.rs` for architectural reference; only [`OpusDecoder`] is
//! part of the public SemVer API):
//!
//! - [`toc`]: Table of Contents (TOC) byte parser ([RFC 6716 Section 3.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-3.1>)).
//! - [`packet`]: Opus packet framing for Codes `0..=3`, VBR/CBR, padding, and self-delimited
//!   multi-stream packets ([RFC 6716 Section 3.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-3.2>),
//!   [Appendix B](<https://datatracker.ietf.org/doc/html/rfc6716#appendix-B>)).
//! - [`header`]: Ogg Opus `OpusHead` identification header and channel mapping tables
//!   ([RFC 7845 Section 5](<https://datatracker.ietf.org/doc/html/rfc7845#section-5>)).
//! - [`entropy`]: Forward range decoder and backward raw-bit reader
//!   ([RFC 6716 Section 4.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.1>)).
//! - [`silk`]: SILK linear-predictive low-bitrate speech layer
//!   ([RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>)).
//! - [`celt`]: CELT full-bandwidth MDCT transform audio layer
//!   ([RFC 6716 Section 4.3](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3>)).
//! - [`stream`]: Single elementary-stream sequencer, Hybrid synthesis, 5 ms redundant CELT mode
//!   transitions, and packet loss concealment ([RFC 6716 Sections 4.4 - 4.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.4>)).
//! - [`routing`]: Multi-stream packet demultiplexing and Vorbis / RTP channel matrixing
//!   ([RFC 7845 Section 5.1.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1.1>)).
//! - [`decoder`]: Top-level [`OpusDecoder`] implementing Symphonia's `AudioDecoder` trait.
//! - [`fixed`], [`sample_rate`], [`planes`], [`layout`]: Q-format fixed-point primitives, output
//!   rate geometry, and planar `f32` channel buffers.
//!
//! # Logging
//!
//! The decoder logs through the `log` crate at two points only: `warn` when a declared sample rate
//! outside `{8, 12, 16, 24, 48} kHz` falls back to 48 kHz, and `debug` when concealing a lost
//! packet. Normal per-frame decoding never logs.

#![forbid(unsafe_code)]
#![deny(missing_docs)]
#![allow(clippy::needless_return)]
#![allow(rustdoc::private_intra_doc_links)]
#![cfg_attr(not(test), deny(clippy::unwrap_used))]

mod celt;
mod convert;
mod decoder;
mod entropy;
mod fixed;
mod header;
mod layout;
mod packet;
mod planes;
mod routing;
mod sample_rate;
mod silk;
mod slices;
mod stream;
#[cfg(test)]
mod test_vectors;
mod toc;

pub use decoder::OpusDecoder;
