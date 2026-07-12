package com.codex.videolearnenglish

import android.Manifest
import android.app.AlertDialog
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.SurfaceTexture
import android.graphics.Matrix
import android.graphics.drawable.GradientDrawable
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
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
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.SeekBar
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import android.os.Handler
import android.os.Looper
import android.text.TextPaint
import org.json.JSONArray
import org.json.JSONObject

class LearningActivity : Activity() {
    private lateinit var textureView: TextureView
    private lateinit var videoPreviewImage: ImageView
    private lateinit var statusText: TextView
    private lateinit var currentCaptionText: TextView
    private lateinit var subtitleList: LinearLayout
    private lateinit var subtitleScroll: ScrollView
    private lateinit var playPauseButton: Button
    private lateinit var modeButton: Button
    private lateinit var loopButton: Button
    private lateinit var currentTranslationButton: Button
    private lateinit var playbackSeekBar: SeekBar
    private lateinit var playbackTimeText: TextView
    private lateinit var transientNavRow: LinearLayout
    private lateinit var dictionary: Dictionary
    private lateinit var onDeviceWhisper: OnDeviceWhisperTranscriber

    private val handler = Handler(Looper.getMainLooper())
    private val subtitles = mutableListOf<SubtitleLine>()
    private var mediaPlayer: MediaPlayer? = null
    private var videoSurface: Surface? = null
    private var currentVideoUri: Uri? = null
    private var selectedIndex = -1
    private var displayMode = DisplayMode.ENGLISH
    private var showCurrentTranslation = false
    private var loopSentence = true
    private var normalPlayback = false
    private var subtitleOffsetMs = 0
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var textToSpeechInitializing = false
    private var pendingSpeechTerm: String? = null
    private var pronunciationPlayer: MediaPlayer? = null
    private var englishChineseTranslator: Translator? = null
    private var pendingResumePositionMs = 0
    private var lastProgressSaveAtMs = 0L
    private var isUserSeeking = false
    private var pendingStartAfterSeek = false
    private var showingWordbook = false
    private var pendingWordbookExample: WordbookEntry? = null
    private var learningReturnSnapshot: LearningSnapshot? = null
    private var wordbookReturnDay: String? = null
    private var playingWordbookExample = false
    private var pendingPreparedMessage: String? = null
    private var pendingPrepareSeekMs: Int? = null
    private var pendingPreparePlayWhenReady = false
    private var currentTrackInfo: MediaTrackInfo? = null
    private var trackMismatchWarningShown = false
    private var videoPreviewToken = 0
    private var pendingExportBilingual = false
    private var translationInProgress = false

    private val pickVideoRequest = 81
    private val pickSubtitleRequest = 82
    private val permissionRequest = 83
    private val notificationPermissionRequest = 84
    private val exportSubtitleRequest = 85
    private val testVideoPath = "/sdcard/Download/Full Gear List for Solo Backpacking.mp4"
    private val prefsName = "video_english_learning"
    private val serviceUrlKey = "whisper_service_url"
    private val serviceUrlCandidatesKey = "whisper_service_url_candidates"
    private val lastVideoUriKey = "last_video_uri"
    private val lastVideoPositionKey = "last_video_position_ms"
    private val lastVideoSelectedIndexKey = "last_video_selected_index"
    private val lastVideoNormalPlaybackKey = "last_video_normal_playback"
    private val videoStatePrefix = "video_state_"
    private val videoStatePositionKey = "position_ms"
    private val videoStateSelectedIndexKey = "selected_index"
    private val videoStateNormalPlaybackKey = "normal_playback"
    private val videoStateSubtitleOffsetKey = "subtitle_offset_ms"
    private val emulatorServiceUrl = "http://10.0.2.2:8765/transcribe"
    private val phoneUsbServiceUrl = "http://127.0.0.1:8765/transcribe"
    private val legacyEmulatorServiceUrl = "http://10.0.2.2:8765/transcribe?video=backpacking"
    private val subtitleCacheDirName = "subtitles_cache"
    private val wordbookFileName = "wordbook_history.json"
    private val sentenceEndTrimMs = 250
    private val nextSentenceGuardMs = 80
    private val seekBarProgressMax = 1000
    private val progressWatcher = object : Runnable {
        override fun run() {
            val player = mediaPlayer
            if (player?.isPlaying == true && normalPlayback) {
                val currentMs = player.currentPosition
                if (pauseAtVideoTrackEndIfNeeded(currentMs)) {
                    updatePlaybackSeekBar()
                    updateButtons()
                    handler.postDelayed(this, 120)
                    return
                }
                val index = currentSubtitleIndex(currentMs)
                if (index != selectedIndex) {
                    selectedIndex = index
                    renderSubtitles()
                    scrollToSelected()
                }
                updateCurrentCaption()
                saveLearningStateThrottled()
            } else if (player?.isPlaying == true && selectedIndex >= 0) {
                val line = subtitles.getOrNull(selectedIndex)
                if (line != null && player.currentPosition >= playbackEndMs(selectedIndex, line)) {
                    if (playingWordbookExample) {
                        player.pause()
                    } else if (loopSentence) {
                        seekTo(startMs(line), playWhenReady = true)
                    } else {
                        player.pause()
                    }
                }
                saveLearningStateThrottled()
            }
            updatePlaybackSeekBar()
            updateButtons()
            handler.postDelayed(this, 120)
        }
    }
    private var captionReceiverRegistered = false
    private val captionGenerationReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: android.content.Context?, intent: Intent?) {
            when (intent?.action) {
                CaptionGenerationService.ACTION_PROGRESS -> {
                    statusText.text = intent.getStringExtra(CaptionGenerationService.EXTRA_MESSAGE).orEmpty()
                }
                CaptionGenerationService.ACTION_DONE -> {
                    val uriText = intent.getStringExtra(CaptionGenerationService.EXTRA_VIDEO_URI)
                    val count = intent.getIntExtra(CaptionGenerationService.EXTRA_COUNT, 0)
                    if (uriText == currentVideoUri?.toString()) {
                        val message = currentVideoUri?.let { loadCachedSubtitles(it) }
                        statusText.text = message ?: "字幕已生成并缓存 $count 条。"
                    } else {
                        statusText.text = "字幕已在后台生成完成，重新导入对应视频会自动加载。"
                    }
                }
                CaptionGenerationService.ACTION_TRANSLATION_DONE -> {
                    translationInProgress = false
                    val uriText = intent.getStringExtra(CaptionGenerationService.EXTRA_VIDEO_URI)
                    val count = intent.getIntExtra(CaptionGenerationService.EXTRA_COUNT, 0)
                    val source = intent.getStringExtra(CaptionGenerationService.EXTRA_MESSAGE).orEmpty()
                    if (uriText == currentVideoUri?.toString()) {
                        currentVideoUri?.let { loadCachedSubtitles(it) }
                        statusText.text = "已用${source}完成 $count 句中文翻译，并缓存到本机。"
                    } else {
                        statusText.text = "后台翻译已完成，重新导入对应视频会自动加载。"
                    }
                }
                CaptionGenerationService.ACTION_ERROR -> {
                    translationInProgress = false
                    val message = intent.getStringExtra(CaptionGenerationService.EXTRA_MESSAGE).orEmpty()
                    val taskKind = intent.getStringExtra(CaptionGenerationService.EXTRA_TASK_KIND).orEmpty()
                    val label = if (
                        taskKind == CaptionGenerationService.TASK_TRANSLATE_REMOTE ||
                        taskKind == CaptionGenerationService.TASK_TRANSLATE_PHONE
                    ) {
                        "中文翻译失败，英文字幕已保留"
                    } else {
                        "后台任务失败"
                    }
                    statusText.text = "$label：$message"
                    Toast.makeText(this@LearningActivity, "$label：$message", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dictionary = Dictionary(this)
        onDeviceWhisper = OnDeviceWhisperTranscriber(this)
        initTextToSpeech()
        requestVideoPermissionIfNeeded()
        buildUi()
        registerCaptionGenerationReceiver()
        handleAutomationIntent(intent)
        handler.post(progressWatcher)
    }

    override fun onPause() {
        saveLearningState()
        clearKeepScreenOn()
        super.onPause()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) {
            setIntent(intent)
            handleAutomationIntent(intent)
        }
    }

    override fun onDestroy() {
        saveLearningState()
        clearKeepScreenOn()
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
        unregisterCaptionGenerationReceiver()
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
            pickVideoRequest -> {
                learningReturnSnapshot = null
                wordbookReturnDay = null
                playingWordbookExample = false
                loadVideo(uri, "视频已导入。")
            }
            pickSubtitleRequest -> loadSubtitleFile(uri)
            exportSubtitleRequest -> exportSubtitlesToUri(uri, pendingExportBilingual)
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

    override fun onBackPressed() {
        if (showingWordbook) {
            buildUi()
        } else {
            super.onBackPressed()
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
            val top = 18 + statusBarHeightPx()
            val bottom = if (landscape) 30 else 12
            setPadding(18, top, 18, bottom)
        }
        val subtitlePane = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val top = if (landscape) 8 + statusBarHeightPx() else 8
            setPadding(12, top, 18, 18)
        }

        val videoFrame = FrameLayout(this).apply { setBackgroundColor(0xFF101418.toInt()) }
        textureView = TextureView(this).apply {
            surfaceTextureListener = object : TextureView.SurfaceTextureListener {
                override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) {
                    videoSurface?.release()
                    videoSurface = Surface(texture)
                    currentVideoUri?.let {
                        val message = pendingPreparedMessage ?: readyMessage()
                        val seekMs = pendingPrepareSeekMs
                        val playWhenReady = pendingPreparePlayWhenReady
                        pendingPreparedMessage = null
                        pendingPrepareSeekMs = null
                        pendingPreparePlayWhenReady = false
                        preparePlayer(it, message, explicitSeekMs = seekMs, playWhenReadyAfterPrepare = playWhenReady)
                    }
                }

                override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) {
                    mediaPlayer?.let { fitVideoInsideView(it.videoWidth, it.videoHeight) }
                }

                override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                    mediaPlayer?.setSurface(null)
                    videoSurface?.release()
                    videoSurface = null
                    return true
                }

                override fun onSurfaceTextureUpdated(surface: SurfaceTexture) {
                    hideVideoPreview()
                }
            }
        }
        videoFrame.addView(textureView, FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        videoPreviewImage = ImageView(this).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(0xFF101418.toInt())
            visibility = View.GONE
        }
        videoFrame.addView(videoPreviewImage, FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        if (landscape) {
            videoPane.addView(videoFrame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        } else {
            videoPane.addView(videoFrame, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, portraitVideoHeightPx()))
        }

        statusText = TextView(this).apply {
            text = "测试视频：https://youtu.be/LDVW1qlxdi4"
            textSize = if (landscape) 12f else 14f
            setTextColor(0xFF34434A.toInt())
            setPadding(0, if (landscape) 8 else 12, 0, 6)
            if (landscape) maxLines = 2
        }
        videoPane.addView(statusText)

        transientNavRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        videoPane.addView(transientNavRow)

        val playbackProgressRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        playbackSeekBar = SeekBar(this).apply {
            max = 1000
            progress = 0
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                    if (!fromUser) return
                    val player = mediaPlayer ?: return
                    val duration = player.duration.takeIf { it > 0 } ?: return
                    val targetMs = (duration.toLong() * progress / seekBarProgressMax).toInt()
                    updatePlaybackTimeText(targetMs, duration)
                }

                override fun onStartTrackingTouch(seekBar: SeekBar?) {
                    isUserSeeking = true
                }

                override fun onStopTrackingTouch(seekBar: SeekBar?) {
                    val player = mediaPlayer
                    if (player != null) {
                        val duration = player.duration.takeIf { it > 0 } ?: 0
                        val targetMs = (duration.toLong() * (seekBar?.progress ?: 0) / seekBarProgressMax).toInt()
                        normalPlayback = true
                        selectedIndex = currentSubtitleIndex(targetMs)
                        seekTo(targetMs, playWhenReady = player.isPlaying)
                        renderSubtitles()
                        scrollToSelected()
                        saveLearningState()
                    }
                    isUserSeeking = false
                }
            })
        }
        playbackProgressRow.addView(playbackSeekBar, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        playbackTimeText = TextView(this).apply {
            text = "00:00 / 00:00"
            textSize = 12f
            setTextColor(0xFF52636A.toInt())
            gravity = Gravity.CENTER_VERTICAL
            setPadding(8, 0, 0, 0)
        }
        playbackProgressRow.addView(playbackTimeText, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        videoPane.addView(playbackProgressRow, LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        currentCaptionText = TextView(this).apply {
            textSize = 18f
            setTextColor(0xFF102027.toInt())
            setBackgroundColor(0xFFEAF4F0.toInt())
            setPadding(18, 14, 18, 14)
            visibility = View.GONE
        }
        videoPane.addView(currentCaptionText, LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

        val controlsPane = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 6, 0, 8)
        }

        val videoControls = controlRow()
        playPauseButton = controlButton("播放") { toggleNormalPlayback() }
        videoControls.addView(playPauseButton)
        videoControls.addView(controlButton("导入") { pickVideo() })
        videoControls.addView(controlButton("上句") { moveSelection(-1) })
        videoControls.addView(controlButton("下句") { moveSelection(1) })
        controlsPane.addView(videoControls)

        val subtitleControls = controlRow()
        modeButton = controlButton("英文") {
            displayMode = displayMode.next()
            updateButtons()
            renderSubtitles()
            translateIfNeededForDisplay()
        }.apply {
            setOnLongClickListener {
                showTranslationSourceDialog()
                true
            }
        }
        loopButton = controlButton("Loop On") {
            loopSentence = !loopSentence
            updateButtons()
        }
        currentTranslationButton = controlButton("翻译关") {
            showCurrentTranslation = !showCurrentTranslation
            updateButtons()
            translateIfNeededForDisplay()
        }
        subtitleControls.addView(currentTranslationButton)
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
        controlsPane.addView(subtitleControls)

        val syncControls = controlRow()
        syncControls.addView(controlButton("早0.5秒") { adjustSubtitleOffset(-500) })
        syncControls.addView(controlButton("晚0.5秒") { adjustSubtitleOffset(500) })
        syncControls.addView(controlButton("导出") { showExportSubtitleDialog() })
        syncControls.addView(controlButton("单词本") { showWordbook() })
        controlsPane.addView(syncControls)
        if (landscape) {
            subtitlePane.addView(controlsPane, LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        } else {
            videoPane.addView(controlsPane, LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }

        subtitleList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        subtitleScroll = ScrollView(this).apply { addView(subtitleList) }
        subtitlePane.addView(subtitleScroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        if (landscape) {
            root.addView(videoPane, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1.25f))
            root.addView(subtitlePane, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f))
        } else {
            root.addView(videoPane, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            root.addView(subtitlePane, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        }

        setContentView(root)
        updateButtons()
        updateTransientNavigation()
        renderSubtitles()
        currentVideoUri?.let { showVideoPreview(it, pendingResumePositionMs) }
        if (currentVideoUri == null) {
            restoreLastSessionOrOpenTest()
        }
        showingWordbook = false
    }

    private fun controlRow(): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 4, 0, 4)
        }
    }

    private fun portraitVideoHeightPx(): Int {
        val horizontalPadding = dp(36)
        val widthBased = ((resources.displayMetrics.widthPixels - horizontalPadding).coerceAtLeast(dp(240)) * 9f / 16f).toInt()
        val maxHeight = (resources.displayMetrics.heightPixels * 0.32f).toInt()
        val minHeight = (resources.displayMetrics.heightPixels * 0.18f).toInt()
        return widthBased.coerceIn(minHeight, maxHeight)
    }

    private fun statusBarHeightPx(): Int {
        val resourceId = resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (resourceId > 0) resources.getDimensionPixelSize(resourceId) else dp(24)
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
            setTextColor(0xFF17333A.toInt())
            background = roundedBackground(0xFFE2E8E5.toInt(), 10f)
            setPadding(4, 0, 4, 0)
            setOnClickListener { action() }
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                setMargins(4, 0, 4, 0)
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
        playingWordbookExample = false
        if (player.isPlaying) {
            player.pause()
            statusText.text = "已暂停。"
        } else {
            ensureVideoSurfaceBound()
            hideVideoPreview()
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
        scrollToSelected()
        if (currentVideoUri == null) openTestVideo()
        seekTo(startMs(line), playWhenReady = true)
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
        currentTranslationButton.text = if (showCurrentTranslation) "翻译开" else "翻译关"
        playPauseButton.text = if (mediaPlayer?.isPlaying == true && normalPlayback) "暂停" else "播放"
        updateKeepScreenOn()
        updateCurrentCaption()
    }

    private fun updateTransientNavigation() {
        if (!::transientNavRow.isInitialized) return
        transientNavRow.removeAllViews()
        val hasLearningReturn = learningReturnSnapshot != null
        val hasWordbookReturn = wordbookReturnDay != null && learningReturnSnapshot != null
        if (!hasLearningReturn && !hasWordbookReturn) {
            transientNavRow.visibility = View.GONE
            return
        }
        transientNavRow.visibility = View.VISIBLE
        if (hasLearningReturn) {
            transientNavRow.addView(controlButton("回学习") { returnToLearningSnapshot() })
        }
        if (hasWordbookReturn) {
            transientNavRow.addView(controlButton("回单词本") { returnToWordbook() })
        }
    }

    private fun updateKeepScreenOn() {
        if (mediaPlayer?.isPlaying == true) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            clearKeepScreenOn()
        }
    }

    private fun clearKeepScreenOn() {
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun updateCurrentCaption() {
        val line = subtitles.getOrNull(selectedIndex)
        if (line == null) {
            currentCaptionText.visibility = View.GONE
        } else {
            currentCaptionText.visibility = View.VISIBLE
            currentCaptionText.text = clickableCaption(line.currentCaptionText(showCurrentTranslation))
            currentCaptionText.movementMethod = LinkMovementMethod.getInstance()
            currentCaptionText.linksClickable = true
        }
    }

    private fun updatePlaybackSeekBar() {
        if (!::playbackSeekBar.isInitialized || isUserSeeking) return
        val player = mediaPlayer ?: run {
            playbackSeekBar.progress = 0
            return
        }
        val duration = runCatching { player.duration }.getOrDefault(0)
        val position = runCatching { player.currentPosition }.getOrDefault(0)
        playbackSeekBar.progress = if (duration > 0) {
            (position.toLong() * seekBarProgressMax / duration).toInt().coerceIn(0, seekBarProgressMax)
        } else {
            0
        }
        updatePlaybackTimeText(position, duration)
    }

    private fun updatePlaybackTimeText(positionMs: Int, durationMs: Int) {
        if (!::playbackTimeText.isInitialized) return
        playbackTimeText.text = "${formatMs(positionMs.coerceAtLeast(0))} / ${formatMs(durationMs.coerceAtLeast(0))}"
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
        saveWordbookEntry(result, currentWordbookContext())
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

    private fun currentSentenceForWordbook(): String {
        val line = subtitles.getOrNull(selectedIndex)
        return line?.displayText(DisplayMode.BILINGUAL)
            ?: currentCaptionText.text?.toString().orEmpty()
    }

    private fun currentWordbookContext(): WordbookContext {
        val line = subtitles.getOrNull(selectedIndex)
        return if (line != null) {
            WordbookContext(
                subtitleIndex = selectedIndex,
                startMs = line.startMs,
                endMs = line.endMs,
                englishText = line.englishText,
                chineseText = line.chineseText.orEmpty(),
                sentence = line.displayText(DisplayMode.BILINGUAL),
                videoUri = currentVideoUri?.toString().orEmpty(),
                videoId = currentVideoUri?.let { videoIdForUri(it) }.orEmpty()
            )
        } else {
            WordbookContext(
                sentence = currentSentenceForWordbook(),
                videoUri = currentVideoUri?.toString().orEmpty(),
                videoId = currentVideoUri?.let { videoIdForUri(it) }.orEmpty()
            )
        }
    }

    private fun saveWordbookEntry(result: LookupResult, context: WordbookContext) {
        runCatching {
            val file = wordbookFile()
            val existing = if (file.exists()) JSONArray(file.readText(Charsets.UTF_8)) else JSONArray()
            val next = JSONArray()
            next.put(JSONObject().apply {
                put("time", System.currentTimeMillis())
                put("term", result.term)
                put("phonetic", result.phonetic)
                put("meaning", result.meaning.lineSequence().firstOrNull().orEmpty())
                put("definition", result.definition)
                put("sentence", context.sentence)
                put("englishText", context.englishText)
                put("chineseText", context.chineseText)
                put("subtitleIndex", context.subtitleIndex)
                put("startMs", context.startMs)
                put("endMs", context.endMs)
                put("videoUri", context.videoUri)
                put("videoId", context.videoId)
            })
            val keepCount = existing.length().coerceAtMost(999)
            for (i in 0 until keepCount) {
                next.put(existing.getJSONObject(i))
            }
            file.writeText(next.toString(), Charsets.UTF_8)
        }
    }

    private fun showWordbook() {
        val entries = readWordbookEntries()
        showingWordbook = true
        if (learningReturnSnapshot == null) {
            wordbookReturnDay = null
            pendingWordbookExample = null
            playingWordbookExample = false
        }
        mediaPlayer?.pause()
        updateButtons()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFFF7F8F5.toInt())
            setPadding(18, 72, 18, 18)
        }
        val header = wordbookHeader("单词本", "返回") { returnFromWordbookHome() }
        root.addView(header)
        addWordbookReturnControls(root)

        if (entries.isEmpty()) {
            root.addView(emptyWordbookView(), LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        } else {
            val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
            entries.groupBy { wordbookDay(it) }.forEach { (day, dayEntries) ->
                val uniqueCount = dayEntries.map { it.term.lowercase(Locale.US) }.distinct().size
                list.addView(wordbookDateRow(day, uniqueCount, dayEntries.size) {
                    showWordbookDay(day, dayEntries)
                })
            }
            root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        setContentView(root)
    }

    private fun returnFromWordbookHome() {
        showingWordbook = false
        if (learningReturnSnapshot == null) {
            wordbookReturnDay = null
            pendingWordbookExample = null
            playingWordbookExample = false
        }
        buildUi()
    }

    private fun showWordbookDay(day: String, entries: List<WordbookEntry>) {
        showingWordbook = true
        wordbookReturnDay = day
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFFF7F8F5.toInt())
            setPadding(18, 72, 18, 18)
        }
        root.addView(wordbookHeader(day, "日期") { showWordbook() })
        addWordbookReturnControls(root)

        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val timeFormat = chinaDateFormat("HH:mm")
        entries.forEach { entry ->
            list.addView(wordbookEntryCard(entry, timeFormat.format(Date(entry.time))))
        }
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
    }

    private fun wordbookHeader(title: String, backLabel: String, backAction: () -> Unit): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, 14)
            addView(Button(context).apply {
                text = backLabel
                textSize = 15f
                gravity = Gravity.CENTER
                isAllCaps = false
                includeFontPadding = false
                minWidth = 0
                minimumWidth = 0
                setTextColor(0xFF17333A.toInt())
                background = roundedBackground(0xFFE2E8E5.toInt(), 10f)
                setPadding(8, 0, 8, 0)
                setOnClickListener { backAction() }
            }, LinearLayout.LayoutParams(dp(72), dp(44)))
            addView(TextView(context).apply {
                text = title
                textSize = 24f
                setTextColor(0xFF102027.toInt())
                setPadding(18, 0, 0, 0)
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
    }

    private fun addWordbookReturnControls(root: LinearLayout) {
        if (learningReturnSnapshot == null) return
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 14)
        }
        row.addView(controlButton("回学习") { returnToLearningSnapshot() })
        root.addView(row)
    }

    private fun emptyWordbookView(): TextView {
        return TextView(this).apply {
            text = "还没有查词记录。\n在字幕当前句里点击单词或短语后，会按日期自动保存到这里。"
            textSize = 17f
            setTextColor(0xFF52636A.toInt())
            gravity = Gravity.CENTER
            setPadding(24, 24, 24, 24)
        }
    }

    private fun wordbookDateRow(day: String, uniqueCount: Int, lookupCount: Int, action: () -> Unit): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20, 16, 20, 16)
            background = roundedBackground(0xFFFFFFFF.toInt(), 12f)
            setOnClickListener { action() }
            addView(TextView(context).apply {
                text = day
                textSize = 20f
                setTextColor(0xFF102027.toInt())
            })
            addView(TextView(context).apply {
                text = "$uniqueCount 个单词/短语，$lookupCount 次查询"
                textSize = 14f
                setTextColor(0xFF52636A.toInt())
                setPadding(0, 8, 0, 0)
            })
        }.apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(0, 0, 0, 12)
            }
        }
    }

    private fun wordbookEntryCard(entry: WordbookEntry, timeLabel: String): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20, 16, 20, 16)
            background = roundedBackground(0xFFFFFFFF.toInt(), 12f)

            val titleRow = LinearLayout(context).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            titleRow.addView(TextView(context).apply {
                text = entry.term
                textSize = 22f
                setTextColor(0xFF0B6F6A.toInt())
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            titleRow.addView(TextView(context).apply {
                text = "听"
                textSize = 12f
                gravity = Gravity.CENTER
                setTextColor(0xFF17333A.toInt())
                background = roundedBackground(0xFFE2E8E5.toInt(), 10f)
                setOnClickListener { speakTerm(entry.term) }
            }, LinearLayout.LayoutParams(64, 40))
            addView(titleRow)

            val phoneticLine = buildString {
                if (entry.phonetic.isNotBlank()) append(entry.phonetic).append("  ")
                append(timeLabel)
            }
            addView(TextView(context).apply {
                text = phoneticLine
                textSize = 13f
                setTextColor(0xFF6A7A80.toInt())
                setPadding(0, 4, 0, 0)
            })

            if (entry.meaning.isNotBlank()) {
                addView(TextView(context).apply {
                    text = entry.meaning
                    textSize = 16f
                    setTextColor(0xFF223238.toInt())
                    setPadding(0, 10, 0, 0)
                })
            }

            val example = buildString {
                if (entry.englishText.isNotBlank()) append(entry.englishText) else append(entry.sentence)
                if (entry.chineseText.isNotBlank()) append("\n").append(entry.chineseText)
            }.trim()
            if (example.isNotBlank()) {
                addView(TextView(context).apply {
                    text = example
                    textSize = 16f
                    setTextColor(0xFF27383F.toInt())
                    setPadding(16, 12, 16, 12)
                    background = roundedBackground(0xFFEAF4F0.toInt(), 10f)
                    setOnClickListener { playWordbookExample(entry) }
                }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    setMargins(0, 12, 0, 0)
                })
            }
        }.apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(0, 0, 0, 12)
            }
        }
    }

    private fun playWordbookExample(entry: WordbookEntry) {
        if (learningReturnSnapshot == null) {
            learningReturnSnapshot = captureLearningSnapshot()
        }
        wordbookReturnDay = wordbookDay(entry)
        val targetUri = entry.videoUri.takeIf { it.isNotBlank() }?.let { Uri.parse(it) }
        if (targetUri != null && !isWordbookVideoCurrentlyLoaded(entry, targetUri)) {
            pendingWordbookExample = entry
            pendingResumePositionMs = 0
            selectedIndex = -1
            normalPlayback = false
            buildUi()
            handler.postDelayed({
                runCatching {
                    if (targetUri.scheme == "content") {
                        contentResolver.takePersistableUriPermission(targetUri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    loadVideo(targetUri, "正在播放单词本例句，点“回学习”回到刚才的视频。", restoreSavedState = false)
                }.onFailure { error ->
                    pendingWordbookExample = null
                    statusText.text = "无法打开这个单词本例句的原视频：${error.message}。请重新导入原视频后再试。"
                }
            }, 250)
            return
        }

        buildUi()
        handler.postDelayed({
            playWordbookExampleInLoadedVideo(entry)
        }, 500)
    }

    private fun isWordbookVideoCurrentlyLoaded(entry: WordbookEntry, targetUri: Uri): Boolean {
        val current = currentVideoUri ?: return false
        val currentId = videoIdForUri(current)
        val targetId = entry.videoId.ifBlank { videoIdForUri(targetUri) }
        return currentId == targetId
    }

    private fun playWordbookExampleInLoadedVideo(entry: WordbookEntry) {
        val matchedIndex = findWordbookSubtitleIndex(entry)
        if (matchedIndex != null) {
            playingWordbookExample = true
            playLine(matchedIndex)
            statusText.text = "正在播放单词本例句，点“回学习”回到刚才的视频。"
        } else if (entry.startMs > 0) {
            playingWordbookExample = true
            normalPlayback = false
            selectedIndex = currentSubtitleIndex(entry.startMs)
            seekTo(entry.startMs, playWhenReady = true)
            renderSubtitles()
            scrollToSelected()
            statusText.text = "正在播放单词本例句：${formatMs(entry.startMs)}，点“回学习”回到刚才的视频。"
        } else {
            Toast.makeText(this, "这个记录没有可回放的时间点。", Toast.LENGTH_SHORT).show()
        }
        updateTransientNavigation()
    }

    private fun captureLearningSnapshot(): LearningSnapshot? {
        val uri = currentVideoUri ?: return null
        return LearningSnapshot(
            uri = uri,
            positionMs = mediaPlayer?.currentPosition ?: pendingResumePositionMs,
            selectedIndex = selectedIndex,
            normalPlayback = normalPlayback,
            subtitleOffsetMs = subtitleOffsetMs,
            subtitles = subtitles.toList()
        )
    }

    private fun returnToLearningSnapshot() {
        val snapshot = learningReturnSnapshot ?: return
        learningReturnSnapshot = null
        wordbookReturnDay = null
        pendingWordbookExample = null
        playingWordbookExample = false
        pendingResumePositionMs = snapshot.positionMs.coerceAtLeast(0)
        selectedIndex = snapshot.selectedIndex
        normalPlayback = snapshot.normalPlayback
        subtitleOffsetMs = snapshot.subtitleOffsetMs
        subtitles.clear()
        subtitles.addAll(snapshot.subtitles)
        buildUi()
        handler.postDelayed({
            loadVideo(snapshot.uri, "已回到刚才学习的视频。", loadCached = false)
        }, 250)
    }

    private fun returnToWordbook() {
        val day = wordbookReturnDay ?: return
        val entries = readWordbookEntries().filter { wordbookDay(it) == day }
        if (entries.isEmpty()) {
            showWordbook()
        } else {
            showWordbookDay(day, entries)
        }
    }

    private fun findWordbookSubtitleIndex(entry: WordbookEntry): Int? {
        val exactIndex = entry.subtitleIndex.takeIf { it in subtitles.indices }
        if (exactIndex != null) {
            val line = subtitles[exactIndex]
            if (entry.englishText.isBlank() || line.englishText == entry.englishText || kotlin.math.abs(line.startMs - entry.startMs) <= 800) {
                return exactIndex
            }
        }
        return subtitles.indexOfFirst {
            kotlin.math.abs(it.startMs - entry.startMs) <= 800 ||
                (entry.englishText.isNotBlank() && it.englishText == entry.englishText)
        }.takeIf { it >= 0 }
    }

    private fun readWordbookEntries(): List<WordbookEntry> {
        return runCatching {
            val file = wordbookFile()
            if (!file.exists()) return emptyList()
            val array = JSONArray(file.readText(Charsets.UTF_8))
            (0 until array.length()).mapNotNull { index ->
                val item = array.optJSONObject(index) ?: return@mapNotNull null
                WordbookEntry(
                    time = item.optLong("time", 0L),
                    term = item.optString("term"),
                    phonetic = item.optString("phonetic"),
                    sentence = item.optString("sentence"),
                    meaning = item.optString("meaning"),
                    definition = item.optString("definition"),
                    englishText = item.optString("englishText", item.optString("sentence").lineSequence().firstOrNull().orEmpty()),
                    chineseText = item.optString("chineseText"),
                    subtitleIndex = item.optInt("subtitleIndex", -1),
                    startMs = item.optInt("startMs", 0),
                    endMs = item.optInt("endMs", 0),
                    videoUri = item.optString("videoUri"),
                    videoId = item.optString("videoId")
                )
            }
        }.getOrElse { emptyList() }.filter { it.term.isNotBlank() }
    }

    private fun wordbookDay(entry: WordbookEntry): String = chinaDateFormat("yyyy-MM-dd").format(Date(entry.time))

    private fun wordbookFile(): File = File(filesDir, wordbookFileName)

    private fun chinaDateFormat(pattern: String): SimpleDateFormat {
        return SimpleDateFormat(pattern, Locale.CHINA).apply {
            timeZone = TimeZone.getTimeZone("Asia/Shanghai")
        }
    }

    private fun roundedBackground(color: Int, radius: Float): GradientDrawable {
        return GradientDrawable().apply {
            setColor(color)
            cornerRadius = radius
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
        subtitleScroll.post {
            val target = (child.top - subtitleScroll.height / 3).coerceAtLeast(0)
            subtitleScroll.smoothScrollTo(0, target)
        }
    }

    private fun openTestVideo() {
        val file = File(testVideoPath)
        if (file.exists()) {
            val uri = Uri.fromFile(file)
            loadVideo(uri, "测试视频已加载，可以播放。")
        } else {
            statusText.text = "没有找到测试视频：$testVideoPath。请手动导入视频。"
        }
    }

    private fun restoreLastSessionOrOpenTest() {
        val prefs = getSharedPreferences(prefsName, MODE_PRIVATE)
        val uriText = prefs.getString(lastVideoUriKey, null)
        if (uriText.isNullOrBlank()) {
            openTestVideo()
            return
        }
        val uri = Uri.parse(uriText)
        applySavedLearningState(uri)
        runCatching {
            if (uri.scheme == "content") {
                contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            loadVideo(uri, "已恢复上次学习的视频。")
        }.onFailure {
            pendingResumePositionMs = 0
            selectedIndex = -1
            normalPlayback = false
            statusText.text = "上次视频无法打开，已回到测试视频。"
            openTestVideo()
        }
    }

    private fun saveLearningStateThrottled() {
        val now = System.currentTimeMillis()
        if (now - lastProgressSaveAtMs >= 3_000L) {
            saveLearningState()
            lastProgressSaveAtMs = now
        }
    }

    private fun saveLearningState() {
        if (playingWordbookExample || pendingWordbookExample != null) return
        val uri = currentVideoUri ?: return
        val position = mediaPlayer?.currentPosition ?: pendingResumePositionMs
        saveLearningState(uri, position, selectedIndex, normalPlayback)
    }

    private fun saveLearningState(uri: Uri, positionMs: Int, selected: Int, normal: Boolean) {
        val safePosition = positionMs.coerceAtLeast(0)
        val prefs = getSharedPreferences(prefsName, MODE_PRIVATE)
        val editor = prefs.edit()
            .putString(lastVideoUriKey, uri.toString())
            .putInt(lastVideoPositionKey, safePosition)
            .putInt(lastVideoSelectedIndexKey, selected)
            .putBoolean(lastVideoNormalPlaybackKey, normal)
        val prefix = videoStateKeyPrefix(uri)
        editor
            .putString("${prefix}uri", uri.toString())
            .putInt("${prefix}$videoStatePositionKey", safePosition)
            .putInt("${prefix}$videoStateSelectedIndexKey", selected)
            .putBoolean("${prefix}$videoStateNormalPlaybackKey", normal)
            .putInt("${prefix}$videoStateSubtitleOffsetKey", subtitleOffsetMs)
            .apply()
    }

    private fun applySavedLearningState(uri: Uri) {
        val state = readSavedLearningState(uri)
        if (state == null) {
            pendingResumePositionMs = 0
            selectedIndex = -1
            normalPlayback = false
            subtitleOffsetMs = 0
            return
        }
        pendingResumePositionMs = state.positionMs
        selectedIndex = state.selectedIndex
        normalPlayback = state.normalPlayback
        subtitleOffsetMs = state.subtitleOffsetMs
    }

    private fun readSavedLearningState(uri: Uri): SavedVideoState? {
        val prefs = getSharedPreferences(prefsName, MODE_PRIVATE)
        val prefix = videoStateKeyPrefix(uri)
        val positionKey = "${prefix}$videoStatePositionKey"
        if (!prefs.contains(positionKey)) return null
        return SavedVideoState(
            positionMs = prefs.getInt(positionKey, 0).coerceAtLeast(0),
            selectedIndex = prefs.getInt("${prefix}$videoStateSelectedIndexKey", -1),
            normalPlayback = prefs.getBoolean("${prefix}$videoStateNormalPlaybackKey", false),
            subtitleOffsetMs = prefs.getInt("${prefix}$videoStateSubtitleOffsetKey", 0)
        )
    }

    private fun videoStateKeyPrefix(uri: Uri): String {
        return "$videoStatePrefix${stableCacheKey(uri)}_"
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

    private fun showExportSubtitleDialog() {
        if (subtitles.isEmpty()) {
            Toast.makeText(this, "还没有字幕，先生成或导入字幕后再导出。", Toast.LENGTH_LONG).show()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("导出字幕")
            .setItems(arrayOf("仅英文字幕（SRT）", "英中双字幕（SRT）")) { _, which ->
                pendingExportBilingual = which == 1
                startExportSubtitleDocument(pendingExportBilingual)
            }
            .show()
    }

    private fun startExportSubtitleDocument(bilingual: Boolean) {
        val suffix = if (bilingual) "en_zh" else "en"
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "application/x-subrip"
            putExtra(Intent.EXTRA_TITLE, "${exportBaseName()}_$suffix.srt")
        }
        startActivityForResult(intent, exportSubtitleRequest)
    }

    private fun exportSubtitlesToUri(uri: Uri, bilingual: Boolean) {
        runCatching {
            val content = buildSrtContent(bilingual)
            contentResolver.openOutputStream(uri, "wt")?.use { output ->
                output.write(content.toByteArray(Charsets.UTF_8))
            } ?: error("无法打开导出位置")
        }.onSuccess {
            val mode = if (bilingual) "英中双字幕" else "英文字幕"
            statusText.text = "已导出$mode。"
            Toast.makeText(this, "字幕导出成功。", Toast.LENGTH_SHORT).show()
        }.onFailure {
            statusText.text = "导出字幕失败：${it.message}"
            Toast.makeText(this, "导出字幕失败：${it.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun buildSrtContent(bilingual: Boolean): String {
        return buildString {
            subtitles.forEachIndexed { index, line ->
                append(index + 1).append('\n')
                val start = line.startMs.coerceAtLeast(0)
                val end = line.endMs.coerceAtLeast(start + 1)
                append(formatSrtTime(start))
                    .append(" --> ")
                    .append(formatSrtTime(end))
                    .append('\n')
                append(line.englishText.trim()).append('\n')
                if (bilingual && !line.chineseText.isNullOrBlank()) {
                    append(line.chineseText.trim()).append('\n')
                }
                append('\n')
            }
        }
    }

    private fun formatSrtTime(ms: Int): String {
        val safeMs = ms.coerceAtLeast(0)
        val hours = safeMs / 3_600_000
        val minutes = (safeMs % 3_600_000) / 60_000
        val seconds = (safeMs % 60_000) / 1000
        val millis = safeMs % 1000
        return String.format(Locale.US, "%02d:%02d:%02d,%03d", hours, minutes, seconds, millis)
    }

    private fun exportBaseName(): String {
        val rawName = currentVideoUri?.lastPathSegment
            ?.substringAfterLast('/')
            ?.substringBeforeLast('.')
            ?.takeIf { it.isNotBlank() }
            ?: "video_subtitles"
        return rawName.replace(Regex("[^A-Za-z0-9._-]+"), "_").trim('_').ifBlank { "video_subtitles" }
    }

    private fun generateCaptions() {
        if (subtitles.isNotEmpty() && subtitles.any { it.chineseText.isNullOrBlank() }) {
            translateCurrentSubtitlesWithRemoteFallback()
            return
        }
        startCaptionGenerationService()
    }

    private fun translateIfNeededForDisplay() {
        if (translationInProgress || subtitles.isEmpty()) return
        val wantsTranslation = showCurrentTranslation ||
            displayMode == DisplayMode.CHINESE ||
            displayMode == DisplayMode.BILINGUAL
        if (wantsTranslation && subtitles.any { it.chineseText.isNullOrBlank() && it.englishText.isNotBlank() }) {
            translateCurrentSubtitlesWithRemoteFallback()
        }
    }

    private fun showTranslationSourceDialog() {
        if (subtitles.isEmpty()) {
            Toast.makeText(this, "当前视频还没有字幕。", Toast.LENGTH_SHORT).show()
            return
        }
        val translated = subtitles.filter { !it.chineseText.isNullOrBlank() }
        val computerCount = translated.count { it.translationSource == TranslationSource.COMPUTER.id }
        val phoneCount = translated.count { it.translationSource == TranslationSource.PHONE.id }
        val importedCount = translated.count { it.translationSource == TranslationSource.IMPORTED.id }
        val unknownCount = translated.size - computerCount - phoneCount - importedCount
        val message = buildString {
            append("当前中文翻译来源：\n")
            append("电脑端：").append(computerCount).append(" 句\n")
            append("手机端：").append(phoneCount).append(" 句\n")
            append("导入字幕：").append(importedCount).append(" 句\n")
            append("未知/旧缓存：").append(unknownCount.coerceAtLeast(0)).append(" 句\n\n")
            append("重新翻译会覆盖当前中文字幕，并和英文字幕一起保存到本地缓存。")
        }
        AlertDialog.Builder(this)
            .setTitle("中文翻译来源")
            .setMessage(message)
            .setPositiveButton("电脑端重翻") { _, _ ->
                subtitles.replaceAll { it.copy(chineseText = null, translationSource = null) }
                saveCachedSubtitles()
                renderSubtitles()
                updateCurrentCaption()
                startSubtitleTranslationService(CaptionGenerationService.TASK_TRANSLATE_REMOTE)
            }
            .setNeutralButton("手机端重翻") { _, _ ->
                subtitles.replaceAll { it.copy(chineseText = null, translationSource = null) }
                saveCachedSubtitles()
                renderSubtitles()
                updateCurrentCaption()
                startSubtitleTranslationService(CaptionGenerationService.TASK_TRANSLATE_PHONE)
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun startCaptionGenerationService() {
        val uri = currentVideoUri
        if (uri == null) {
            statusText.text = "请先导入或加载视频。"
            return
        }
        requestNotificationPermissionIfNeeded()
        statusText.text = "已开始后台生成字幕。可以切到其他软件，完成后会自动加载字幕。"
        val intent = Intent(this, CaptionGenerationService::class.java)
            .putExtra(CaptionGenerationService.EXTRA_VIDEO_URI, uri.toString())
            .putExtra(CaptionGenerationService.EXTRA_SERVICE_URL, currentServiceUrl())
            .putExtra(CaptionGenerationService.EXTRA_SERVICE_URLS, JSONArray(serviceUrlCandidates()).toString())
            .putExtra(CaptionGenerationService.EXTRA_TASK_KIND, CaptionGenerationService.TASK_GENERATE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun startSubtitleTranslationService(taskKind: String) {
        val uri = currentVideoUri
        if (uri == null) {
            statusText.text = "请先导入或加载视频。"
            return
        }
        if (subtitles.none { it.englishText.isNotBlank() }) {
            statusText.text = "当前视频还没有英文字幕，请先生成或导入字幕。"
            return
        }
        requestNotificationPermissionIfNeeded()
        translationInProgress = true
        val label = if (taskKind == CaptionGenerationService.TASK_TRANSLATE_REMOTE) "电脑端" else "手机端"
        statusText.text = "已开始后台${label}翻译。完成后会自动更新本地字幕。"
        val intent = Intent(this, CaptionGenerationService::class.java)
            .putExtra(CaptionGenerationService.EXTRA_VIDEO_URI, uri.toString())
            .putExtra(CaptionGenerationService.EXTRA_SERVICE_URL, currentServiceUrl())
            .putExtra(CaptionGenerationService.EXTRA_SERVICE_URLS, JSONArray(serviceUrlCandidates()).toString())
            .putExtra(CaptionGenerationService.EXTRA_TASK_KIND, taskKind)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    private fun registerCaptionGenerationReceiver() {
        if (captionReceiverRegistered) return
        val filter = IntentFilter().apply {
            addAction(CaptionGenerationService.ACTION_PROGRESS)
            addAction(CaptionGenerationService.ACTION_DONE)
            addAction(CaptionGenerationService.ACTION_TRANSLATION_DONE)
            addAction(CaptionGenerationService.ACTION_ERROR)
        }
        ContextCompat.registerReceiver(
            this,
            captionGenerationReceiver,
            filter,
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        captionReceiverRegistered = true
    }

    private fun unregisterCaptionGenerationReceiver() {
        if (!captionReceiverRegistered) return
        runCatching { unregisterReceiver(captionGenerationReceiver) }
        captionReceiverRegistered = false
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            notificationPermissionRequest
        )
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
        val uri = currentVideoUri
        if (uri == null) {
            statusText.text = "请先导入或加载视频。"
            return
        }
        val serviceUrl = currentServiceUrl()
        statusText.text = "正在检查 Whisper 服务连接..."
        Thread {
            var audioForUpload: RemoteAudioFile? = null
            var shouldDeleteAudioCache = false
            runCatching {
                ensureWhisperServiceReachable(serviceUrl)
                runOnUiThread {
                    statusText.text = "Whisper 服务已连接，正在从视频中提取音频..."
                }
                val audio = onDeviceWhisper.extractAudioForRemoteUpload(uri) { percent ->
                    runOnUiThread {
                        val bounded = percent.coerceIn(0, 100)
                        val stage = when {
                            bounded < 75 -> "正在提取音频"
                            bounded < 100 -> "正在压缩音频"
                            else -> "音频准备完成"
                        }
                        statusText.text = "$stage：$bounded%"
                    }
                }
                audioForUpload = audio
                runOnUiThread {
                    statusText.text = "音频已准备：${formatMs(audio.durationMs)}，${formatBytes(audio.file.length())}，正在上传到 Whisper 服务..."
                }
                try {
                    val jobId = createTranscriptJobWithRetry(serviceUrl, audio)
                    pollTranscriptJob(serviceUrl, jobId)
                } catch (error: Exception) {
                    if (error.message.orEmpty().contains("HTTP 404")) {
                        runOnUiThread {
                            statusText.text = "服务端不支持进度任务接口，改用同步生成字幕..."
                        }
                        requestTranscriptSync(serviceUrl, audio)
                    } else {
                        throw error
                    }
                }
            }.onSuccess { json ->
                val loaded = parseTranscriptJson(json)
                shouldDeleteAudioCache = loaded.isNotEmpty()
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
                        statusText.text = "已生成并缓存 ${loaded.size} 条字幕。"
                    }
                }
            }.onFailure { error ->
                runOnUiThread {
                    statusText.text = "生成字幕失败：${friendlyGenerationError(error)}"
                    audioForUpload?.let { audio ->
                        statusText.text = "生成字幕失败：${friendlyGenerationError(error)}。已保留音频缓存：${formatBytes(audio.file.length())}，下次会直接重试上传。"
                    }
                    Toast.makeText(this, "字幕失败时会保留音频缓存，下次可直接重试。", Toast.LENGTH_LONG).show()
                }
            }.also {
                if (shouldDeleteAudioCache) {
                    onDeviceWhisper.deleteCachedRemoteAudio(uri)
                }
            }
        }.start()
    }

    private fun ensureWhisperServiceReachable(serviceUrl: String) {
        try {
            requestJobJson(URL(pingUrl(serviceUrl)))
        } catch (error: Exception) {
            if (error.message.orEmpty().contains("HTTP 401")) {
                error("服务 token 不匹配。服务窗口如果打印了 Auth token，App 地址必须在末尾加 ?token=那个token；本地局域网也可以重新运行脚本且不带 -UseAuth 来关闭 token。")
            }
            error(
                "连接不上 Whisper 服务。USB 调试用 http://127.0.0.1:8765/transcribe 并执行 adb reverse；" +
                    "同一局域网用电脑 Wi-Fi IP，例如 http://192.168.0.133:8765/transcribe。原始错误：${error.message}"
            )
        }
    }

    private fun createTranscriptJobWithRetry(serviceUrl: String, audio: RemoteAudioFile): String {
        return try {
            createTranscriptJob(serviceUrl, audio)
        } catch (first: Exception) {
            val message = first.message.orEmpty()
            if (!message.contains("unexpected end", ignoreCase = true) &&
                !message.contains("Connection reset", ignoreCase = true) &&
                !message.contains("Broken pipe", ignoreCase = true)
            ) {
                throw first
            }
            Thread.sleep(1_500)
            ensureWhisperServiceReachable(serviceUrl)
            createTranscriptJob(serviceUrl, audio)
        }
    }

    private fun friendlyGenerationError(error: Throwable): String {
        val message = error.message.orEmpty()
        return when {
            message.contains("服务 token 不匹配") -> message
            message.contains("连接不上 Whisper 服务") -> message
            message.contains("Broken pipe", ignoreCase = true) ->
                "上传被服务端提前拒绝。最常见原因是服务启用了 token，但 App 地址没有加 ?token=...；请用服务窗口打印的完整 App URL，或重新运行局域网脚本关闭 token。原始错误：$message"
            message.contains("Failed to connect", ignoreCase = true) ||
                message.contains("Connection refused", ignoreCase = true) ->
                "连接不上 Whisper 服务。USB 调试请确认服务在运行并已执行 adb reverse tcp:8765 tcp:8765；局域网请填电脑 Wi-Fi IP，例如 http://192.168.0.133:8765/transcribe，并确认防火墙允许访问。原始错误：$message"
            message.contains("unexpected end", ignoreCase = true) ||
                message.contains("Connection reset", ignoreCase = true) ->
                "上传连接中断。通常是电脑端 Whisper 服务中途退出、USB reverse 断开，或局域网不稳定；请重新启动服务后重试。原始错误：$message"
            message.contains("HTTP 401") ->
                "服务 token 不匹配。请长按“生成”检查地址里的 token 是否和服务窗口打印的一致。"
            else -> message.ifBlank { error.javaClass.simpleName }
        }
    }

    private fun createTranscriptJob(serviceUrl: String, audio: RemoteAudioFile): String {
        val audioFile = audio.file
        val url = URL(jobCreateUrl(serviceUrl))
        val totalBytes = audioFile.length().coerceAtLeast(1L)
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Content-Type", audio.mimeType)
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(totalBytes)
        }
        var sentBytes = 0L
        connection.outputStream.use { output ->
            audioFile.inputStream().use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    output.write(buffer, 0, read)
                    sentBytes += read
                    val percent = (sentBytes * 100 / totalBytes).toInt().coerceIn(0, 100)
                    runOnUiThread {
                        statusText.text = "正在上传音频：$percent%（${formatBytes(sentBytes)} / ${formatBytes(totalBytes)}）"
                    }
                }
            }
        }
        val response = requestJobJson(connection)
        return JSONObject(response).optString("job_id").ifBlank {
            error("服务端没有返回 job_id：$response")
        }
    }

    private fun requestTranscriptSync(serviceUrl: String, audio: RemoteAudioFile): String {
        val audioFile = audio.file
        val url = URL(serviceUrl)
        val totalBytes = audioFile.length().coerceAtLeast(1L)
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 30 * 60 * 1000
            doOutput = true
            setRequestProperty("Content-Type", audio.mimeType)
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(totalBytes)
        }
        var sentBytes = 0L
        connection.outputStream.use { output ->
            audioFile.inputStream().use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    output.write(buffer, 0, read)
                    sentBytes += read
                    val percent = (sentBytes * 100 / totalBytes).toInt().coerceIn(0, 100)
                    runOnUiThread {
                        statusText.text = "正在上传音频：$percent%（同步模式）"
                    }
                }
            }
        }
        runOnUiThread {
            statusText.text = "音频上传完成，正在等待 Whisper 服务返回字幕..."
        }
        return requestJobJson(connection)
    }

    private fun pollTranscriptJob(serviceUrl: String, jobId: String): String {
        while (true) {
            val json = requestJobJson(URL(jobStatusUrl(serviceUrl, jobId)))
            val item = JSONObject(json)
            val status = item.optString("status")
            val progress = item.optInt("progress", 0).coerceIn(0, 100)
            val message = item.optString("message").ifBlank { item.optString("stage") }
            runOnUiThread {
                statusText.text = "正在生成字幕：$progress% $message"
            }
            when (status) {
                "done" -> {
                    val result = item.optJSONArray("result") ?: JSONArray()
                    return result.toString()
                }
                "error" -> error(item.optString("error").ifBlank { message.ifBlank { "服务端生成失败" } })
            }
            Thread.sleep(1_000)
        }
    }

    private fun requestJobJson(url: URL): String {
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 60_000
        }
        return requestJobJson(connection)
    }

    private fun requestJobJson(connection: HttpURLConnection): String {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) {
            error("HTTP $code: $body")
        }
        return body
    }

    private fun jobCreateUrl(serviceUrl: String): String {
        val base = serviceUrl.substringBefore("?").removeSuffix("/")
        val query = serviceUrl.substringAfter("?", "")
        val jobsBase = when {
            base.endsWith("/jobs") -> base
            base.endsWith("/transcribe") -> base.removeSuffix("/transcribe") + "/jobs"
            else -> "$base/jobs"
        }
        return if (query.isBlank()) jobsBase else "$jobsBase?$query"
    }

    private fun jobStatusUrl(serviceUrl: String, jobId: String): String {
        val createUrl = jobCreateUrl(serviceUrl)
        val base = createUrl.substringBefore("?").removeSuffix("/")
        val query = createUrl.substringAfter("?", "")
        val statusUrl = "$base/$jobId"
        return if (query.isBlank()) statusUrl else "$statusUrl?$query"
    }

    private fun translateUrl(serviceUrl: String): String {
        val base = serviceUrl.substringBefore("?").removeSuffix("/")
        val query = serviceUrl.substringAfter("?", "")
        val root = when {
            base.endsWith("/translate") -> base
            base.endsWith("/transcribe") -> base.removeSuffix("/transcribe") + "/translate"
            base.endsWith("/jobs") -> base.removeSuffix("/jobs") + "/translate"
            else -> "$base/translate"
        }
        return if (query.isBlank()) root else "$root?$query"
    }

    private fun translateCurrentSubtitlesWithRemoteFallback() {
        if (translationInProgress) {
            statusText.text = "正在翻译字幕，请稍等..."
            return
        }
        val pending = subtitles
            .mapIndexed { index, line -> index to line }
            .filter { (_, line) -> line.chineseText.isNullOrBlank() && line.englishText.isNotBlank() }
        if (pending.isEmpty()) {
            statusText.text = "当前字幕已经有中文翻译。"
            return
        }
        saveCachedSubtitles()
        startSubtitleTranslationService(CaptionGenerationService.TASK_TRANSLATE_REMOTE)
    }

    private fun requestRemoteTranslations(texts: List<String>): List<String> {
        val payload = JSONObject().apply {
            val array = JSONArray()
            texts.forEach { array.put(it) }
            put("texts", array)
        }.toString().toByteArray(Charsets.UTF_8)
        val serviceUrl = selectReachableServiceUrl(serviceUrlCandidates())
        val connection = (URL(translateUrl(serviceUrl)).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 10 * 60 * 1000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(payload.size)
        }
        connection.outputStream.use { it.write(payload) }
        val json = requestJobJson(connection)
        val array = JSONObject(json).optJSONArray("translations")
            ?: error("电脑端没有返回 translations：$json")
        return (0 until array.length()).map { array.optString(it) }
    }

    private fun translateCurrentSubtitlesOnDevice() {
        if (translationInProgress) {
            statusText.text = "正在翻译字幕，请稍等..."
            return
        }
        val pending = subtitles
            .mapIndexed { index, line -> index to line }
            .filter { (_, line) -> line.chineseText.isNullOrBlank() && line.englishText.isNotBlank() }
        if (pending.isEmpty()) {
            statusText.text = "当前字幕已经有中文翻译。"
            return
        }
        translationInProgress = true
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
                translationInProgress = false
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
            translationInProgress = false
            saveCachedSubtitles()
            renderSubtitles()
            statusText.text = "已在手机端完成 ${pending.size} 句中文翻译，并缓存到本机。"
            return
        }
        val (subtitleIndex, line) = pending[position]
        translator.translate(line.englishText)
            .addOnSuccessListener { translated ->
                    subtitles[subtitleIndex] = line.copy(
                        chineseText = translated.trim().ifBlank { null },
                        translationSource = TranslationSource.PHONE.id
                    )
                if (position % 5 == 0 || position == pending.lastIndex) {
                    renderSubtitles()
                    statusText.text = "手机端翻译中：${position + 1}/${pending.size}"
                }
                translateSubtitleAt(translator, pending, position + 1)
            }
            .addOnFailureListener { error ->
                translationInProgress = false
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
        val defaultUrl = if (isRunningOnEmulator()) emulatorServiceUrl else phoneUsbServiceUrl
        val saved = getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(serviceUrlKey, defaultUrl)
            .orEmpty()
            .ifBlank { defaultUrl }
        if (!isRunningOnEmulator() && (saved == legacyEmulatorServiceUrl || saved.contains("10.0.2.2"))) {
            return defaultUrl
        }
        if (isRunningOnEmulator() && saved == legacyEmulatorServiceUrl) {
            return emulatorServiceUrl
        }
        return saved
    }

    private fun serviceUrlCandidates(): List<String> {
        val ordered = linkedSetOf<String>()
        val defaultUrl = if (isRunningOnEmulator()) emulatorServiceUrl else phoneUsbServiceUrl
        ordered += defaultUrl
        val current = currentServiceUrl()
        if (current.isNotBlank()) ordered += current
        val saved = getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(serviceUrlCandidatesKey, null)
            .orEmpty()
        runCatching {
            val array = JSONArray(saved)
            for (i in 0 until array.length()) {
                val url = array.optString(i).trim()
                if (url.isNotBlank()) ordered += url
            }
        }
        return ordered
            .filterNot { !isRunningOnEmulator() && it.contains("10.0.2.2") }
            .ifEmpty { listOf(defaultUrl) }
    }

    private fun saveServiceUrlCandidates(urls: List<String>) {
        val cleaned = urls.map { it.trim() }.filter { it.isNotBlank() }.distinct()
        if (cleaned.isEmpty()) return
        getSharedPreferences(prefsName, MODE_PRIVATE)
            .edit()
            .putString(serviceUrlCandidatesKey, JSONArray(cleaned).toString())
            .apply()
    }

    private fun configUrl(serviceUrl: String): String {
        val base = serviceUrl.substringBefore("?").removeSuffix("/")
        val root = when {
            base.endsWith("/transcribe") -> base.removeSuffix("/transcribe")
            base.endsWith("/jobs") -> base.removeSuffix("/jobs")
            base.endsWith("/translate") -> base.removeSuffix("/translate")
            else -> base
        }
        return "$root/config"
    }

    private fun configuredServiceUrls(seedUrl: String): List<String> {
        val json = requestJobJson(URL(configUrl(seedUrl)))
        val item = JSONObject(json)
        val array = item.optJSONArray("transcribe_urls") ?: return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            array.optString(index).trim().takeIf { it.isNotBlank() }
        }
    }

    private fun selectReachableServiceUrl(candidates: List<String>): String {
        val expanded = linkedSetOf<String>()
        candidates.forEach { candidate ->
            if (candidate.isNotBlank()) expanded += candidate
            runCatching {
                val configured = configuredServiceUrls(candidate)
                if (configured.isNotEmpty()) {
                    saveServiceUrlCandidates(configured)
                    expanded.addAll(configured)
                }
            }
        }
        val errors = mutableListOf<String>()
        for (url in expanded) {
            runCatching {
                requestJobJson(URL(pingUrl(url)))
            }.onSuccess {
                getSharedPreferences(prefsName, MODE_PRIVATE)
                    .edit()
                    .putString(serviceUrlKey, url)
                    .apply()
                return url
            }.onFailure { error ->
                errors += "${url}: ${error.message}"
            }
        }
        error("所有 Whisper 地址都连接失败。${errors.takeLast(3).joinToString("；")}")
    }

    private fun isRunningOnEmulator(): Boolean {
        val fingerprint = Build.FINGERPRINT.lowercase(Locale.US)
        val model = Build.MODEL.lowercase(Locale.US)
        val manufacturer = Build.MANUFACTURER.lowercase(Locale.US)
        return fingerprint.contains("generic") ||
            fingerprint.contains("emulator") ||
            model.contains("sdk") ||
            model.contains("emulator") ||
            manufacturer.contains("genymotion")
    }

    private fun showServiceUrlDialog() {
        val input = EditText(this).apply {
            setSingleLine(true)
            setText(currentServiceUrl())
            setSelection(text.length)
        }
        AlertDialog.Builder(this)
            .setTitle("Whisper 服务地址")
            .setMessage("模拟器用 10.0.2.2。真机 USB 用 http://127.0.0.1:8765/transcribe，并先执行 adb reverse。电脑和手机同一局域网时，填电脑 Wi-Fi IP，例如 http://192.168.0.133:8765/transcribe。远程使用填公网 HTTPS 地址。")
            .setView(input)
            .setPositiveButton("保存") { _, _ ->
                getSharedPreferences(prefsName, MODE_PRIVATE)
                    .edit()
                    .putString(serviceUrlKey, input.text.toString().trim())
                    .apply()
                Toast.makeText(this, "已保存服务地址。", Toast.LENGTH_SHORT).show()
            }
            .setNeutralButton("测试") { _, _ ->
                val url = input.text.toString().trim()
                testServiceUrl(url)
            }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun testServiceUrl(serviceUrl: String) {
        if (serviceUrl.isBlank()) {
            Toast.makeText(this, "服务地址不能为空。", Toast.LENGTH_SHORT).show()
            return
        }
        statusText.text = "正在测试 Whisper 服务地址..."
        Thread {
            runCatching {
                requestJobJson(URL(pingUrl(serviceUrl)))
                serviceUrl
            }.onSuccess {
                runOnUiThread {
                    getSharedPreferences(prefsName, MODE_PRIVATE)
                        .edit()
                        .putString(serviceUrlKey, it)
                        .apply()
                    statusText.text = "Whisper 服务连接正常。可以返回后点“生成”。"
                }
            }.onFailure { error ->
                runCatching {
                    selectReachableServiceUrl(listOf(serviceUrl) + serviceUrlCandidates())
                }.onSuccess { reachable ->
                    runOnUiThread {
                        statusText.text = "原地址不可用，已自动切换到可用 Whisper 服务：${serviceLabel(reachable)}。可以返回后点“生成”。"
                    }
                }.onFailure {
                    runOnUiThread {
                        statusText.text = "Whisper 服务连接失败：${error.message}"
                    }
                }
            }
        }.start()
    }

    private fun serviceLabel(url: String): String {
        return when {
            url.contains("127.0.0.1") -> "USB"
            url.contains("10.0.2.2") -> "模拟器"
            url.startsWith("https://") -> "公网"
            else -> "局域网"
        }
    }

    private fun pingUrl(serviceUrl: String): String {
        val base = serviceUrl.substringBefore("?").removeSuffix("/")
        val query = serviceUrl.substringAfter("?", "")
        val root = when {
            base.endsWith("/transcribe") -> base.removeSuffix("/transcribe")
            base.endsWith("/jobs") -> base.removeSuffix("/jobs")
            else -> base
        }
        val url = "$root/ping"
        return if (query.isBlank()) url else "$url?$query"
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

    private fun loadVideo(uri: Uri, message: String, loadCached: Boolean = true, restoreSavedState: Boolean = loadCached) {
        val switchingVideo = currentVideoUri?.toString() != uri.toString()
        currentVideoUri = uri
        if (restoreSavedState) {
            applySavedLearningState(uri)
        }
        if (::videoPreviewImage.isInitialized) {
            showVideoPreview(uri, pendingResumePositionMs)
        }
        currentTrackInfo = readMediaTrackInfo(uri)
        trackMismatchWarningShown = false
        currentTrackInfo?.let { trackInfo ->
            if (trackInfo.hasShortVideoTrack && pendingResumePositionMs > trackInfo.safeVideoEndMs) {
                pendingResumePositionMs = trackInfo.safeVideoEndMs
                selectedIndex = currentSubtitleIndex(pendingResumePositionMs)
            }
        }
        val cacheMessage = if (loadCached) loadCachedSubtitles(uri) else null
        val readyMessage = cacheMessage ?: if (loadCached) {
            clearSubtitlesForNewVideo()
            "$message 这个视频还没有字幕，请点“生成”自动识别，或点“字幕”导入 SRT。"
        } else {
            message
        }
        if (pendingWordbookExample == null) {
            saveLearningState(uri, pendingResumePositionMs, selectedIndex, normalPlayback)
        }
        if (switchingVideo && ::textureView.isInitialized) {
            pendingPreparedMessage = readyMessage
            pendingPrepareSeekMs = pendingResumePositionMs.takeIf { it > 0 }
            pendingPreparePlayWhenReady = false
            resetVideoOutput()
            buildUi()
            return
        }
        if (videoSurface == null || !textureView.isAvailable) {
            statusText.text = "$readyMessage 正在准备视频画面。"
            return
        }
        preparePlayer(uri, readyMessage)
    }

    private fun clearSubtitlesForNewVideo() {
        subtitles.clear()
        selectedIndex = -1
        pendingWordbookExample = null
        playingWordbookExample = false
        renderSubtitles()
        updateCurrentCaption()
    }

    private fun preparePlayer(
        uri: Uri,
        message: String,
        explicitSeekMs: Int? = null,
        playWhenReadyAfterPrepare: Boolean = false
    ) {
        val surface = videoSurface ?: return
        mediaPlayer?.release()
        mediaPlayer = MediaPlayer().apply {
            setSurface(surface)
            setDataSource(this@LearningActivity, uri)
            setOnVideoSizeChangedListener { _, width, height ->
                fitVideoInsideView(width, height)
            }
            setOnPreparedListener {
                fitVideoInsideView(videoWidth, videoHeight)
                statusText.text = videoTrackWarningMessage() ?: message
                val pendingExample = pendingWordbookExample
                when {
                    explicitSeekMs != null -> seekTo(explicitSeekMs, playWhenReady = playWhenReadyAfterPrepare)
                    pendingExample != null && isWordbookVideoCurrentlyLoaded(pendingExample, uri) -> {
                        pendingWordbookExample = null
                        handler.post { playWordbookExampleInLoadedVideo(pendingExample) }
                    }
                    pendingResumePositionMs > 0 -> seekTo(pendingResumePositionMs)
                    selectedIndex >= 0 && selectedIndex <= subtitles.lastIndex -> seekTo(startMs(subtitles[selectedIndex]))
                }
                updatePlaybackSeekBar()
                renderSubtitles()
                scrollToSelected()
                if (explicitSeekMs == null && pendingResumePositionMs <= 0 && selectedIndex < 0) {
                    seekTo(0)
                }
            }
            setOnSeekCompleteListener {
                updatePlaybackSeekBar()
                saveLearningState()
                if (pendingStartAfterSeek) {
                    pendingStartAfterSeek = false
                    hideVideoPreview()
                    it.start()
                    updateButtons()
                }
            }
            setOnErrorListener { _, _, _ ->
                statusText.text = "Could not open this video."
                true
            }
            prepareAsync()
        }
    }

    private fun resetVideoOutput() {
        runCatching {
            mediaPlayer?.release()
        }
        mediaPlayer = null
        runCatching {
            videoSurface?.release()
        }
        videoSurface = null
    }

    private fun showVideoPreview(uri: Uri, positionMs: Int) {
        val token = ++videoPreviewToken
        if (::videoPreviewImage.isInitialized) {
            videoPreviewImage.visibility = View.VISIBLE
        }
        val requestedTimeUs = positionMs.coerceAtLeast(0).toLong() * 1000L
        Thread {
            val bitmap = runCatching {
                val retriever = MediaMetadataRetriever()
                try {
                    retriever.setDataSource(this, uri)
                    retriever.getFrameAtTime(requestedTimeUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                        ?: retriever.getFrameAtTime(0L, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                } finally {
                    retriever.release()
                }
            }.getOrNull()
            handler.post {
                if (token != videoPreviewToken || !::videoPreviewImage.isInitialized || mediaPlayer?.isPlaying == true) {
                    bitmap?.recycle()
                    return@post
                }
                if (bitmap != null) {
                    videoPreviewImage.setImageBitmap(bitmap)
                    videoPreviewImage.visibility = View.VISIBLE
                } else {
                    videoPreviewImage.visibility = View.GONE
                }
            }
        }.start()
    }

    private fun hideVideoPreview() {
        if (::videoPreviewImage.isInitialized) {
            videoPreviewImage.visibility = View.GONE
        }
    }

    private fun readMediaTrackInfo(uri: Uri): MediaTrackInfo? {
        return runCatching {
            val extractor = MediaExtractor()
            extractor.setDataSource(this, uri, null)
            try {
                var videoDurationMs: Int? = null
                var audioDurationMs: Int? = null
                for (index in 0 until extractor.trackCount) {
                    val format = extractor.getTrackFormat(index)
                    val mime = format.getString(MediaFormat.KEY_MIME).orEmpty()
                    if (!format.containsKey(MediaFormat.KEY_DURATION)) continue
                    val durationMs = (format.getLong(MediaFormat.KEY_DURATION) / 1000L)
                        .coerceAtMost(Int.MAX_VALUE.toLong())
                        .toInt()
                    when {
                        mime.startsWith("video/") -> videoDurationMs = maxOf(videoDurationMs ?: 0, durationMs)
                        mime.startsWith("audio/") -> audioDurationMs = maxOf(audioDurationMs ?: 0, durationMs)
                    }
                }
                MediaTrackInfo(videoDurationMs, audioDurationMs)
            } finally {
                extractor.release()
            }
        }.getOrNull()
    }

    private fun videoTrackWarningMessage(): String? {
        val info = currentTrackInfo ?: return null
        if (!info.hasShortVideoTrack) return null
        return "这个文件的视频画面只有 ${formatMs(info.videoDurationMs ?: 0)}，音频有 ${formatMs(info.audioDurationMs ?: 0)}。后面没有画面，请重新下载或修复视频文件。"
    }

    private fun pauseAtVideoTrackEndIfNeeded(currentMs: Int): Boolean {
        val info = currentTrackInfo ?: return false
        if (!info.hasShortVideoTrack || currentMs < info.safeVideoEndMs) return false
        val player = mediaPlayer ?: return false
        player.pause()
        normalPlayback = false
        seekTo(info.safeVideoEndMs)
        val warning = videoTrackWarningMessage()
        if (warning != null) {
            statusText.text = warning
            if (!trackMismatchWarningShown) {
                Toast.makeText(this, warning, Toast.LENGTH_LONG).show()
                trackMismatchWarningShown = true
            }
        }
        saveLearningState()
        return true
    }

    private fun fitVideoInsideView(videoWidth: Int, videoHeight: Int) {
        if (videoWidth <= 0 || videoHeight <= 0 || textureView.width <= 0 || textureView.height <= 0) {
            return
        }
        val viewWidth = textureView.width.toFloat()
        val viewHeight = textureView.height.toFloat()
        val videoAspect = videoWidth.toFloat() / videoHeight.toFloat()
        val viewAspect = viewWidth / viewHeight
        val scaleX: Float
        val scaleY: Float
        if (videoAspect > viewAspect) {
            scaleX = 1f
            scaleY = viewAspect / videoAspect
        } else {
            scaleX = videoAspect / viewAspect
            scaleY = 1f
        }
        val matrix = Matrix()
        matrix.setScale(scaleX, scaleY, viewWidth / 2f, viewHeight / 2f)
        textureView.setTransform(matrix)
    }

    private fun seekTo(positionMs: Int, playWhenReady: Boolean = false) {
        val player = mediaPlayer ?: return
        ensureVideoSurfaceBound()
        val safePosition = positionMs.coerceAtLeast(0)
        pendingStartAfterSeek = playWhenReady
        if (playWhenReady && player.isPlaying) {
            player.pause()
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            player.seekTo(safePosition.toLong(), MediaPlayer.SEEK_CLOSEST)
        } else {
            @Suppress("DEPRECATION")
            player.seekTo(safePosition)
        }
        updatePlaybackSeekBar()
    }

    private fun ensureVideoSurfaceBound() {
        val player = mediaPlayer ?: return
        val surface = videoSurface ?: return
        runCatching {
            player.setSurface(surface)
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
                val (englishText, chineseText) = splitSrtSubtitleText(textLines)
                result.add(
                    SubtitleLine(
                        index = number.trim().trimStart('\uFEFF').toIntOrNull() ?: result.size + 1,
                        startMs = parseTimestamp(parts[0].trim()),
                        endMs = parseTimestamp(parts[1].trim()),
                        englishText = englishText,
                        chineseText = chineseText,
                        translationSource = if (chineseText.isNullOrBlank()) null else TranslationSource.IMPORTED.id
                    )
                )
            }
        }
        return result
    }

    private fun splitSrtSubtitleText(textLines: List<String>): Pair<String, String?> {
        val cleaned = textLines.map { it.trim() }.filter { it.isNotBlank() }
        if (cleaned.isEmpty()) return "" to null
        val firstChineseLine = cleaned.indexOfFirst { containsCjk(it) }
        return if (firstChineseLine > 0) {
            cleaned.take(firstChineseLine).joinToString(" ").trim() to
                cleaned.drop(firstChineseLine).joinToString("\n").trim().ifBlank { null }
        } else if (firstChineseLine == 0) {
            cleaned.first() to cleaned.drop(1).joinToString("\n").trim().ifBlank { null }
        } else {
            cleaned.joinToString(" ").trim() to null
        }
    }

    private fun containsCjk(text: String): Boolean {
        return text.any { char ->
            char in '\u3400'..'\u4DBF' ||
                char in '\u4E00'..'\u9FFF' ||
                char in '\uF900'..'\uFAFF'
        }
    }

    private fun parseTranscriptJson(json: String): List<SubtitleLine> {
        val array = JSONArray(json)
        return mergeShortSubtitleFragments((0 until array.length()).mapNotNull { index ->
            val body = array.optJSONObject(index) ?: return@mapNotNull null
            val start = body.optDouble("start", Double.NaN).takeIf { !it.isNaN() } ?: return@mapNotNull null
            val end = body.optDouble("end", Double.NaN).takeIf { !it.isNaN() } ?: return@mapNotNull null
            val text = body.optString("text").takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val translation = body.optString("translation").takeIf { it.isNotBlank() }
            SubtitleLine(
                index = index + 1,
                startMs = (start * 1000).toInt(),
                endMs = (end * 1000).toInt(),
                englishText = text,
                chineseText = translation,
                translationSource = if (translation.isNullOrBlank()) null else TranslationSource.COMPUTER.id
            )
        })
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
                    put("translationSource", line.translationSource ?: JSONObject.NULL)
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
                        chineseText = item.optString("chineseText").takeIf { it.isNotBlank() && it != "null" },
                        translationSource = item.optString("translationSource").takeIf { it.isNotBlank() && it != "null" }
                    )
                )
            }
            if (loaded.isEmpty()) return null
            val normalized = mergeShortSubtitleFragments(loaded)
            subtitles.clear()
            subtitles.addAll(normalized)
            selectedIndex = selectedIndex.takeIf { it in subtitles.indices }
                ?: currentSubtitleIndex(pendingResumePositionMs).takeIf { it in subtitles.indices }
                ?: -1
            renderSubtitles()
            scrollToSelected()
            "已加载缓存字幕 ${normalized.size} 条。点“生成”可重新生成更新字幕。"
        }.getOrNull()
    }

    private fun mergeShortSubtitleFragments(lines: List<SubtitleLine>): List<SubtitleLine> {
        if (lines.size < 2) return lines
        val merged = mutableListOf<SubtitleLine>()
        var index = 0
        while (index < lines.size) {
            val current = lines[index]
            val next = lines.getOrNull(index + 1)
            if (next != null && shouldMergeSubtitleFragments(current, next)) {
                merged.add(
                    current.copy(
                        index = merged.size + 1,
                endMs = next.endMs,
                englishText = joinSubtitleText(current.englishText, next.englishText),
                chineseText = joinNullableSubtitleText(current.chineseText, next.chineseText),
                translationSource = if (current.translationSource == next.translationSource) current.translationSource else null
            )
        )
                index += 2
            } else {
                merged.add(current.copy(index = merged.size + 1))
                index += 1
            }
        }
        return merged
    }

    private fun shouldMergeSubtitleFragments(current: SubtitleLine, next: SubtitleLine): Boolean {
        val text = current.englishText.trim()
        if (text.isBlank() || hasSentenceEnding(text)) return false
        val gapMs = next.startMs - current.endMs
        val wordCount = text.split(Regex("\\s+")).count { it.isNotBlank() }
        val combinedLength = text.length + 1 + next.englishText.trim().length
        return gapMs <= 1_500 && combinedLength <= 140 && (wordCount <= 3 || text.length <= 24)
    }

    private fun hasSentenceEnding(text: String): Boolean {
        return Regex("[.!?][\"')\\]]*$").containsMatchIn(text.trim())
    }

    private fun joinSubtitleText(left: String, right: String): String {
        return "${left.trimEnd()} ${right.trimStart()}".trim()
    }

    private fun joinNullableSubtitleText(left: String?, right: String?): String? {
        val joined = listOfNotNull(left?.trim(), right?.trim())
            .filter { it.isNotBlank() }
            .joinToString("\n")
        return joined.ifBlank { null }
    }

    private fun subtitleCacheFile(uri: Uri): File {
        val dir = File(filesDir, subtitleCacheDirName).apply { mkdirs() }
        return File(dir, "${stableCacheKey(uri)}.json")
    }

    private fun stableCacheKey(uri: Uri): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(uri.toString().toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun videoIdForUri(uri: Uri): String = stableCacheKey(uri)

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

    private fun formatBytes(bytes: Long): String {
        val mb = bytes / 1024.0 / 1024.0
        return if (mb >= 10.0) {
            "${mb.toInt()}MB"
        } else {
            String.format(Locale.US, "%.1fMB", mb)
        }
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density + 0.5f).toInt()
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
        val chineseText: String?,
        val translationSource: String? = null
    ) {
        fun displayText(mode: DisplayMode): String {
            return when (mode) {
                DisplayMode.ENGLISH -> englishText
                DisplayMode.CHINESE -> chineseText ?: englishText
                DisplayMode.BILINGUAL -> if (chineseText.isNullOrBlank()) englishText else "$englishText\n$chineseText"
            }
        }

        fun currentCaptionText(showTranslation: Boolean): String {
            return if (showTranslation && !chineseText.isNullOrBlank()) {
                "$englishText\n$chineseText"
            } else {
                englishText
            }
        }
    }

    private enum class TranslationSource(val id: String, val label: String) {
        COMPUTER("computer", "电脑端"),
        PHONE("phone", "手机端"),
        IMPORTED("imported", "导入字幕")
    }

    private data class WordbookEntry(
        val time: Long,
        val term: String,
        val phonetic: String,
        val sentence: String,
        val meaning: String,
        val definition: String,
        val englishText: String,
        val chineseText: String,
        val subtitleIndex: Int,
        val startMs: Int,
        val endMs: Int,
        val videoUri: String,
        val videoId: String
    )

    private data class WordbookContext(
        val subtitleIndex: Int = -1,
        val startMs: Int = 0,
        val endMs: Int = 0,
        val englishText: String = "",
        val chineseText: String = "",
        val sentence: String = "",
        val videoUri: String = "",
        val videoId: String = ""
    )

    private data class LearningSnapshot(
        val uri: Uri,
        val positionMs: Int,
        val selectedIndex: Int,
        val normalPlayback: Boolean,
        val subtitleOffsetMs: Int,
        val subtitles: List<SubtitleLine>
    )

    private data class SavedVideoState(
        val positionMs: Int,
        val selectedIndex: Int,
        val normalPlayback: Boolean,
        val subtitleOffsetMs: Int
    )

    private data class MediaTrackInfo(
        val videoDurationMs: Int?,
        val audioDurationMs: Int?
    ) {
        val hasShortVideoTrack: Boolean
            get() = videoDurationMs != null &&
                audioDurationMs != null &&
                audioDurationMs - videoDurationMs > 5_000

        val safeVideoEndMs: Int
            get() = ((videoDurationMs ?: 0) - 500).coerceAtLeast(0)
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
