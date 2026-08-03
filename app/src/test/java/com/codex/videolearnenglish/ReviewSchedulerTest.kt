package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReviewSchedulerTest {
    private val now = 1_700_000_000_000L

    @Test
    fun unseenCardsAreDueImmediately() {
        assertTrue(ReviewScheduler.isDue(null, now))
    }

    @Test
    fun againSchedulesTenMinuteRetryAndRecordsLapse() {
        val next = ReviewScheduler.next(null, ReviewRating.AGAIN, now)

        assertEquals(now + 10 * ReviewScheduler.MINUTE_MS, next.dueAtMs)
        assertEquals(0, next.intervalDays)
        assertEquals(0, next.repetitions)
        assertEquals(1, next.lapses)
    }

    @Test
    fun goodProgressesFromOneDayToThreeDays() {
        val first = ReviewScheduler.next(null, ReviewRating.GOOD, now)
        val secondNow = first.dueAtMs
        val second = ReviewScheduler.next(first, ReviewRating.GOOD, secondNow)

        assertEquals(1, first.intervalDays)
        assertEquals(3, second.intervalDays)
        assertEquals(2, second.repetitions)
        assertEquals(secondNow + 3 * ReviewScheduler.DAY_MS, second.dueAtMs)
    }

    @Test
    fun easyStartsWithLongerIntervalThanGood() {
        val good = ReviewScheduler.next(null, ReviewRating.GOOD, now)
        val easy = ReviewScheduler.next(null, ReviewRating.EASY, now)

        assertEquals(1, good.intervalDays)
        assertEquals(4, easy.intervalDays)
        assertTrue(easy.ease > good.ease)
    }

    @Test
    fun easyRemainsLongerThanGoodOnSecondReview() {
        val first = ReviewScheduler.next(null, ReviewRating.GOOD, now)
        val good = ReviewScheduler.next(first, ReviewRating.GOOD, first.dueAtMs)
        val easy = ReviewScheduler.next(first, ReviewRating.EASY, first.dueAtMs)

        assertEquals(3, good.intervalDays)
        assertTrue(easy.intervalDays > good.intervalDays)
    }

    @Test
    fun hardGrowsMoreSlowlyThanGood() {
        val learned = ReviewState(
            dueAtMs = now,
            intervalDays = 10,
            ease = 2.5,
            repetitions = 3,
            lapses = 0,
            lastReviewedAtMs = now - ReviewScheduler.DAY_MS
        )
        val hard = ReviewScheduler.next(learned, ReviewRating.HARD, now)
        val good = ReviewScheduler.next(learned, ReviewRating.GOOD, now)

        assertEquals(12, hard.intervalDays)
        assertEquals(25, good.intervalDays)
        assertTrue(hard.ease < learned.ease)
    }

    @Test
    fun cardStopsBeingDueUntilItsScheduledTime() {
        val state = ReviewScheduler.next(null, ReviewRating.GOOD, now)

        assertFalse(ReviewScheduler.isDue(state, now))
        assertFalse(ReviewScheduler.isDue(state, state.dueAtMs - 1))
        assertTrue(ReviewScheduler.isDue(state, state.dueAtMs))
    }
}
