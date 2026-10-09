package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Test

class FullscreenSubtitlePositionTest {
    @Test fun defaultIsCenteredNearBottom() {
        assertEquals(400 to 288, FullscreenSubtitlePosition().pixels(800, 400))
    }
    @Test fun dragCannotCrossSafeArea() {
        assertEquals(0 to 400, FullscreenSubtitlePosition.fromPixels(-50f, 500f, 800, 400).pixels(800, 400))
    }
    @Test fun positionScalesWhenRotatedOrResized() {
        val position = FullscreenSubtitlePosition.fromPixels(200f, 100f, 800, 400)
        assertEquals(100 to 200, position.pixels(400, 800))
    }
    @Test fun oversizedSubtitleHasNoNegativeTravel() {
        assertEquals(0 to 0, FullscreenSubtitlePosition().pixels(-30, -20))
        assertEquals(0 to 0, FullscreenSubtitlePosition.fromPixels(50f, 80f, 0, 0).pixels(0, 0))
    }
    @Test fun storedPositionIsClamped() {
        assertEquals(0 to 100, FullscreenSubtitlePosition(-5f, 8f).pixels(100, 100))
    }
}
