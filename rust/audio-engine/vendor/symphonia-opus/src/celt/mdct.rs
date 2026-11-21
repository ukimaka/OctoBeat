//! CELT inverse MDCT with TDAC windowing and overlap-add
//! ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).

use std::sync::OnceLock;

use crate::celt::constant::{CELT_WINDOW, OVERLAP};
use crate::celt::fft::{Complex32, MixedRadixPlan};
use crate::celt::{BlockSize, MAX_FRAME_SIZE, MAX_LM, SHORT_MDCT_SIZE};
use crate::convert::{BoundedFrom, nearest_f32};
use crate::slices::{array_chunks, array_chunks_mut};

/// Maximum full-window MDCT length at 48 kHz (`2 * MAX_FRAME_SIZE = 1920` samples).
pub(crate) const MDCT_MAX_N: usize = 2 * MAX_FRAME_SIZE;

/// Maximum complex quarter-length IFFT size (`MDCT_MAX_N / 4 = 480` complex points).
pub(crate) const MDCT_MAX_N4: usize = MDCT_MAX_N / 4;

/// Precomputed trigonometric and bit-reversal tables for the 48 kHz CELT IMDCT (`shift in 0..=3`).
struct MdctTables {
    /// Forward 480-point FFT twiddles: `fft_twiddles[k] = exp(-j * 2 * pi * k / 480)`.
    fft_twiddles: [Complex32; MDCT_MAX_N4],
    /// Mixed-radix digit-reversal permutation tables for `n4 = 480, 240, 120, 60` (`shift = 0..=3`).
    bitrev: [[u16; MDCT_MAX_N4]; 4],
    /// MDCT pre/post-rotation cosine/sine twiddles for `shift = 0..=3`:
    /// `trig[shift][i] = Complex32::new(cos(theta), -sin(theta))` where
    /// `theta = 2 * pi * (i + 0.125) / n` and `n = 1920 >> shift`.
    trig: [[Complex32; MDCT_MAX_N4]; 4],
}

/// Initializes and returns the singleton [`MdctTables`] for 48 kHz CELT.
fn mdct_tables() -> &'static MdctTables {
    static TABLES: OnceLock<MdctTables> = OnceLock::new();
    return TABLES.get_or_init(|| {
        let fft_twiddles = std::array::from_fn(|k| {
            let phase = (-2.0 * std::f64::consts::PI * f64::from(u32::bounded_from(k)))
                / f64::from(u32::bounded_from(MDCT_MAX_N4));
            Complex32::new(nearest_f32(phase.cos()), nearest_f32(phase.sin()))
        });

        let mut bitrev = [[0u16; MDCT_MAX_N4]; 4];
        let mut trig = [[Complex32::default(); MDCT_MAX_N4]; 4];

        for shift in 0..4 {
            let n = MDCT_MAX_N >> shift;
            let n4 = n >> 2;
            MixedRadixPlan::for_shift(shift).digit_reversal(&mut bitrev[shift][..n4]);

            for (i, slot) in trig[shift][..n4].iter_mut().enumerate() {
                let angle =
                    (2.0 * std::f64::consts::PI * (f64::from(u32::bounded_from(i)) + 0.125))
                        / f64::from(u32::bounded_from(n));
                *slot = Complex32::new(nearest_f32(angle.cos()), nearest_f32(-angle.sin()));
            }
        }

        MdctTables { fft_twiddles, bitrev, trig }
    });
}

/// Computes one unwindowed CELT inverse MDCT block of `n2 = (MDCT_MAX_N >> shift) / 2` samples
/// into `out_unwindowed[..n2]`
/// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).
///
/// Dispatches `shift` (`0..=3`) to a const-generic `N4` kernel so `fft_buf` only zeroes `N4`
/// complex points (`480 B` on short transient blocks instead of `3,840 B`).
#[inline]
fn imdct_unwindowed(
    input: &[f32],
    out_unwindowed: &mut [f32],
    shift: usize,
    stride: usize,
    tables: &MdctTables,
) {
    debug_assert!(shift <= 3);
    match shift {
        0 => imdct_unwindowed_n4::<480>(input, out_unwindowed, 0, stride, tables),
        1 => imdct_unwindowed_n4::<240>(input, out_unwindowed, 1, stride, tables),
        2 => imdct_unwindowed_n4::<120>(input, out_unwindowed, 2, stride, tables),
        _ => imdct_unwindowed_n4::<60>(input, out_unwindowed, 3, stride, tables),
    }
    return;
}

/// Size-specialized quarter-length (`N4`) unwindowed inverse MDCT kernel.
fn imdct_unwindowed_n4<const N4: usize>(
    input: &[f32],
    out_unwindowed: &mut [f32],
    shift: usize,
    stride: usize,
    tables: &MdctTables,
) {
    let n2 = 2 * N4;
    debug_assert_eq!(MDCT_MAX_N4 >> shift, N4);
    debug_assert!(out_unwindowed.len() >= n2);
    debug_assert!(input.len() > (n2 - 1) * stride);

    let trig = &tables.trig[shift];
    let bitrev = &tables.bitrev[shift];

    // Step 1: Pre-rotate input frequency coefficients and scatter into the digit-reversed buffer.
    let mut fft_buf = [Complex32::default(); N4];
    pre_rotate::<N4>(input, stride, trig, bitrev, &mut fft_buf);

    // Step 2: Quarter-length (`N / 4`) mixed-radix complex FFT.
    MixedRadixPlan::for_shift(shift).execute(&mut fft_buf, &tables.fft_twiddles);

    // Step 3: Post-rotate and de-interleave into `out_unwindowed[..n2]`.
    post_rotate::<N4>(&fft_buf, trig, &mut out_unwindowed[..n2]);
    return;
}

/// Pre-rotates the `2 * N4` strided MDCT coefficients of `input` into the quarter-length
/// complex buffer `fft_buf`, scattered through the digit-reversal table `bitrev`.
///
/// Real and imaginary components are swapped (`Complex32::new(yi, yr)`) so that the forward
/// complex DFT of [`MixedRadixPlan::execute`] computes an unscaled inverse DFT.
#[inline]
fn pre_rotate<const N4: usize>(
    input: &[f32],
    stride: usize,
    trig: &[Complex32; MDCT_MAX_N4],
    bitrev: &[u16; MDCT_MAX_N4],
    fft_buf: &mut [Complex32; N4],
) {
    let n2 = 2 * N4;
    if stride == 1 {
        let coeffs = &input[..n2];
        for (((pair, rev_pair), &t), &rev) in array_chunks::<_, 2>(coeffs)
            .0
            .zip(array_chunks::<_, 2>(coeffs).0.rev())
            .zip(&trig[..N4])
            .zip(&bitrev[..N4])
        {
            let [x1, _] = *pair;
            let [_, x2] = *rev_pair;
            let yr = x2 * t.r + x1 * t.i;
            let yi = x1 * t.r - x2 * t.i;
            fft_buf[usize::from(rev)] = Complex32::new(yi, yr);
        }
        return;
    }

    let stride2 = 2 * stride;
    for (i, (&t, &rev)) in trig[..N4].iter().zip(&bitrev[..N4]).enumerate() {
        let x1 = input[i * stride2];
        let x2 = input[(n2 - 1 - 2 * i) * stride];
        let yr = x2 * t.r + x1 * t.i;
        let yi = x1 * t.r - x2 * t.i;
        fft_buf[usize::from(rev)] = Complex32::new(yi, yr);
    }
    return;
}

/// Post-rotates the transformed quarter-length buffer `fft_buf` and de-interleaves the
/// `2 * N4` time-domain samples into `out[..2 * N4]`.
#[inline]
fn post_rotate<const N4: usize>(
    fft_buf: &[Complex32; N4],
    trig: &[Complex32; MDCT_MAX_N4],
    out: &mut [f32],
) {
    let half_n4 = N4 / 2;
    let n2 = 2 * N4;
    debug_assert_eq!(half_n4 * 2, N4);

    let (fft_front, fft_back) = fft_buf.split_at(half_n4);
    let (trig_front, trig_back) = trig[..N4].split_at(half_n4);
    let (front_out, back_out) = out[..n2].split_at_mut(N4);

    for (((((&c0, &c1), &t0), &t1), front_pair), back_pair) in fft_front
        .iter()
        .zip(fft_back.iter().rev())
        .zip(trig_front.iter())
        .zip(trig_back.iter().rev())
        .zip(array_chunks_mut::<_, 2>(front_out))
        .zip(array_chunks_mut::<_, 2>(back_out).rev())
    {
        // Swap real/imag back from the forward-FFT conjugation trick: `re = c.i`, `im = c.r`.
        let re0 = c0.i;
        let im0 = c0.r;
        let re1 = c1.i;
        let im1 = c1.r;

        let yr0 = re0 * t0.r + im0 * t0.i;
        let yi0 = re0 * t0.i - im0 * t0.r;
        let yr1 = re1 * t1.r + im1 * t1.i;
        let yi1 = re1 * t1.i - im1 * t1.r;

        *front_pair = [yr0, yi1];
        *back_pair = [yr1, yi0];
    }
    return;
}

/// Applies the symmetric TDAC window to the overlap region `out[..OVERLAP]`.
///
/// On entry, `out[0 .. OVERLAP / 2]` holds the previous block's unwindowed tail and
/// `out[OVERLAP / 2 .. OVERLAP]` holds the newly synthesized leading half-overlap.
#[inline]
fn window_overlap_add(out: &mut [f32], window: &[f32; OVERLAP]) {
    let half_overlap = OVERLAP / 2;
    let (front, back) = out[..OVERLAP].split_at_mut(half_overlap);
    let (w_front, w_back) = window.split_at(half_overlap);

    for (((front_slot, back_slot), &w1), &w2) in
        front.iter_mut().zip(back.iter_mut().rev()).zip(w_front.iter()).zip(w_back.iter().rev())
    {
        let x1 = *back_slot;
        let x2 = *front_slot;
        *front_slot = x2 * w2 - x1 * w1;
        *back_slot = x2 * w1 + x1 * w2;
    }
    return;
}

/// Inverse-transforms one channel of a frame of block size `lm` into `out_syn` with overlap-add
/// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)):
/// one long MDCT, or in a transient frame `lm.blocks()` short MDCTs of [`SHORT_MDCT_SIZE`]
/// samples whose coefficients are interleaved in `freq`
/// ([Section 4.3.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.1>)).
///
/// `freq` holds the `N = 120 << lm` denormalised coefficients. `out_syn` starts at the frame in
/// the channel's synthesis history and holds at least `N + OVERLAP / 2` samples.
pub(crate) fn mdct_backward_frame(
    freq: &[f32],
    out_syn: &mut [f32],
    lm: BlockSize,
    is_transient: bool,
) {
    let (block, count) = if is_transient { (BlockSize::new(0), lm.blocks()) } else { (lm, 1) };
    let shift = MAX_LM - block.log2();
    let n2 = (MDCT_MAX_N >> shift) >> 1;
    let half_overlap = OVERLAP >> 1;
    let tables = mdct_tables();

    // Indexing (A): short block `i` reads every `count`-th coefficient from `freq[i]` and its
    // windowed output overlaps the next block's, so each block addresses its own offset.
    for i in 0..count {
        let out = &mut out_syn[(i * SHORT_MDCT_SIZE)..];
        imdct_unwindowed(
            &freq[i..],
            &mut out[half_overlap..half_overlap + n2],
            shift,
            count,
            tables,
        );
        window_overlap_add(&mut out[..OVERLAP], &CELT_WINDOW);
    }
    return;
}

/// Inverse-transforms a single mono MDCT spectrum `freq` into both `left_syn` and `right_syn`
/// with independent per-channel overlap-add
/// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).
///
/// Evaluates the unwindowed inverse MDCT once per block into `left_syn`, copies the `n2`
/// unwindowed samples into `right_syn`, and applies [`window_overlap_add`] separately so each
/// channel overlaps against its own prior 60-sample tail while sharing the newly synthesized
/// unwindowed tail across subsequent blocks (including transient short-block cascades).
pub(crate) fn mdct_backward_frame_dual(
    freq: &[f32],
    left_syn: &mut [f32],
    right_syn: &mut [f32],
    lm: BlockSize,
    is_transient: bool,
) {
    let (block, count) = if is_transient { (BlockSize::new(0), lm.blocks()) } else { (lm, 1) };
    let shift = MAX_LM - block.log2();
    let n2 = (MDCT_MAX_N >> shift) >> 1;
    let half_overlap = OVERLAP >> 1;
    let tables = mdct_tables();

    // Indexing (A): as in `mdct_backward_frame`, blocks interleave their coefficients and
    // overlap their outputs.
    for i in 0..count {
        let offset = i * SHORT_MDCT_SIZE;
        let left = &mut left_syn[offset..];
        let right = &mut right_syn[offset..];

        imdct_unwindowed(
            &freq[i..],
            &mut left[half_overlap..half_overlap + n2],
            shift,
            count,
            tables,
        );
        right[half_overlap..half_overlap + n2]
            .copy_from_slice(&left[half_overlap..half_overlap + n2]);

        window_overlap_add(&mut left[..OVERLAP], &CELT_WINDOW);
        window_overlap_add(&mut right[..OVERLAP], &CELT_WINDOW);
    }
    return;
}

#[cfg(test)]
pub(crate) mod tests;
