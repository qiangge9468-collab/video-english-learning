package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Test

class SubtitleNavigationTest {
    private val intervals = listOf(
        SubtitleNavigationInterval(1_000, 2_000),
        SubtitleNavigationInterval(3_000, 4_000),
        SubtitleNavigationInterval(6_000, 7_000)
    )

    @Test
    fun previousFromSubtitleGapUsesSentenceBeforeGap() {
        assertEquals(1, subtitleNavigationTarget(intervals, currentMs = 5_000, direction = -1))
    }

    @Test
    fun nextFromSubtitleGapUsesSentenceAfterGap() {
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 5_000, direction = 1))
    }

    @Test
    fun navigationFromActiveSubtitleMovesRelativeToActiveSentence() {
        assertEquals(0, subtitleNavigationTarget(intervals, currentMs = 3_500, direction = -1))
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 3_500, direction = 1))
    }

    @Test
    fun navigationBeforeFirstSubtitleStaysAtFirstSentence() {
        assertEquals(0, subtitleNavigationTarget(intervals, currentMs = 500, direction = -1))
        assertEquals(0, subtitleNavigationTarget(intervals, currentMs = 500, direction = 1))
    }

    @Test
    fun navigationAfterLastSubtitleStaysAtLastSentence() {
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 8_000, direction = -1))
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 8_000, direction = 1))
    }

    @Test
    fun exactSubtitleBoundaryUsesNewActiveSentence() {
        assertEquals(0, subtitleNavigationTarget(intervals, currentMs = 3_000, direction = -1))
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 3_000, direction = 1))
    }

    @Test
    fun emptySubtitleListHasNoNavigationTarget() {
        assertEquals(-1, subtitleNavigationTarget(emptyList(), currentMs = 5_000, direction = -1))
        assertEquals(-1, subtitleNavigationTarget(emptyList(), currentMs = 5_000, direction = 1))
    }

    @Test
    fun largeDirectionIsNormalizedToSingleSentenceStep() {
        assertEquals(0, subtitleNavigationTarget(intervals, currentMs = 3_500, direction = -99))
        assertEquals(2, subtitleNavigationTarget(intervals, currentMs = 3_500, direction = 99))
    }
}
