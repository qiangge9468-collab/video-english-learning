package com.codex.videolearnenglish

import java.util.Locale

internal enum class ReviewPromptMode(val label: String) {
    MEANING("释义回忆"),
    CLOZE("原句填空"),
    CHINESE_TO_ENGLISH("中译英"),
    LISTENING("听音拼写")
}

internal data class ReviewPrompt(
    val mode: ReviewPromptMode,
    val front: String,
    val instruction: String,
    val expectsTypedAnswer: Boolean
)

internal object ReviewPromptBuilder {
    fun build(
        term: String,
        meaning: String,
        englishText: String,
        chineseText: String,
        repetitions: Int
    ): ReviewPrompt {
        return when (modeFor(repetitions)) {
            ReviewPromptMode.MEANING -> ReviewPrompt(
                ReviewPromptMode.MEANING,
                term,
                "先回忆它的含义和在视频原句中的用法",
                false
            )
            ReviewPromptMode.CLOZE -> {
                val cloze = clozeSentence(englishText, term)
                if (cloze != null) {
                    ReviewPrompt(ReviewPromptMode.CLOZE, cloze, "输入原句中缺少的英文", true)
                } else {
                    translationOrListening(meaning, chineseText)
                }
            }
            ReviewPromptMode.CHINESE_TO_ENGLISH -> translationOrListening(meaning, chineseText)
            ReviewPromptMode.LISTENING -> listeningPrompt()
        }
    }

    fun modeFor(repetitions: Int): ReviewPromptMode {
        val modes = ReviewPromptMode.entries
        return modes[repetitions.coerceAtLeast(0) % modes.size]
    }

    fun clozeSentence(sentence: String, term: String): String? {
        val cleanSentence = sentence.trim()
        val cleanTerm = term.trim()
        if (cleanSentence.isBlank() || cleanTerm.isBlank()) return null
        val pattern = Regex(
            "(?i)(?<![\\p{L}\\p{N}])${Regex.escape(cleanTerm)}(?![\\p{L}\\p{N}])"
        )
        if (!pattern.containsMatchIn(cleanSentence)) return null
        return pattern.replaceFirst(cleanSentence, "_____" )
    }

    fun normalizeAnswer(value: String): String {
        return value
            .lowercase(Locale.US)
            .replace('’', '\'')
            .replace('‘', '\'')
            .replace(Regex("[^\\p{L}\\p{N}'\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    fun isCorrect(answer: String, expected: String): Boolean {
        val normalizedAnswer = normalizeAnswer(answer)
        return normalizedAnswer.isNotBlank() && normalizedAnswer == normalizeAnswer(expected)
    }

    private fun translationOrListening(meaning: String, chineseText: String): ReviewPrompt {
        val clue = chineseText.trim().ifBlank { meaning.trim() }
        return if (clue.isNotBlank()) {
            ReviewPrompt(ReviewPromptMode.CHINESE_TO_ENGLISH, clue, "根据中文输入英文单词或短语", true)
        } else {
            listeningPrompt()
        }
    }

    private fun listeningPrompt(): ReviewPrompt {
        return ReviewPrompt(
            ReviewPromptMode.LISTENING,
            "点击“听发音”，写出听到的英文",
            "可重复播放，完成后检查拼写",
            true
        )
    }
}

internal data class ReviewDailyStats(
    val day: String,
    val completed: Int = 0,
    val typedAttempts: Int = 0,
    val typedCorrect: Int = 0
) {
    val accuracyPercent: Int?
        get() = if (typedAttempts == 0) null else typedCorrect * 100 / typedAttempts

    fun record(typedAnswerCorrect: Boolean?): ReviewDailyStats {
        return copy(
            completed = completed + 1,
            typedAttempts = typedAttempts + if (typedAnswerCorrect == null) 0 else 1,
            typedCorrect = typedCorrect + if (typedAnswerCorrect == true) 1 else 0
        )
    }
}
