package com.codex.videolearnenglish

internal fun retainedPlaybackPosition(currentPositionMs: Int?, pendingResumePositionMs: Int): Int {
    return (currentPositionMs ?: pendingResumePositionMs).coerceAtLeast(0)
}
