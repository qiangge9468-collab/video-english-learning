package com.codex.videolearnenglish

/** Fractions of the available travel, not raw screen pixels: survives rotation/font changes. */
internal data class FullscreenSubtitlePosition(val x: Float = .5f, val y: Float = .86f) {
    fun pixels(availableWidth: Int, availableHeight: Int): Pair<Int, Int> =
        (x.coerceIn(0f, 1f) * availableWidth.coerceAtLeast(0)).toInt() to
            (y.coerceIn(0f, 1f) * availableHeight.coerceAtLeast(0)).toInt()

    companion object {
        fun fromPixels(x: Float, y: Float, availableWidth: Int, availableHeight: Int) =
            FullscreenSubtitlePosition(
                if (availableWidth > 0) (x / availableWidth).coerceIn(0f, 1f) else .5f,
                if (availableHeight > 0) (y / availableHeight).coerceIn(0f, 1f) else .5f
            )
    }
}
