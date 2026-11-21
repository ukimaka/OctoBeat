//! Numeric conversions with a defined result for every input.
//!
//! Widening conversions use `From`. Every other conversion in the crate goes through this module,
//! so no `as` cast elsewhere can silently truncate, wrap or round:
//!
//! ```text
//!   conversion                 input range                  result outside the range
//!   -------------------------  ---------------------------  ------------------------------------
//!   BoundedFrom::bounded_from  guaranteed by RFC limits      debug: panic, release: nearest bound
//!   wrap_i16, wrap_i32         any                          two's-complement low bits (RFC 6716)
//!   ExactF32::exact_f32        |x| <= 2^24                  debug: panic, release: nearest f32
//!   nearest_f32                any f64                      nearest f32
//!   reinterpret_(un)signed     any                          same bits, other signedness
//! ```
//!
//! `BoundedFrom` is for values whose range follows from RFC 6716 limits (frame lengths of at most
//! 1275 bytes, band widths, symbol indices, shift counts). There the conversion is lossless; the
//! clamp only keeps a broken invariant from wrapping into a wrong sign or a huge index.
//! `wrap_i16` and `wrap_i32` are the `(opus_int16)` and `(opus_int32)` narrowings of the RFC 6716
//! Appendix A fixed-point macros; a bit-exact SILK decoder must reproduce them.

/// Lossless conversion of a value whose range the caller guarantees.
///
/// Debug builds assert that the value fits. Release builds clamp to the nearest bound of the
/// target type, so a broken invariant can never wrap.
pub(crate) trait BoundedFrom<T>: Sized {
    fn bounded_from(value: T) -> Self;
}

/// Implements [`BoundedFrom`] for signed sources, which may be below the target's minimum.
macro_rules! bounded_from_signed {
    ($($src:ty => $($dst:ty),+;)+) => {
        $($(
            impl BoundedFrom<$src> for $dst {
                #[inline(always)]
                fn bounded_from(value: $src) -> Self {
                    debug_assert!(
                        <$dst>::try_from(value).is_ok(),
                        "{value} is out of range for {}",
                        stringify!($dst)
                    );
                    return match <$dst>::try_from(value) {
                        Ok(converted) => converted,
                        Err(_) if value < 0 => <$dst>::MIN,
                        Err(_) => <$dst>::MAX,
                    };
                }
            }
        )+)+
    };
}

/// Implements [`BoundedFrom`] for unsigned sources, which can only exceed the target's maximum.
macro_rules! bounded_from_unsigned {
    ($($src:ty => $($dst:ty),+;)+) => {
        $($(
            impl BoundedFrom<$src> for $dst {
                #[inline(always)]
                fn bounded_from(value: $src) -> Self {
                    debug_assert!(
                        <$dst>::try_from(value).is_ok(),
                        "{value} is out of range for {}",
                        stringify!($dst)
                    );
                    return <$dst>::try_from(value).unwrap_or(<$dst>::MAX);
                }
            }
        )+)+
    };
}

bounded_from_signed! {
    i16 => usize;
    i32 => i16, u8, u16, u32, usize;
    i64 => i32, u32;
    isize => usize;
}

bounded_from_unsigned! {
    u32 => u8, i16, i32, usize;
    u64 => u32;
    usize => u8, u16, u32, i16, i32;
}

/// Converts a non-negative `i32` sample position or table index to `usize`, for per-sample loops
/// where a checked conversion measured slower.
///
/// Debug builds assert the sign. Release builds reinterpret the bits: a negative value, which
/// the callers rule out, becomes an index far out of range and panics at the slice access
/// instead of silently selecting a wrong sample.
#[inline(always)]
#[expect(clippy::cast_sign_loss, reason = "non-negative by contract, asserted in debug builds")]
pub(crate) fn nonnegative_index(value: i32) -> usize {
    debug_assert!(value >= 0, "{value} is negative");
    return value as usize;
}

/// Reinterprets the bits of `a` as unsigned, like `i32::cast_unsigned` (stable only after the
/// Rust 1.85 MSRV): two's-complement values map one to one, so no information is lost.
#[inline(always)]
#[expect(clippy::cast_sign_loss, reason = "same-width bit reinterpretation")]
pub(crate) const fn reinterpret_unsigned(a: i32) -> u32 {
    return a as u32;
}

/// Reinterprets the bits of `a` as signed, like `u32::cast_signed` (stable only after the Rust
/// 1.85 MSRV): two's-complement values map one to one, so no information is lost.
#[inline(always)]
#[expect(clippy::cast_possible_wrap, reason = "same-width bit reinterpretation")]
pub(crate) const fn reinterpret_signed(a: u32) -> i32 {
    return a as i32;
}

/// Keeps the low 16 bits of `a` as a two's-complement value: the `(opus_int16)` narrowing of the
/// RFC 6716 Appendix A fixed-point macros (for example the 16-bit operand of `silk_SMULWB`).
#[inline(always)]
#[expect(clippy::cast_possible_truncation, reason = "the RFC reference narrows by truncation")]
pub(crate) const fn wrap_i16(a: i32) -> i16 {
    return a as i16;
}

/// Keeps the low 32 bits of `a` as a two's-complement value: the `(opus_int32)` narrowing of
/// 64-bit products in the RFC 6716 Appendix A fixed-point macros (for example `silk_SMULWW`).
#[inline(always)]
#[expect(clippy::cast_possible_truncation, reason = "the RFC reference narrows by truncation")]
pub(crate) const fn wrap_i32(a: i64) -> i32 {
    return a as i32;
}

/// Largest magnitude every integer up to which `f32` represents exactly (`2^24`).
const F32_EXACT_LIMIT: u32 = 1 << f32::MANTISSA_DIGITS;

/// Conversion of an integer that `f32` represents exactly (magnitude at most `2^24`).
///
/// Debug builds assert the bound; release builds round to the nearest `f32` beyond it.
pub(crate) trait ExactF32: Copy {
    fn exact_f32(self) -> f32;
}

/// Implements [`ExactF32`] for integer types whose magnitude can exceed `2^24`.
macro_rules! exact_f32 {
    ($($src:ty),+) => {
        $(
            impl ExactF32 for $src {
                #[inline(always)]
                #[expect(clippy::cast_precision_loss, reason = "exact below 2^24, asserted")]
                fn exact_f32(self) -> f32 {
                    debug_assert!(
                        u64::try_from(i128::from(self).unsigned_abs())
                            .is_ok_and(|magnitude| magnitude <= u64::from(F32_EXACT_LIMIT)),
                        "{self} is not exactly representable as f32"
                    );
                    return self as f32;
                }
            }
        )+
    };
}

exact_f32!(i32, u32, u64);

impl ExactF32 for usize {
    #[inline(always)]
    fn exact_f32(self) -> f32 {
        // `usize` is at most 64 bits wide on every supported target, so this step is lossless.
        return u64::try_from(self).unwrap_or(u64::MAX).exact_f32();
    }
}

/// Rounds an `f64` to the nearest `f32`, the precision every CELT table and filter runs at.
#[inline(always)]
#[expect(clippy::cast_possible_truncation, reason = "rounding to f32 precision is the intent")]
pub(crate) const fn nearest_f32(x: f64) -> f32 {
    return x as f32;
}

/// Rounds `x` toward zero to an `i16`, saturating at the bounds: Rust's float-to-integer
/// conversion, for test signals built from `f64` formulas.
#[cfg(test)]
#[expect(clippy::cast_possible_truncation, reason = "truncation toward zero is the intent")]
pub(crate) fn trunc_saturating_i16(x: f64) -> i16 {
    return x as i16;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_from_is_lossless_in_range() {
        assert_eq!(i32::bounded_from(5_760usize), 5_760);
        assert_eq!(u8::bounded_from(255u32), 255);
        assert_eq!(usize::bounded_from(17i32), 17);
        assert_eq!(i16::bounded_from(-32_768i32), i16::MIN);
        assert_eq!(u32::bounded_from(0i64), 0);
    }

    #[test]
    #[cfg(not(debug_assertions))]
    fn bounded_from_clamps_out_of_range_in_release() {
        assert_eq!(i16::bounded_from(70_000i32), i16::MAX);
        assert_eq!(usize::bounded_from(-1i32), 0);
        assert_eq!(i32::bounded_from(usize::MAX), i32::MAX);
    }

    #[test]
    #[should_panic(expected = "out of range")]
    #[cfg(debug_assertions)]
    fn bounded_from_asserts_in_debug() {
        let _ = usize::bounded_from(-1i32);
    }

    #[test]
    fn wrap_keeps_low_bits() {
        assert_eq!(wrap_i16(0x1_8000), i16::MIN);
        assert_eq!(wrap_i16(-1), -1);
        assert_eq!(wrap_i32(0x1_0000_0001), 1);
        assert_eq!(wrap_i32(i64::from(i32::MIN)), i32::MIN);
    }

    #[test]
    fn exact_f32_is_exact_up_to_2_pow_24() {
        assert_eq!((1i32 << 24).exact_f32(), 16_777_216.0);
        assert_eq!((-(1i32 << 24)).exact_f32(), -16_777_216.0);
        assert_eq!(5_760usize.exact_f32(), 5_760.0);
    }

    #[test]
    fn nearest_f32_rounds_to_nearest() {
        assert_eq!(nearest_f32(0.1), 0.1_f32);
        assert_eq!(nearest_f32(f64::from(f32::MAX)), f32::MAX);
    }
}
