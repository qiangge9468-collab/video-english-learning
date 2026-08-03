package com.codex.videolearnenglish

import kotlin.math.max
import kotlin.math.roundToInt

internal enum class ReviewRating {
    AGAIN,
    HARD,
    GOOD,
    EASY
}

internal data class ReviewState(
    val dueAtMs: Long,
    val intervalDays: Int,
    val ease: Double,
    val repetitions: Int,
    val lapses: Int,
    val lastReviewedAtMs: Long
)

internal object ReviewScheduler {
    const val MINUTE_MS = 60_000L
    const val DAY_MS = 86_400_000L

    fun isDue(state: ReviewState?, nowMs: Long): Boolean {
        return state == null || state.dueAtMs <= nowMs
    }

    fun next(previous: ReviewState?, rating: ReviewRating, nowMs: Long): ReviewState {
        val old = previous ?: ReviewState(
            dueAtMs = nowMs,
            intervalDays = 0,
            ease = 2.5,
            repetitions = 0,
            lapses = 0,
            lastReviewedAtMs = 0L
        )
        return when (rating) {
            ReviewRating.AGAIN -> ReviewState(
                dueAtMs = nowMs + 10 * MINUTE_MS,
                intervalDays = 0,
                ease = max(1.3, old.ease - 0.2),
                repetitions = 0,
                lapses = old.lapses + 1,
                lastReviewedAtMs = nowMs
            )
            ReviewRating.HARD -> {
                val interval = when (old.repetitions) {
                    0 -> 1
                    else -> max(1, (max(1, old.intervalDays) * 1.2).roundToInt())
                }
                scheduled(old, nowMs, interval, max(1.3, old.ease - 0.05))
            }
            ReviewRating.GOOD -> {
                val interval = when (old.repetitions) {
                    0 -> 1
                    1 -> 3
                    else -> max(1, (max(1, old.intervalDays) * old.ease).roundToInt())
                }
                scheduled(old, nowMs, interval, old.ease)
            }
            ReviewRating.EASY -> {
                val nextEase = old.ease + 0.1
                val interval = when (old.repetitions) {
                    0 -> 4
                    else -> max(4, (max(1, old.intervalDays) * nextEase * 1.3).roundToInt())
                }
                scheduled(old, nowMs, interval, nextEase)
            }
        }
    }

    private fun scheduled(
        old: ReviewState,
        nowMs: Long,
        intervalDays: Int,
        ease: Double
    ): ReviewState {
        return ReviewState(
            dueAtMs = nowMs + intervalDays * DAY_MS,
            intervalDays = intervalDays,
            ease = ease,
            repetitions = old.repetitions + 1,
            lapses = old.lapses,
            lastReviewedAtMs = nowMs
        )
    }
}
