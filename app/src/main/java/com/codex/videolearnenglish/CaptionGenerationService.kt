package com.codex.videolearnenglish

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.TranslatorOptions
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class CaptionGenerationService : Service() {
    private lateinit var onDeviceWhisper: OnDeviceWhisperTranscriber
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    @Volatile private var lastNotificationProgress: Int = -1
    @Volatile private var running = false
    @Volatile private var currentTaskId: String? = null
    @Volatile private var currentTaskKind: String = TASK_GENERATE
    @Volatile private var lastProgressMessage: String = ""
    @Volatile private var lastProgressPercent: Int = -1
    @Volatile private var lastProgressSentAtMs: Long = 0L

    override fun onCreate() {
        super.onCreate()
        onDeviceWhisper = OnDeviceWhisperTranscriber(this)
        ensureNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val effectiveIntent = intent ?: recoverableTaskIntent() ?: run {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val uriText = effectiveIntent.getStringExtra(EXTRA_VIDEO_URI)
        val serviceUrl = effectiveIntent.getStringExtra(EXTRA_SERVICE_URL).orEmpty()
        val serviceUrls = serviceUrlCandidates(effectiveIntent, serviceUrl)
        if (uriText.isNullOrBlank() || serviceUrls.isEmpty()) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val videoUri = Uri.parse(uriText)
        val taskKind = effectiveIntent.getStringExtra(EXTRA_TASK_KIND).orEmpty().ifBlank { TASK_GENERATE }
        val requestedForceTranscribe = effectiveIntent.takeIf { it.hasExtra(EXTRA_FORCE_TRANSCRIBE) }
            ?.getBooleanExtra(EXTRA_FORCE_TRANSCRIBE, false)
        val task = effectiveIntent.getStringExtra(EXTRA_TASK_ID)?.takeIf { it.isNotBlank() }?.let { taskId ->
            CaptionTaskStore.all(this).firstOrNull { it.id == taskId }
        } ?: CaptionTaskStore.enqueue(
            this,
            videoUri,
            effectiveIntent.getStringExtra(EXTRA_VIDEO_TITLE).orEmpty(),
            taskKind,
            forceTranscribe = requestedForceTranscribe
        )
        if (running) {
            sendProgress("字幕识别与翻译仍在后台运行：${task.title}")
            return START_REDELIVER_INTENT
        }
        running = true
        active = true
        currentTaskId = task.id
        currentTaskKind = taskKind
        lastProgressMessage = ""
        lastProgressPercent = -1
        lastProgressSentAtMs = 0L
        CaptionTaskStore.markRunning(this, task.id, "正在准备后台任务")
        lastNotificationProgress = -1
        startCaptionForeground(if (taskKind == TASK_GENERATE) "正在检查 Whisper 服务连接..." else "正在准备后台翻译...")
        acquireWakeLock()
        acquireWifiLock()
        Thread {
            var success = false
            var audioForUpload: RemoteAudioFile? = null
            try {
                if (taskKind == TASK_TRANSLATE_PHONE) {
                    val count = translateCachedSubtitles(videoUri, serviceUrls, taskKind)
                    success = count > 0
                    if (success) {
                        progress("已用手机端完成 $count 句中文翻译。")
                        CaptionTaskStore.markDone(this, task.id, count)
                        sendTranslationDone(videoUri.toString(), count, "手机端")
                    } else {
                        throw IllegalStateException("没有可翻译的英文字幕。")
                    }
                    return@Thread
                }

                val selectedServiceUrl = waitForReachableService(task.id, serviceUrls, task.progress)
                val mode = if (taskKind == TASK_TRANSLATE_REMOTE) "retranslate" else "generate"
                val json = try {
                    runDurableComputerTask(task, videoUri, serviceUrls, selectedServiceUrl, mode)
                } catch (error: Exception) {
                    if (error.message.orEmpty().contains("HTTP 404") && mode == "generate") {
                        progress("电脑端服务版本较旧，改用兼容上传模式...")
                        val audio = onDeviceWhisper.extractAudioForRemoteUpload(videoUri)
                        audioForUpload = audio
                        val jobId = createTranscriptJobWithRetry(serviceUrls, selectedServiceUrl, audio, task.title)
                        pollTranscriptJob(serviceUrls, selectedServiceUrl, jobId, task.id, mode)
                    } else {
                        throw error
                    }
                }
                val count = saveCachedSubtitles(videoUri, json)
                success = count > 0
                if (success) {
                    onDeviceWhisper.deleteCachedRemoteAudio(videoUri)
                    progress("已生成并缓存 $count 条字幕。")
                    CaptionTaskStore.markDone(this, task.id, count)
                    if (taskKind == TASK_TRANSLATE_REMOTE) {
                        sendTranslationDone(videoUri.toString(), count, "电脑端")
                    } else {
                        sendDone(videoUri.toString(), count)
                    }
                } else {
                    throw IllegalStateException("没有生成字幕。")
                }
            } catch (error: Exception) {
                if (error is TaskPausedException) {
                    updateNotification("任务已暂停")
                    sendProgress("任务已暂停")
                    return@Thread
                }
                if (error is TaskCanceledException) {
                    updateNotification("任务已取消")
                    sendProgress("任务已取消")
                    return@Thread
                }
                val isTranslationTask = taskKind == TASK_TRANSLATE_REMOTE || taskKind == TASK_TRANSLATE_PHONE
                val message = buildString {
                    append(if (isTranslationTask) friendlyTranslationError(error) else friendlyGenerationError(error))
                    audioForUpload?.let { append("。已保留音频缓存：").append(formatBytes(it.file.length())).append("，下次会直接重试上传。") }
                }
                updateNotification(if (isTranslationTask) "中文翻译失败：$message" else "生成字幕失败：$message")
                CaptionTaskStore.markFailedOrRetry(this, task.id, message, MAX_AUTO_FAILURES)
                sendError(message, taskKind)
            } finally {
                running = false
                active = false
                currentTaskId = null
                releaseWakeLock()
                releaseWifiLock()
                if (!startNextQueuedTask()) {
                    stopForegroundCompat()
                    stopSelf()
                }
            }
        }.start()
        return START_REDELIVER_INTENT
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        active = false
        releaseWakeLock()
        releaseWifiLock()
        super.onDestroy()
    }

    private fun progress(message: String) {
        ensureTaskActive()
        val percent = extractPercent(message)
        percent?.let { lastNotificationProgress = it }
        val now = System.currentTimeMillis()
        val stageChanged = progressStage(message) != progressStage(lastProgressMessage)
        val percentChanged = percent != null && percent != lastProgressPercent
        val force = message != lastProgressMessage && (stageChanged || message.contains("失败") || message.contains("完成"))
        if (!force && !percentChanged && now - lastProgressSentAtMs < 700L) return
        if (!force && now - lastProgressSentAtMs < 300L) return

        lastProgressMessage = message
        percent?.let { lastProgressPercent = it }
        lastProgressSentAtMs = now
        currentTaskId?.let { CaptionTaskStore.updateProgress(this, it, message) }
        updateNotification(message)
        sendProgress(message)
    }

    private fun startNextQueuedTask(): Boolean {
        val next = CaptionTaskStore.queued(this) ?: return false
        val intent = Intent(this, CaptionGenerationService::class.java)
            .putExtra(EXTRA_TASK_ID, next.id)
            .putExtra(EXTRA_VIDEO_URI, next.uri)
            .putExtra(EXTRA_VIDEO_TITLE, next.title)
            .putExtra(EXTRA_TASK_KIND, next.taskKind.ifBlank { TASK_GENERATE })
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        return true
    }

    private fun recoverableTaskIntent(): Intent? {
        val task = CaptionTaskStore.recoverable(this) ?: return null
        return Intent(this, CaptionGenerationService::class.java)
            .putExtra(EXTRA_TASK_ID, task.id)
            .putExtra(EXTRA_VIDEO_URI, task.uri)
            .putExtra(EXTRA_VIDEO_TITLE, task.title)
            .putExtra(EXTRA_TASK_KIND, task.taskKind.ifBlank { TASK_GENERATE })
    }

    private fun ensureTaskActive() {
        val id = currentTaskId ?: return
        val task = CaptionTaskStore.all(this).firstOrNull { it.id == id } ?: return
        when (task.status) {
            CaptionTaskStatus.PAUSED -> throw TaskPausedException()
            CaptionTaskStatus.CANCELED -> throw TaskCanceledException()
            else -> Unit
        }
    }

    private fun extractPercent(message: String): Int? {
        Regex("""(\d{1,3})%""").find(message)?.let { match ->
            return match.groupValues[1].toIntOrNull()?.coerceIn(0, 100)
        }
        Regex("""(\d+)\s*/\s*(\d+)""").find(message)?.let { match ->
            val current = match.groupValues[1].toIntOrNull() ?: return null
            val total = match.groupValues[2].toIntOrNull()?.takeIf { it > 0 } ?: return null
            val fraction = current.toDouble() / total.toDouble()
            return if (message.contains("Translat", ignoreCase = true) || message.contains("\u7ffb\u8bd1")) {
                (92 + (fraction * 7).toInt()).coerceIn(92, 99)
            } else {
                (current * 100 / total).coerceIn(0, 100)
            }
        }
        return null
    }

    private fun progressStage(message: String): String {
        return when {
            message.contains("提取音频") || message.contains("压缩音频") -> "extract"
            message.contains("上传") -> "upload"
            message.contains("翻译") -> "translate"
            message.contains("Whisper") || message.contains("生成字幕") -> "transcribe"
            message.contains("保存") -> "save"
            message.contains("连接") -> "connect"
            else -> "other"
        }
    }

    private fun sendProgress(message: String) {
        sendBroadcast(Intent(ACTION_PROGRESS).setPackage(packageName).putExtra(EXTRA_MESSAGE, message))
    }

    private fun sendDone(uri: String, count: Int) {
        sendBroadcast(
            Intent(ACTION_DONE)
                .setPackage(packageName)
                .putExtra(EXTRA_VIDEO_URI, uri)
                .putExtra(EXTRA_COUNT, count)
        )
    }

    private fun sendTranslationDone(uri: String, count: Int, sourceLabel: String) {
        sendBroadcast(
            Intent(ACTION_TRANSLATION_DONE)
                .setPackage(packageName)
                .putExtra(EXTRA_VIDEO_URI, uri)
                .putExtra(EXTRA_COUNT, count)
                .putExtra(EXTRA_MESSAGE, sourceLabel)
        )
    }

    private fun sendError(message: String, taskKind: String) {
        sendBroadcast(
            Intent(ACTION_ERROR)
                .setPackage(packageName)
                .putExtra(EXTRA_MESSAGE, message)
                .putExtra(EXTRA_TASK_KIND, taskKind)
        )
    }

    private fun serviceUrlCandidates(intent: Intent?, primaryUrl: String): List<String> {
        val ordered = linkedSetOf<String>()
        val raw = intent?.getStringExtra(EXTRA_SERVICE_URLS).orEmpty()
        runCatching {
            val array = JSONArray(raw)
            for (i in 0 until array.length()) {
                val url = array.optString(i).trim()
                if (url.isNotBlank()) ordered += url
            }
        }
        if (primaryUrl.isNotBlank()) ordered += primaryUrl
        ordered += if (isRunningOnEmulator()) EMULATOR_SERVICE_URL else PHONE_USB_SERVICE_URL
        val saved = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .getString(SERVICE_URL_CANDIDATES_KEY, null)
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
            .sortedWith(compareBy { serviceUrlPriority(it) })
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
        for (url in expanded.sortedWith(compareBy { serviceUrlPriority(it) })) {
            runCatching {
                requestJobJson(URL(pingUrl(url)))
            }.onSuccess {
                getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
                    .edit()
                    .putString(SERVICE_URL_KEY, url)
                    .apply()
                progress("已选择 Whisper 服务：${serviceLabel(url)}")
                return url
            }.onFailure { error ->
                errors += "${serviceLabel(url)}: ${error.message}"
            }
        }
        error("所有 Whisper 地址都连接失败。${errors.takeLast(3).joinToString("；")}")
    }

    private fun serviceUrlPriority(url: String): Int {
        val lower = url.lowercase()
        return when {
            isRunningOnEmulator() && (lower.contains("10.0.2.2") || lower.contains("127.0.0.1")) -> 0
            !isRunningOnEmulator() && lower.contains("127.0.0.1") -> 0
            lower.startsWith("http://192.168.") || lower.startsWith("http://10.") || lower.startsWith("http://172.") -> 1
            lower.startsWith("http://") -> 2
            lower.startsWith("https://") -> 3
            else -> 4
        }
    }

    private fun isRunningOnEmulator(): Boolean {
        val fingerprint = Build.FINGERPRINT.lowercase()
        val model = Build.MODEL.lowercase()
        val product = Build.PRODUCT.lowercase()
        return fingerprint.contains("generic") ||
            fingerprint.contains("emulator") ||
            model.contains("sdk") ||
            model.contains("emulator") ||
            product.contains("sdk")
    }

    private fun configuredServiceUrls(seedUrl: String): List<String> {
        val json = requestJobJson(URL(configUrl(seedUrl)))
        val item = JSONObject(json)
        val array = item.optJSONArray("transcribe_urls") ?: return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            array.optString(index).trim().takeIf { it.isNotBlank() }
        }
    }

    private fun saveServiceUrlCandidates(urls: List<String>) {
        val cleaned = urls.map { it.trim() }.filter { it.isNotBlank() }.distinct()
        if (cleaned.isEmpty()) return
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .edit()
            .putString(SERVICE_URL_CANDIDATES_KEY, JSONArray(cleaned).toString())
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

    private fun serviceLabel(url: String): String {
        return when {
            url.contains("127.0.0.1") -> "USB"
            url.contains("10.0.2.2") -> "模拟器"
            url.startsWith("https://") -> "公网"
            else -> "局域网"
        }
    }

    private fun waitForReachableService(taskId: String, serviceUrls: List<String>, progress: Int): String {
        var retryDelayMs = 2_000L
        val fallback = serviceUrls.firstOrNull().orEmpty()
        while (true) {
            ensureTaskActive()
            try {
                return selectReachableServiceUrl(serviceUrls)
            } catch (_: Exception) {
                val waitSeconds = (retryDelayMs / 1000L).coerceAtLeast(1L)
                remoteTaskProgress(
                    taskId,
                    "等待连接电脑",
                    progress.coerceIn(0, 99),
                    "手机暂时无法连接电脑，${waitSeconds}秒后自动重试；已提交的电脑任务不会中止。",
                    fallback
                )
                Thread.sleep(retryDelayMs)
                retryDelayMs = (retryDelayMs * 2).coerceAtMost(60_000L)
            }
        }
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

    private fun runDurableComputerTask(
        initialTask: CaptionTask,
        videoUri: Uri,
        serviceUrls: List<String>,
        initialServiceUrl: String,
        mode: String
    ): String {
        var task = CaptionTaskStore.all(this).firstOrNull { it.id == initialTask.id } ?: initialTask
        if (task.remoteJobId.isNotBlank()) {
            return pollTranscriptJob(serviceUrls, initialServiceUrl, task.remoteJobId, task.id, mode)
        }

        var serviceUrl = initialServiceUrl
        val upload = ensureDurableUpload(task, videoUri, serviceUrls, serviceUrl)
        serviceUrl = upload.serviceUrl
        task = CaptionTaskStore.all(this).firstOrNull { it.id == task.id } ?: task
        val segments = if (mode == "retranslate") cachedSegmentsForServer(videoUri) else null
        val submitted = completeDurableUploadWithReconnect(
            task.id,
            serviceUrls,
            serviceUrl,
            upload.uploadId,
            task.title,
            mode,
            force = mode == "generate" && task.forceTranscribe,
            segments = segments
        )
        serviceUrl = submitted.first
        val jobId = submitted.second
        CaptionTaskStore.recordRemoteJob(this, task.id, jobId)
        return pollTranscriptJob(serviceUrls, serviceUrl, jobId, task.id, mode)
    }

    private data class DurableUpload(
        val uploadId: String,
        val audioHash: String,
        val offset: Long,
        val totalBytes: Long,
        val serviceUrl: String
    )

    private fun ensureDurableUpload(
        initialTask: CaptionTask,
        videoUri: Uri,
        serviceUrls: List<String>,
        initialServiceUrl: String
    ): DurableUpload {
        var task = initialTask
        var audio: RemoteAudioFile? = null
        var audioHash = task.audioHash
        var totalBytes = task.totalBytes
        var serviceUrl = initialServiceUrl

        if (audioHash.isBlank() || totalBytes <= 0L) {
            progress("正在准备可复用音频文件...")
            audio = onDeviceWhisper.extractAudioForRemoteUpload(videoUri) { percent ->
                val overall = (percent.coerceIn(0, 100) * 10 / 100).coerceIn(0, 10)
                progress("正在提取音频：$overall%（本阶段 $percent%）")
            }
            audioHash = sha256File(audio.file) { percent ->
                val overall = 8 + percent.coerceIn(0, 100) * 2 / 100
                progress("正在校验音频指纹：$overall%")
            }
            totalBytes = audio.file.length()
        }

        val recoveredSession = createUploadSessionWithReconnect(
            task.id,
            serviceUrls,
            serviceUrl,
            audioHash,
            totalBytes,
            audio?.mimeType ?: "audio/mp4",
            task.title
        )
        serviceUrl = recoveredSession.first
        var session = recoveredSession.second
        var uploadId = session.optString("upload_id").ifBlank { audioHash }
        var offset = session.optLong("offset", 0L).coerceIn(0L, totalBytes)
        CaptionTaskStore.recordUpload(this, task.id, audioHash, uploadId, offset, totalBytes)
        if (session.optBoolean("complete", false) || offset >= totalBytes) {
            remoteTaskProgress(task.id, "音频已在电脑缓存", 30, "电脑端已存在相同音频，跳过上传。", serviceUrl)
            return DurableUpload(uploadId, audioHash, totalBytes, totalBytes, serviceUrl)
        }

        if (audio == null) {
            progress("电脑端缺少缓存，正在重新读取手机音频...")
            audio = onDeviceWhisper.extractAudioForRemoteUpload(videoUri)
            val actualHash = sha256File(audio.file)
            if (actualHash != audioHash || audio.file.length() != totalBytes) {
                audioHash = actualHash
                totalBytes = audio.file.length()
                session = createUploadSession(serviceUrl, audioHash, totalBytes, audio.mimeType, task.title)
                uploadId = session.optString("upload_id").ifBlank { audioHash }
                offset = session.optLong("offset", 0L).coerceIn(0L, totalBytes)
            }
        }

        val file = checkNotNull(audio).file
        while (offset < totalBytes) {
            ensureTaskActive()
            val length = minOf(UPLOAD_CHUNK_BYTES.toLong(), totalBytes - offset).toInt()
            try {
                session = uploadChunk(serviceUrl, uploadId, file, offset, length)
                offset = session.optLong("offset", offset + length).coerceIn(0L, totalBytes)
            } catch (error: Exception) {
                if (error.message.orEmpty().contains("HTTP 404")) throw error
                val recovered = createUploadSessionWithReconnect(
                    task.id,
                    serviceUrls,
                    serviceUrl,
                    audioHash,
                    totalBytes,
                    audio.mimeType,
                    task.title
                )
                serviceUrl = recovered.first
                session = recovered.second
                uploadId = session.optString("upload_id").ifBlank { audioHash }
                offset = session.optLong("offset", offset).coerceIn(0L, totalBytes)
                CaptionTaskStore.recordUpload(this, task.id, audioHash, uploadId, offset, totalBytes)
                remoteTaskProgress(
                    task.id,
                    "等待续传",
                    10 + (if (totalBytes > 0L) (offset * 20 / totalBytes).toInt() else 0),
                    "连接已恢复，将从 ${formatBytes(offset)} 继续上传。",
                    serviceUrl
                )
                continue
            }
            CaptionTaskStore.recordUpload(this, task.id, audioHash, uploadId, offset, totalBytes)
            val uploadPercent = if (totalBytes > 0) (offset * 100 / totalBytes).toInt() else 0
            val overall = 10 + uploadPercent * 20 / 100
            remoteTaskProgress(
                task.id,
                "上传音频",
                overall,
                "正在断点上传：$uploadPercent%（${formatBytes(offset)} / ${formatBytes(totalBytes)}）",
                serviceUrl
            )
        }
        return DurableUpload(uploadId, audioHash, offset, totalBytes, serviceUrl)
    }

    private fun createUploadSession(
        serviceUrl: String,
        audioHash: String,
        totalBytes: Long,
        mimeType: String,
        videoTitle: String
    ): JSONObject {
        val payload = JSONObject().apply {
            put("audio_hash", audioHash)
            put("total_bytes", totalBytes)
            put("mime_type", mimeType)
            put("video_title", videoTitle)
        }
        return JSONObject(postJson(uploadCollectionUrl(serviceUrl), payload))
    }

    private fun createUploadSessionWithReconnect(
        taskId: String,
        serviceUrls: List<String>,
        initialServiceUrl: String,
        audioHash: String,
        totalBytes: Long,
        mimeType: String,
        videoTitle: String
    ): Pair<String, JSONObject> {
        var serviceUrl = initialServiceUrl
        while (true) {
            ensureTaskActive()
            try {
                return serviceUrl to createUploadSession(serviceUrl, audioHash, totalBytes, mimeType, videoTitle)
            } catch (error: Exception) {
                if (error.message.orEmpty().contains("HTTP 404")) throw error
                serviceUrl = waitForReachableService(taskId, serviceUrls, 10)
            }
        }
    }

    private fun uploadChunk(
        serviceUrl: String,
        uploadId: String,
        file: File,
        offset: Long,
        length: Int
    ): JSONObject {
        val connection = (URL(uploadItemUrl(serviceUrl, uploadId)).openConnection() as HttpURLConnection).apply {
            requestMethod = "PUT"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Content-Type", "application/octet-stream")
            setRequestProperty("X-Upload-Offset", offset.toString())
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(length)
        }
        file.inputStream().use { input ->
            input.channel.position(offset)
            connection.outputStream.use { output ->
                var remaining = length
                val buffer = ByteArray(256 * 1024)
                while (remaining > 0) {
                    ensureTaskActive()
                    val read = input.read(buffer, 0, minOf(buffer.size, remaining))
                    if (read <= 0) error("读取音频分块失败")
                    output.write(buffer, 0, read)
                    remaining -= read
                }
            }
        }
        return JSONObject(requestJobJson(connection))
    }

    private fun completeDurableUpload(
        serviceUrl: String,
        uploadId: String,
        videoTitle: String,
        mode: String,
        force: Boolean,
        segments: JSONArray?
    ): String {
        val payload = JSONObject().apply {
            put("video_title", videoTitle)
            put("mode", mode)
            put("force", force)
            if (segments != null) put("segments", segments)
        }
        val response = JSONObject(postJson(uploadCompleteUrl(serviceUrl, uploadId), payload))
        return response.optString("job_id").ifBlank { error("电脑端没有返回 job_id：$response") }
    }

    private fun completeDurableUploadWithReconnect(
        taskId: String,
        serviceUrls: List<String>,
        initialServiceUrl: String,
        uploadId: String,
        videoTitle: String,
        mode: String,
        force: Boolean,
        segments: JSONArray?
    ): Pair<String, String> {
        var serviceUrl = initialServiceUrl
        while (true) {
            ensureTaskActive()
            try {
                return serviceUrl to completeDurableUpload(serviceUrl, uploadId, videoTitle, mode, force, segments)
            } catch (error: Exception) {
                if (error.message.orEmpty().contains("HTTP 404")) throw error
                serviceUrl = waitForReachableService(taskId, serviceUrls, 30)
            }
        }
    }

    private fun cachedSegmentsForServer(uri: Uri): JSONArray {
        val file = subtitleCacheFile(uri)
        if (!file.exists()) error("没有可供电脑端重翻的英文字幕。")
        val cached = JSONArray(file.readText(Charsets.UTF_8))
        val result = JSONArray()
        for (i in 0 until cached.length()) {
            val item = cached.optJSONObject(i) ?: continue
            val text = item.optString("englishText").trim()
            if (text.isBlank()) continue
            result.put(JSONObject().apply {
                put("start", item.optLong("startMs", 0L) / 1000.0)
                put("end", item.optLong("endMs", 0L) / 1000.0)
                put("text", text)
                put("translation", "")
            })
        }
        if (result.length() == 0) error("没有可供电脑端重翻的英文字幕。")
        return result
    }

    private fun postJson(urlText: String, payload: JSONObject): String {
        val body = payload.toString().toByteArray(Charsets.UTF_8)
        val connection = (URL(urlText).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(body.size)
        }
        connection.outputStream.use { it.write(body) }
        return requestJobJson(connection)
    }

    private fun sha256File(file: File, onProgress: ((Int) -> Unit)? = null): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val total = file.length().coerceAtLeast(1L)
        var processed = 0L
        file.inputStream().use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
                processed += read
                onProgress?.invoke((processed * 100 / total).toInt().coerceIn(0, 100))
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun remoteTaskProgress(
        taskId: String,
        stage: String,
        percent: Int,
        message: String,
        serviceUrl: String
    ) {
        lastNotificationProgress = percent.coerceIn(0, 100)
        CaptionTaskStore.updateRemoteProgress(
            this,
            taskId,
            stage,
            percent,
            message,
            serviceLabel(serviceUrl)
        )
        updateNotification(message)
        sendProgress(message)
    }

    private fun createTranscriptJobWithRetry(serviceUrls: List<String>, initialServiceUrl: String, audio: RemoteAudioFile, videoTitle: String): String {
        var serviceUrl = initialServiceUrl
        return try {
            createTranscriptJob(serviceUrl, audio, videoTitle)
        } catch (first: Exception) {
            val message = first.message.orEmpty()
            if (!message.contains("unexpected end", ignoreCase = true) &&
                !message.contains("Connection reset", ignoreCase = true) &&
                !message.contains("Broken pipe", ignoreCase = true)
            ) {
                throw first
            }
            Thread.sleep(1_500)
            serviceUrl = selectReachableServiceUrl(serviceUrls)
            progress("上传连接中断，已切换到${serviceLabel(serviceUrl)}重试上传...")
            ensureWhisperServiceReachable(serviceUrl)
            createTranscriptJob(serviceUrl, audio, videoTitle)
        }
    }

    private fun createTranscriptJob(serviceUrl: String, audio: RemoteAudioFile, videoTitle: String): String {
        val audioFile = audio.file
        val url = URL(jobCreateUrl(serviceUrl))
        val totalBytes = audioFile.length().coerceAtLeast(1L)
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Content-Type", audio.mimeType)
            setRequestProperty("X-Video-Title", URLEncoder.encode(videoTitle, Charsets.UTF_8.name()))
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(totalBytes)
        }
        var sentBytes = 0L
        connection.outputStream.use { output ->
            audioFile.inputStream().use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    ensureTaskActive()
                    val read = input.read(buffer)
                    if (read <= 0) break
                    output.write(buffer, 0, read)
                    sentBytes += read
                    val percent = (sentBytes * 100 / totalBytes).toInt().coerceIn(0, 100)
                    progress("正在上传音频：$percent%（${formatBytes(sentBytes)} / ${formatBytes(totalBytes)}）")
                }
            }
        }
        val response = requestJobJson(connection)
        return JSONObject(response).optString("job_id").ifBlank {
            error("服务端没有返回 job_id：$response")
        }
    }

    private fun requestTranscriptSync(serviceUrl: String, audio: RemoteAudioFile, videoTitle: String): String {
        val audioFile = audio.file
        val url = URL(serviceUrl)
        val totalBytes = audioFile.length().coerceAtLeast(1L)
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 30 * 60 * 1000
            doOutput = true
            setRequestProperty("Content-Type", audio.mimeType)
            setRequestProperty("X-Video-Title", URLEncoder.encode(videoTitle, Charsets.UTF_8.name()))
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(totalBytes)
        }
        var sentBytes = 0L
        connection.outputStream.use { output ->
            audioFile.inputStream().use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    ensureTaskActive()
                    val read = input.read(buffer)
                    if (read <= 0) break
                    output.write(buffer, 0, read)
                    sentBytes += read
                    val percent = (sentBytes * 100 / totalBytes).toInt().coerceIn(0, 100)
                    progress("正在上传音频：$percent%（同步模式）")
                }
            }
        }
        progress("音频上传完成，正在等待 Whisper 服务返回字幕...")
        return requestJobJson(connection)
    }

    private fun pollTranscriptJob(
        serviceUrls: List<String>,
        initialServiceUrl: String,
        jobId: String,
        taskId: String,
        mode: String
    ): String {
        var serviceUrl = initialServiceUrl
        var lastSwitchCheckAt = 0L
        var retryDelayMs = 2_000L
        var lastKnownProgress = CaptionTaskStore.all(this).firstOrNull { it.id == taskId }?.progress ?: 30
        while (true) {
            ensureTaskActive()
            val now = System.currentTimeMillis()
            if (now - lastSwitchCheckAt >= 5_000L) {
                lastSwitchCheckAt = now
                val preferred = runCatching { selectReachableServiceUrl(serviceUrls) }.getOrNull()
                if (preferred != null && preferred != serviceUrl && serviceUrlPriority(preferred) < serviceUrlPriority(serviceUrl)) {
                    serviceUrl = preferred
                    remoteTaskProgress(taskId, "连接电脑", lastKnownProgress, "检测到更稳定的连接，已切换到${serviceLabel(serviceUrl)}查询电脑任务。", serviceUrl)
                }
            }
            val json = try {
                requestJobJson(URL(jobStatusUrl(serviceUrl, jobId)))
            } catch (error: Exception) {
                val taskMissingAtThisAddress = error.message.orEmpty().contains("HTTP 404")
                val preferred = runCatching { selectReachableServiceUrl(serviceUrls) }.getOrNull()
                if (preferred != null) serviceUrl = preferred
                val waitSeconds = (retryDelayMs / 1000L).coerceAtLeast(1L)
                val reconnectMessage = if (taskMissingAtThisAddress) {
                    "当前地址暂时找不到电脑任务，已保留任务 ID；${waitSeconds}秒后继续尝试其他连接。"
                } else {
                    "电脑仍会独立处理；手机暂时无法获取进度，${waitSeconds}秒后自动重连。"
                }
                remoteTaskProgress(
                    taskId,
                    "等待连接电脑",
                    lastKnownProgress,
                    reconnectMessage,
                    serviceUrl
                )
                Thread.sleep(retryDelayMs)
                retryDelayMs = (retryDelayMs * 2).coerceAtMost(60_000L)
                continue
            }
            retryDelayMs = 2_000L
            val item = JSONObject(json)
            val status = item.optString("status")
            val serverPercent = item.optInt("progress", 0).coerceIn(0, 100)
            val serverStage = item.optString("stage")
            val stageProgress = item.optInt("stage_progress", serverPercent).coerceIn(0, 100)
            val processedSeconds = item.optLong("processed_seconds", 0L)
            val totalSeconds = item.optLong("total_seconds", 0L)
            val detail = item.optString("message").ifBlank { serverStage }
            val overall = if (mode == "retranslate") {
                (85 + serverPercent * 14 / 100).coerceIn(85, 99)
            } else {
                (30 + serverPercent * 69 / 100).coerceIn(30, 99)
            }
            lastKnownProgress = overall
            val timeDetail = if (processedSeconds > 0L && totalSeconds > 0L) {
                " ${formatSeconds(processedSeconds)} / ${formatSeconds(totalSeconds)}"
            } else {
                ""
            }
            val stageLabel = remoteStageLabel(serverStage, mode)
            remoteTaskProgress(
                taskId,
                stageLabel,
                overall,
                "$stageLabel：本阶段 $stageProgress%$timeDetail；总进度 $overall%。$detail",
                serviceUrl
            )
            when (status) {
                "done" -> return (item.optJSONArray("result") ?: JSONArray()).toString()
                "error" -> error(item.optString("error").ifBlank { detail.ifBlank { "电脑端生成失败" } })
            }
            Thread.sleep(1_500L)
        }
    }

    private fun remoteStageLabel(stage: String, mode: String): String = when (stage.lowercase()) {
        "queued", "starting", "loading", "detecting" -> "电脑准备任务"
        "transcribing" -> "识别英文字幕"
        "postprocessing" -> "整理字幕断句"
        "translating" -> if (mode == "retranslate") "重新翻译中文" else "翻译中文字幕"
        "done" -> "电脑处理完成"
        else -> if (mode == "retranslate") "重新翻译中文" else "电脑生成字幕"
    }

    private fun formatSeconds(seconds: Long): String {
        val safe = seconds.coerceAtLeast(0L)
        return "%02d:%02d".format(safe / 60, safe % 60)
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
        if (code !in 200..299) error("HTTP $code: $body")
        return body
    }

    private fun uploadCollectionUrl(serviceUrl: String): String = serviceEndpointUrl(serviceUrl, "/uploads")

    private fun uploadItemUrl(serviceUrl: String, uploadId: String): String =
        serviceEndpointUrl(serviceUrl, "/uploads/$uploadId")

    private fun uploadCompleteUrl(serviceUrl: String, uploadId: String): String =
        serviceEndpointUrl(serviceUrl, "/uploads/$uploadId/complete")

    private fun serviceEndpointUrl(serviceUrl: String, endpoint: String): String {
        val base = serviceUrl.substringBefore("?").removeSuffix("/")
        val query = serviceUrl.substringAfter("?", "")
        val root = when {
            base.endsWith("/transcribe") -> base.removeSuffix("/transcribe")
            base.endsWith("/translate") -> base.removeSuffix("/translate")
            base.endsWith("/jobs") -> base.removeSuffix("/jobs")
            else -> base
        }
        val target = "$root$endpoint"
        return if (query.isBlank()) target else "$target?$query"
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

    private fun saveCachedSubtitles(uri: Uri, transcriptJson: String): Int {
        val transcript = JSONArray(transcriptJson)
        val cache = JSONArray()
        var missingTranslations = 0
        for (i in 0 until transcript.length()) {
            val item = transcript.optJSONObject(i) ?: continue
            val start = item.optDouble("start", Double.NaN)
            val end = item.optDouble("end", Double.NaN)
            val text = item.optString("text").takeIf { it.isNotBlank() } ?: continue
            if (start.isNaN() || end.isNaN()) continue
            val translation = item.optString("translation").trim()
            if (translation.isBlank()) missingTranslations += 1
            cache.put(JSONObject().apply {
                put("index", cache.length() + 1)
                put("startMs", (start * 1000).toInt())
                put("endMs", (end * 1000).toInt())
                put("englishText", text)
                put("chineseText", translation.takeIf { it.isNotBlank() } ?: JSONObject.NULL)
                put("translationSource", if (translation.isNotBlank()) TRANSLATION_SOURCE_COMPUTER else JSONObject.NULL)
            })
        }
        if (cache.length() == 0) return 0
        if (missingTranslations > 0) {
            error("新英文字幕中有 $missingTranslations 句没有中文翻译，旧字幕已保留，请检查电脑端翻译模型后重试。")
        }
        writeSubtitleCacheAtomically(subtitleCacheFile(uri), cache)
        return cache.length()
    }

    private fun translateCachedSubtitles(uri: Uri, serviceUrls: List<String>, taskKind: String): Int {
        val file = subtitleCacheFile(uri)
        if (!file.exists()) error("这个视频还没有缓存字幕，请先生成或导入英文字幕。")
        val array = JSONArray(file.readText(Charsets.UTF_8))
        val indices = mutableListOf<Int>()
        val texts = mutableListOf<String>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val english = item.optString("englishText").trim()
            if (english.isNotBlank()) {
                indices += i
                texts += english
            }
        }
        if (texts.isEmpty()) return 0
        val translations = if (taskKind == TASK_TRANSLATE_REMOTE) {
            val selectedServiceUrl = selectReachableServiceUrl(serviceUrls)
            progress("正在请求电脑端翻译 ${texts.size} 句字幕...")
            requestRemoteTranslations(serviceUrls, selectedServiceUrl, texts)
        } else {
            progress("正在准备手机端翻译模型...")
            requestPhoneTranslations(texts)
        }
        if (translations.size != texts.size) error("翻译结果数量不一致：${translations.size}/${texts.size}")
        val blankTranslations = translations.count { it.isBlank() }
        if (blankTranslations > 0) error("有 $blankTranslations 句没有得到中文翻译，原字幕已保留。")
        val source = if (taskKind == TASK_TRANSLATE_REMOTE) TRANSLATION_SOURCE_COMPUTER else TRANSLATION_SOURCE_PHONE
        var updated = 0
        indices.forEachIndexed { position, itemIndex ->
            val translated = translations[position].trim()
            if (translated.isNotBlank()) {
                val item = array.getJSONObject(itemIndex)
                item.put("chineseText", translated)
                item.put("translationSource", source)
                updated += 1
            }
            if (position % 5 == 0 || position == indices.lastIndex) {
                val label = if (taskKind == TASK_TRANSLATE_REMOTE) "电脑端" else "手机端"
                progress("${label}翻译中：${position + 1}/${indices.size}")
            }
        }
        writeSubtitleCacheAtomically(file, array)
        return updated
    }

    private fun writeSubtitleCacheAtomically(file: File, array: JSONArray) {
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, "${file.name}.new")
        temporary.writeText(array.toString(), Charsets.UTF_8)
        try {
            Files.move(
                temporary.toPath(),
                file.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING)
        } finally {
            temporary.delete()
        }
    }

    private fun requestRemoteTranslations(serviceUrls: List<String>, initialServiceUrl: String, texts: List<String>): List<String> {
        val translated = mutableListOf<String>()
        var start = 0
        var serviceUrl = initialServiceUrl
        while (start < texts.size) {
            ensureTaskActive()
            val end = (start + REMOTE_TRANSLATION_BATCH_SIZE).coerceAtMost(texts.size)
            val preferred = runCatching { selectReachableServiceUrl(serviceUrls) }.getOrNull()
            if (preferred != null && preferred != serviceUrl && serviceUrlPriority(preferred) < serviceUrlPriority(serviceUrl)) {
                serviceUrl = preferred
                progress("检测到更稳定的连接，已切换到${serviceLabel(serviceUrl)}继续翻译...")
            }
            progress("电脑端翻译中：${start + 1}-$end/${texts.size}（首次加载模型可能较久）")
            translated += requestRemoteTranslationBatchWithRetry(serviceUrls, serviceUrl, texts.subList(start, end), start + 1, end, texts.size)
            progress("电脑端翻译中：$end/${texts.size}")
            start = end
        }
        return translated
    }

    private fun requestRemoteTranslationBatchWithRetry(
        serviceUrls: List<String>,
        initialServiceUrl: String,
        texts: List<String>,
        from: Int,
        to: Int,
        total: Int
    ): List<String> {
        var lastError: Exception? = null
        var serviceUrl = initialServiceUrl
        repeat(3) { attempt ->
            try {
                val preferred = runCatching { selectReachableServiceUrl(serviceUrls) }.getOrNull()
                if (preferred != null && preferred != serviceUrl && serviceUrlPriority(preferred) < serviceUrlPriority(serviceUrl)) {
                    serviceUrl = preferred
                    progress("检测到更稳定的连接，已切换到${serviceLabel(serviceUrl)}重试翻译...")
                }
                return requestRemoteTranslationBatch(serviceUrl, texts)
            } catch (error: Exception) {
                lastError = error
                if (attempt < 2) {
                    progress("电脑端翻译中：$from-$to/$total 连接中断，正在重试 ${attempt + 2}/3...")
                    Thread.sleep(1200L * (attempt + 1))
                }
            }
        }
        throw IllegalStateException("电脑端第 $from-$to/$total 句翻译失败：${lastError?.message}", lastError)
    }

    private fun requestRemoteTranslationBatch(serviceUrl: String, texts: List<String>): List<String> {
        val payload = JSONObject().apply {
            val array = JSONArray()
            texts.forEach { array.put(it) }
            put("texts", array)
        }.toString().toByteArray(Charsets.UTF_8)
        val connection = (URL(translateUrl(serviceUrl)).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 10 * 60 * 1000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Connection", "close")
            setFixedLengthStreamingMode(payload.size)
        }
        connection.outputStream.use { it.write(payload) }
        val json = requestJobJson(connection)
        val array = JSONObject(json).optJSONArray("translations")
            ?: error("电脑端没有返回 translations：$json")
        return (0 until array.length()).map { array.optString(it) }
    }

    private fun requestPhoneTranslations(texts: List<String>): List<String> {
        val options = TranslatorOptions.Builder()
            .setSourceLanguage(TranslateLanguage.ENGLISH)
            .setTargetLanguage(TranslateLanguage.CHINESE)
            .build()
        val translator = Translation.getClient(options)
        val conditions = DownloadConditions.Builder().build()
        try {
            awaitMlKitTask<Void>("手机端翻译模型准备失败") {
                translator.downloadModelIfNeeded(conditions)
            }
            return texts.mapIndexed { index, text ->
                ensureTaskActive()
                progress("手机端翻译中：${index + 1}/${texts.size}")
                awaitMlKitTask<String>("手机端翻译失败") {
                    translator.translate(text)
                }.orEmpty().trim()
            }
        } finally {
            translator.close()
        }
    }

    private fun <T> awaitMlKitTask(label: String, starter: () -> com.google.android.gms.tasks.Task<T>): T? {
        val latch = CountDownLatch(1)
        val result = AtomicReference<T>()
        val error = AtomicReference<Exception>()
        starter()
            .addOnSuccessListener { value ->
                result.set(value)
                latch.countDown()
            }
            .addOnFailureListener { failure ->
                error.set(failure)
                latch.countDown()
            }
        if (!latch.await(10, TimeUnit.MINUTES)) error("$label：等待超时")
        error.get()?.let { throw IllegalStateException("$label：${it.message}", it) }
        return result.get()
    }

    private fun subtitleCacheFile(uri: Uri): File {
        val dir = File(filesDir, SUBTITLE_CACHE_DIR).apply { mkdirs() }
        return File(dir, "${stableCacheKey(uri)}.json")
    }

    private fun stableCacheKey(uri: Uri): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(uri.toString().toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
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

    private fun friendlyTranslationError(error: Throwable): String {
        val message = error.message.orEmpty()
        return when {
            message.contains("check_hostname requires server_hostname", ignoreCase = true) ->
                "电脑端中文翻译模型加载失败，通常是 Windows/Python 代理配置导致 HuggingFace 模型下载异常。英文字幕已保留；请检查代理环境变量，或先在电脑端预下载翻译模型。原始错误：$message"
            message.contains("could not load translation model", ignoreCase = true) ->
                "电脑端中文翻译模型没有加载成功。英文字幕已保留；请确认已运行 requirements.txt 安装 transformers、sentencepiece、torch，并确认电脑能下载或已缓存 Helsinki-NLP/opus-mt-en-zh。原始错误：$message"
            message.contains("HTTP 500") && message.contains("translation failed", ignoreCase = true) ->
                "电脑端翻译接口报错。英文字幕已保留；请查看 PowerShell 服务窗口里的 Python 错误，修好后长按“英文/双语/中文”选择“电脑端重翻”。原始错误：$message"
            message.contains("Failed to connect", ignoreCase = true) ||
                message.contains("Connection refused", ignoreCase = true) ->
                "连接不上电脑端翻译服务。英文字幕已保留；请确认一键脚本仍在运行，并长按“生成”测试服务地址。原始错误：$message"
            else -> message.ifBlank { error.javaClass.simpleName }
        }
    }

    private fun formatMs(ms: Int): String {
        val totalSeconds = ms.coerceAtLeast(0) / 1000
        return String.format("%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    private fun formatBytes(bytes: Long): String {
        val mb = bytes / 1024.0 / 1024.0
        return if (mb >= 10.0) "${mb.toInt()}MB" else String.format("%.1fMB", mb)
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL_ID, "字幕生成", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun updateNotification(message: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(message))
    }

    private fun startCaptionForeground(message: String) {
        val item = notification(message)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, item, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, item)
        }
    }

    private fun notification(message: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, LearningActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle(if (currentTaskKind == TASK_GENERATE) "正在识别并翻译字幕" else "正在翻译字幕")
            .setContentText(message)
            .setStyle(Notification.BigTextStyle().bigText(message))
            .setProgress(100, lastNotificationProgress.coerceIn(0, 100), lastNotificationProgress !in 0..100)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_PROGRESS)
            .setContentIntent(pendingIntent)
            .build()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val powerManager = getSystemService(PowerManager::class.java)
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "$packageName:CaptionGeneration"
        ).apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { lock ->
            if (lock.isHeld) {
                runCatching { lock.release() }
            }
        }
        wakeLock = null
    }

    private fun acquireWifiLock() {
        if (wifiLock?.isHeld == true) return
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
        wifiLock = wifiManager.createWifiLock(
            WifiManager.WIFI_MODE_FULL_HIGH_PERF,
            "$packageName:CaptionGenerationWifi"
        ).apply {
            setReferenceCounted(false)
            runCatching { acquire() }
        }
    }

    private fun releaseWifiLock() {
        wifiLock?.let { lock ->
            if (lock.isHeld) {
                runCatching { lock.release() }
            }
        }
        wifiLock = null
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    companion object {
        @Volatile private var active = false

        fun isActive(): Boolean = active

        const val ACTION_PROGRESS = "com.codex.videolearnenglish.CAPTION_PROGRESS"
        const val ACTION_DONE = "com.codex.videolearnenglish.CAPTION_DONE"
        const val ACTION_TRANSLATION_DONE = "com.codex.videolearnenglish.TRANSLATION_DONE"
        const val ACTION_ERROR = "com.codex.videolearnenglish.CAPTION_ERROR"
        const val EXTRA_VIDEO_URI = "video_uri"
        const val EXTRA_SERVICE_URL = "service_url"
        const val EXTRA_SERVICE_URLS = "service_urls"
        const val EXTRA_TASK_KIND = "task_kind"
        const val EXTRA_TASK_ID = "task_id"
        const val EXTRA_FORCE_TRANSCRIBE = "force_transcribe"
        const val EXTRA_VIDEO_TITLE = "video_title"
        const val EXTRA_MESSAGE = "message"
        const val EXTRA_COUNT = "count"
        const val TASK_GENERATE = "generate"
        const val TASK_TRANSLATE_REMOTE = "translate_remote"
        const val TASK_TRANSLATE_PHONE = "translate_phone"
        const val TRANSLATION_SOURCE_COMPUTER = "computer"
        const val TRANSLATION_SOURCE_PHONE = "phone"
        private const val MAX_AUTO_FAILURES = 5
        private const val UPLOAD_CHUNK_BYTES = 1024 * 1024
        private const val CHANNEL_ID = "caption_generation"
        private const val NOTIFICATION_ID = 42
        private const val SUBTITLE_CACHE_DIR = "subtitles_cache"
        private const val REMOTE_TRANSLATION_BATCH_SIZE = 16
        private const val PREFS_NAME = "video_english_learning"
        private const val SERVICE_URL_KEY = "whisper_service_url"
        private const val SERVICE_URL_CANDIDATES_KEY = "whisper_service_url_candidates"
        private const val PHONE_USB_SERVICE_URL = "http://127.0.0.1:8765/transcribe"
        private const val EMULATOR_SERVICE_URL = "http://10.0.2.2:8765/transcribe"
    }

    private class TaskPausedException : RuntimeException("task paused")
    private class TaskCanceledException : RuntimeException("task canceled")
}
