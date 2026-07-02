package com.codex.videolearnenglish

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.util.Locale

data class LookupResult(
    val term: String,
    val phonetic: String = "",
    val meaning: String,
    val definition: String = ""
)

class Dictionary(private val context: Context) {
    private val database: SQLiteDatabase? by lazy { openBundledDatabase() }

    fun close() {
        database?.close()
    }

    fun lookup(rawText: String): LookupResult {
        val term = cleanTerm(rawText)
        if (term.isBlank()) {
            return LookupResult(rawText, meaning = "没有可查询的内容。")
        }

        if (term.contains(' ')) {
            PhraseLibrary.lookup(term)?.let { return it }
            lookupDatabase(term)?.let { return it }
            return LookupResult(term, meaning = "本地短语库暂未收录。可以尝试点击其中的单词查询。")
        }

        lookupDatabase(term)?.let { return it }
        val lemma = guessLemma(term)
        lookupDatabase(lemma)?.let {
            return it.copy(term = term, meaning = "${it.meaning}\n原形：$lemma")
        }

        return LookupResult(term, meaning = "本地词典暂未收录。")
    }

    private fun openBundledDatabase(): SQLiteDatabase? {
        val dbName = "dictionary.db"
        val dbFile = File(context.filesDir, dbName)
        return runCatching {
            if (!dbFile.exists() || dbFile.length() == 0L) {
                context.assets.open(dbName).use { input ->
                    dbFile.outputStream().use { output -> input.copyTo(output) }
                }
            }
            SQLiteDatabase.openDatabase(dbFile.path, null, SQLiteDatabase.OPEN_READONLY)
        }.getOrNull()
    }

    private fun lookupDatabase(term: String): LookupResult? {
        val db = database ?: return null
        return db.rawQuery(
            "SELECT word, phonetic, translation, definition FROM entries WHERE word = ? LIMIT 1",
            arrayOf(term)
        ).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            val translation = cursor.getString(2).orEmpty()
            val definition = cursor.getString(3).orEmpty()
            LookupResult(
                term = cursor.getString(0).orEmpty(),
                phonetic = cursor.getString(1).orEmpty(),
                meaning = cleanDictionaryText(translation.ifBlank { definition.ifBlank { "词典中有该词，但暂无中文释义。" } }),
                definition = cleanDictionaryText(definition)
            )
        }
    }

    private fun guessLemma(word: String): String {
        return when {
            word.endsWith("ies") && word.length > 4 -> word.dropLast(3) + "y"
            word.endsWith("ing") && word.length > 5 -> word.dropLast(3).let { stem ->
                if (stem.length > 2 && stem.last() == stem[stem.lastIndex - 1]) stem.dropLast(1) else stem
            }
            word.endsWith("ed") && word.length > 4 -> word.dropLast(2)
            word.endsWith("es") && word.length > 4 -> word.dropLast(2)
            word.endsWith("s") && word.length > 3 -> word.dropLast(1)
            else -> word
        }
    }

    private fun cleanTerm(text: String): String {
        return text
            .lowercase(Locale.US)
            .replace(Regex("[\\u2018\\u2019\\u201B\\u2032]"), "'")
            .replace(Regex("[^a-z'\\-\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun cleanDictionaryText(text: String): String {
        return text
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\t", " ")
            .replace(Regex("[ \t]+"), " ")
            .trim()
    }
}

object PhraseLibrary {
    private val phrases = mapOf(
        "a lot of" to "许多，大量",
        "lots of" to "许多，大量",
        "gear haul" to "装备采购/装备大收集",
        "come up" to "即将发生；被提到；出现",
        "coming up" to "即将到来",
        "go on" to "继续；发生；进行",
        "went on" to "继续；进行了",
        "need to" to "需要；必须",
        "have to" to "不得不；必须",
        "happy with" to "对……满意",
        "welcome back" to "欢迎回来",
        "check out" to "查看；了解一下",
        "set up" to "搭建；安排；配置",
        "try out" to "试用；尝试",
        "look for" to "寻找",
        "look at" to "看；查看",
        "look up" to "查找；查询",
        "because of" to "因为；由于",
        "as you can see" to "如你所见",
        "right now" to "现在；马上",
        "make sure" to "确保；确认",
        "kind of" to "有点；某种",
        "out of" to "从……中；由于；缺少",
        "figure out" to "弄明白；解决",
        "get into" to "进入；开始喜欢",
        "get ready" to "准备好",
        "take a look" to "看一看",
        "take care of" to "照顾；处理"
    )

    fun lookup(term: String): LookupResult? {
        val meaning = phrases[term] ?: return null
        return LookupResult(term = term, meaning = meaning)
    }

    fun findPhrases(text: String): List<PhraseSpan> {
        val lower = text.lowercase(Locale.US)
        return phrases.keys
            .mapNotNull { phrase ->
                val regex = Regex("\\b${Regex.escape(phrase)}\\b")
                regex.find(lower)?.let { match ->
                    PhraseSpan(match.range.first, match.range.last + 1, phrase)
                }
            }
            .sortedWith(compareBy<PhraseSpan> { it.start }.thenByDescending { it.end - it.start })
    }
}

data class PhraseSpan(val start: Int, val end: Int, val phrase: String)
