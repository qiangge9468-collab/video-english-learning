package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReviewPracticeTest {
    @Test
    fun promptModesCycleWithSuccessfulRepetitions() {
        assertEquals(ReviewPromptMode.MEANING, ReviewPromptBuilder.modeFor(0))
        assertEquals(ReviewPromptMode.CLOZE, ReviewPromptBuilder.modeFor(1))
        assertEquals(ReviewPromptMode.CHINESE_TO_ENGLISH, ReviewPromptBuilder.modeFor(2))
        assertEquals(ReviewPromptMode.LISTENING, ReviewPromptBuilder.modeFor(3))
        assertEquals(ReviewPromptMode.MEANING, ReviewPromptBuilder.modeFor(4))
    }

    @Test
    fun clozeReplacesWholePhraseIgnoringCase() {
        assertEquals(
            "We finally _____ before sunset.",
            ReviewPromptBuilder.clozeSentence("We finally Made It there before sunset.", "made it there")
        )
    }

    @Test
    fun clozeDoesNotReplacePartOfAnotherWord() {
        assertNull(ReviewPromptBuilder.clozeSentence("The theater is open.", "he"))
    }

    @Test
    fun missingClozeFallsBackToChinesePrompt() {
        val prompt = ReviewPromptBuilder.build(
            term = "stuck",
            meaning = "被困住的",
            englishText = "The road is closed.",
            chineseText = "我们被困在这里。",
            repetitions = 1
        )
        assertEquals(ReviewPromptMode.CHINESE_TO_ENGLISH, prompt.mode)
        assertTrue(prompt.expectsTypedAnswer)
    }

    @Test
    fun answerComparisonNormalizesCaseSpacingPunctuationAndApostrophes() {
        assertTrue(ReviewPromptBuilder.isCorrect("  DON’T   KNOW! ", "don't know"))
        assertFalse(ReviewPromptBuilder.isCorrect("do know", "don't know"))
        assertFalse(ReviewPromptBuilder.isCorrect("   ", "don't know"))
    }

    @Test
    fun dailyStatsTrackCompletionAndTypedAccuracy() {
        val stats = ReviewDailyStats("2026-07-31")
            .record(null)
            .record(true)
            .record(false)

        assertEquals(3, stats.completed)
        assertEquals(2, stats.typedAttempts)
        assertEquals(1, stats.typedCorrect)
        assertEquals(50, stats.accuracyPercent)
    }

    @Test
    fun dailyAccuracyIsAbsentBeforeTypedAnswers() {
        assertNull(ReviewDailyStats("2026-07-31").record(null).accuracyPercent)
    }
}
