//! Decoder conformance against the RFC 6716 / RFC 8251 test vectors.
//!
//! [RFC 6716 Section 6](<https://datatracker.ietf.org/doc/html/rfc6716#section-6>) defines
//! compliance through the reference decoder of Appendix A, for every test vector and for every
//! supported output sampling rate and channel count:
//!
//! - a compliant decoder MUST have the same final range decoder state as the reference decoder:
//!   `opus_demo -d` compares the decoder final range with the encoder final range stored for every
//!   packet and stops with "Range coder state mismatch between encoder and decoder";
//! - its output MUST be within the threshold of the `opus_compare.c` tool when compared with the
//!   reference output
//!   ([RFC 6716 Section 6.1](<https://datatracker.ietf.org/doc/html/rfc6716#section-6.1>)):
//!   quality 0 is the passing threshold, 100 means identical output, and a quality above 90 is
//!   RECOMMENDED at 48 kHz. Bit-exact output is not required.
//!
//! RFC 6716 Section 6.1 decodes every vector as `opus_demo -d <rate> <channels> testvectorX.bit
//! testX.out`, "where `<rate>` is the sampling rate and can be 8000, 12000, 16000, 24000, or
//! 48000, and `<channels>` is 1 for mono or 2 for stereo", and compares the output of every rate
//! with the same 48 kHz reference decode, `opus_compare [-s] -r <rate> testvectorX.dec testX.out`:
//! "For other sampling rates, it is normal for the quality metric to be lower (typically, as low
//! as 50 even for a good implementation) because of harmless mismatch with the delay and phase of
//! the internal sampling rate conversion." The `run_vectors.sh <exec path> <vector path> <rate>`
//! script of Appendix A runs the twelve vectors in mono and stereo for one rate; the tests below
//! do the same for each of the five rates.
//!
//! [RFC 8251 Section 11](<https://datatracker.ietf.org/doc/html/rfc8251#section-11>) updates the
//! vectors with two decoded outputs per bitstream: `testvectorNN.dec` applies the CELT 180-degree
//! phase shift allowed by RFC 8251 Section 10 and `testvectorNNm.dec` does not. An implementation
//! passes when its output passes against either set.
//!
//! The vectors are not part of the repository. The tests are ignored by default and read the
//! vector directory from `OPUS_TESTVECTORS_DIR` (and optional `opus_demo -d` reference outputs
//! `ref_<vector>_<rate>_<layout>.pcm` from `OPUS_REFERENCE_OUTPUT_DIR`):
//!
//! ```text
//! OPUS_TESTVECTORS_DIR=/path/to/opus_newvectors cargo test --release \
//!     --test rfc6716_conformance -- --ignored --nocapture
//! ```

#![allow(clippy::needless_return)]

mod conformance;

use conformance::*;
use std::path::PathBuf;

/// One ignored conformance test per `(rate, layout)` pair of RFC 6716 Section 6.1.
macro_rules! conformance_tests {
    ($($name:ident => ($rate:expr, $layout:expr)),* $(,)?) => {
        $(
            #[test]
            #[ignore = "needs OPUS_TESTVECTORS_DIR with the RFC 8251 test vectors"]
            fn $name() {
                assert_conformance($rate, $layout);
            }
        )*
    };
}

conformance_tests! {
    rfc6716_test_vectors_8k_mono => (8_000, Layout::Mono),
    rfc6716_test_vectors_8k_stereo => (8_000, Layout::Stereo),
    rfc6716_test_vectors_12k_mono => (12_000, Layout::Mono),
    rfc6716_test_vectors_12k_stereo => (12_000, Layout::Stereo),
    rfc6716_test_vectors_16k_mono => (16_000, Layout::Mono),
    rfc6716_test_vectors_16k_stereo => (16_000, Layout::Stereo),
    rfc6716_test_vectors_24k_mono => (24_000, Layout::Mono),
    rfc6716_test_vectors_24k_stereo => (24_000, Layout::Stereo),
    rfc6716_test_vectors_48k_mono => (48_000, Layout::Mono),
    rfc6716_test_vectors_48k_stereo => (48_000, Layout::Stereo),
}

/// Compares all 120 `(vector, rate, layout)` runs sample by sample against `ref_*.pcm` files from
/// `OPUS_REFERENCE_OUTPUT_DIR`.
#[test]
#[ignore = "needs OPUS_TESTVECTORS_DIR and OPUS_REFERENCE_OUTPUT_DIR"]
fn rfc8251_reference_decoder_sample_comparison() {
    let Some(ref_dir_os) = std::env::var_os(REFERENCE_OUTPUT_DIR_ENV)
    else {
        println!(
            "{REFERENCE_OUTPUT_DIR_ENV} is not set; skipping sample-by-sample reference comparison"
        );
        return;
    };
    let ref_dir = PathBuf::from(ref_dir_os);
    let vec_dir = vectors_dir();

    let mut runs = Vec::with_capacity(TEST_VECTOR_COUNT * SAMPLE_RATES.len() * LAYOUTS.len());
    for &rate in &SAMPLE_RATES {
        for &layout in &LAYOUTS {
            for vector in 1..=TEST_VECTOR_COUNT {
                runs.push((vector, rate, layout));
            }
        }
    }

    let workers = std::thread::available_parallelism().map_or(1, usize::from).min(MAX_WORKERS);
    let mut comparisons: Vec<SampleComparison> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..workers)
            .map(|i| {
                let vec_dir = vec_dir.as_path();
                let ref_dir = ref_dir.as_path();
                let runs = runs.as_slice();
                scope.spawn(move || {
                    runs.iter()
                        .skip(i)
                        .step_by(workers)
                        .map(|&(vector, rate, layout)| {
                            compare_with_reference_output(vec_dir, ref_dir, vector, rate, layout)
                        })
                        .collect::<Vec<_>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|handle| handle.join().expect("reference comparison worker panicked"))
            .collect()
    });
    comparisons.sort_by_key(|c| (c.rate, c.layout.channels(), c.vector));

    comparisons.iter().for_each(|comparison| println!("{comparison}"));
    let failures: Vec<String> = comparisons
        .iter()
        .filter(|comparison| !comparison.passes())
        .map(ToString::to_string)
        .collect();
    assert!(
        failures.is_empty(),
        "{} of {} reference comparisons failed:\n{}",
        failures.len(),
        comparisons.len(),
        failures.join("\n")
    );
}

/// Prints a bit-exact output digest for each of the 120 `(vector, rate, layout)` runs, once as
/// recorded and once with every 7th packet lost, so that two builds can be compared with `diff`.
#[test]
#[ignore = "needs OPUS_TESTVECTORS_DIR with the RFC 8251 test vectors"]
fn rfc8251_output_digest() {
    let vec_dir = vectors_dir();
    let files: Vec<Vec<u8>> = (1..=TEST_VECTOR_COUNT)
        .map(|vector| read_file(&vec_dir.join(format!("testvector{vector:02}.bit"))))
        .collect();
    let mut runs = Vec::with_capacity(2 * files.len() * SAMPLE_RATES.len() * LAYOUTS.len());
    for loss in [Loss::None, Loss::EVERY_7TH] {
        for &rate in &SAMPLE_RATES {
            for &layout in &LAYOUTS {
                for vector in 1..=TEST_VECTOR_COUNT {
                    runs.push((loss, rate, layout, vector));
                }
            }
        }
    }

    let workers = std::thread::available_parallelism().map_or(1, usize::from).min(MAX_WORKERS);
    let mut lines: Vec<DigestLine> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..workers)
            .map(|i| {
                let runs = runs.as_slice();
                let files = files.as_slice();
                scope.spawn(move || {
                    runs.iter()
                        .skip(i)
                        .step_by(workers)
                        .map(|&(loss, rate, layout, vector)| {
                            let records = parse_bit_records(&files[vector - 1])
                                .unwrap_or_else(|err| panic!("testvector{vector:02}: {err}"));
                            let digest = output_digest(&records, rate, layout, loss);
                            DigestLine { loss, rate, layout, vector, digest }
                        })
                        .collect::<Vec<_>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|handle| handle.join().expect("digest worker panicked"))
            .collect()
    });
    lines.sort_by_key(|line| (line.loss, line.rate, line.layout.channels(), line.vector));
    lines.iter().for_each(|line| println!("{line}"));
    assert_eq!(lines.len(), runs.len());
}
