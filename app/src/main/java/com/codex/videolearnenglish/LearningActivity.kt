package com.codex.videolearnenglish

import android.Manifest
import android.app.AlertDialog
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.SurfaceTexture
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.text.SpannableString
import android.text.Spanned
import android.text.method.LinkMovementMethod
import android.text.style.ClickableSpan
import android.view.Gravity
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Locale
import android.os.Handler
import android.os.Looper
import android.text.TextPaint
import org.json.JSONArray
import org.json.JSONObject

class LearningActivity : Activity() {
    private lateinit var textureView: TextureView
    private lateinit var statusText: TextView
    private lateinit var currentCaptionText: TextView
    private lateinit var subtitleList: LinearLayout
    private lateinit var subtitleScroll: ScrollView
    private lateinit var playPauseButton: Button
    private lateinit var modeButton: Button
    private lateinit var loopButton: Button
    private lateinit var dictionary: Dictionary
    private lateinit var onDeviceWhisper: OnDeviceWhisperTranscriber

    private val handler = Handler(Looper.getMainLooper())
    private val subtitles = mutableListOf<SubtitleLine>()
    private var mediaPlayer: MediaPlayer? = null
    private var videoSurface: Surface? = null
    private var currentVideoUri: Uri? = null
    private var selectedIndex = -1
    private var displayMode = DisplayMode.ENGLISH
    private var loopSentence = true
    private var normalPlayback = false
    private var subtitleOffsetMs = 0
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var textToSpeechInitializing = false
    private var pendingSpeechTerm: String? = null
    private var pronunciationPlayer: MediaPlayer? = null
    private var englishChineseTranslator: Translator? = null

    private val pickVideoRequest = 81
    private val pickSubtitleRequest = 82
    private val permissionRequest = 83
    private val testVideoPath = "/sdcard/Download/Full Gear List for Solo Backpacking.mp4"
    private val prefsName = "video_english_learning"
    private val serviceUrlKey = "whisper_service_url"
    private val defaultServiceUrl = "http://10.0.2.2:8765/transcribe?video=backpacking"
    private val subtitleCacheDirName = "subtitles_cache"
    private val sentenceEndTrimMs = 250
    private val nextSentenceGuardMs = 80

    private val progressWatcher = object : Runnable {
        override fun run() {
            val player = mediaPlayer
            if (player?.isPlaying == true && normalPlayback) {
                val currentMs = player.currentPosition
                val index = currentSubtitleIndex(currentMs)
                if (index != selectedIndex) {
                    selectedIndex = index
                    renderSubtitles()
                    scrollToSelected()
                }
                updateCurrentCaption()
            } else if (player?.isPlaying == true && selectedIndex >= 0) {
                val line = subtitles.getOrNull(selectedIndex)
                if (line != null && player.currentPosition >= playbackEndMs(selectedIndex, line)) {
                    if (loopSentence) {
                        seekTo(startMs(line))
                        player.start()
                    } else {
                        player.pause()
                    }
                }
            }
            updateButtons()
            handler.postDelayed(this, 120)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dictionary = Dictionary(this)
        onDeviceWhisper = OnDeviceWhisperTranscriber(this)
        initTextToSpeech()
        requestVideoPermissionIfNeeded()
        buildUi()
        handleAutomationIntent(intent)
        handler.post(progressWatcher)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) {
            setIntent(intent)
            handleAutomationIntent(intent)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        mediaPlayer?.release()
        videoSurface?.release()
        mediaPlayer = null
        videoSurface = null
        textToSpeech?.stop()
        textToSpeech?.shutdown()
        textToSpeech = null
        pronunciationPlayer?.release()
        pronunciationPlayer = null
        englishChineseTranslator?.close()
        englishChineseTranslator = null
        if (::dictionary.isInitialized) dictionary.close()
        super.onDestroy()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        mediaPlayer?.release()
        videoSurface?.release()
        mediaPlayer = null
        videoSurface = null
        buildUi()
        if (selectedIndex >= 0) {
            handler.postDelayed({ playLine(selectedIndex) }, 700)
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data?.data == null) return
        val uri = data.data!!
        runCatching {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        when (requestCode) {
            pickVideoRequest -> loadVideo(uri, "视频已导入。")
            pickSubtitleRequest -> loadSubtitleFile(uri)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == permissionRequest && grantResults.any { it == PackageManager.PERMISSION_GRANTED }) {
            Toast.makeText(this, "已获得视频读取权限。", Toast.LENGTH_SHORT).show()
        }
    }

    private fun buildUi() {
        val landscape = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        val root = LinearLayout(this).apply {
            orientation = if (landscape) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
            setBackgroundColor(0xFFF7F8F5.toInt())
        }

        val videoPane = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(18, 18, 18, 12)
        }
        val subtitlePane = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(12, 18, 18, 18)
        }

        val videoFrame = FrameLayout(this).apply { setBackgroundColor(0xFF101418.toInt()) }
        textureView = TextureView(this).apply {
            surfaceTextureListener = object : TextureView.SurfaceTextureListener {
                override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) {
                    videoSurface?.release()
                    videoSurface = Surface(texture)
                    currentVideoUri?.let { preparePlayer(it, readyMessage()) }
                }

                override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = Unit

                override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                    mediaPlayer?.setSurface(null)
                    videoSurface?.release()
                    videoSurface = null
                    return true
                }

                override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit
            }
        }
        videoFrame.addView(textureView, FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        videoPane.addView(videoFrame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        statusText = TextView(this).apply {
            text = "测试视频：https://youtu.be/LDVW1qlxdi4"
            textSize = 14f
            setTextColor(0xFF34434A.toInt())
            setPadding(0, 12, 0, 8)
        }
        videoPane.addView(statusText)

        currentCaptionText = TextView(this).apply {
            textSize = 18f
            setTextColor(0xFF102027.toInt())
            setBackgroundColor(0xFFEAF4F0.toInt())
            setPadding(18, 14, 18, 14)
            visibility = View.GONE
        }
        videoPane.addView(currentCaptionText, LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        val videoControls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        playPauseButton = controlButton("播放") { toggleNormalPlayback() }
        videoControls.addView(playPauseButton)
        videoControls.addView(controlButton("测试") { openTestVideo() })
        videoControls.addView(controlButton("导入") { pickVideo() })
        videoControls.addView(controlButton("上句") { moveSelection(-1) })
        videoControls.addView(controlButton("下句") { moveSelection(1) })
        videoPane.addView(videoControls)

        val subtitleControls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 8)
        }
        modeButton = controlButton("英文") {
            displayMode = displayMode.next()
            updateButtons()
            renderSubtitles()
        }
        loopButton = controlButton("Loop On") {
            loopSentence = !loopSentence
            updateButtons()
        }
        subtitleControls.addView(modeButton)
        subtitleControls.addView(loopButton)
        subtitleControls.addView(controlButton("复读") { replaySelected() })
        val generateButton = controlButton("生成") { generateCaptions() }.apply {
            setOnLongClickListener {
                showServiceUrlDialog()
                true
            }
        }
        subtitleControls.addView(generateButton)
        subtitleControls.addView(controlButton("字幕") { pickSubtitle() })
        subtitlePane.addView(subtitleControls)

        val syncControls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 8)
        }
        syncControls.addView(controlButton("早0.5秒") { adjustSubtitleOffset(-500) })
        syncControls.addView(controlButton("晚0.5秒") { adjustSubtitleOffset(500) })
        syncControls.addView(controlButton("示例字幕") { loadDemoSubtitlesForUiTest() })
        subtitlePane.addView(syncControls)

        subtitleList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        subtitleScroll = ScrollView(this).apply { addView(subtitleList) }
        subtitlePane.addView(subtitleScroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        if (landscape) {
            root.addView(videoPane, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1.25f))
            root.addView(subtitlePane, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f))
        } else {
            root.addView(videoPane, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
            root.addView(subtitlePane, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        }

        setContentView(root)
        updateButtons()
        renderSubtitles()
        openTestVideo()
    }

    private fun controlButton(label: String, action: () -> Unit): Button {
        return Button(this).apply {
            text = label
            textSize = 12f
            isAllCaps = false
            maxLines = 1
            includeFontPadding = false
            minHeight = 44
            minWidth = 0
            minimumWidth = 0
            setPadding(4, 0, 4, 0)
            setOnClickListener { action() }
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(4, 4, 4, 4)
            }
        }
    }

    private fun renderSubtitles() {
        subtitleList.removeAllViews()
        if (subtitles.isEmpty()) {
            subtitleList.addView(TextView(this).apply {
                text = "还没有真实字幕。可以点“生成”自动识别英文字幕，或点“字幕”导入匹配这个视频的 SRT。"
                textSize = 17f
                setTextColor(0xFF59686D.toInt())
                setBackgroundColor(0xFFFFFFFF.toInt())
                setPadding(18, 18, 18, 18)
            })
            updateCurrentCaption()
            return
        }

        subtitles.forEachIndexed { index, line ->
            subtitleList.addView(TextView(this).apply {
                text = line.displayText(displayMode)
                textSize = 17f
                setTextColor(if (index == selectedIndex) 0xFF0F2C35.toInt() else 0xFF27383F.toInt())
                setBackgroundColor(if (index == selectedIndex) 0xFFE0F2EA.toInt() else 0xFFFFFFFF.toInt())
                setPadding(18, 16, 18, 16)
                setOnClickListener { playLine(index) }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(0, 0, 0, 10)
            })
        }
        updateCurrentCaption()
    }

    private fun toggleNormalPlayback() {
        val player = mediaPlayer ?: return
        normalPlayback = true
        if (player.isPlaying) {
            player.pause()
            statusText.text = "已暂停。"
        } else {
            player.start()
            statusText.text = if (subtitles.isEmpty()) {
                "正常播放中。生成或导入字幕后会同步显示。"
            } else {
                "正常播放中，字幕会跟随当前时间。"
            }
        }
        updateButtons()
    }

    private fun playLine(index: Int) {
        val line = subtitles.getOrNull(index) ?: return
        normalPlayback = false
        selectedIndex = index
        renderSubtitles()
        if (currentVideoUri == null) openTestVideo()
        seekTo(startMs(line))
        mediaPlayer?.start()
        statusText.text = "正在练第 ${index + 1} 句：${formatMs(line.startMs)} - ${formatMs(line.endMs)}"
        updateButtons()
    }

    private fun replaySelected() {
        if (subtitles.isEmpty()) return
        playLine(if (selectedIndex < 0) 0 else selectedIndex)
    }

    private fun moveSelection(delta: Int) {
        if (subtitles.isEmpty()) return
        val next = if (selectedIndex < 0) 0 else (selectedIndex + delta).coerceIn(0, subtitles.lastIndex)
        playLine(next)
    }

    private fun updateButtons() {
        modeButton.text = when (displayMode) {
            DisplayMode.ENGLISH -> "英文"
            DisplayMode.CHINESE -> "中文"
            DisplayMode.BILINGUAL -> "双语"
        }
        loopButton.text = if (loopSentence) "循环" else "单次"
        playPauseButton.text = if (mediaPlayer?.isPlaying == true && normalPlayback) "暂停" else "播放"
        updateCurrentCaption()
    }

    private fun updateCurrentCaption() {
        val line = subtitles.getOrNull(selectedIndex)
        if (line == null) {
            currentCaptionText.visibility = View.GONE
        } else {
            currentCaptionText.visibility = View.VISIBLE
            currentCaptionText.text = clickableCaption(line.displayText(displayMode))
            currentCaptionText.movementMethod = LinkMovementMethod.getInstance()
            currentCaptionText.linksClickable = true
        }
    }

    private fun clickableCaption(text: String): SpannableString {
        val spannable = SpannableString(text)
        val used = BooleanArray(text.length)

        PhraseLibrary.findPhrases(text).forEach { span ->
            if (span.start >= 0 && span.end <= text.length && used.sliceArray(span.start until span.end).none { it }) {
                spannable.setSpan(lookupSpan(span.phrase), span.start, span.end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                for (i in span.start until span.end) used[i] = true
            }
        }

        Regex("[A-Za-z][A-Za-z'\\-]*").findAll(text).forEach { match ->
            val start = match.range.first
            val end = match.range.last + 1
            if (used.sliceArray(start until end).any { it }) return@forEach
            spannable.setSpan(lookupSpan(match.value), start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }

        return spannable
    }

    private fun lookupSpan(term: String): ClickableSpan {
        return object : ClickableSpan() {
            override fun onClick(widget: View) {
                showLookup(term)
            }

            override fun updateDrawState(ds: TextPaint) {
                super.updateDrawState(ds)
                ds.color = 0xFF0B6F6A.toInt()
                ds.isUnderlineText = false
            }
        }
    }

    private fun showLookup(term: String) {
        val result = dictionary.lookup(term)
        val message = buildString {
            if (result.phonetic.isNotBlank()) append(result.phonetic).append("\n\n")
            append(result.meaning)
            if (result.definition.isNotBlank() && result.definition != result.meaning) {
                append("\n\n").append(result.definition)
            }
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(result.term)
            .setMessage(message)
            .setNeutralButton("发音", null)
            .setPositiveButton("知道了", null)
            .show()
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
            speakTerm(result.term)
        }
    }

    private fun initTextToSpeech() {
        if (textToSpeechInitializing || textToSpeechReady) return
        textToSpeechInitializing = true
        textToSpeech = TextToSpeech(this) { status ->
            textToSpeechInitializing = false
            if (status == TextToSpeech.SUCCESS) {
                val availability = textToSpeech?.setLanguage(Locale.US)
                textToSpeechReady = availability != null &&
                    availability != TextToSpeech.LANG_MISSING_DATA &&
                    availability != TextToSpeech.LANG_NOT_SUPPORTED
                textToSpeech?.setSpeechRate(0.9f)
                if (textToSpeechReady) {
                    pendingSpeechTerm?.let { term ->
                        pendingSpeechTerm = null
                        speakTerm(term)
                    }
                } else {
                    pendingSpeechTerm?.let { term ->
                        pendingSpeechTerm = null
                        playOnlinePronunciation(term)
                    }
                }
            } else {
                textToSpeechReady = false
                pendingSpeechTerm?.let { term ->
                    pendingSpeechTerm = null
                    playOnlinePronunciation(term)
                }
            }
        }
    }

    private fun speakTerm(term: String) {
        val cleaned = term
            .replace(Regex("[^A-Za-z'\\-\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
        if (cleaned.isBlank()) return
        val speaker = textToSpeech
        if (speaker == null || !textToSpeechReady) {
            pendingSpeechTerm = cleaned
            if (speaker == null || textToSpeechInitializing) {
                initTextToSpeech()
                Toast.makeText(this, "正在准备系统英文发音...", Toast.LENGTH_SHORT).show()
            } else {
                pendingSpeechTerm = null
                playOnlinePronunciation(cleaned)
            }
            return
        }
        speaker.speak(cleaned, TextToSpeech.QUEUE_FLUSH, null, "lookup-${System.nanoTime()}")
    }

    private fun playOnlinePronunciation(term: String) {
        val encoded = URLEncoder.encode(term, Charsets.UTF_8.name())
        val url = "https://dict.youdao.com/dictvoice?audio=$encoded&type=2"
        Toast.makeText(this, "正在播放在线单词发音...", Toast.LENGTH_SHORT).show()
        pronunciationPlayer?.release()
        pronunciationPlayer = MediaPlayer().apply {
            setDataSource(url)
            setOnPreparedListener { it.start() }
            setOnCompletionListener {
                it.release()
                if (pronunciationPlayer === it) pronunciationPlayer = null
            }
            setOnErrorListener { player, _, _ ->
                player.release()
                if (pronunciationPlayer === player) pronunciationPlayer = null
                Toast.makeText(this@LearningActivity, "单词发音播放失败，请检查网络或系统 TTS。", Toast.LENGTH_SHORT).show()
                true
            }
            prepareAsync()
        }
    }

    private fun scrollToSelected() {
        val child = subtitleList.getChildAt(selectedIndex) ?: return
        subtitleScroll.post { subtitleScroll.smoothScrollTo(0, child.top) }
    }

    private fun openTestVideo() {
        val file = File(testVideoPath)
        if (file.exists()) {
            loadVideo(Uri.fromFile(file), "测试视频已加载，可以播放。")
        } else {
            statusText.text = "没有找到测试视频：$testVideoPath。请手动导入视频。"
        }
    }

    private fun handleAutomationIntent(intent: Intent?) {
        if (intent?.getBooleanExtra("auto_generate", false) != true) return
        handler.postDelayed({
            if (currentVideoUri == null) openTestVideo()
            handler.postDelayed({ generateCaptions() }, 1500)
        }, 2000)
    }

    private fun pickVideo() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "video/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        startActivityForResult(intent, pickVideoRequest)
    }

    private fun pickSubtitle() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        startActivityForResult(intent, pickSubtitleRequest)
    }

    private fun loadSubtitleFile(uri: Uri) {
        val loaded = contentResolver.openInputStream(uri)?.use { stream ->
            parseSrt(BufferedReader(InputStreamReader(stream)))
        }.orEmpty()
        if (loaded.isEmpty()) {
            Toast.makeText(this, "没有找到有效的 SRT 字幕。", Toast.LENGTH_LONG).show()
            return
        }
        subtitles.clear()
        subtitles.addAll(loaded)
        selectedIndex = -1
        subtitleOffsetMs = 0
        saveCachedSubtitles()
        renderSubtitles()
        statusText.text = "已导入 ${loaded.size} 条字幕。"
    }

    private fun generateCaptions() {
        if (subtitles.isNotEmpty() && subtitles.any { it.chineseText.isNullOrBlank() }) {
            translateCurrentSubtitlesOnDevice()
            return
        }
        generateCaptionsOnDeviceOrFallback()
    }

    private fun generateCaptionsOnDeviceOrFallback() {
        val uri = currentVideoUri
        if (uri == null) {
            statusText.text = "请先导入或加载视频。"
            return
        }
        if (!onDeviceWhisper.canTranscribe()) {
            statusText.text = onDeviceWhisper.status()
            return
        }
        statusText.text = "正在解码视频音频，随后会显示 Whisper 识别进度..."
        Thread {
            runCatching {
                onDeviceWhisper.transcribe(uri) { percent, processedMs, totalMs, chunkIndex, chunkCount ->
                    runOnUiThread {
                        statusText.text = buildWhisperProgressText(
                            percent,
                            processedMs,
                            totalMs,
                            chunkIndex,
                            chunkCount
                        )
                    }
                }.mapIndexed { index, segment ->
                    SubtitleLine(
                        index = index + 1,
                        startMs = segment.startMs,
                        endMs = segment.endMs,
                        englishText = segment.text,
                        chineseText = null
                    )
                }.filter { it.englishText.isNotBlank() }
            }.onSuccess { loaded ->
                runOnUiThread {
                    if (loaded.isEmpty()) {
                        statusText.text = "手机端 Whisper 没有生成有效字幕。"
                    } else {
                        subtitles.clear()
                        subtitles.addAll(loaded)
                        selectedIndex = -1
                        subtitleOffsetMs = 0
                        saveCachedSubtitles()
                        renderSubtitles()
                        statusText.text = "手机端已生成 ${loaded.size} 条英文字幕。再次点“生成”可在手机端补中文翻译。"
                    }
                }
            }.onFailure { error ->
                runOnUiThread {
                    statusText.text = "手机端 Whisper 失败：${error.message}"
                }
            }
        }.start()
    }

    private fun buildWhisperProgressText(
        percent: Int,
        processedMs: Int,
        totalMs: Int,
        chunkIndex: Int,
        chunkCount: Int
    ): String {
        val total = if (totalMs > 0) formatMs(totalMs) else "--:--"
        val processed = formatMs(processedMs.coerceAtLeast(0))
        val chunkText = if (chunkCount > 0) "第 ${chunkIndex + 1}/$chunkCount 段" else "准备识别"
        return "手机端 Whisper 生成中：${percent.coerceIn(0, 100)}%（$processed / $total，$chunkText）。small.en 准确率较好，但手机端会比较慢。"
    }

    private fun generateCaptionsFromService() {
        val serviceUrl = currentServiceUrl()
        statusText.text = "正在调用 Whisper 服务生成英文字幕..."
        Thread {
            runCatching {
                val url = URL(serviceUrl)
                val connection = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 15_000
                    readTimeout = 30 * 60 * 1000
                }
                if (connection.responseCode !in 200..299) {
                    error("HTTP ${connection.responseCode}: ${connection.errorStream?.bufferedReader()?.readText().orEmpty()}")
                }
                connection.inputStream.bufferedReader().use { it.readText() }
            }.onSuccess { json ->
                val loaded = parseTranscriptJson(json)
                runOnUiThread {
                    if (loaded.isEmpty()) {
                        statusText.text = "没有生成字幕。"
                    } else {
                        subtitles.clear()
                        subtitles.addAll(loaded)
                        selectedIndex = -1
                        subtitleOffsetMs = 0
                        saveCachedSubtitles()
                        renderSubtitles()
                        statusText.text = "已生成并缓存 ${loaded.size} 条英文字幕。"
                    }
                }
            }.onFailure { error ->
                runOnUiThread {
                    statusText.text = "生成字幕失败：${error.message}"
                    Toast.makeText(this, "请先启动 Whisper 服务。真机可长按“生成”设置电脑 IP。", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun translateCurrentSubtitlesOnDevice() {
        val pending = subtitles
            .mapIndexed { index, line -> index to line }
            .filter { (_, line) -> line.chineseText.isNullOrBlank() && line.englishText.isNotBlank() }
        if (pending.isEmpty()) {
            statusText.text = "当前字幕已经有中文翻译。"
            return
        }
        val translator = englishChineseTranslator ?: createEnglishChineseTranslator().also {
            englishChineseTranslator = it
        }
        statusText.text = "正在手机端准备英译中模型，首次使用需要下载一次模型..."
        translator.downloadModelIfNeeded(DownloadConditions.Builder().build())
            .addOnSuccessListener {
                statusText.text = "正在手机端翻译 ${pending.size} 句字幕..."
                translateSubtitleAt(translator, pending, 0)
            }
            .addOnFailureListener { error ->
                statusText.text = "手机端翻译模型准备失败：${error.message}"
                Toast.makeText(this, "请先让手机联网下载一次英译中模型。下载后可离线翻译。", Toast.LENGTH_LONG).show()
            }
    }

    private fun translateSubtitleAt(
        translator: Translator,
        pending: List<Pair<Int, SubtitleLine>>,
        position: Int
    ) {
        if (position >= pending.size) {
            saveCachedSubtitles()
            renderSubtitles()
            statusText.text = "已在手机端完成 ${pending.size} 句中文翻译，并缓存到本机。"
            return
        }
        val (subtitleIndex, line) = pending[position]
        translator.translate(line.englishText)
            .addOnSuccessListener { translated ->
                subtitles[subtitleIndex] = line.copy(chineseText = translated.trim().ifBlank { null })
                if (position % 5 == 0 || position == pending.lastIndex) {
                    renderSubtitles()
                    statusText.text = "手机端翻译中：${position + 1}/${pending.size}"
                }
                translateSubtitleAt(translator, pending, position + 1)
            }
            .addOnFailureListener { error ->
                saveCachedSubtitles()
                renderSubtitles()
                statusText.text = "手机端翻译到第 ${position + 1} 句失败：${error.message}"
            }
    }

    private fun createEnglishChineseTranslator(): Translator {
        val options = TranslatorOptions.Builder()
            .setSourceLanguage(TranslateLanguage.ENGLISH)
            .setTargetLanguage(TranslateLanguage.CHINESE)
            .build()
        return Translation.getClient(options)
    }

    private fun currentServiceUrl(): String {
        return getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(serviceUrlKey, defaultServiceUrl)
            .orEmpty()
            .ifBlank { defaultServiceUrl }
    }

    private fun showServiceUrlDialog() {
        val input = EditText(this).apply {
            setSingleLine(true)
            setText(currentServiceUrl())
            setSelection(text.length)
        }
        AlertDialog.Builder(this)
            .setTitle("Whisper 服务地址")
            .setMessage("模拟器默认用 10.0.2.2。真机请填电脑局域网 IP，例如：http://192.168.1.23:8765/transcribe?video=backpacking")
            .setView(input)
            .setPositiveButton("保存") { _, _ ->
                getSharedPreferences(prefsName, MODE_PRIVATE)
                    .edit()
                    .putString(serviceUrlKey, input.text.toString().trim())
                    .apply()
                Toast.makeText(this, "已保存服务地址。", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun loadDemoSubtitlesForUiTest() {
        subtitles.clear()
        subtitles.addAll(loadDemoSubtitles())
        selectedIndex = -1
        subtitleOffsetMs = 0
        renderSubtitles()
        statusText.text = "已加载示例字幕，仅用于测试界面，不是这个视频的真实字幕。"
    }

    private fun adjustSubtitleOffset(deltaMs: Int) {
        subtitleOffsetMs += deltaMs
        renderSubtitles()
        statusText.text = "字幕偏移：${subtitleOffsetMs / 1000.0f} 秒。负数提前，正数延后。"
    }

    private fun loadVideo(uri: Uri, message: String) {
        currentVideoUri = uri
        val cacheMessage = loadCachedSubtitles(uri)
        val readyMessage = cacheMessage ?: message
        if (videoSurface == null || !textureView.isAvailable) {
            statusText.text = "$readyMessage 正在准备视频画面。"
            return
        }
        preparePlayer(uri, readyMessage)
    }

    private fun preparePlayer(uri: Uri, message: String) {
        val surface = videoSurface ?: return
        mediaPlayer?.release()
        mediaPlayer = MediaPlayer().apply {
            setSurface(surface)
            setDataSource(this@LearningActivity, uri)
            setOnPreparedListener {
                statusText.text = message
                if (selectedIndex >= 0) seekTo(startMs(subtitles[selectedIndex]))
            }
            setOnErrorListener { _, _, _ ->
                statusText.text = "Could not open this video."
                true
            }
            prepareAsync()
        }
    }

    private fun seekTo(positionMs: Int) {
        val player = mediaPlayer ?: return
        val safePosition = positionMs.coerceAtLeast(0)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            player.seekTo(safePosition.toLong(), MediaPlayer.SEEK_CLOSEST)
        } else {
            @Suppress("DEPRECATION")
            player.seekTo(safePosition)
        }
    }

    private fun requestVideoPermissionIfNeeded() {
        val permission = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            Manifest.permission.READ_MEDIA_VIDEO
        } else {
            Manifest.permission.READ_EXTERNAL_STORAGE
        }
        if (ContextCompat.checkSelfPermission(this, permission) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(permission), permissionRequest)
        }
    }

    private fun loadDemoSubtitles(): List<SubtitleLine> {
        return assets.open("backpacking_demo_subtitles.srt").use { stream ->
            parseSrt(BufferedReader(InputStreamReader(stream)))
        }
    }

    private fun parseSrt(reader: BufferedReader): List<SubtitleLine> {
        val result = mutableListOf<SubtitleLine>()
        while (true) {
            val number = readNextNonBlankLine(reader) ?: break
            val timing = reader.readLine() ?: break
            val textLines = mutableListOf<String>()
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isBlank()) break
                textLines.add(line)
            }
            val parts = timing.split("-->")
            if (parts.size == 2 && textLines.isNotEmpty()) {
                result.add(
                    SubtitleLine(
                        index = number.trim().toIntOrNull() ?: result.size + 1,
                        startMs = parseTimestamp(parts[0].trim()),
                        endMs = parseTimestamp(parts[1].trim()),
                        englishText = textLines.first(),
                        chineseText = textLines.drop(1).joinToString("\n").ifBlank { null }
                    )
                )
            }
        }
        return result
    }

    private fun parseTranscriptJson(json: String): List<SubtitleLine> {
        val objects = Regex("\\{([^{}]*)\\}").findAll(json).map { it.groupValues[1] }
        return objects.mapIndexedNotNull { index, body ->
            val start = numberField(body, "start") ?: return@mapIndexedNotNull null
            val end = numberField(body, "end") ?: return@mapIndexedNotNull null
            val text = stringField(body, "text").takeIf { it.isNotBlank() } ?: return@mapIndexedNotNull null
            val translation = stringField(body, "translation").takeIf { it.isNotBlank() }
            SubtitleLine(
                index = index + 1,
                startMs = (start * 1000).toInt(),
                endMs = (end * 1000).toInt(),
                englishText = text,
                chineseText = translation
            )
        }.toList()
    }

    private fun numberField(body: String, name: String): Double? {
        return Regex("\"$name\"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)").find(body)?.groupValues?.get(1)?.toDoubleOrNull()
    }

    private fun stringField(body: String, name: String): String {
        val raw = Regex("\"$name\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"").find(body)?.groupValues?.get(1).orEmpty()
        return raw
            .replace("\\n", "\n")
            .replace("\\\"", "\"")
            .replace("\\\\", "\\")
    }

    private fun saveCachedSubtitles() {
        val uri = currentVideoUri ?: return
        if (subtitles.isEmpty()) return
        runCatching {
            val array = JSONArray()
            subtitles.forEach { line ->
                array.put(JSONObject().apply {
                    put("index", line.index)
                    put("startMs", line.startMs)
                    put("endMs", line.endMs)
                    put("englishText", line.englishText)
                    put("chineseText", line.chineseText ?: JSONObject.NULL)
                })
            }
            subtitleCacheFile(uri).writeText(array.toString(), Charsets.UTF_8)
        }.onFailure {
            Toast.makeText(this, "字幕缓存保存失败：${it.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun loadCachedSubtitles(uri: Uri): String? {
        return runCatching {
            val file = subtitleCacheFile(uri)
            if (!file.exists()) return null
            val array = JSONArray(file.readText(Charsets.UTF_8))
            val loaded = mutableListOf<SubtitleLine>()
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                loaded.add(
                    SubtitleLine(
                        index = item.optInt("index", i + 1),
                        startMs = item.getInt("startMs"),
                        endMs = item.getInt("endMs"),
                        englishText = item.getString("englishText"),
                        chineseText = item.optString("chineseText").takeIf { it.isNotBlank() && it != "null" }
                    )
                )
            }
            if (loaded.isEmpty()) return null
            subtitles.clear()
            subtitles.addAll(loaded)
            selectedIndex = -1
            subtitleOffsetMs = 0
            renderSubtitles()
            "已加载缓存字幕 ${loaded.size} 条。点“生成”可重新生成更新字幕。"
        }.getOrNull()
    }

    private fun subtitleCacheFile(uri: Uri): File {
        val dir = File(filesDir, subtitleCacheDirName).apply { mkdirs() }
        return File(dir, "${stableCacheKey(uri)}.json")
    }

    private fun stableCacheKey(uri: Uri): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(uri.toString().toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun readNextNonBlankLine(reader: BufferedReader): String? {
        while (true) {
            val line = reader.readLine() ?: return null
            if (line.isNotBlank()) return line
        }
    }

    private fun parseTimestamp(value: String): Int {
        val main = value.replace(',', '.').split(":")
        if (main.size != 3) return 0
        val seconds = main[2].split(".")
        return main[0].toIntOrNull().orZero() * 60 * 60 * 1000 +
            main[1].toIntOrNull().orZero() * 60 * 1000 +
            seconds.getOrNull(0).orEmpty().toIntOrNull().orZero() * 1000 +
            seconds.getOrNull(1).orEmpty().padEnd(3, '0').take(3).toIntOrNull().orZero()
    }

    private fun startMs(line: SubtitleLine): Int = (line.startMs + subtitleOffsetMs).coerceAtLeast(0)

    private fun endMs(line: SubtitleLine): Int = (line.endMs + subtitleOffsetMs).coerceAtLeast(startMs(line) + 1)

    private fun currentSubtitleIndex(currentMs: Int): Int {
        for (index in subtitles.indices.reversed()) {
            val line = subtitles[index]
            if (currentMs >= startMs(line) && currentMs < endMs(line)) return index
        }
        return -1
    }

    private fun playbackEndMs(index: Int, line: SubtitleLine): Int {
        val start = startMs(line)
        val displayedEnd = endMs(line)
        val trimmedEnd = displayedEnd - sentenceEndTrimMs
        val nextStartCap = subtitles.getOrNull(index + 1)?.let { startMs(it) - nextSentenceGuardMs }
        val cappedEnd = listOfNotNull(trimmedEnd, nextStartCap).minOrNull() ?: trimmedEnd
        val minimumEnd = (start + 300).coerceAtMost(displayedEnd)
        return cappedEnd.coerceIn(minimumEnd, displayedEnd)
    }

    private fun formatMs(ms: Int): String {
        val totalSeconds = ms / 1000
        return String.format(Locale.US, "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    private fun readyMessage(): String {
        return if (subtitles.isEmpty()) {
            "视频已就绪。可点“生成”自动识别英文字幕，或点“字幕”导入 SRT。"
        } else {
            "视频已就绪。播放时字幕会同步跟随。"
        }
    }

    private fun Int?.orZero(): Int = this ?: 0

    private data class SubtitleLine(
        val index: Int,
        val startMs: Int,
        val endMs: Int,
        val englishText: String,
        val chineseText: String?
    ) {
        fun displayText(mode: DisplayMode): String {
            return when (mode) {
                DisplayMode.ENGLISH -> englishText
                DisplayMode.CHINESE -> chineseText ?: englishText
                DisplayMode.BILINGUAL -> if (chineseText.isNullOrBlank()) englishText else "$englishText\n$chineseText"
            }
        }
    }

    private enum class DisplayMode {
        ENGLISH,
        BILINGUAL,
        CHINESE;

        fun next(): DisplayMode {
            return when (this) {
                ENGLISH -> BILINGUAL
                BILINGUAL -> CHINESE
                CHINESE -> ENGLISH
            }
        }
    }
}
