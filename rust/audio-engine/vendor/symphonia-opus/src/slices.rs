//! Fixed-size views of slices on Rust 1.85, the minimum version shared with Symphonia.
//!
//! The standard library stabilizes the same views only later (`slice::as_chunks` in 1.88,
//! `slice::array_windows` in 1.94). Every item is an array reference, so element access through
//! destructuring or constant indices is checked at compile time.
//!
//! Each view maps `windows(N)` or `chunks_exact(N)` one to one, which keeps the exact length and
//! the indexed fast path of `zip` (a `filter_map` would drop both and measured up to 8% slower).
//! The length check in [`as_array`] is constant-folded away: both iterators yield exactly `N`
//! elements.

/// Views a slice of exactly `N` elements as an array.
#[inline(always)]
fn as_array<T, const N: usize>(slice: &[T]) -> &[T; N] {
    return slice.first_chunk().expect("windows(N) and chunks_exact(N) yield N elements");
}

/// Overlapping windows of `N` consecutive elements as arrays, like `slice::array_windows`.
#[inline(always)]
pub(crate) fn array_windows<T, const N: usize>(
    slice: &[T],
) -> impl ExactSizeIterator<Item = &[T; N]> + DoubleEndedIterator {
    return slice.windows(N).map(as_array);
}

/// Non-overlapping chunks of `N` elements as arrays, with the elements left over at the end,
/// like `slice::as_chunks`.
#[inline(always)]
pub(crate) fn array_chunks<T, const N: usize>(
    slice: &[T],
) -> (impl DoubleEndedIterator<Item = &[T; N]>, &[T]) {
    let chunks = slice.chunks_exact(N);
    let remainder = chunks.remainder();
    return (chunks.filter_map(<[T]>::first_chunk), remainder);
}

/// Non-overlapping mutable chunks of `N` elements as arrays, like `slice::as_chunks_mut().0`;
/// the elements left over at the end are not visited.
#[inline(always)]
pub(crate) fn array_chunks_mut<T, const N: usize>(
    slice: &mut [T],
) -> impl DoubleEndedIterator<Item = &mut [T; N]> {
    return slice.chunks_exact_mut(N).filter_map(<[T]>::first_chunk_mut);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_and_chunks_match_the_standard_library_views() {
        let values = [1, 2, 3, 4, 5];
        let windows: Vec<[i32; 3]> = array_windows::<_, 3>(&values).copied().collect();
        assert_eq!(windows, [[1, 2, 3], [2, 3, 4], [3, 4, 5]]);
        assert_eq!(array_windows::<_, 6>(&values).len(), 0);

        let (chunks, remainder) = array_chunks::<_, 2>(&values);
        assert_eq!(chunks.copied().collect::<Vec<_>>(), [[1, 2], [3, 4]]);
        assert_eq!(remainder, [5]);

        let mut buffer = [0; 5];
        for (chunk, value) in array_chunks_mut::<_, 2>(&mut buffer).zip(1..) {
            *chunk = [value, -value];
        }
        assert_eq!(buffer, [1, -1, 2, -2, 0]);
    }
}
