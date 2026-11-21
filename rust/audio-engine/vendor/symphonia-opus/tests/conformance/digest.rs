//! Bit-exact output digests: a 64-bit FNV-1a hash over the `f32` bit pattern of every decoded
//! sample, used to show that a change leaves the decoder output unchanged, down to the sign of
//! zero and below one 16-bit LSB.

use super::*;
use symphonia_core::codecs::audio::AudioDecoder;
use symphonia_core::packet::PacketRef;
use symphonia_core::units::{Duration, Timestamp};

/// FNV-1a 64-bit offset basis.
const FNV_OFFSET_BASIS: u64 = 0xcbf2_9ce4_8422_2325;

/// FNV-1a 64-bit prime.
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// Marker hashed in place of the samples of a packet whose decode failed.
const DECODE_ERROR_MARKER: u64 = 0xdead_beef_dead_beef;

/// Which packets a digest run replaces with an empty payload (a lost packet for `decode_ref`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Loss {
    /// Every packet is decoded as recorded.
    None,
    /// Packet `i` is lost when `i % period == offset`, in addition to the recorded losses.
    Periodic { period: usize, offset: usize },
}

impl Loss {
    /// Loss pattern of the second digest pass: every 7th packet, starting with packet 3.
    pub(crate) const EVERY_7TH: Self = Self::Periodic { period: 7, offset: 3 };

    fn drops(self, i: usize) -> bool {
        return match self {
            Self::None => false,
            Self::Periodic { period, offset } => i % period == offset,
        };
    }

    pub(crate) fn name(self) -> &'static str {
        return match self {
            Self::None => "clean",
            Self::Periodic { .. } => "loss-7",
        };
    }
}

/// Incremental FNV-1a 64-bit hasher over little-endian words.
struct Fnv1a(u64);

impl Fnv1a {
    fn new() -> Self {
        return Self(FNV_OFFSET_BASIS);
    }

    fn write(&mut self, bytes: &[u8]) {
        self.0 = bytes
            .iter()
            .fold(self.0, |hash, &byte| (hash ^ u64::from(byte)).wrapping_mul(FNV_PRIME));
        return;
    }

    fn write_u64(&mut self, word: u64) {
        self.write(&word.to_le_bytes());
        return;
    }
}

/// Digest of one `(vector, rate, layout, loss)` run: every output sample's `f32::to_bits`, the
/// per-packet sample count, and a marker for each failed packet.
pub(crate) fn output_digest(
    records: &[BitRecord<'_>],
    rate: u32,
    layout: Layout,
    loss: Loss,
) -> u64 {
    let mut decoder = new_decoder(rate, layout);
    let mut hasher = Fnv1a::new();
    let mut samples: Vec<f32> = Vec::new();
    for (i, record) in records.iter().enumerate() {
        let payload: &[u8] = match loss.drops(i) {
            true => &[],
            false => record.payload,
        };
        let packet = PacketRef::new(0, Timestamp::from(0u32), Duration::from(0u64), payload);
        match decoder.decode_ref(&packet) {
            Ok(buf) => {
                buf.copy_to_vec_interleaved(&mut samples);
                hasher.write_u64(u64::try_from(samples.len()).unwrap_or(u64::MAX));
                samples.iter().for_each(|sample| hasher.write(&sample.to_bits().to_le_bytes()));
            }
            Err(_) => hasher.write_u64(DECODE_ERROR_MARKER),
        }
        hasher.write(&decoder.final_range().to_le_bytes());
    }
    return hasher.0;
}

/// One digest line, sortable by `(loss, rate, channels, vector)`.
pub(crate) struct DigestLine {
    pub(crate) loss: Loss,
    pub(crate) rate: u32,
    pub(crate) layout: Layout,
    pub(crate) vector: usize,
    pub(crate) digest: u64,
}

impl std::fmt::Display for DigestLine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        return write!(
            f,
            "{} testvector{:02} {:>5} Hz {:<6} {:016x}",
            self.loss.name(),
            self.vector,
            self.rate,
            self.layout.name(),
            self.digest
        );
    }
}
