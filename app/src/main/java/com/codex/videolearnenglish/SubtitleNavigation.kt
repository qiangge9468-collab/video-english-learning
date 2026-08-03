package com.codex.videolearnenglish

internal data class SubtitleNavigationInterval(
    val startMs: Int,
    val endMs: Int
)

internal fun subtitleNavigationTarget(
    intervals: List<SubtitleNavigationInterval>,
    currentMs: Int,
    direction: Int
): Int {
    if (intervals.isEmpty() || direction == 0) return -1
    val activeIndex = intervals.indexOfLast { interval ->
        currentMs >= interval.startMs && currentMs < interval.endMs
    }
    if (activeIndex >= 0) {
        return (activeIndex + direction.sign()).coerceIn(intervals.indices)
    }
    return if (direction < 0) {
        intervals.indexOfLast { it.endMs <= currentMs }
            .takeIf { it >= 0 }
            ?: 0
    } else {
        intervals.indexOfFirst { it.startMs > currentMs }
            .takeIf { it >= 0 }
            ?: intervals.lastIndex
    }
}

private fun Int.sign(): Int = if (this < 0) -1 else 1
