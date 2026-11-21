//! CELT pitch comb post-filter
//! ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
//!
//! After the inverse MDCT, each frame is filtered by a 5-tap comb at the decoded pitch period
//! with a decoded gain and tapset; when the setting changes between frames the first `OVERLAP`
//! samples cross-fade from the old filter output to the new one with the squared MDCT window.
//!
//! ```text
//!   y[i] = x[i] + G * ( g0 * x[i - T]
//!                      + g1 * (x[i - T - 1] + x[i - T + 1])
//!                      + g2 * (x[i - T - 2] + x[i - T + 2]) )
//!   cross-fade:  y[i] = x[i] + (1 - w[i]^2) * comb_old[i] + w[i]^2 * comb_new[i]
//! ```

use crate::celt::constant::{CELT_WINDOW, COMB_FILTER_GAINS};
use crate::celt::rate::PostFilterParams;
use crate::celt::{BlockSize, DECODE_BUFFER_SIZE, MIN_PITCH_PERIOD, OVERLAP, SHORT_MDCT_SIZE};
use crate::slices::array_chunks;

/// One channel of synthesis history: `DECODE_BUFFER_SIZE` past samples followed by the `OVERLAP`
/// samples of the pending MDCT overlap-add tail
/// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>)).
pub(crate) type ChannelHistory = [f32; DECODE_BUFFER_SIZE + OVERLAP];

/// Comb post-filter state carried across frames: the setting of the most recent frame and the
/// setting it cross-faded from over its first `OVERLAP` samples
/// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(crate) struct CombFilter {
    /// Pitch period, gain and tapset in force at the end of the most recent frame.
    pub(crate) current: PostFilterParams,
    /// Pitch period, gain and tapset the most recent frame cross-faded from.
    pub(crate) previous: PostFilterParams,
}

impl CombFilter {
    /// Returns the filter to its initial disabled state (zero period, gain and tapset)
    /// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
    pub(crate) fn reset(&mut self) {
        *self = Self::default();
        return;
    }

    /// The current setting with its period raised to the minimum comb period, which a lost
    /// frame keeps applying
    /// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
    pub(crate) fn held(&self) -> PostFilterParams {
        return PostFilterParams {
            period: self.current.period.max(MIN_PITCH_PERIOD),
            gain: self.current.gain,
            tapset: self.current.tapset,
        };
    }

    /// Filters the `n` newest samples of every channel in `history` in place and advances the
    /// state to `next`: the first short block cross-fades from `previous` to `current`, the rest
    /// of a long frame from `current` to `next`
    /// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
    pub(crate) fn apply(
        &mut self,
        history: &mut [ChannelHistory],
        n: usize,
        lm: BlockSize,
        next: PostFilterParams,
    ) {
        let out_offset = DECODE_BUFFER_SIZE - n;
        self.current.period = self.current.period.max(MIN_PITCH_PERIOD);
        self.previous.period = self.previous.period.max(MIN_PITCH_PERIOD);

        for channel in history.iter_mut() {
            filter_in_place(channel, out_offset, self.previous, self.current, SHORT_MDCT_SIZE);
            if lm.log2() != 0 {
                filter_in_place(
                    channel,
                    out_offset + SHORT_MDCT_SIZE,
                    self.current,
                    next,
                    n - SHORT_MDCT_SIZE,
                );
            }
        }

        self.previous = self.current;
        self.current = next;
        if lm.log2() != 0 {
            self.previous = self.current;
        }
        return;
    }

    /// Undoes the comb filter on the `OVERLAP` samples that follow a pitch-based concealment and
    /// folds them with the MDCT window, so the next decoded frame overlap-adds onto them
    /// ([RFC 6716 Section 4.3.7](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7>),
    /// [Section 4.4](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.4>)).
    pub(crate) fn prefilter_and_fold(&self, history: &mut [ChannelHistory], n: usize) {
        let history_offset = DECODE_BUFFER_SIZE - n;
        let mut etmp = [0.0_f32; OVERLAP];

        for channel in history.iter_mut() {
            comb_filter(
                &mut etmp,
                channel,
                history_offset,
                inverted(self.previous),
                inverted(self.current),
            );

            fold_overlap(&mut channel[history_offset..history_offset + OVERLAP / 2], &etmp);
        }
        return;
    }
}

/// The comb filter setting with its gain negated, which undoes a filter already applied
/// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
#[inline]
fn inverted(params: PostFilterParams) -> PostFilterParams {
    return PostFilterParams { gain: -params.gain, ..params };
}

/// SIMD chunk width for recursive in-place comb filtering. Because `MIN_PITCH_PERIOD` is `15`,
/// all five taps (`period - 2 ..= period + 2`) of `8` consecutive output samples lie strictly
/// inside the already-filtered prefix (`15 - 2 = 13 >= 8`).
const LANES: usize = 8;

/// Contiguous history window (`LANES + 4 = 12` samples) spanning all five taps across `LANES`
/// consecutive output samples.
const TAP_WINDOW: usize = LANES + 4;

const _: () = assert!(MIN_PITCH_PERIOD >= LANES + 2);

/// Tap weights of one comb filter setting: the gain times the tapset's three symmetric taps
/// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
#[derive(Debug, Clone, Copy, PartialEq)]
struct CombFilterTaps {
    /// Weight of `x[i - T]`.
    center: f32,
    /// Weight of `x[i - T - 1]` and `x[i - T + 1]`.
    first: f32,
    /// Weight of `x[i - T - 2]` and `x[i - T + 2]`.
    second: f32,
}

impl CombFilterTaps {
    /// Unscaled symmetric tap weights of `params.tapset`.
    #[inline]
    fn unscaled(params: PostFilterParams) -> Self {
        let [center, first, second] = COMB_FILTER_GAINS[params.tapset.min(2)];
        return Self { center, first, second };
    }

    /// Scales each tap weight by `gain`.
    #[inline]
    fn scaled(self, gain: f32) -> Self {
        return Self {
            center: gain * self.center,
            first: gain * self.first,
            second: gain * self.second,
        };
    }

    /// Tap weights of `params`, scaled by `weight` (the cross-fade factor, or `1`).
    #[inline]
    fn of(params: PostFilterParams, weight: f32) -> Self {
        return Self::unscaled(params).scaled(weight * params.gain);
    }

    /// Comb term of the taps centred on `x[p]`.
    #[inline]
    fn comb(&self, x: &[f32], p: usize) -> f32 {
        return self.center * x[p]
            + self.first * (x[p + 1] + x[p - 1])
            + self.second * (x[p + 2] + x[p - 2]);
    }

    /// Comb term of `lane` within a `TAP_WINDOW` slice starting at `pos - period - 2`.
    #[inline(always)]
    fn comb_lane(&self, taps: &[f32; TAP_WINDOW], lane: usize) -> f32 {
        return self.center * taps[lane + 2]
            + self.first * (taps[lane + 3] + taps[lane + 1])
            + self.second * (taps[lane + 4] + taps[lane]);
    }

    /// Adds the comb term of `lane` within `taps` onto `acc` in left-to-right tap order.
    #[inline(always)]
    fn accumulate_lane(&self, acc: f32, taps: &[f32; TAP_WINDOW], lane: usize) -> f32 {
        return acc
            + self.center * taps[lane + 2]
            + self.first * (taps[lane + 3] + taps[lane + 1])
            + self.second * (taps[lane + 4] + taps[lane]);
    }
}

/// Returns the `TAP_WINDOW` history samples starting at `past.len() - period - 2`.
#[inline(always)]
fn tap_window(past: &[f32], period: usize) -> Option<&[f32; TAP_WINDOW]> {
    let start = past.len().checked_sub(period + 2)?;
    return past.get(start..)?.first_chunk::<TAP_WINDOW>();
}

/// Pitch period of a comb filter setting, raised to [`MIN_PITCH_PERIOD`].
#[inline]
fn period_of(params: PostFilterParams) -> usize {
    return params.period.max(MIN_PITCH_PERIOD);
}

/// Applies the 5-tap comb post-filter recursively in place on
/// `signal_buf[history_offset..history_offset + n]`, cross-fading from `from` to `to` over the
/// first `OVERLAP` samples with the squared MDCT window
/// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
fn filter_in_place(
    signal_buf: &mut [f32],
    history_offset: usize,
    from: PostFilterParams,
    to: PostFilterParams,
    n: usize,
) {
    let (g0, g1) = (from.gain, to.gain);
    if g0 == 0.0 && g1 == 0.0 {
        return;
    }

    let period0 = period_of(from);
    let period1 = period_of(to);
    debug_assert!(history_offset >= period0 + 2);
    debug_assert!(history_offset >= period1 + 2);
    debug_assert!(signal_buf.len() >= history_offset + n);

    let signal_buf = &mut signal_buf[..history_offset + n];
    let old_unit = CombFilterTaps::unscaled(from);
    let new_unit = CombFilterTaps::unscaled(to);
    let new = new_unit.scaled(g1);

    let same_filter = g0 == g1 && period0 == period1 && from.tapset == to.tapset;
    let xfade_len = if same_filter { 0 } else { OVERLAP.min(n) };

    // Indexing (P): both loops filter 8 samples at a time and split the buffer at each block's
    // position so the lagged taps can be read while the block is written; this form compiles to
    // 8-lane SIMD (commit `759a5c3`). Callers pass `n` of 120 or `n - 120` and a cross-fade of 0
    // or 120 samples, all multiples of the 8 lanes, so no scalar tail is needed.
    debug_assert!(xfade_len % LANES == 0 && n % LANES == 0);
    let xfade_windows = array_chunks::<_, LANES>(&CELT_WINDOW[..xfade_len]).0;
    for (chunk_step, win) in xfade_windows.enumerate() {
        let pos = history_offset + chunk_step * LANES;
        let (past, rest) = signal_buf.split_at_mut(pos);
        let (Some(current), Some(taps0), Some(taps1)) =
            (rest.first_chunk_mut::<LANES>(), tap_window(past, period0), tap_window(past, period1))
        else {
            return;
        };
        for (lane, (sample, &w)) in current.iter_mut().zip(win.iter()).enumerate() {
            let f = w * w;
            let fading_out = old_unit.scaled((1.0_f32 - f) * g0);
            let fading_in = new_unit.scaled(f * g1);
            let out_comb = fading_out.comb_lane(taps0, lane);
            *sample = fading_in.accumulate_lane(*sample + out_comb, taps1, lane);
        }
    }
    if g1 == 0.0 {
        return;
    }

    for base in (xfade_len..n).step_by(LANES) {
        let pos = history_offset + base;
        let (past, rest) = signal_buf.split_at_mut(pos);
        let (Some(current), Some(taps1)) =
            (rest.first_chunk_mut::<LANES>(), tap_window(past, period1))
        else {
            return;
        };
        for (lane, sample) in current.iter_mut().enumerate() {
            *sample = new.accumulate_lane(*sample, taps1, lane);
        }
    }
    return;
}

/// Folds the post-filtered overlap `etmp` back over its first half with the window's time-domain
/// aliasing cancellation: `out[i] = w[i] * etmp[O - 1 - i] + w[O - 1 - i] * etmp[i]`
/// ([RFC 6716 Section 4.4](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.4>)).
fn fold_overlap(out: &mut [f32], etmp: &[f32; OVERLAP]) {
    let (window_rising, window_falling) = CELT_WINDOW.split_at(OVERLAP / 2);
    let windows = window_rising.iter().zip(window_falling.iter().rev());
    let samples = etmp.iter().zip(etmp.iter().rev());
    for (slot, ((&w_low, &w_high), (&e_low, &e_high))) in out.iter_mut().zip(windows.zip(samples)) {
        *slot = w_low * e_high + w_high * e_low;
    }
    return;
}

/// Applies the 5-tap symmetric pitch comb post-filter, reading from `x_buf` at `history_offset`
/// and writing `y_out.len()` filtered samples into `y_out`
/// ([RFC 6716 Section 4.3.7.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-4.3.7.1>)).
///
/// When `from` and `to` differ, the first `OVERLAP` samples cross-fade from the old filter
/// output to the new filter output with the squared MDCT window weight `w[i]^2`.
pub(crate) fn comb_filter(
    y_out: &mut [f32],
    x_buf: &[f32],
    history_offset: usize,
    from: PostFilterParams,
    to: PostFilterParams,
) {
    let n = y_out.len();
    debug_assert!(x_buf.len() >= history_offset + n);

    let (g0, g1) = (from.gain, to.gain);
    if g0 == 0.0 && g1 == 0.0 {
        y_out.copy_from_slice(&x_buf[history_offset..history_offset + n]);
        return;
    }

    let period0 = period_of(from);
    let period1 = period_of(to);
    debug_assert!(history_offset >= period0 + 2);
    debug_assert!(history_offset >= period1 + 2);

    let old = CombFilterTaps::of(from, 1.0);
    let new = CombFilterTaps::of(to, 1.0);

    let same_filter = g0 == g1 && period0 == period1 && from.tapset == to.tapset;
    let xfade_len = if same_filter { 0 } else { OVERLAP.min(n) };

    for (i, (y_slot, &w)) in y_out.iter_mut().zip(CELT_WINDOW.iter()).enumerate().take(xfade_len) {
        let pos = history_offset + i;
        let f = w * w;
        let old_comb = old.comb(x_buf, pos - period0);
        let new_comb = new.comb(x_buf, pos - period1);
        *y_slot = x_buf[pos] + (1.0 - f) * old_comb + f * new_comb;
    }

    if g1 == 0.0 {
        y_out[xfade_len..].copy_from_slice(&x_buf[history_offset + xfade_len..history_offset + n]);
        return;
    }

    for (i, y_slot) in y_out.iter_mut().enumerate().skip(xfade_len) {
        let pos = history_offset + i;
        *y_slot = x_buf[pos] + new.comb(x_buf, pos - period1);
    }
    return;
}

#[cfg(test)]
mod tests;
