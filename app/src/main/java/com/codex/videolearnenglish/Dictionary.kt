package com.codex.videolearnenglish

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.util.Locale

data class LookupResult(
    val term: String,
    val phonetic: String = "",
    val ukPhonetic: String = "",
    val usPhonetic: String = "",
    val meaning: String,
    val definition: String = "",
    val lemma: String = "",
    val inflection: String = "",
    val collocations: List<Collocation> = emptyList()
)

class Dictionary(private val context: Context) {
    private val database: SQLiteDatabase? by lazy { openBundledDatabase() }
    private val lemmaDatabase: SQLiteDatabase? by lazy {
        openAssetDatabase("lemma_v2_0_6.db", "lemma_v2_0_6.db")
    }

    fun close() {
        database?.close()
        lemmaDatabase?.close()
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
    fun lookupRich(rawText: String, sentence: String = ""): LookupResult {
        val term = cleanTerm(rawText)
        if (term.isBlank() || term.contains(' ')) return lookup(rawText)

        val exact = lookupDatabase(term)
        val lemma = lookupLemma(term)
            ?: irregularForms[term]?.first
            ?: if (exact == null) lemmaCandidates(term).firstNotNullOfOrNull { candidate ->
                candidate.first.takeIf { lookupDatabase(it) != null }
            } else null
        val base = lemma?.takeIf { it != term }?.let(::lookupDatabase)
        val selected = base ?: exact
        if (selected != null) {
            val resolvedLemma = base?.term.orEmpty()
            val enrichment = lookupEnrichment(resolvedLemma.ifBlank { term })
            val pronunciation = PronunciationLibrary.resolve(
                term = term,
                lemma = resolvedLemma,
                fallback = exact?.phonetic?.takeIf { it.isNotBlank() } ?: selected.phonetic
            )
            return LookupResult(
                term = term,
                phonetic = pronunciation.common,
                ukPhonetic = pronunciation.uk,
                usPhonetic = pronunciation.us,
                meaning = summarizeMeaning(selected.meaning),
                definition = mergeDefinitions(selected.definition, enrichment),
                lemma = resolvedLemma,
                inflection = if (resolvedLemma.isNotBlank()) describeInflection(term, resolvedLemma) else "",
                collocations = PhraseLibrary.collocationsFor(term, resolvedLemma, sentence)
            )
        }
        return lookup(rawText)
    }

    private fun lookupLemma(word: String): String? {
        val db = lemmaDatabase ?: return null
        return db.rawQuery(
            "SELECT lemma FROM forms WHERE form = ? LIMIT 1",
            arrayOf(word)
        ).use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0)?.takeIf { it.isNotBlank() } else null
        }
    }

    private fun describeInflection(word: String, lemma: String): String = when {
        word in irregularForms -> irregularForms.getValue(word).second
        word.endsWith("ing") -> "现在分词或动名词"
        word.endsWith("ed") || word.endsWith("en") -> "过去式或过去分词"
        word.endsWith("s") && lemma != word -> "复数或第三人称单数"
        else -> "词形变化"
    }

    private fun lookupEnrichment(word: String): LexicalEnrichment? {
        val db = lemmaDatabase ?: return null
        return db.rawQuery(
            "SELECT definitions, related, examples FROM enrichment WHERE word = ? LIMIT 1",
            arrayOf(word)
        ).use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            LexicalEnrichment(
                definitions = cursor.getString(0).orEmpty(),
                related = cursor.getString(1).orEmpty(),
                examples = cursor.getString(2).orEmpty()
            )
        }
    }

    private fun mergeDefinitions(original: String, enrichment: LexicalEnrichment?): String {
        val blocks = mutableListOf<String>()
        summarizeDefinition(original).takeIf { it.isNotBlank() }?.let(blocks::add)
        enrichment?.definitions?.takeIf { it.isNotBlank() }?.let {
            blocks += "Open English WordNet：\n$it"
        }
        enrichment?.related?.takeIf { it.isNotBlank() }?.let {
            blocks += "近义／相关词：$it"
        }
        enrichment?.examples?.takeIf { it.isNotBlank() }?.let {
            blocks += "英文例句：\n$it"
        }
        return blocks.joinToString("\n\n").take(1200)
    }

    private fun lemmaCandidates(word: String): List<Pair<String, String>> {
        irregularForms[word]?.let { return listOf(it) }
        if (word in nonInflectedWords) return emptyList()

        val candidates = linkedSetOf<String>()
        val formLabel = when {
            word.endsWith("ies") && word.length > 4 -> {
                candidates += word.dropLast(3) + "y"
                "\u590d\u6570\u6216\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"
            }
            word.endsWith("ing") && word.length > 5 -> {
                val stem = word.dropLast(3)
                if (stem.length > 2 && stem.last() == stem[stem.lastIndex - 1] && stem.last() in doubledInflectionConsonants) {
                    candidates += stem.dropLast(1)
                }
                candidates += stem
                candidates += stem + "e"
                "\u73b0\u5728\u5206\u8bcd\u6216\u52a8\u540d\u8bcd"
            }
            word.endsWith("ied") && word.length > 4 -> {
                candidates += word.dropLast(3) + "y"
                "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"
            }
            word.endsWith("ed") && word.length > 4 -> {
                val stem = word.dropLast(2)
                if (stem.length > 2 && stem.last() == stem[stem.lastIndex - 1] && stem.last() in doubledInflectionConsonants) {
                    candidates += stem.dropLast(1)
                }
                candidates += stem
                candidates += word.dropLast(1)
                "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"
            }
            word.endsWith("es") && word.length > 4 -> {
                candidates += word.dropLast(2)
                candidates += word.dropLast(1)
                "\u590d\u6570\u6216\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"
            }
            word.endsWith("s") && word.length > 3 -> {
                candidates += word.dropLast(1)
                "\u590d\u6570\u6216\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"
            }
            else -> return emptyList()
        }
        return candidates.filter { it != word }.map { it to formLabel }
    }

    private fun summarizeMeaning(text: String): String {
        return text.lineSequence()
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .take(5)
            .joinToString("\n")
            .take(360)
    }

    private fun summarizeDefinition(text: String): String {
        return text.lineSequence()
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .take(3)
            .joinToString("\n")
            .take(420)
    }

    private val nonInflectedWords = setOf(
        "news", "series", "species", "physics", "mathematics", "this", "his", "is", "was"
    )


    private val doubledInflectionConsonants = setOf('b', 'd', 'g', 'm', 'n', 'p', 'r', 't')
    private val irregularForms = mapOf(
        "am" to ("be" to "\u7b2c\u4e00\u4eba\u79f0\u5355\u6570"),
        "is" to ("be" to "\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"),
        "are" to ("be" to "\u73b0\u5728\u65f6"),
        "was" to ("be" to "\u8fc7\u53bb\u5f0f"),
        "were" to ("be" to "\u8fc7\u53bb\u5f0f"),
        "been" to ("be" to "\u8fc7\u53bb\u5206\u8bcd"),
        "being" to ("be" to "\u73b0\u5728\u5206\u8bcd"),
        "has" to ("have" to "\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"),
        "had" to ("have" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "does" to ("do" to "\u7b2c\u4e09\u4eba\u79f0\u5355\u6570"),
        "did" to ("do" to "\u8fc7\u53bb\u5f0f"),
        "done" to ("do" to "\u8fc7\u53bb\u5206\u8bcd"),
        "went" to ("go" to "\u8fc7\u53bb\u5f0f"),
        "gone" to ("go" to "\u8fc7\u53bb\u5206\u8bcd"),
        "made" to ("make" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "took" to ("take" to "\u8fc7\u53bb\u5f0f"),
        "taken" to ("take" to "\u8fc7\u53bb\u5206\u8bcd"),
        "came" to ("come" to "\u8fc7\u53bb\u5f0f"),
        "saw" to ("see" to "\u8fc7\u53bb\u5f0f"),
        "seen" to ("see" to "\u8fc7\u53bb\u5206\u8bcd"),
        "got" to ("get" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "gave" to ("give" to "\u8fc7\u53bb\u5f0f"),
        "given" to ("give" to "\u8fc7\u53bb\u5206\u8bcd"),
        "found" to ("find" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "thought" to ("think" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "knew" to ("know" to "\u8fc7\u53bb\u5f0f"),
        "known" to ("know" to "\u8fc7\u53bb\u5206\u8bcd"),
        "said" to ("say" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "told" to ("tell" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "felt" to ("feel" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "left" to ("leave" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "kept" to ("keep" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "heard" to ("hear" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "caught" to ("catch" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "bought" to ("buy" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "brought" to ("bring" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "wrote" to ("write" to "\u8fc7\u53bb\u5f0f"),
        "written" to ("write" to "\u8fc7\u53bb\u5206\u8bcd"),
        "spoke" to ("speak" to "\u8fc7\u53bb\u5f0f"),
        "spoken" to ("speak" to "\u8fc7\u53bb\u5206\u8bcd"),
        "ran" to ("run" to "\u8fc7\u53bb\u5f0f"),
        "ate" to ("eat" to "\u8fc7\u53bb\u5f0f"),
        "eaten" to ("eat" to "\u8fc7\u53bb\u5206\u8bcd"),
        "wore" to ("wear" to "\u8fc7\u53bb\u5f0f"),
        "worn" to ("wear" to "\u8fc7\u53bb\u5206\u8bcd"),
        "chose" to ("choose" to "\u8fc7\u53bb\u5f0f"),
        "chosen" to ("choose" to "\u8fc7\u53bb\u5206\u8bcd"),
        "built" to ("build" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "lost" to ("lose" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "met" to ("meet" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "stood" to ("stand" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd"),
        "understood" to ("understand" to "\u8fc7\u53bb\u5f0f\u6216\u8fc7\u53bb\u5206\u8bcd")
    )



    private fun openBundledDatabase(): SQLiteDatabase? =
        openAssetDatabase("dictionary.db", "dictionary.db")

    private fun openAssetDatabase(assetName: String, targetName: String): SQLiteDatabase? {
        val dbFile = File(context.filesDir, targetName)
        return runCatching {
            if (!dbFile.exists() || dbFile.length() == 0L) {
                context.assets.open(assetName).use { input ->
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
        "take care of" to "照顾；处理",
        "thanks so much" to "非常感谢",
        "thank you so much" to "非常感谢",
        "so much" to "非常；这么多",
        "for your help" to "感谢你的帮助；因为你的帮助",
        "you bet" to "当然；没问题；不客气",
        "let's see" to "让我想想；看看",
        "pretty easy" to "相当简单",
        "easy to do" to "容易做",
        "plan on" to "计划；打算",
        "planning on" to "正打算；正计划",
        "in the field" to "在现场；在实地",
        "cap in the field" to "在现场封盖/盖上",
        "capping in the field" to "正在现场封盖/盖上",
        "go ahead" to "继续；请便",
        "pick up" to "拿起；学会；接人",
        "put on" to "穿上；戴上；播放",
        "take off" to "起飞；脱下；开始流行",
        "come back" to "回来",
        "back up" to "备份；支持；倒退",
        "end up" to "最终；结果",
        "run into" to "遇到；撞上",
        "turn out" to "结果是；证明是",
        "work out" to "解决；锻炼；进展",
        "hang out" to "闲逛；一起待着",
        "show up" to "出现；到场",
        "hold on" to "等一下；坚持",
        "move on" to "继续前进；进入下一步",
        "as well" to "也；同样",
        "at least" to "至少",
        "by the way" to "顺便说一下",
        "in terms of" to "就……而言",
        "a little bit" to "一点点",
        "sort of" to "有点；算是",
        "of course" to "当然",
        "make sense" to "有道理；讲得通",
        "keep going" to "继续",
        "get started" to "开始",
        "get back" to "回来；取回",
        "come in" to "进来；到达",
        "go through" to "经历；仔细检查",
        "come across" to "偶然遇到；给人……印象"
    )

    private val collocations = mapOf(
        "end" to listOf(
            "the end of ..." to "……的最后／末尾",
            "in the end" to "终于；最后（强调结果）",
            "at the end of ..." to "在……末尾／尽头",
            "by the end of ..." to "到……结束时为止",
            "end up doing ..." to "最终做了……",
            "put an end to ..." to "结束；终止……"
        ),
        "suppose" to listOf(
            "be supposed to do ..." to "应该做……；按理应当……",
            "suppose that ..." to "假设／认为……",
            "I suppose so" to "我想是的",
            "what's that supposed to mean?" to "那是什么意思？"
        ),
        "progress" to listOf(
            "make progress" to "取得进步",
            "in progress" to "正在进行中",
            "progress toward(s) ..." to "朝着……推进",
            "slow and steady progress" to "缓慢而稳步的进展"
        ),
        "cross" to listOf(
            "cross the road" to "过马路",
            "cross the line" to "越界；做得过分",
            "cross over" to "穿过；转入另一领域",
            "cross one's mind" to "闪过某人的脑海"
        ),
        "take" to listOf(
            "take a look" to "看一看",
            "take part in ..." to "参加……",
            "take care of ..." to "照顾；处理……",
            "take place" to "发生；举行"
        ),
        "get" to listOf(
            "get ready" to "准备好",
            "get used to ..." to "习惯于……",
            "get along with ..." to "与……相处",
            "get back" to "回来；取回"
        ),
        "make" to listOf(
            "make sure" to "确保",
            "make sense" to "有道理；讲得通",
            "make a difference" to "产生影响；带来改变",
            "make up one's mind" to "下定决心"
        ),
        "look" to listOf(
            "look for ..." to "寻找……",
            "look forward to ..." to "期待……",
            "look after ..." to "照顾……",
            "look up ..." to "查找；查阅……"
        ),
        "go" to listOf(
            "go on" to "继续；发生",
            "go through ..." to "经历；仔细检查……",
            "go ahead" to "继续；请便",
            "go back" to "回去；追溯到"
        ),
        "come" to listOf(
            "come across ..." to "偶然遇到……",
            "come up with ..." to "想出……",
            "come back" to "回来",
            "come true" to "实现；成真"
        ),
        "work" to listOf(
            "work out" to "解决；锻炼；进展顺利",
            "work on ..." to "致力于；继续改进……",
            "at work" to "在工作；起作用",
            "work with ..." to "与……合作；使用……"
        ),
        "learn" to listOf(
            "learn from ..." to "向……学习；从……吸取经验",
            "learn how to ..." to "学习如何……",
            "learn by doing" to "在实践中学习",
            "learn one's lesson" to "吸取教训"
        )
    )

    fun lookup(term: String): LookupResult? {
        val meaning = phrases[term] ?: return null
        return LookupResult(term = term, meaning = meaning)
    }

    fun findPhrases(text: String): List<PhraseSpan> {
        val lower = text
            .lowercase(Locale.US)
            .replace(Regex("[\\u2018\\u2019\\u201B\\u2032]"), "'")
        return phrases.keys
            .flatMap { phrase ->
                val regex = Regex("\\b${Regex.escape(phrase)}\\b")
                regex.findAll(lower).map { match ->
                    PhraseSpan(match.range.first, match.range.last + 1, phrase)
                }.toList()
            }
            .sortedWith(compareByDescending<PhraseSpan> { it.end - it.start }.thenBy { it.start })
    }

    fun collocationsFor(term: String, lemma: String, sentence: String): List<Collocation> {
        val key = lemma.ifBlank { term }
        val result = linkedSetOf<Collocation>()
        collocations[key].orEmpty().forEach { (phrase, meaning) ->
            result += Collocation(phrase, meaning)
        }
        val normalizedSentence = sentence.lowercase(Locale.US)
        phrases.forEach { (phrase, meaning) ->
            if (normalizedSentence.contains(phrase) &&
                Regex("\\b${Regex.escape(key)}\\b").containsMatchIn(phrase)
            ) {
                result += Collocation(phrase, meaning)
            }
        }
        return result.take(6)
    }
}

data class PhraseSpan(val start: Int, val end: Int, val phrase: String)
data class Collocation(val phrase: String, val meaning: String)

private data class Pronunciation(val common: String, val uk: String, val us: String)

private object PronunciationLibrary {
    private val entries = mapOf(
        "suppose" to Pronunciation("", "səˈpəʊz", "səˈpoʊz"),
        "supposed" to Pronunciation("", "səˈpəʊzd", "səˈpoʊzd"),
        "progress" to Pronunciation("", "ˈprəʊɡres", "ˈprɑːɡres"),
        "cross" to Pronunciation("", "krɒs", "krɔːs"),
        "end" to Pronunciation("", "end", "end"),
        "ended" to Pronunciation("", "ˈendɪd", "ˈendɪd"),
        "schedule" to Pronunciation("", "ˈʃedjuːl", "ˈskedʒuːl"),
        "tomato" to Pronunciation("", "təˈmɑːtəʊ", "təˈmeɪtoʊ"),
        "either" to Pronunciation("", "ˈaɪðə", "ˈiːðər"),
        "route" to Pronunciation("", "ruːt", "ruːt")
    )

    fun resolve(term: String, lemma: String, fallback: String): Pronunciation {
        val known = entries[term] ?: entries[lemma]
        return if (known != null) known.copy(common = fallback)
        else Pronunciation(common = fallback, uk = "", us = "")
    }
}

private data class LexicalEnrichment(
    val definitions: String,
    val related: String,
    val examples: String
)
