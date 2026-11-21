//! Multi-stream packet splitting and output channel routing
//! ([RFC 7845 Section 5.1.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1.1>)).
//!
//! A multi-stream packet
//! ([RFC 7845 Section 3](<https://datatracker.ietf.org/doc/html/rfc7845#section-3>)) carries
//! `N - 1` self-delimited elementary stream packets
//! ([RFC 6716 Appendix B](<https://datatracker.ietf.org/doc/html/rfc6716#appendix-B>)) followed
//! by one undelimited packet. [`OpusDecoder`](crate::decoder::OpusDecoder) decodes the `M`
//! coupled stereo streams and the `N - M` uncoupled mono streams with one
//! [`StreamDecoder`](crate::stream::StreamDecoder) each and routes their channels to the output
//! planes through the `OpusHead` channel mapping table
//! ([RFC 7845 Section 5.1.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1.1>)),
//! scaled by the Q7.8 dB `output_gain`
//! ([RFC 7845 Section 5.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1>)).

use symphonia_core::audio::{AudioBuffer, AudioMut};
use symphonia_core::errors::{Error as SymphoniaError, Result};

use crate::packet::FramePacket;
use crate::planes::Planes;
use crate::stream::MAX_PACKET_SAMPLES_48K;

/// The elementary stream packets of a multi-stream Opus packet, in stream order: `count - 1`
/// self-delimited packets
/// ([RFC 6716 Appendix B](<https://datatracker.ietf.org/doc/html/rfc6716#appendix-B>)) followed
/// by one undelimited packet that runs to the end of the data
/// ([RFC 7845 Section 3](<https://datatracker.ietf.org/doc/html/rfc7845#section-3>)).
pub(crate) struct StreamPackets<'a> {
    data: &'a [u8],
    remaining: usize,
}

impl<'a> StreamPackets<'a> {
    /// Splits `data` into `count` elementary stream packets.
    pub(crate) const fn new(data: &'a [u8], count: usize) -> Self {
        return Self { data, remaining: count };
    }
}

impl<'a> Iterator for StreamPackets<'a> {
    type Item = Result<FramePacket<'a>>;

    fn next(&mut self) -> Option<Self::Item> {
        self.remaining = self.remaining.checked_sub(1)?;
        if self.remaining == 0 {
            return Some(FramePacket::new(self.data).map_err(SymphoniaError::from));
        }
        let parsed = FramePacket::parse_self_delimited(self.data).map_err(SymphoniaError::from);
        return Some(parsed.map(|(packet, consumed)| {
            self.data = &self.data[consumed..];
            packet
        }));
    }
}

/// Where each decoded stream channel goes
/// ([RFC 7845 Section 5.1.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1.1>)):
/// coupled stream `s` feeds the output channels whose mapping entry is `2s` (left) or `2s + 1`
/// (right); uncoupled stream `s` feeds the entries equal to `coupled_count + s`. Samples are
/// scaled by the output gain
/// ([RFC 7845 Section 5.1](<https://datatracker.ietf.org/doc/html/rfc7845#section-5.1>)).
///
/// Whenever every channel of an elementary stream maps to at least one output plane, the stream
/// decodes directly into its target [`AudioBuffer`] plane (via [`AudioMut::plane_mut`] for mono
/// streams or [`AudioMut::plane_pair_mut`] for coupled stereo streams) with zero heap allocation
/// and zero intermediate buffer copies.
#[derive(Clone, Copy)]
pub(crate) struct OutputRouting<'a> {
    pub(crate) channel_mapping: &'a [u8],
    pub(crate) coupled_count: usize,
    /// Linear output gain, `None` when the `output_gain` field is zero.
    pub(crate) gain: Option<f32>,
}

impl OutputRouting<'_> {
    /// Whether any decoded channel across `stream_count` elementary streams (`coupled_count` of
    /// them coupled) is absent from `channel_mapping` and therefore needs a staging scratch buffer.
    pub(crate) fn needs_scratch(
        channel_mapping: &[u8],
        stream_count: usize,
        coupled_count: usize,
    ) -> bool {
        let decoded_channels = coupled_count + stream_count;
        return (0..decoded_channels)
            .any(|decoded| !channel_mapping.iter().any(|&map| usize::from(map) == decoded));
    }

    /// Returns the first output plane index mapped to `decoded`, or `None` if unmapped.
    #[inline]
    fn first_plane(&self, decoded: usize) -> Option<usize> {
        return self.channel_mapping.iter().position(|&map| usize::from(map) == decoded);
    }

    /// Decodes `total_samples` of elementary stream `stream_pos` with `decode` directly into its
    /// mapped [`AudioBuffer`] planes when every channel of the stream is mapped, or through
    /// `scratch` when any channel of the stream is absent from `channel_mapping`.
    pub(crate) fn decode_stream<F>(
        &self,
        stream_pos: usize,
        total_samples: usize,
        scratch: Option<&mut [[f32; MAX_PACKET_SAMPLES_48K]; 2]>,
        buffer: &mut AudioBuffer<f32>,
        decode: F,
    ) -> Result<()>
    where
        F: FnOnce(Planes<'_>) -> Result<usize>,
    {
        if stream_pos >= self.coupled_count {
            let decoded = self.coupled_count + stream_pos;
            let Some(primary) = self.first_plane(decoded)
            else {
                return self.decode_via_scratch(stream_pos, total_samples, scratch, buffer, decode);
            };
            let plane = buffer
                .plane_mut(primary)
                .ok_or(SymphoniaError::DecodeError("opus: missing output plane"))?;
            let written = decode(Planes::mono(&mut plane[..total_samples]))?;
            debug_assert_eq!(written, total_samples);
            return self.finish_mapped_channel(decoded, primary, total_samples, buffer);
        }

        let (left_decoded, right_decoded) = (2 * stream_pos, 2 * stream_pos + 1);
        let (Some(left_ch), Some(right_ch)) =
            (self.first_plane(left_decoded), self.first_plane(right_decoded))
        else {
            return self.decode_via_scratch(stream_pos, total_samples, scratch, buffer, decode);
        };
        let (left, right) = buffer
            .plane_pair_mut(left_ch, right_ch)
            .ok_or(SymphoniaError::DecodeError("opus: missing output plane"))?;
        let written =
            decode(Planes::stereo(&mut left[..total_samples], &mut right[..total_samples]))?;
        debug_assert_eq!(written, total_samples);
        self.finish_mapped_channel(left_decoded, left_ch, total_samples, buffer)?;
        return self.finish_mapped_channel(right_decoded, right_ch, total_samples, buffer);
    }

    /// Scales `primary` in-place when `self.gain` is non-unity and copies it into any additional
    /// output planes that also map `decoded`.
    fn finish_mapped_channel(
        &self,
        decoded: usize,
        primary: usize,
        total_samples: usize,
        buffer: &mut AudioBuffer<f32>,
    ) -> Result<()> {
        if let Some(scale) = self.gain {
            let plane = buffer
                .plane_mut(primary)
                .ok_or(SymphoniaError::DecodeError("opus: missing output plane"))?;
            plane[..total_samples].iter_mut().for_each(|sample| *sample *= scale);
        }
        for (ch, &map) in self.channel_mapping.iter().enumerate().skip(primary + 1) {
            if usize::from(map) != decoded {
                continue;
            }
            let (src, dst) = buffer
                .plane_pair_mut(primary, ch)
                .ok_or(SymphoniaError::DecodeError("opus: missing output plane"))?;
            dst[..total_samples].copy_from_slice(&src[..total_samples]);
        }
        return Ok(());
    }

    /// Fallback for an elementary stream that has at least one unmapped channel: decodes into
    /// `scratch` and copies any mapped channel to its output plane(s).
    fn decode_via_scratch<F>(
        &self,
        stream_pos: usize,
        total_samples: usize,
        scratch: Option<&mut [[f32; MAX_PACKET_SAMPLES_48K]; 2]>,
        buffer: &mut AudioBuffer<f32>,
        decode: F,
    ) -> Result<()>
    where
        F: FnOnce(Planes<'_>) -> Result<usize>,
    {
        let scratch = scratch.ok_or(SymphoniaError::DecodeError(
            "opus: missing scratch buffer for unmapped stream",
        ))?;
        let is_coupled = stream_pos < self.coupled_count;
        let mut planes = Planes::from_rows(scratch, is_coupled);
        let written = decode(planes.range(..total_samples))?;
        debug_assert_eq!(written, total_samples);

        let mono = (self.coupled_count + stream_pos, 1);
        let (first, count) = if is_coupled { (2 * stream_pos, 2) } else { mono };
        for (ch, &map) in self.channel_mapping.iter().enumerate() {
            let Some(k) = usize::from(map).checked_sub(first).filter(|k| *k < count)
            else {
                continue;
            };
            let src = &scratch[k][..total_samples];
            let dst = buffer
                .plane_mut(ch)
                .ok_or(SymphoniaError::DecodeError("opus: missing output plane"))?;
            let dst = &mut dst[..total_samples];
            match self.gain {
                Some(scale) => dst.iter_mut().zip(src).for_each(|(d, &s)| *d = s * scale),
                None => dst.copy_from_slice(src),
            }
        }
        return Ok(());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use symphonia_core::audio::{Audio, AudioSpec, Channels};

    fn make_buffer(channels: u16, frames: usize) -> AudioBuffer<f32> {
        let spec = AudioSpec::new(48_000, Channels::Discrete(channels));
        let mut buf = AudioBuffer::new(spec, frames);
        buf.render_uninit(Some(frames));
        return buf;
    }

    #[test]
    fn needs_scratch_only_when_a_decoded_channel_is_unmapped() {
        assert!(!OutputRouting::needs_scratch(&[0], 1, 0));
        assert!(!OutputRouting::needs_scratch(&[0, 1], 1, 1));
        assert!(!OutputRouting::needs_scratch(&[1, 0], 1, 1));
        assert!(!OutputRouting::needs_scratch(&[0, 0], 1, 0));
        assert!(!OutputRouting::needs_scratch(&[0, 2, 1], 2, 1));
        assert!(!OutputRouting::needs_scratch(&[0, 4, 1, 2, 3, 5], 4, 2));
        assert!(OutputRouting::needs_scratch(&[255], 1, 0));
        assert!(OutputRouting::needs_scratch(&[0, 255], 1, 1));
        assert!(OutputRouting::needs_scratch(&[0, 255, 1], 2, 1));
        return;
    }

    #[test]
    fn zero_copy_routes_swapped_duplicated_and_scaled_planes_without_scratch() {
        let mut swapped = make_buffer(2, 4);
        let routing = OutputRouting { channel_mapping: &[1, 0], coupled_count: 1, gain: Some(2.0) };
        routing
            .decode_stream(0, 4, None, &mut swapped, |planes| {
                planes.left.copy_from_slice(&[1.0, 2.0, 3.0, 4.0]);
                planes.right.unwrap().copy_from_slice(&[-1.0, -2.0, -3.0, -4.0]);
                Ok(4)
            })
            .unwrap();
        assert_eq!(swapped.plane(0).unwrap(), &[-2.0, -4.0, -6.0, -8.0]);
        assert_eq!(swapped.plane(1).unwrap(), &[2.0, 4.0, 6.0, 8.0]);

        let mut duplicated = make_buffer(2, 3);
        let dup_routing =
            OutputRouting { channel_mapping: &[0, 0], coupled_count: 0, gain: Some(0.5) };
        dup_routing
            .decode_stream(0, 3, None, &mut duplicated, |planes| {
                planes.left.copy_from_slice(&[2.0, 4.0, 6.0]);
                assert!(planes.right.is_none());
                Ok(3)
            })
            .unwrap();
        assert_eq!(duplicated.plane(0).unwrap(), &[1.0, 2.0, 3.0]);
        assert_eq!(duplicated.plane(1).unwrap(), &[1.0, 2.0, 3.0]);
        return;
    }

    #[test]
    fn partially_unmapped_coupled_stream_routes_via_scratch() {
        let mut buf = make_buffer(2, 3);
        buf.plane_mut(1).unwrap().fill(0.0);
        let mut scratch = [[0.0_f32; MAX_PACKET_SAMPLES_48K]; 2];
        let routing = OutputRouting { channel_mapping: &[0, 255], coupled_count: 1, gain: None };
        routing
            .decode_stream(0, 3, Some(&mut scratch), &mut buf, |planes| {
                planes.left.copy_from_slice(&[0.25, 0.5, 0.75]);
                planes.right.unwrap().copy_from_slice(&[9.0, 9.0, 9.0]);
                Ok(3)
            })
            .unwrap();
        assert_eq!(buf.plane(0).unwrap(), &[0.25, 0.5, 0.75]);
        assert_eq!(buf.plane(1).unwrap(), &[0.0, 0.0, 0.0]);
        return;
    }
}
