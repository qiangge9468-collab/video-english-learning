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
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class CaptionGenerationService : Service() {
    private lateinit var onDeviceWhisper: OnDeviceWhisperTranscriber
    private var wakeLock: PowerManager.WakeLock? = null
    @Volatile private var running = false

    override fun onCreate() {
        super.onCreate()
        onDeviceWhisper = OnDeviceWhisperTranscriber(this)
        ensureNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val uriText = intent?.getStringExtra(EXTRA_VIDEO_URI)
        val serviceUrl = intent?.getStringExtra(EXTRA_SERVICE_URL).orEmpty()
        val serviceUrls = serviceUrlCandidates(intent, serviceUrl)
        if (uriText.isNullOrBlank() || serviceUrls.isEmpty()) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        if (running) {
            sendProgress("已有字幕生成任务正在进行中。")
            return START_NOT_STICKY
        }
        val videoUri = Uri.parse(uriText)
        val taskKind = intent?.getStringExtra(EXTRA_TASK_KIND).orEmpty().ifBlank { TASK_GENERATE }
        running = true
        startCaptionForeground(if (taskKind == TASK_GENERATE) "正在检查 Whisper 服务连接..." else "正在准备后台翻译...")
        acquireWakeLock()
        Thread {
            var success = false
            var audioForUpload: RemoteAudioFile? = null
            try {
                if (taskKind == TASK_TRANSLATE_REMOTE || taskKind == TASK_TRANSLATE_PHONE) {
                    val count = translateCachedSubtitles(videoUri, serviceUrls, taskKind)
                    success = count > 0
                    if (success) {
                        val label = if (taskKind == TASK_TRANSLATE_REMOTE) "电脑端" else "手机端"
                        progress("已用${label}完成 $count 句中文翻译。")
                        sendTranslationDone(videoUri.toString(), count, label)
                    } else {
                        throw IllegalStateException("没有可翻译的英文字幕。")
                    }
                    return@Thread
                }

                val selectedServiceUrl = selectReachableServiceUrl(serviceUrls)
                progress("Whisper 服务已连接，正在从视频中提取音频...")
                val audio = onDeviceWhisper.extractAudioForRemoteUpload(videoUri) { percent ->
                    val bounded = percent.coerceIn(0, 100)
                    val stage = when {
                        bounded < 75 -> "正在提取音频"
                        bounded < 100 -> "正在压缩音频"
                        else -> "音频准备完成"
                    }
                    progress("$stage：$bounded%")
                }
                audioForUpload = audio
                progress("音频已准备：${formatMs(audio.durationMs)}，${formatBytes(audio.file.length())}，正在上传到 Whisper 服务...")
                val json = try {
                    val jobId = createTranscriptJobWithRetry(selectedServiceUrl, audio)
                    pollTranscriptJob(selectedServiceUrl, jobId)
                } catch (error: Exception) {
                    if (error.message.orEmpty().contains("HTTP 404")) {
                        progress("服务端不支持进度任务接口，改用同步生成字幕...")
                        requestTranscriptSync(selectedServiceUrl, audio)
                    } else {
                        throw error
                    }
                }
                val count = saveCachedSubtitles(videoUri, json)
                success = count > 0
                if (success) {
                    onDeviceWhisper.deleteCachedRemoteAudio(videoUri)
                    progress("已生成并缓存 $count 条字幕。")
                    sendDone(videoUri.toString(), count)
                } else {
                    throw IllegalStateException("没有生成字幕。")
                }
            } catch (error: Exception) {
                val isTranslationTask = taskKind == TASK_TRANSLATE_REMOTE || taskKind == TASK_TRANSLATE_PHONE
                val message = buildString {
                    append(if (isTranslationTask) friendlyTranslationError(error) else friendlyGenerationError(error))
                    audioForUpload?.let { append("。已保留音频缓存：").append(formatBytes(it.file.length())).append("，下次会直接重试上传。") }
                }
                updateNotification(if (isTranslationTask) "中文翻译失败：$message" else "生成字幕失败：$message")
                sendError(message, taskKind)
            } finally {
            running = false
            releaseWakeLock()
            stopForegroundCompat()
            stopSelf(startId)
        }
        }.start()
        return START_REDELIVER_INTENT
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        releaseWakeLock()
        super.onDestroy()
    }

    private fun progress(message: String) {
        updateNotification(message)
        sendProgress(message)
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
        return ordered.toList()
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
                    progress("正在上传音频：$percent%（${formatBytes(sentBytes)} / ${formatBytes(totalBytes)}）")
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
                    progress("正在上传音频：$percent%（同步模式）")
                }
            }
        }
        progress("音频上传完成，正在等待 Whisper 服务返回字幕...")
        return requestJobJson(connection)
    }

    private fun pollTranscriptJob(serviceUrl: String, jobId: String): String {
        while (true) {
            val json = requestJobJson(URL(jobStatusUrl(serviceUrl, jobId)))
            val item = JSONObject(json)
            val status = item.optString("status")
            val percent = item.optInt("progress", 0).coerceIn(0, 100)
            val message = item.optString("message").ifBlank { item.optString("stage") }
            progress("正在生成字幕：$percent% $message")
            when (status) {
                "done" -> return (item.optJSONArray("result") ?: JSONArray()).toString()
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
        if (code !in 200..299) error("HTTP $code: $body")
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
        for (i in 0 until transcript.length()) {
            val item = transcript.optJSONObject(i) ?: continue
            val start = item.optDouble("start", Double.NaN)
            val end = item.optDouble("end", Double.NaN)
            val text = item.optString("text").takeIf { it.isNotBlank() } ?: continue
            if (start.isNaN() || end.isNaN()) continue
            cache.put(JSONObject().apply {
                put("index", cache.length() + 1)
                put("startMs", (start * 1000).toInt())
                put("endMs", (end * 1000).toInt())
                put("englishText", text)
                put("chineseText", item.optString("translation").takeIf { it.isNotBlank() } ?: JSONObject.NULL)
                put("translationSource", if (item.optString("translation").isNotBlank()) TRANSLATION_SOURCE_COMPUTER else JSONObject.NULL)
            })
        }
        if (cache.length() > 0) {
            subtitleCacheFile(uri).writeText(cache.toString(), Charsets.UTF_8)
        }
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
            requestRemoteTranslations(selectedServiceUrl, texts)
        } else {
            progress("正在准备手机端翻译模型...")
            requestPhoneTranslations(texts)
        }
        if (translations.size != texts.size) error("翻译结果数量不一致：${translations.size}/${texts.size}")
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
        file.writeText(array.toString(), Charsets.UTF_8)
        return updated
    }

    private fun requestRemoteTranslations(serviceUrl: String, texts: List<String>): List<String> {
        val translated = mutableListOf<String>()
        var start = 0
        while (start < texts.size) {
            val end = (start + REMOTE_TRANSLATION_BATCH_SIZE).coerceAtMost(texts.size)
            progress("电脑端翻译中：${start + 1}-$end/${texts.size}（首次加载模型可能较久）")
            translated += requestRemoteTranslationBatchWithRetry(serviceUrl, texts.subList(start, end), start + 1, end, texts.size)
            progress("电脑端翻译中：$end/${texts.size}")
            start = end
        }
        return translated
    }

    private fun requestRemoteTranslationBatchWithRetry(
        serviceUrl: String,
        texts: List<String>,
        from: Int,
        to: Int,
        total: Int
    ): List<String> {
        var lastError: Exception? = null
        repeat(3) { attempt ->
            try {
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
            .setContentTitle("正在生成字幕")
            .setContentText(message)
            .setStyle(Notification.BigTextStyle().bigText(message))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
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
            acquire(3 * 60 * 60 * 1000L)
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

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    companion object {
        const val ACTION_PROGRESS = "com.codex.videolearnenglish.CAPTION_PROGRESS"
        const val ACTION_DONE = "com.codex.videolearnenglish.CAPTION_DONE"
        const val ACTION_TRANSLATION_DONE = "com.codex.videolearnenglish.TRANSLATION_DONE"
        const val ACTION_ERROR = "com.codex.videolearnenglish.CAPTION_ERROR"
        const val EXTRA_VIDEO_URI = "video_uri"
        const val EXTRA_SERVICE_URL = "service_url"
        const val EXTRA_SERVICE_URLS = "service_urls"
        const val EXTRA_TASK_KIND = "task_kind"
        const val EXTRA_MESSAGE = "message"
        const val EXTRA_COUNT = "count"
        const val TASK_GENERATE = "generate"
        const val TASK_TRANSLATE_REMOTE = "translate_remote"
        const val TASK_TRANSLATE_PHONE = "translate_phone"
        const val TRANSLATION_SOURCE_COMPUTER = "computer"
        const val TRANSLATION_SOURCE_PHONE = "phone"
        private const val CHANNEL_ID = "caption_generation"
        private const val NOTIFICATION_ID = 42
        private const val SUBTITLE_CACHE_DIR = "subtitles_cache"
        private const val REMOTE_TRANSLATION_BATCH_SIZE = 16
        private const val PREFS_NAME = "video_english_learning"
        private const val SERVICE_URL_KEY = "whisper_service_url"
        private const val SERVICE_URL_CANDIDATES_KEY = "whisper_service_url_candidates"
    }
}
