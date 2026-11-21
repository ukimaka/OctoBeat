//! Fixed-point arithmetic shared by the SILK layer
//! ([RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>)).
//!
//! SILK is specified in integer arithmetic: every intermediate value carries an implicit binary
//! point, written `Qn` for `n` fractional bits. A `Q16` value `x` represents `x / 2^16`. The
//! helpers here are the handful of primitive operations the RFC's normative decoder relies on,
//! named by what they compute rather than by any C macro. All of them are branch-free or
//! saturate explicitly so that results are identical on every platform.
//!
//! ```text
//!   operation                 inputs            result
//!   ------------------------  ----------------  ----------------------------------------
//!   mul_q16(a, b)             Qa, Qb            Q(a + b - 16): (a * b) >> 16
//!   mul_q16_i16(a, b)         Qa (i32), Qb      Q(a + b - 16) with a 16-bit multiplier
//!   mul_add_q16(acc, a, b)    acc + mul_q16     wrapping add of the Q16 product
//!   mul_high_i32(a, b)        Qa, Qb            Q(a + b - 32): (a * b) >> 32
//!   round_shift(a, n)         Qa                Q(a - n), rounded to nearest
//!   saturate_i16(a)           i32               clamped to the i16 range
//!   shl_saturating(a, n)      i32               (a << n) clamped to the i32 range
//!   reciprocal_q(b, q)        i32               (1 << q) / b, about 16 significant bits
//!   div_q(a, b, q)            i32, i32          (a << q) / b, about 16 significant bits
//! ```

use crate::convert::{BoundedFrom, reinterpret_unsigned, wrap_i16, wrap_i32};

/// Multiplies a 32-bit value by a 16-bit value and drops 16 fractional bits: `(a * b) >> 16`.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn mul_q16_i16(a: i32, b: i16) -> i32 {
    return wrap_i32((i64::from(a) * i64::from(b)) >> 16);
}

/// Adds the `Q16` product of a 32-bit and a 16-bit value to `acc` with wrapping arithmetic:
/// `acc + ((a * b) >> 16)`.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn mul_add_q16_i16(acc: i32, a: i32, b: i16) -> i32 {
    return acc.wrapping_add(mul_q16_i16(a, b));
}

/// Multiplies two 32-bit values and drops 16 fractional bits: `(a * b) >> 16`.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn mul_q16(a: i32, b: i32) -> i32 {
    return wrap_i32((i64::from(a) * i64::from(b)) >> 16);
}

/// Adds the `Q16` product of two 32-bit values to `acc` with wrapping arithmetic:
/// `acc + ((a * b) >> 16)`.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn mul_add_q16(acc: i32, a: i32, b: i32) -> i32 {
    return acc.wrapping_add(mul_q16(a, b));
}

/// Multiplies the low 16 bits of `a` and `b` as signed values: `(i16)a * (i16)b`, the
/// `silk_SMULBB` primitive of the RFC 6716 reference decoder, which narrows its operands by
/// truncation.
#[inline(always)]
pub(crate) fn mul_low_i16(a: i32, b: i32) -> i32 {
    return i32::from(wrap_i16(a)) * i32::from(wrap_i16(b));
}

/// Multiplies two 32-bit values and keeps the high word: `(a * b) >> 32`.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn mul_high_i32(a: i32, b: i32) -> i32 {
    return wrap_i32((i64::from(a) * i64::from(b)) >> 32);
}

/// Arithmetic right shift by `shift >= 1` bits with round-to-nearest (ties away from zero for
/// positive values, matching the normative decoder).
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn round_shift(a: i32, shift: u32) -> i32 {
    if shift == 1 {
        return (a >> 1) + (a & 1);
    }
    return ((a >> (shift - 1)) + 1) >> 1;
}

/// 64-bit variant of [`round_shift`].
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn round_shift_i64(a: i64, shift: u32) -> i64 {
    if shift == 1 {
        return (a >> 1) + (a & 1);
    }
    return ((a >> (shift - 1)) + 1) >> 1;
}

/// Clamps a 32-bit value into the 16-bit signed range.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn saturate_i16(a: i32) -> i16 {
    return i16::bounded_from(a.clamp(i32::from(i16::MIN), i32::from(i16::MAX)));
}

/// Left shift that saturates instead of overflowing; a shift of 31 or more maps every non-zero
/// value to the nearest 32-bit bound.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline(always)]
pub(crate) fn shl_saturating(a: i32, shift: u32) -> i32 {
    if shift >= 31 {
        if a > 0 {
            return i32::MAX;
        }
        if a < 0 {
            return i32::MIN;
        }
        return 0;
    }
    let shifted = i64::from(a) << shift;
    return i32::bounded_from(shifted.clamp(i64::from(i32::MIN), i64::from(i32::MAX)));
}

/// Compile-time constant left shift (`SHIFT < 31`) that saturates at the 32-bit signed bounds
/// directly in 32-bit registers without widening to 64 bits.
#[inline(always)]
pub(crate) fn shl_saturating_const<const SHIFT: u32>(a: i32) -> i32 {
    const {
        assert!(SHIFT < 31);
    }
    let max_in = i32::MAX >> SHIFT;
    let min_in = i32::MIN >> SHIFT;
    if a > max_in {
        return i32::MAX;
    }
    if a < min_in {
        return i32::MIN;
    }
    return a.wrapping_shl(SHIFT);
}

/// Approximates `(1 << q_res) / b` with one Newton refinement step, exactly as the normative
/// decoder does, so that gains and prediction coefficients stay bit-identical.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline]
pub(crate) fn reciprocal_q(b: i32, q_res: i32) -> i32 {
    if b == 0 || q_res <= 0 {
        return 0;
    }

    let b_headroom = headroom(b);
    let b_normalized = b.wrapping_shl(reinterpret_unsigned(b_headroom));
    // The top 16 bits of an `i32` always fit in an `i16`.
    let denominator = b_normalized >> 16;
    if denominator == 0 {
        return 0;
    }

    let b_inverse = (i32::MAX >> 2) / denominator;
    let mut result = b_inverse.wrapping_shl(16);
    let error_q32 = ((1i32 << 29) - mul_q16_i16(b_normalized, wrap_i16(b_inverse))).wrapping_shl(3);
    result = mul_add_q16(result, error_q32, b_inverse);

    let left_shift = 61 - b_headroom - q_res;
    if left_shift <= 0 {
        return shl_saturating(result, left_shift.unsigned_abs());
    }
    return result.checked_shr(left_shift.unsigned_abs()).unwrap_or(0);
}

/// Redundant sign bits of `a`: its leading zeros of the magnitude minus one (`silk_CLZ32` of
/// `silk_abs` minus one), `-1` for `i32::MIN`.
#[inline]
fn headroom(a: i32) -> i32 {
    // At most 32 leading zeros.
    return i32::bounded_from(a.unsigned_abs().leading_zeros()) - 1;
}

/// Approximates `(a << q_res) / b` with one Newton refinement step, exactly as the normative
/// decoder does.
/// One of the bit-exact SILK fixed-point primitives of
/// [RFC 6716 Section 4.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2>).
#[inline]
pub(crate) fn div_q(a: i32, b: i32, q_res: i32) -> i32 {
    if b == 0 || q_res < 0 || a == 0 {
        return 0;
    }

    let a_headroom = headroom(a);
    let mut a_normalized = a.wrapping_shl(reinterpret_unsigned(a_headroom));
    let b_headroom = headroom(b);
    let b_normalized = b.wrapping_shl(reinterpret_unsigned(b_headroom));
    // The top 16 bits of an `i32` always fit in an `i16`.
    let denominator = b_normalized >> 16;
    if denominator == 0 {
        return 0;
    }

    let b_inverse = (i32::MAX >> 2) / denominator;
    let mut result = mul_q16_i16(a_normalized, wrap_i16(b_inverse));
    a_normalized = a_normalized.wrapping_sub(mul_high_i32(b_normalized, result).wrapping_shl(3));
    result = mul_add_q16_i16(result, a_normalized, wrap_i16(b_inverse));

    let left_shift = 29 + a_headroom - b_headroom - q_res;
    if left_shift < 0 {
        return shl_saturating(result, left_shift.unsigned_abs());
    }
    return result.checked_shr(left_shift.unsigned_abs()).unwrap_or(0);
}

/// Square root base for an odd leading bit position, `32768` (`2^15`)
/// ([RFC 6716 Section 4.2.7.5.3](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.3>)).
const SQRT_BASE_ODD: i32 = 32_768;

/// Square root base for an even leading bit position, `46214` (`2^15.5`).
const SQRT_BASE_EVEN: i32 = 46_214;

/// Q16 slope of the linear correction from the seven bits below the leading one (`213`).
const SQRT_FRACTION_SLOPE_Q16: i32 = 213;

/// The seven bits below the leading one that refine the square root.
const SQRT_FRACTION_MASK: u32 = 0x7F;

/// Bit position, counted from the top, at which the seven refining bits end (`24`).
const SQRT_FRACTION_END: i32 = 24;

/// Approximate square root of `x` from its leading bit position and the seven bits below it, as
/// SILK computes the NLSF weights; `0` for `x <= 0`
/// ([RFC 6716 Section 4.2.7.5.3](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.3>)).
#[inline]
pub(crate) fn sqrt_approx(x: i32) -> i32 {
    if x <= 0 {
        return 0;
    }
    let magnitude = x.unsigned_abs();
    let leading_zeros = i32::bounded_from(magnitude.leading_zeros());
    // `rotate_right` reduces modulo 32, so a negative rotation becomes the matching left
    // rotation, as in `silk_ROR32`.
    let rotation = reinterpret_unsigned(SQRT_FRACTION_END - leading_zeros);
    let fraction = i32::bounded_from(magnitude.rotate_right(rotation) & SQRT_FRACTION_MASK);
    let base = if (leading_zeros & 1) != 0 { SQRT_BASE_ODD } else { SQRT_BASE_EVEN };
    let y = base >> (leading_zeros >> 1);
    return mul_add_q16_i16(y, y, wrap_i16(SQRT_FRACTION_SLOPE_Q16 * fraction));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn q16_products_drop_sixteen_fractional_bits() {
        const ONE_Q16: i32 = 1 << 16;
        const HALF_Q16: i32 = 1 << 15;
        assert_eq!(mul_q16(ONE_Q16, HALF_Q16), HALF_Q16);
        assert_eq!(mul_q16_i16(ONE_Q16, i16::MAX), i32::from(i16::MAX));
        assert_eq!(mul_add_q16(7, ONE_Q16, HALF_Q16), 7 + HALF_Q16);
        assert_eq!(mul_add_q16_i16(i32::MAX, ONE_Q16, 1), i32::MIN);
        assert_eq!(mul_high_i32(i32::MAX, i32::MAX), (1 << 30) - 1);
        return;
    }

    #[test]
    fn round_shift_rounds_to_nearest() {
        assert_eq!(round_shift(5, 1), 3);
        assert_eq!(round_shift(-5, 1), -2);
        assert_eq!(round_shift(6, 2), 2);
        assert_eq!(round_shift(7, 2), 2);
        assert_eq!(round_shift(10, 2), 3);
        assert_eq!(round_shift_i64(1 << 40, 20), 1 << 20);
        return;
    }

    #[test]
    fn saturating_operations_clamp_at_the_type_bounds() {
        assert_eq!(saturate_i16(40_000), i16::MAX);
        assert_eq!(saturate_i16(-40_000), i16::MIN);
        assert_eq!(saturate_i16(-7), -7);
        assert_eq!(shl_saturating(1, 30), 1 << 30);
        assert_eq!(shl_saturating(3, 30), i32::MAX);
        assert_eq!(shl_saturating(-3, 31), i32::MIN);
        assert_eq!(shl_saturating(0, 40), 0);
        return;
    }

    #[test]
    fn reciprocal_and_division_track_the_exact_quotient() {
        for (a, b, q) in
            [(1_000, 3, 16), (123_456, 789, 12), (-65_536, 1_000, 16), (7, 1 << 20, 30)]
        {
            let exact = i32::try_from((i64::from(a) << q) / i64::from(b)).unwrap();
            let approximate = div_q(a, b, q);
            let tolerance = (exact.abs() >> 14) + 2;
            assert!(
                (approximate - exact).abs() <= tolerance,
                "div_q({a}, {b}, {q}) = {approximate}, exact {exact}"
            );
        }
        for (b, q) in [(3, 20), (1_000, 29), (65_536, 30)] {
            let exact = i32::try_from((1i64 << q) / i64::from(b)).unwrap();
            let approximate = reciprocal_q(b, q);
            let tolerance = (exact.abs() >> 14) + 2;
            assert!(
                (approximate - exact).abs() <= tolerance,
                "reciprocal_q({b}, {q}) = {approximate}, exact {exact}"
            );
        }
        assert_eq!(div_q(5, 0, 16), 0);
        assert_eq!(reciprocal_q(0, 16), 0);
        return;
    }
}
