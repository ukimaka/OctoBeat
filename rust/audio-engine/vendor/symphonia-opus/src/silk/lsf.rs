//! SILK normalized line spectral frequency decoding
//! ([RFC 6716 Section 4.2.7.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5>)).
//!
//! Two-stage codebook decoding, backward prediction of the second-stage residual, inverse
//! weighting, minimum-spacing stabilization, and the interpolation of the first half of a
//! 20 ms frame. The per-bandwidth tables are grouped behind [`NlsfCodebook`]; the conversion to
//! LPC coefficients lives in [`crate::silk::lpc`].

use symphonia_core::errors::Result;

use crate::convert::{BoundedFrom, wrap_i16};
use crate::entropy::{self, Cdf};
use crate::fixed::sqrt_approx;
use crate::silk::constant;
use crate::silk::error::Error;
use crate::silk::lpc::nlsf_to_lpc_q12;
use crate::silk::{CodingReferences, Frame, MAX_LPC_ORDER, SignalType, SilkLayout};
use crate::slices::array_windows;
use crate::toc::{Bandwidth, FrameDuration};

/// Number of first-stage codebook vectors (RFC 6716 Section 4.2.7.5.1).
const NLSF_STAGE_ONE_VECTORS: usize = 32;

/// Offset turning a second-stage symbol (`0..=8`) into a residual index (`-4..=4`)
/// (RFC 6716 Section 4.2.7.5.2).
const NLSF_STAGE_TWO_INDEX_OFFSET: i16 = 4;

/// Residual index magnitude that is followed by an extension symbol (RFC 6716 Section 4.2.7.5.2).
const NLSF_STAGE_TWO_EXTENSION_MAGNITUDE: i16 = 4;

/// Left shift turning a residual index into a Q10 quantization level (RFC 6716 Section 4.2.7.5.2).
const NLSF_INDEX_TO_Q10_SHIFT: u32 = 10;

/// Right shift of the Q8 prediction weight times Q10 residual product (RFC 6716 Section 4.2.7.5.2).
const NLSF_PREDICTION_WEIGHT_Q8_SHIFT: u32 = 8;

/// Right shift of the Q10 level times Q16 quantization step product (RFC 6716 Section 4.2.7.5.2).
const NLSF_QUANTIZATION_STEP_Q16_SHIFT: u32 = 16;

/// Left shift turning a Q8 codebook entry into Q15 (RFC 6716 Section 4.2.7.5.3).
const NLSF_CODEBOOK_Q8_TO_Q15_SHIFT: u32 = 7;

/// Upper end of the Q8 codebook range, the neighbour of the last codebook entry
/// (RFC 6716 Section 4.2.7.5.3).
const NLSF_CODEBOOK_RANGE_Q8: i32 = 256;

/// Numerator of the inverse codebook spacing terms, `1024 / (cb1[k] - cb1[k - 1])`
/// (RFC 6716 Section 4.2.7.5.3).
const NLSF_WEIGHT_NUMERATOR: i32 = 1024;

/// Left shift turning the summed inverse spacings into Q18 (RFC 6716 Section 4.2.7.5.3).
const NLSF_WEIGHT_SUM_TO_Q18_SHIFT: u32 = 16;

/// Left shift of the Q10 residual before dividing by the Q9 weight to land in Q15
/// (RFC 6716 Section 4.2.7.5.3).
const NLSF_RESIDUAL_Q10_TO_Q24_SHIFT: u32 = 14;

/// Largest NLSF value in Q15 (RFC 6716 Section 4.2.7.5.3).
const NLSF_MAX_Q15: i32 = i16::MAX as i32;

/// Upper bound of the NLSF range in Q15, `1.0` (RFC 6716 Section 4.2.7.5.4).
const NLSF_RANGE_Q15: i32 = 1 << 15;

/// Stabilization rounds before falling back to sorting (RFC 6716 Section 4.2.7.5.4).
const MAX_STABILIZATION_ITERATIONS: usize = 20;

/// Interpolation weight that reproduces the current frame NLSFs, `1.0` in Q2
/// (RFC 6716 Section 4.2.7.5.5).
const NLSF_INTERPOLATION_FULL_Q2: u8 = 4;

/// Fraction bits of the interpolation weight (RFC 6716 Section 4.2.7.5.5).
const NLSF_INTERPOLATION_Q2_SHIFT: u32 = 2;

/// Number of subframes sharing the interpolated first-half NLSFs (RFC 6716 Section 4.2.7.5.5).
const NLSF_FIRST_HALF_SUBFRAMES: usize = 2;

/// Converts a fixed-width codebook matrix into an array of row slices in `const` context
/// (MSRV 1.85 compatible).
const fn slice_rows<T, const COLS: usize, const ROWS: usize>(
    table: &'static [[T; COLS]; ROWS],
) -> [&'static [T]; ROWS] {
    let mut out: [&'static [T]; ROWS] = [&[]; ROWS];
    let mut i = 0;
    while i < ROWS {
        out[i] = &table[i];
        i += 1;
    }
    return out;
}

/// Compile-time validated codebook tables and parameters for one NLSF bandwidth family
/// ([RFC 6716 Section 4.2.7.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5>)).
struct NlsfSpec {
    order: usize,
    /// Stage-1 vector index CDFs indexed `[usize::from(voiced)]`.
    stage_one_cdfs: [Cdf<'static>; 2],
    /// `32` Q8 stage-1 codebook vectors of length `order`.
    stage_one_q8: [&'static [u8]; NLSF_STAGE_ONE_VECTORS],
    /// `32` stage-2 CDF selector rows of length `order`.
    stage_two_selectors: [&'static [u8]; NLSF_STAGE_ONE_VECTORS],
    /// `32` backward-prediction weight selector rows of length `order - 1`.
    prediction_weight_selectors: [&'static [u8]; NLSF_STAGE_ONE_VECTORS],
    /// Two rows of `order - 1` Q8 backward-prediction weights.
    prediction_weights: [&'static [u16]; 2],
    quantization_step_q16: i32,
    /// Minimum Q15 spacing between consecutive NLSFs (`order + 1` entries).
    min_spacing_q15: &'static [i32],
}

impl NlsfSpec {
    /// Checks every symbol count and row width at compile time so runtime lookups cannot go out
    /// of bounds.
    const fn validated(self) -> Self {
        assert!(self.order > 1 && self.order <= MAX_LPC_ORDER);
        assert!(self.stage_one_cdfs[0].symbols() == NLSF_STAGE_ONE_VECTORS);
        assert!(self.stage_one_cdfs[1].symbols() == NLSF_STAGE_ONE_VECTORS);
        assert!(self.prediction_weights[0].len() == self.order - 1);
        assert!(self.prediction_weights[1].len() == self.order - 1);
        assert!(self.min_spacing_q15.len() == self.order + 1);
        let mut i = 0;
        while i < NLSF_STAGE_ONE_VECTORS {
            assert!(self.stage_one_q8[i].len() == self.order);
            assert!(self.stage_two_selectors[i].len() == self.order);
            assert!(self.prediction_weight_selectors[i].len() == self.order - 1);
            i += 1;
        }
        return self;
    }
}

/// Codebook descriptors indexed by [`NlsfCodebook`].
static NLSF_SPECS: [NlsfSpec; 2] = [
    NlsfSpec {
        order: 10,
        stage_one_cdfs: [
            constant::CDF_NORMALIZED_LSF_STAGE_ONE_INDEX_NARROWBAND_OR_MEDIUMBAND_UNVOICED,
            constant::CDF_NORMALIZED_LSF_STAGE_ONE_INDEX_NARROWBAND_OR_MEDIUMBAND_VOICED,
        ],
        stage_one_q8: slice_rows(
            &constant::CODEBOOK_NORMALIZED_LSF_STAGE_ONE_NARROWBAND_OR_MEDIUMBAND,
        ),
        stage_two_selectors: slice_rows(
            &constant::CODEBOOK_NORMALIZED_LSF_STAGE_TWO_INDEX_NARROWBAND_OR_MEDIUMBAND,
        ),
        prediction_weight_selectors: slice_rows(&constant::PREDICTION_WEIGHT_SELECTION_NB_MB),
        prediction_weights: [
            &constant::PREDICTION_WEIGHTS_NB_MB[0],
            &constant::PREDICTION_WEIGHTS_NB_MB[1],
        ],
        quantization_step_q16: constant::LSF_STAGE_TWO_QUANTIZATION_STEP_Q16_NB_MB,
        min_spacing_q15: &constant::MINIMUM_SPACING_NORMALIZED_LSF_NARROWBAND_MEDIUMBAND,
    }
    .validated(),
    NlsfSpec {
        order: 16,
        stage_one_cdfs: [
            constant::CDF_NORMALIZED_LSF_STAGE_ONE_INDEX_WIDEBAND_UNVOICED,
            constant::CDF_NORMALIZED_LSF_STAGE_ONE_INDEX_WIDEBAND_VOICED,
        ],
        stage_one_q8: slice_rows(&constant::CODEBOOK_NORMALIZED_LSF_STAGE_ONE_WIDEBAND),
        stage_two_selectors: slice_rows(
            &constant::CODEBOOK_NORMALIZED_LSF_STAGE_TWO_INDEX_WIDEBAND,
        ),
        prediction_weight_selectors: slice_rows(&constant::PREDICTION_WEIGHT_SELECTION_WB),
        prediction_weights: [
            &constant::PREDICTION_WEIGHTS_WB[0],
            &constant::PREDICTION_WEIGHTS_WB[1],
        ],
        quantization_step_q16: constant::LSF_STAGE_TWO_QUANTIZATION_STEP_Q16_WB,
        min_spacing_q15: &constant::MINIMUM_SPACING_NORMALIZED_LSF_WB,
    }
    .validated(),
];

/// The NLSF codebook family of a bandwidth: the 10-coefficient narrowband and mediumband tables
/// or the 16-coefficient wideband tables
/// ([RFC 6716 Section 4.2.7.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5>)).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum NlsfCodebook {
    /// Order 10 codebooks shared by narrowband and mediumband frames.
    NarrowbandMediumband = 0,
    /// Order 16 codebooks of wideband frames.
    Wideband = 1,
}

impl NlsfCodebook {
    /// Codebook family used at `bandwidth`.
    const fn for_bandwidth(bandwidth: Bandwidth) -> Self {
        return match bandwidth {
            Bandwidth::Narrowband | Bandwidth::MediumBand => Self::NarrowbandMediumband,
            Bandwidth::Wideband | Bandwidth::SuperWideband | Bandwidth::Fullband => Self::Wideband,
        };
    }

    /// Descriptor row of `self` in [`NLSF_SPECS`].
    #[inline]
    const fn spec(self) -> &'static NlsfSpec {
        return &NLSF_SPECS[self as usize];
    }

    /// Number of NLSF coefficients, the LPC order (RFC 6716 Section 4.2.7.5).
    const fn order(self) -> usize {
        return self.spec().order;
    }

    /// First-stage vector index CDF for `signal_type` (RFC 6716 Section 4.2.7.5.1).
    fn stage_one_cdf(self, signal_type: SignalType) -> Cdf<'static> {
        return self.spec().stage_one_cdfs[usize::from(signal_type == SignalType::Voiced)];
    }

    /// First-stage codebook vector `i1` in Q8 (RFC 6716 Section 4.2.7.5.1).
    fn stage_one_vector_q8(self, i1: usize) -> &'static [u8] {
        return self.spec().stage_one_q8[i1];
    }

    /// Per-coefficient second-stage CDF selectors of first-stage vector `i1`
    /// (RFC 6716 Section 4.2.7.5.2).
    fn stage_two_cdf_selectors(self, i1: usize) -> &'static [u8] {
        return self.spec().stage_two_selectors[i1];
    }

    /// Q8 backward prediction weight of coefficient `i` for first-stage vector `i1`
    /// (RFC 6716 Section 4.2.7.5.2).
    fn prediction_weight_q8(self, i1: usize, i: usize) -> i32 {
        let spec = self.spec();
        let selector = usize::from(spec.prediction_weight_selectors[i1][i]);
        return i32::from(spec.prediction_weights[selector][i]);
    }

    /// Second-stage quantization step in Q16 (RFC 6716 Section 4.2.7.5.2).
    const fn quantization_step_q16(self) -> i32 {
        return self.spec().quantization_step_q16;
    }

    /// Minimum spacing between consecutive NLSFs in Q15, `order + 1` entries including both
    /// range ends (RFC 6716 Section 4.2.7.5.4).
    const fn min_spacing_q15(self) -> &'static [i32] {
        return self.spec().min_spacing_q15;
    }
}

impl CodingReferences {
    /// Decodes the NLSFs of `frame`, interpolates the first half of a 20 ms frame against the
    /// previous frame when signalled, and stores the Q12 LPC coefficients of every subframe
    /// ([RFC 6716 Section 4.2.7.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5>)).
    pub(crate) fn decode_lsf(
        &mut self,
        decoder: &mut entropy::Decoder<'_>,
        frame: &mut Frame,
        layout: &SilkLayout,
    ) -> Result<()> {
        let codebook = NlsfCodebook::for_bandwidth(layout.bandwidth);
        let order = codebook.order();

        let i1 = decode_lsf_stage1(decoder, codebook, frame.frame_type.signal_type)?;
        let indices = decode_lsf_stage2_indices(decoder, codebook, i1)?;
        let res_q10 = dequantize_lsf_residual_q10(codebook, i1, &indices);
        let mut nlsf_q15 = reconstruct_nlsf_q15(codebook, i1, &res_q10);
        stabilize_nlsf(&mut nlsf_q15[..order], codebook)?;
        let a1_q12 = nlsf_to_lpc_q12(&nlsf_q15[..order])?;

        let w_q2 = self.decode_interpolation_weight(decoder, frame, layout)?;
        let interpolate = w_q2 < NLSF_INTERPOLATION_FULL_Q2 && frame.num_subframes == 4;
        let (nlsf0_q15, a0_q12) = interpolate
            .then(|| {
                let nlsf0_q15 = interpolate_nlsf_q15(&self.prev_nlsf_q15, &nlsf_q15, order, w_q2);
                nlsf_to_lpc_q12(&nlsf0_q15[..order]).map(|a0_q12| (nlsf0_q15, a0_q12))
            })
            .transpose()?
            .unwrap_or((nlsf_q15, a1_q12));

        for (k, subframe) in frame.active_subframes_mut().iter_mut().enumerate() {
            let first_half = k < NLSF_FIRST_HALF_SUBFRAMES;
            (subframe.nlsf_q15, subframe.lpc_coeffs_q12) =
                if first_half { (nlsf0_q15, a0_q12) } else { (nlsf_q15, a1_q12) };
        }

        self.prev_nlsf_q15 = nlsf_q15;
        return Ok(());
    }

    /// Decodes the Q2 interpolation weight of a 20 ms frame, forced to `1.0` on the first frame
    /// after a reset; 10 ms frames carry none
    /// ([RFC 6716 Section 4.2.7.5.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.5>)).
    fn decode_interpolation_weight(
        &self,
        decoder: &mut entropy::Decoder<'_>,
        frame: &mut Frame,
        layout: &SilkLayout,
    ) -> Result<u8> {
        if layout.frame_duration != FrameDuration::Ms20 {
            frame.lsf_interpolation_index = None;
            return Ok(NLSF_INTERPOLATION_FULL_Q2);
        }

        let coded_w_q2 = decoder.decode_symbol(constant::CDF_NORMALIZED_LSF_INTERPOLATION_INDEX)?;
        let w_q2 =
            if self.first_frame_after_reset { NLSF_INTERPOLATION_FULL_Q2 } else { coded_w_q2 };
        frame.lsf_interpolation_index = Some(w_q2);
        return Ok(w_q2);
    }
}

/// Decodes the first-stage codebook vector index
/// ([RFC 6716 Section 4.2.7.5.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.1>)).
fn decode_lsf_stage1(
    decoder: &mut entropy::Decoder<'_>,
    codebook: NlsfCodebook,
    signal_type: SignalType,
) -> Result<usize> {
    return Ok(usize::from(decoder.decode_symbol(codebook.stage_one_cdf(signal_type))?));
}

/// Decodes the second-stage residual index of every coefficient, including the extension of
/// indices at the ends of the range
/// ([RFC 6716 Section 4.2.7.5.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.2>)).
fn decode_lsf_stage2_indices(
    decoder: &mut entropy::Decoder<'_>,
    codebook: NlsfCodebook,
    i1: usize,
) -> Result<[i16; MAX_LPC_ORDER]> {
    let mut indices = [0i16; MAX_LPC_ORDER];
    for (index, &selector) in indices.iter_mut().zip(codebook.stage_two_cdf_selectors(i1).iter()) {
        let cdf = constant::CDF_NORMALIZED_LSF_STAGE_TWO_INDEX[usize::from(selector)];
        let mut value = i16::from(decoder.decode_symbol(cdf)?) - NLSF_STAGE_TWO_INDEX_OFFSET;
        if value.abs() == NLSF_STAGE_TWO_EXTENSION_MAGNITUDE {
            let extension = i16::from(
                decoder.decode_symbol(constant::CDF_NORMALIZED_LSF_STAGE_TWO_INDEX_EXTENSION)?,
            );
            value += if value < 0 { -extension } else { extension };
        }
        *index = value;
    }
    return Ok(indices);
}

/// Dequantizes the second-stage residual indices into Q10 residuals with backward prediction
/// from the next higher coefficient
/// ([RFC 6716 Section 4.2.7.5.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.2>)).
fn dequantize_lsf_residual_q10(
    codebook: NlsfCodebook,
    i1: usize,
    indices: &[i16; MAX_LPC_ORDER],
) -> [i16; MAX_LPC_ORDER] {
    let order = codebook.order();
    let qstep_q16 = i64::from(codebook.quantization_step_q16());
    let mut res_q10 = [0i16; MAX_LPC_ORDER];
    // Residual of the next higher coefficient; the highest coefficient has no predictor.
    let mut next_q10: Option<i16> = None;
    for (i, (res, &index)) in res_q10[..order].iter_mut().zip(indices).enumerate().rev() {
        let pred_q10 = next_q10.map_or(0, |next_q10| {
            (i32::from(next_q10) * codebook.prediction_weight_q8(i1, i))
                >> NLSF_PREDICTION_WEIGHT_Q8_SHIFT
        });
        // A Q10 level of at most about 10 << 10 times a step below 2^14 stays far inside `i32`.
        let step_q10 = i32::bounded_from(
            (i64::from(quantization_level_q10(index)) * qstep_q16)
                >> NLSF_QUANTIZATION_STEP_Q16_SHIFT,
        );
        *res = wrap_i16(pred_q10 + step_q10);
        next_q10 = Some(*res);
    }
    return res_q10;
}

/// Q10 quantization level of a residual index, pulled towards zero by the level offset
/// ([RFC 6716 Section 4.2.7.5.2](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.2>)).
#[inline]
fn quantization_level_q10(index: i16) -> i32 {
    let index = i32::from(index);
    return match index.cmp(&0) {
        std::cmp::Ordering::Greater => {
            (index << NLSF_INDEX_TO_Q10_SHIFT)
                - constant::LSF_STAGE_TWO_QUANTIZATION_LEVEL_OFFSET_Q10
        }
        std::cmp::Ordering::Less => {
            (index << NLSF_INDEX_TO_Q10_SHIFT)
                + constant::LSF_STAGE_TWO_QUANTIZATION_LEVEL_OFFSET_Q10
        }
        std::cmp::Ordering::Equal => 0,
    };
}

/// Adds the inversely weighted residuals to the first-stage vector and clamps the result to
/// the Q15 NLSF range
/// ([RFC 6716 Section 4.2.7.5.3](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.3>)).
fn reconstruct_nlsf_q15(
    codebook: NlsfCodebook,
    i1: usize,
    res_q10: &[i16; MAX_LPC_ORDER],
) -> [i16; MAX_LPC_ORDER] {
    let cb1_q8 = codebook.stage_one_vector_q8(i1);
    let neighbours = with_neighbours(cb1_q8, 0, NLSF_CODEBOOK_RANGE_Q8);
    let mut nlsf_q15 = [0i16; MAX_LPC_ORDER];
    let windows = array_windows::<_, 3>(&neighbours).take(cb1_q8.len());
    for ((nlsf, &[cb1_prev, cb1_cur, cb1_next]), &res) in
        nlsf_q15.iter_mut().zip(windows).zip(res_q10)
    {
        let w_q9 = inverse_spacing_weight_q9(cb1_prev, cb1_cur, cb1_next);
        let weighted_residual_q15 = (i32::from(res) << NLSF_RESIDUAL_Q10_TO_Q24_SHIFT) / w_q9;
        let unclamped_q15 = (cb1_cur << NLSF_CODEBOOK_Q8_TO_Q15_SHIFT) + weighted_residual_q15;
        *nlsf = i16::bounded_from(unclamped_q15.clamp(0, NLSF_MAX_Q15));
    }
    return nlsf_q15;
}

/// `values` widened to `i32` between `low` and `high`: the first `values.len() + 2` entries are
/// `[low, values..., high]`, so that a window of three gives every value both neighbours.
fn with_neighbours<T: Copy + Into<i32>>(
    values: &[T],
    low: i32,
    high: i32,
) -> [i32; MAX_LPC_ORDER + 2] {
    let mut padded = [high; MAX_LPC_ORDER + 2];
    padded[0] = low;
    for (slot, &value) in padded[1..].iter_mut().zip(values) {
        *slot = value.into();
    }
    return padded;
}

/// Q9 weight of a codebook entry, the square root of the summed inverse distances to its
/// neighbours, approximated from the leading bit position and the next seven bits
/// ([RFC 6716 Section 4.2.7.5.3](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.3>)).
#[inline]
fn inverse_spacing_weight_q9(prev_q8: i32, cur_q8: i32, next_q8: i32) -> i32 {
    let diff_prev = (cur_q8 - prev_q8).max(1);
    let diff_next = (next_q8 - cur_q8).max(1);
    let w2_q18 = ((NLSF_WEIGHT_NUMERATOR / diff_prev) + (NLSF_WEIGHT_NUMERATOR / diff_next))
        << NLSF_WEIGHT_SUM_TO_Q18_SHIFT;

    return sqrt_approx(w2_q18).max(1);
}

/// Enforces the minimum spacing between consecutive NLSFs, first by moving the closest pair
/// apart for up to 20 rounds, then by sorting and clamping
/// ([RFC 6716 Section 4.2.7.5.4](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.4>)).
fn stabilize_nlsf(nlsf_q15: &mut [i16], codebook: NlsfCodebook) -> Result<()> {
    let order = nlsf_q15.len();
    let min_delta = codebook.min_spacing_q15();
    if order == 0 || min_delta.len() < order + 1 {
        return Err(Error::InvalidLSFCoefficients.into());
    }

    for _ in 0..MAX_STABILIZATION_ITERATIONS {
        let (min_diff, i) = smallest_spacing_margin(nlsf_q15, min_delta);
        if min_diff >= 0 {
            return Ok(());
        }
        widen_spacing_at(nlsf_q15, min_delta, i);
    }

    enforce_spacing_by_sorting(nlsf_q15, min_delta);
    return Ok(());
}

/// Smallest margin above the minimum spacing over all gaps, including the gaps to both range
/// ends, and the index of the gap (RFC 6716 Section 4.2.7.5.4).
fn smallest_spacing_margin(nlsf_q15: &[i16], min_delta: &[i32]) -> (i32, usize) {
    let edges = with_neighbours(nlsf_q15, 0, NLSF_RANGE_Q15);
    let gaps = array_windows::<_, 2>(&edges).zip(min_delta).take(nlsf_q15.len() + 1);
    // The first smallest margin wins, as in the RFC's ascending search.
    return gaps.enumerate().fold(
        (i32::MAX, 0),
        |(best_diff, best_i), (i, (&[lower, upper], &delta))| {
            let diff = upper - (lower + delta);
            match diff < best_diff {
                true => (diff, i),
                false => (best_diff, best_i),
            }
        },
    );
}

/// Moves the two NLSFs around gap `i` apart to the minimum spacing, around their centre when
/// both exist and against the range end otherwise (RFC 6716 Section 4.2.7.5.4).
fn widen_spacing_at(nlsf_q15: &mut [i16], min_delta: &[i32], i: usize) {
    let order = nlsf_q15.len();
    match i {
        0 => {
            nlsf_q15[0] = i16::bounded_from(min_delta[0]);
        }
        i if i == order => {
            nlsf_q15[order - 1] = i16::bounded_from(NLSF_RANGE_Q15 - min_delta[order]);
        }
        i => {
            let min_center_q15: i32 = min_delta[0..i].iter().sum::<i32>() + (min_delta[i] >> 1);
            let max_center_q15: i32 = NLSF_RANGE_Q15
                - min_delta[(i + 1)..=order].iter().sum::<i32>()
                - (min_delta[i] - (min_delta[i] >> 1));

            let raw_center = (i32::from(nlsf_q15[i - 1]) + i32::from(nlsf_q15[i]) + 1) >> 1;
            let center_freq_q15 = raw_center.clamp(min_center_q15, max_center_q15);

            // The clamped centre keeps both NLSFs inside `0..2^15`.
            nlsf_q15[i - 1] = i16::bounded_from(center_freq_q15 - (min_delta[i] >> 1));
            nlsf_q15[i] = i16::bounded_from(i32::from(nlsf_q15[i - 1]) + min_delta[i]);
        }
    }
}

/// Fallback stabilization: sorts the NLSFs, then pushes each one up to the minimum spacing
/// above its predecessor and down to the minimum spacing below its successor
/// (RFC 6716 Section 4.2.7.5.4; the lower bound saturates instead of wrapping,
/// [RFC 8251 Section 7](<https://datatracker.ietf.org/doc/html/rfc8251#section-7>)).
fn enforce_spacing_by_sorting(nlsf_q15: &mut [i16], min_delta: &[i32]) {
    nlsf_q15.sort_unstable();
    let mut prev = 0;
    for (nlsf, &delta) in nlsf_q15.iter_mut().zip(min_delta) {
        let lower_q15 = (prev + delta).clamp(i32::from(i16::MIN), i32::from(i16::MAX));
        *nlsf = i16::bounded_from(i32::from(*nlsf).max(lower_q15));
        prev = i32::from(*nlsf);
    }
    // The upper bound is stored with the reference decoder's 16-bit narrowing.
    let mut next = NLSF_RANGE_Q15;
    for (nlsf, &delta) in nlsf_q15.iter_mut().zip(&min_delta[1..]).rev() {
        *nlsf = wrap_i16(i32::from(*nlsf).min(next - delta));
        next = i32::from(*nlsf);
    }
    return;
}

/// Interpolates the previous and current NLSFs with the Q2 weight for the first half of a
/// 20 ms frame ([RFC 6716 Section 4.2.7.5.5](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.2.7.5.5>)).
fn interpolate_nlsf_q15(
    prev_nlsf_q15: &[i16; MAX_LPC_ORDER],
    nlsf_q15: &[i16; MAX_LPC_ORDER],
    order: usize,
    w_q2: u8,
) -> [i16; MAX_LPC_ORDER] {
    let mut interpolated = [0i16; MAX_LPC_ORDER];
    let pairs = prev_nlsf_q15.iter().zip(nlsf_q15).take(order);
    for (slot, (&prev, &curr)) in interpolated.iter_mut().zip(pairs) {
        let (prev, curr) = (i32::from(prev), i32::from(curr));
        // A weight of at most 1 keeps the result between `prev` and `curr`.
        *slot = i16::bounded_from(
            prev + (((curr - prev) * i32::from(w_q2)) >> NLSF_INTERPOLATION_Q2_SHIFT),
        );
    }
    return interpolated;
}

#[cfg(test)]
mod tests {
    // Fixtures: packets and expected values recorded from libopus 1.6.1. The behaviour they pin is
    // normative (RFC 6716 Section 4.2.7.5) and is verified against the RFC 8251 test vectors by
    // `tests/rfc6716_conformance.rs`.
    use super::*;

    #[test]
    fn nlsf_stages_backward_prediction_and_stabilization_match_recorded_values() {
        // Range-coded symbols and the values they decode to:
        // Stage-2 symbols for i1 = 0 with extensions (+6 at k=8, -5 at k=9):
        const LSF_STAGE2_NB_EXT_BYTES: [u8; 3] = [0xb6, 0x6e, 0x3b];
        const EXPECTED_NLSF_Q15_NB: [i16; 10] =
            [1547, 4508, 7814, 10871, 14261, 17641, 21363, 25184, 26336, 26339];

        let codebook = NlsfCodebook::NarrowbandMediumband;
        let mut dec_nb = entropy::Decoder::new(&LSF_STAGE2_NB_EXT_BYTES);
        let indices = decode_lsf_stage2_indices(&mut dec_nb, codebook, 0).unwrap();
        let res_q10_nb = dequantize_lsf_residual_q10(codebook, 0, &indices);
        assert_eq!(codebook.order(), 10);
        assert_eq!(res_q10_nb[9], -904);
        assert_eq!(res_q10_nb[8], 511);

        let mut nlsf_nb = reconstruct_nlsf_q15(codebook, 0, &res_q10_nb);
        stabilize_nlsf(&mut nlsf_nb[..10], codebook).unwrap();
        assert_eq!(&nlsf_nb[..10], &EXPECTED_NLSF_Q15_NB);

        // Test WB (16 coefficients) stabilization with pathological disordered input
        let mut pathological_wb =
            [32760, 10, 32700, 5, 20000, 100, 50, 40, 30, 20, 15, 12, 8, 4, 2, 0];
        stabilize_nlsf(&mut pathological_wb, NlsfCodebook::Wideband).unwrap();
        let min_delta_wb = &constant::MINIMUM_SPACING_NORMALIZED_LSF_WB;
        let edges = with_neighbours(&pathological_wb, 0, NLSF_RANGE_Q15);
        let gaps = array_windows::<_, 2>(&edges).zip(min_delta_wb);
        for (i, (&[lower, upper], &delta)) in gaps.enumerate() {
            assert!(upper - lower >= delta, "WB NLSF spacing violated at gap {i}");
        }
    }

    /// RFC 8251 Section 7: enforcing the minimum NLSF spacing saturates at the Q15 ceiling and never
    /// wraps, so a vector pinned at `i16::MAX` must stabilise to a non-negative strictly increasing one.
    #[test]
    fn nlsf_stabilization_saturates_at_the_q15_ceiling() {
        let mut saturated_wb = [i16::MAX; 16];
        stabilize_nlsf(&mut saturated_wb, NlsfCodebook::Wideband).unwrap();
        assert!(saturated_wb.iter().all(|&v| v >= 0));
        assert!(saturated_wb.windows(2).all(|w| w[0] < w[1]));

        let mut saturated_nb = [i16::MAX; 10];
        stabilize_nlsf(&mut saturated_nb, NlsfCodebook::NarrowbandMediumband).unwrap();
        assert!(saturated_nb.iter().all(|&v| v >= 0));
        assert!(saturated_nb.windows(2).all(|w| w[0] < w[1]));
        return;
    }

    #[test]
    fn nlsf_four_subframe_interpolation_matches_recorded_values() {
        // Range-coded symbols and the values they decode to:
        const LSF_INTERP_TWO_FRAMES_BYTES: [u8; 4] = [0x13, 0x8d, 0x29, 0x80];
        const EXPECTED_F0_NLSF_Q15: [i16; 10] =
            [1536, 4480, 7680, 10624, 13824, 16896, 20096, 23040, 26368, 29184];
        const EXPECTED_F1_NLSF_Q15: [i16; 10] =
            [3840, 6272, 9600, 12416, 15488, 18176, 21120, 23808, 26752, 29312];

        let layout = SilkLayout::new(Bandwidth::Narrowband, FrameDuration::Ms20).unwrap();
        let mut state = CodingReferences::new();
        let mut dec = entropy::Decoder::new(&LSF_INTERP_TWO_FRAMES_BYTES);

        let mut frame0 = Frame::new(160, 4, 10);
        state.decode_lsf(&mut dec, &mut frame0, &layout).unwrap();
        state.first_frame_after_reset = false;

        assert_eq!(frame0.lsf_interpolation_index, Some(4));
        for sf in frame0.active_subframes() {
            assert_eq!(sf.nlsf_q15[..10], EXPECTED_F0_NLSF_Q15);
        }

        let mut frame1 = Frame::new(160, 4, 10);
        state.decode_lsf(&mut dec, &mut frame1, &layout).unwrap();

        assert_eq!(frame1.lsf_interpolation_index, Some(2));
        assert_eq!(frame1.subframes[2].nlsf_q15[..10], EXPECTED_F1_NLSF_Q15);
        assert_eq!(frame1.subframes[3].nlsf_q15[..10], EXPECTED_F1_NLSF_Q15);

        // Weight 2 of 4: halfway between the two frames.
        let expected: [i16; 10] = std::array::from_fn(|i| {
            let (f0, f1) = (i32::from(EXPECTED_F0_NLSF_Q15[i]), i32::from(EXPECTED_F1_NLSF_Q15[i]));
            i16::bounded_from(f0 + (((f1 - f0) * 2) >> 2))
        });
        assert_eq!(frame1.subframes[0].nlsf_q15[..10], expected);
        assert_eq!(frame1.subframes[1].nlsf_q15[..10], expected);
    }
}
