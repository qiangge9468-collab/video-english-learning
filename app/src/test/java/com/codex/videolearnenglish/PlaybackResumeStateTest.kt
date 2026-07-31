package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Test

class PlaybackResumeStateTest {
    @Test
    fun currentPlayerPositionReplacesStalePendingPositionWhenLeavingLearningTab() {
        val stalePendingPosition = 27 * 60 * 1000 + 8 * 1000
        val positionAtTabSwitch = 28 * 60 * 1000 + 2 * 1000

        assertEquals(
            positionAtTabSwitch,
            retainedPlaybackPosition(positionAtTabSwitch, stalePendingPosition)
        )
    }

    @Test
    fun pendingPositionIsRetainedUntilPlayerIsAvailable() {
        assertEquals(123_456, retainedPlaybackPosition(null, 123_456))
    }

    @Test
    fun invalidPositionsAreClampedToVideoStart() {
        assertEquals(0, retainedPlaybackPosition(-1, 123_456))
        assertEquals(0, retainedPlaybackPosition(null, -1))
    }
}
