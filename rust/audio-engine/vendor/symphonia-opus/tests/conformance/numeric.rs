//! Numeric conversions of the conformance harness. The decoder's conversion module is private
//! to the crate, so the harness keeps its own audited set: every `as` cast of the suite is here.

/// Converts a count to `f64`, exact for every count the suite handles (far below `2^53`).
#[expect(clippy::cast_precision_loss, reason = "counts below 2^53 are exact in f64")]
pub(crate) fn count_f64(n: usize) -> f64 {
    debug_assert!(u64::try_from(n).is_ok_and(|n| n < 1 << f64::MANTISSA_DIGITS));
    return n as f64;
}

/// Converts a count to `f32`, exact below `2^24` (window sizes, band widths, sample indices).
#[expect(clippy::cast_precision_loss, reason = "counts below 2^24 are exact in f32")]
pub(crate) fn count_f32(n: usize) -> f32 {
    debug_assert!(u32::try_from(n).is_ok_and(|n| n < 1 << f32::MANTISSA_DIGITS));
    return n as f32;
}

/// Rounds an `f64` to the nearest `f32`, as `opus_compare.c` and the reference float build do
/// when they store a double into a float.
#[expect(clippy::cast_possible_truncation, reason = "rounding to f32 precision is the intent")]
pub(crate) fn nearest_f32(x: f64) -> f32 {
    return x as f32;
}

/// Converts an integral `f32` inside the 16-bit range to `i16`, exactly.
#[expect(clippy::cast_possible_truncation, reason = "integral and inside the i16 range")]
pub(crate) fn integral_i16(x: f32) -> i16 {
    debug_assert!(x.fract() == 0.0 && (f32::from(i16::MIN)..=f32::from(i16::MAX)).contains(&x));
    return x as i16;
}
