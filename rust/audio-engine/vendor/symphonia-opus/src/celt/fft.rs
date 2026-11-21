//! Mixed-radix complex FFT kernel of the CELT inverse MDCT
//! ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).
//!
//! The inverse MDCT of a block of `N` coefficients is evaluated as a quarter-length (`N / 4`)
//! complex FFT between a pre-rotation and a post-rotation. The quarter lengths used by the 48 kHz
//! CELT mode (`480`, `240`, `120`, `60` points) factor into radix `2`, `3`, `4`, and `5` stages,
//! which [`MixedRadixPlan`] evaluates in place on a digit-reversed input buffer.

use crate::celt::mdct::MDCT_MAX_N4;
use crate::convert::BoundedFrom;
use crate::slices::array_chunks_mut;

/// Single-precision complex number used in the mixed-radix quarter-length FFT.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(crate) struct Complex32 {
    /// Real part.
    pub(crate) r: f32,
    /// Imaginary part.
    pub(crate) i: f32,
}

impl Complex32 {
    /// Creates a new complex number `r + i * j`.
    #[inline(always)]
    pub(crate) const fn new(r: f32, i: f32) -> Self {
        return Self { r, i };
    }

    /// Component-wise complex addition `self + rhs`.
    #[inline(always)]
    pub(crate) fn add(self, rhs: Self) -> Self {
        return Self { r: self.r + rhs.r, i: self.i + rhs.i };
    }

    /// Component-wise complex subtraction `self - rhs`.
    #[inline(always)]
    pub(crate) fn sub(self, rhs: Self) -> Self {
        return Self { r: self.r - rhs.r, i: self.i - rhs.i };
    }

    /// Complex multiplication `self * rhs`.
    #[inline(always)]
    pub(crate) fn mul(self, rhs: Self) -> Self {
        return Self { r: self.r * rhs.r - self.i * rhs.i, i: self.r * rhs.i + self.i * rhs.r };
    }
}

/// Twiddle table slot holding `exp(-j * 2 * pi / 3)`, whose imaginary part `-sqrt(3) / 2`
/// drives the radix-3 butterfly.
const RADIX3_TWIDDLE: usize = MDCT_MAX_N4 / 3;

/// Twiddle table slot holding `exp(-j * 2 * pi / 5)` for the radix-5 butterfly.
const RADIX5_TWIDDLE_A: usize = MDCT_MAX_N4 / 5;

/// Twiddle table slot holding `exp(-j * 4 * pi / 5)` for the radix-5 butterfly.
const RADIX5_TWIDDLE_B: usize = 2 * MDCT_MAX_N4 / 5;

/// Mixed-radix `(radix, span)` stage lists for `n4 = 480 >> shift` (`shift in 0..=3`),
/// outermost stage first; `span` is the number of points each butterfly of that stage covers.
static STAGES_BY_SHIFT: [&[(usize, usize)]; 4] = validated_stage_lists([
    &[(5, 96), (3, 32), (4, 8), (2, 4), (4, 1)],
    &[(5, 48), (3, 16), (4, 4), (4, 1)],
    &[(5, 24), (3, 8), (2, 4), (4, 1)],
    &[(5, 12), (3, 4), (4, 1)],
]);

/// Verifies at compile time that every stage list factors `MDCT_MAX_N4 >> shift` and that each
/// stage's `span` equals the product of the remaining inner radices.
const fn validated_stage_lists(
    lists: [&'static [(usize, usize)]; 4],
) -> [&'static [(usize, usize)]; 4] {
    let mut shift = 0;
    while shift < lists.len() {
        let stages = lists[shift];
        let mut expected_points = 1usize;
        let mut k = stages.len();
        while k > 0 {
            k -= 1;
            let (radix, span) = stages[k];
            assert!(span == expected_points);
            expected_points *= radix;
        }
        assert!(expected_points == (MDCT_MAX_N4 >> shift));
        shift += 1;
    }
    return lists;
}

/// Mixed-radix factorization of one quarter-length inverse MDCT FFT
/// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).
///
/// A plan is selected by the block-size `shift in 0..=3` (`n4 = 480 >> shift` complex points)
/// and provides the digit-reversal permutation of its input together with the in-place
/// butterfly cascade over the shared 480-point twiddle table.
#[derive(Debug, Clone, Copy)]
pub(super) struct MixedRadixPlan {
    /// Block-size right-shift (`0..=3`); the twiddle stride is scaled by `1 << shift`.
    shift: usize,
    /// Radix stages, outermost first; the final stage is always the radix-4 base case.
    stages: &'static [(usize, usize)],
}

impl MixedRadixPlan {
    /// Returns the plan of the `n4 = 480 >> shift` point FFT for `shift in 0..=3`.
    #[inline]
    pub(super) const fn for_shift(shift: usize) -> Self {
        let clamped = if shift < STAGES_BY_SHIFT.len() { shift } else { STAGES_BY_SHIFT.len() - 1 };
        return Self { shift, stages: STAGES_BY_SHIFT[clamped] };
    }

    /// Number of complex points transformed by this plan (`480 >> shift`).
    #[inline]
    pub(super) const fn len(&self) -> usize {
        return MDCT_MAX_N4 >> self.shift;
    }

    /// Fills `out[..self.len()]` with the digit-reversal permutation that scatters natural-order
    /// input into the order expected by [`MixedRadixPlan::execute`].
    pub(super) fn digit_reversal(&self, out: &mut [u16]) {
        digit_reversal_recursive(0, out, 0, 1, 1, self.stages);
        return;
    }

    /// Runs the in-place butterfly cascade on the digit-reversed buffer `fout[..self.len()]`
    /// using the 480-point twiddle table `twiddles[k] = exp(-j * 2 * pi * k / 480)`.
    pub(super) fn execute(&self, fout: &mut [Complex32], twiddles: &[Complex32; MDCT_MAX_N4]) {
        let n4 = self.len();
        let fout = &mut fout[..n4];

        // Innermost stage: radix 4 over a span of one point.
        butterfly_radix4_base(fout);

        // Remaining stages from inner to outer.
        let mut fstride = n4 / 4;
        for &(radix, span) in self.stages[..self.stages.len() - 1].iter().rev() {
            fstride /= radix;
            let twiddle_stride = fstride << self.shift;
            match radix {
                2 => butterfly_radix2(fout, twiddle_stride, twiddles),
                3 => butterfly_radix3(fout, twiddle_stride, span, twiddles),
                4 => butterfly_radix4(fout, twiddle_stride, span, twiddles),
                5 => butterfly_radix5(fout, twiddle_stride, span, twiddles),
                _ => unreachable!("unsupported FFT radix"),
            }
        }
        return;
    }
}

/// Recursively populates the mixed-radix digit-reversal table for the remaining `stages`.
fn digit_reversal_recursive(
    fout: usize,
    out: &mut [u16],
    in_offset: usize,
    fstride: usize,
    in_stride: usize,
    stages: &[(usize, usize)],
) {
    let (radix, span) = stages[0];
    let rest = &stages[1..];
    if span == 1 {
        let slots = out[in_offset..].iter_mut().step_by(fstride * in_stride);
        for (slot, index) in slots.zip(fout..fout + radix) {
            *slot = u16::bounded_from(index);
        }
        return;
    }
    let mut fout_cur = fout;
    let mut offset_cur = in_offset;
    for _ in 0..radix {
        digit_reversal_recursive(fout_cur, out, offset_cur, fstride * radix, in_stride, rest);
        offset_cur += fstride * in_stride;
        fout_cur += span;
    }
    return;
}

/// Radix-4 butterfly over a span of one point (innermost stage, no twiddles).
#[inline]
fn butterfly_radix4_base(fout: &mut [Complex32]) {
    for quad in array_chunks_mut::<_, 4>(fout) {
        let [f0, f1, f2, f3] = *quad;

        let scratch0 = f0.sub(f2);
        let f0_plus_f2 = f0.add(f2);
        let scratch1 = f1.add(f3);
        let scratch2 = f1.sub(f3);

        *quad = [
            f0_plus_f2.add(scratch1),
            Complex32::new(scratch0.r + scratch2.i, scratch0.i - scratch2.r),
            f0_plus_f2.sub(scratch1),
            Complex32::new(scratch0.r - scratch2.i, scratch0.i + scratch2.r),
        ];
    }
    return;
}

/// Radix-4 butterfly stage over groups of `4 * span` points.
#[inline]
fn butterfly_radix4(
    fout: &mut [Complex32],
    fstride: usize,
    span: usize,
    twiddles: &[Complex32; MDCT_MAX_N4],
) {
    let group_len = 4 * span;
    let mut rem = fout;
    while rem.len() >= group_len {
        let (group, tail) = rem.split_at_mut(group_len);
        rem = tail;
        let (leg0, rest) = group.split_at_mut(span);
        let (leg1, rest) = rest.split_at_mut(span);
        let (leg2, leg3) = rest.split_at_mut(span);
        for (j, (((f0_slot, f1_slot), f2_slot), f3_slot)) in leg0
            .iter_mut()
            .zip(leg1.iter_mut())
            .zip(leg2.iter_mut())
            .zip(leg3.iter_mut())
            .enumerate()
        {
            let tw1 = twiddles[j * fstride];
            let tw2 = twiddles[j * fstride * 2];
            let tw3 = twiddles[j * fstride * 3];

            let scratch0 = f1_slot.mul(tw1);
            let scratch1 = f2_slot.mul(tw2);
            let scratch2 = f3_slot.mul(tw3);

            let f0 = *f0_slot;
            let scratch5 = f0.sub(scratch1);
            let f0_plus_s1 = f0.add(scratch1);
            let scratch3 = scratch0.add(scratch2);
            let scratch4 = scratch0.sub(scratch2);

            *f2_slot = f0_plus_s1.sub(scratch3);
            *f0_slot = f0_plus_s1.add(scratch3);

            *f1_slot = Complex32::new(scratch5.r + scratch4.i, scratch5.i - scratch4.r);
            *f3_slot = Complex32::new(scratch5.r - scratch4.i, scratch5.i + scratch4.r);
        }
    }
    return;
}

/// Radix-2 butterfly stage, which only occurs with a span of four points.
#[inline]
fn butterfly_radix2(fout: &mut [Complex32], fstride: usize, twiddles: &[Complex32; MDCT_MAX_N4]) {
    const SPAN: usize = 4;
    const GROUP_LEN: usize = 2 * SPAN;
    for group in array_chunks_mut::<_, GROUP_LEN>(fout) {
        let (leg0, leg1) = group.split_at_mut(SPAN);
        for (j, (f0_slot, f1_slot)) in leg0.iter_mut().zip(leg1.iter_mut()).enumerate() {
            let tw = twiddles[j * fstride];
            let t = f1_slot.mul(tw);
            let f0 = *f0_slot;
            *f1_slot = f0.sub(t);
            *f0_slot = f0.add(t);
        }
    }
    return;
}

/// Radix-3 butterfly stage over groups of `3 * span` points.
#[inline]
fn butterfly_radix3(
    fout: &mut [Complex32],
    fstride: usize,
    span: usize,
    twiddles: &[Complex32; MDCT_MAX_N4],
) {
    let epi3_i = twiddles[RADIX3_TWIDDLE].i;
    let group_len = 3 * span;
    let mut rem = fout;

    while rem.len() >= group_len {
        let (group, tail) = rem.split_at_mut(group_len);
        rem = tail;
        let (leg0, rest) = group.split_at_mut(span);
        let (leg1, leg2) = rest.split_at_mut(span);
        for (j, ((f0_slot, f1_slot), f2_slot)) in
            leg0.iter_mut().zip(leg1.iter_mut()).zip(leg2.iter_mut()).enumerate()
        {
            let tw1 = twiddles[j * fstride];
            let tw2 = twiddles[j * fstride * 2];

            let scratch1 = f1_slot.mul(tw1);
            let scratch2 = f2_slot.mul(tw2);
            let scratch3 = scratch1.add(scratch2);
            let scratch0 = scratch1.sub(scratch2);

            let f0 = *f0_slot;
            let f_mid = Complex32::new(f0.r - 0.5 * scratch3.r, f0.i - 0.5 * scratch3.i);
            let rot = Complex32::new(scratch0.i * epi3_i, -scratch0.r * epi3_i);

            *f0_slot = f0.add(scratch3);
            *f2_slot = f_mid.add(rot);
            *f1_slot = f_mid.sub(rot);
        }
    }
    return;
}

/// Radix-5 butterfly stage over groups of `5 * span` points.
#[inline]
fn butterfly_radix5(
    fout: &mut [Complex32],
    fstride: usize,
    span: usize,
    twiddles: &[Complex32; MDCT_MAX_N4],
) {
    let ya = twiddles[RADIX5_TWIDDLE_A];
    let yb = twiddles[RADIX5_TWIDDLE_B];
    let group_len = 5 * span;
    let mut rem = fout;

    while rem.len() >= group_len {
        let (group, tail) = rem.split_at_mut(group_len);
        rem = tail;
        let (leg0, rest) = group.split_at_mut(span);
        let (leg1, rest) = rest.split_at_mut(span);
        let (leg2, rest) = rest.split_at_mut(span);
        let (leg3, leg4) = rest.split_at_mut(span);
        for (j, ((((f0_slot, f1_slot), f2_slot), f3_slot), f4_slot)) in leg0
            .iter_mut()
            .zip(leg1.iter_mut())
            .zip(leg2.iter_mut())
            .zip(leg3.iter_mut())
            .zip(leg4.iter_mut())
            .enumerate()
        {
            let scratch0 = *f0_slot;
            let scratch1 = f1_slot.mul(twiddles[j * fstride]);
            let scratch2 = f2_slot.mul(twiddles[2 * j * fstride]);
            let scratch3 = f3_slot.mul(twiddles[3 * j * fstride]);
            let scratch4 = f4_slot.mul(twiddles[4 * j * fstride]);

            let scratch7 = scratch1.add(scratch4);
            let scratch10 = scratch1.sub(scratch4);
            let scratch8 = scratch2.add(scratch3);
            let scratch9 = scratch2.sub(scratch3);

            *f0_slot = scratch0.add(scratch7).add(scratch8);

            let scratch5 = Complex32::new(
                scratch0.r + scratch7.r * ya.r + scratch8.r * yb.r,
                scratch0.i + scratch7.i * ya.r + scratch8.i * yb.r,
            );
            let scratch6 = Complex32::new(
                scratch10.i * ya.i + scratch9.i * yb.i,
                -(scratch10.r * ya.i + scratch9.r * yb.i),
            );

            *f1_slot = scratch5.sub(scratch6);
            *f4_slot = scratch5.add(scratch6);

            let scratch11 = Complex32::new(
                scratch0.r + scratch7.r * yb.r + scratch8.r * ya.r,
                scratch0.i + scratch7.i * yb.r + scratch8.i * ya.r,
            );
            let scratch12 = Complex32::new(
                -scratch10.i * yb.i + scratch9.i * ya.i,
                scratch10.r * yb.i - scratch9.r * ya.i,
            );

            *f2_slot = scratch11.add(scratch12);
            *f3_slot = scratch11.sub(scratch12);
        }
    }
    return;
}
