package com.codex.videolearnenglish

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

enum class CaptionTaskStatus(val id: String) {
    QUEUED("queued"),
    RUNNING("running"),
    PAUSED("paused"),
    DONE("done"),
    FAILED("failed"),
    CANCELED("canceled");

    companion object {
        fun from(value: String?): CaptionTaskStatus =
            values().firstOrNull { it.id == value } ?: QUEUED
    }
}

data class CaptionTask(
    val id: String,
    val uri: String,
    val title: String,
    val status: CaptionTaskStatus,
    val taskKind: String,
    val stage: String,
    val progress: Int,
    val message: String,
    val connectionLabel: String,
    val subtitleCount: Int,
    val bilingual: Boolean,
    val failureCount: Int,
    val createdAt: Long,
    val updatedAt: Long,
    val completedAt: Long,
    val error: String?,
    val audioHash: String,
    val uploadId: String,
    val uploadedBytes: Long,
    val totalBytes: Long,
    val remoteJobId: String,
    val remoteUpdatedAt: Long,
    val forceTranscribe: Boolean
)

object CaptionTaskStore {
    private const val FILE_NAME = "caption_tasks.json"
    const val TASK_GENERATE = "generate"
    const val TASK_TRANSLATE_REMOTE = "translate_remote"
    const val TASK_TRANSLATE_PHONE = "translate_phone"

    @Synchronized
    fun all(context: Context): List<CaptionTask> = read(context)

    @Synchronized
    fun enqueue(
        context: Context,
        uri: Uri,
        title: String,
        taskKind: String = TASK_GENERATE,
        resetFailures: Boolean = true,
        forceTranscribe: Boolean? = null
    ): CaptionTask {
        val now = System.currentTimeMillis()
        val id = stableId(uri.toString())
        val tasks = read(context).toMutableList()
        val existingIndex = tasks.indexOfFirst { it.id == id }
        val existing = tasks.getOrNull(existingIndex)
        val forceRegeneration = taskKind == TASK_GENERATE && (
            forceTranscribe ?: (existing?.forceTranscribe == true || existing?.status == CaptionTaskStatus.DONE)
        )
        val task = CaptionTask(
            id = id,
            uri = uri.toString(),
            title = title.ifBlank { displayNameFromUri(uri) },
            status = CaptionTaskStatus.QUEUED,
            taskKind = taskKind,
            stage = "等待中",
            progress = 0,
            message = "已加入字幕生成队列",
            connectionLabel = "",
            subtitleCount = 0,
            bilingual = false,
            failureCount = if (resetFailures) 0 else existing?.failureCount ?: 0,
            createdAt = existing?.createdAt ?: now,
            updatedAt = now,
            completedAt = 0L,
            error = null,
            audioHash = existing?.audioHash.orEmpty(),
            uploadId = existing?.uploadId.orEmpty(),
            uploadedBytes = existing?.uploadedBytes ?: 0L,
            totalBytes = existing?.totalBytes ?: 0L,
            remoteJobId = "",
            remoteUpdatedAt = existing?.remoteUpdatedAt ?: 0L,
            forceTranscribe = forceRegeneration
        )
        if (existingIndex >= 0) tasks[existingIndex] = task else tasks.add(0, task)
        write(context, tasks)
        return task
    }

    @Synchronized
    fun markRunning(context: Context, id: String, message: String = "处理中") {
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.RUNNING,
                stage = stageFromMessage(message),
                message = message,
                progress = percentFromMessage(message) ?: it.progress.coerceAtLeast(1),
                connectionLabel = connectionFromMessage(message).ifBlank { it.connectionLabel },
                updatedAt = System.currentTimeMillis(),
                error = null
            )
        }
    }

    @Synchronized
    fun updateProgress(context: Context, id: String, message: String) {
        update(context, id) { task ->
            val connection = connectionFromMessage(message)
            if (isConnectionOnlyMessage(message)) {
                task.copy(
                    status = CaptionTaskStatus.RUNNING,
                    connectionLabel = connection.ifBlank { task.connectionLabel },
                    updatedAt = System.currentTimeMillis()
                )
            } else {
                task.copy(
                    status = CaptionTaskStatus.RUNNING,
                    stage = stageFromMessage(message),
                    message = stableDisplayMessage(message),
                    progress = percentFromMessage(message) ?: task.progress,
                    connectionLabel = connection.ifBlank { task.connectionLabel },
                    updatedAt = System.currentTimeMillis()
                )
            }
        }
    }

    @Synchronized
    fun markDone(context: Context, id: String, subtitleCount: Int) {
        val now = System.currentTimeMillis()
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.DONE,
                stage = "已完成",
                progress = 100,
                message = "已生成中英双语字幕",
                subtitleCount = subtitleCount,
                bilingual = true,
                failureCount = 0,
                updatedAt = now,
                completedAt = now,
                error = null
            )
        }
    }

    @Synchronized
    fun markFailed(context: Context, id: String, message: String) {
        val now = System.currentTimeMillis()
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.FAILED,
                stage = "失败",
                message = message,
                error = message,
                failureCount = it.failureCount + 1,
                updatedAt = now
            )
        }
    }

    @Synchronized
    fun markFailedOrRetry(context: Context, id: String, message: String, maxFailures: Int): Boolean {
        var willRetry = false
        val now = System.currentTimeMillis()
        update(context, id) {
            val failures = it.failureCount + 1
            willRetry = failures < maxFailures
            if (willRetry) {
                it.copy(
                    status = CaptionTaskStatus.QUEUED,
                    stage = "等待续跑",
                    progress = it.progress.coerceAtMost(99),
                    message = "任务中断，已保留缓存，稍后自动继续（第 $failures/$maxFailures 次）。$message",
                    failureCount = failures,
                    updatedAt = now,
                    error = message
                )
            } else {
                it.copy(
                    status = CaptionTaskStatus.FAILED,
                    stage = "失败",
                    message = "已自动重试 $maxFailures 次仍失败，请检查电脑端服务后手动重试。$message",
                    failureCount = failures,
                    updatedAt = now,
                    error = message
                )
            }
        }
        return willRetry
    }

    @Synchronized
    fun recordUpload(
        context: Context,
        id: String,
        audioHash: String,
        uploadId: String,
        uploadedBytes: Long,
        totalBytes: Long
    ) {
        update(context, id) {
            it.copy(
                audioHash = audioHash.ifBlank { it.audioHash },
                uploadId = uploadId.ifBlank { it.uploadId },
                uploadedBytes = uploadedBytes.coerceAtLeast(0L),
                totalBytes = totalBytes.coerceAtLeast(0L),
                remoteUpdatedAt = System.currentTimeMillis(),
                updatedAt = System.currentTimeMillis()
            )
        }
    }

    @Synchronized
    fun recordRemoteJob(context: Context, id: String, jobId: String) {
        update(context, id) {
            it.copy(
                remoteJobId = jobId,
                remoteUpdatedAt = System.currentTimeMillis(),
                updatedAt = System.currentTimeMillis(),
                error = null
            )
        }
    }

    @Synchronized
    fun updateRemoteProgress(
        context: Context,
        id: String,
        stage: String,
        progress: Int,
        message: String,
        connectionLabel: String = ""
    ) {
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.RUNNING,
                stage = stage,
                progress = progress.coerceIn(0, 100),
                message = message,
                connectionLabel = connectionLabel.ifBlank { it.connectionLabel },
                remoteUpdatedAt = System.currentTimeMillis(),
                updatedAt = System.currentTimeMillis(),
                error = null
            )
        }
    }

    @Synchronized
    fun markWaitingForComputer(context: Context, id: String, message: String) {
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.QUEUED,
                stage = "等待连接电脑",
                message = message,
                updatedAt = System.currentTimeMillis(),
                error = null
            )
        }
    }

    @Synchronized
    fun clearRemoteJob(context: Context, id: String) {
        update(context, id) {
            it.copy(remoteJobId = "", remoteUpdatedAt = 0L, updatedAt = System.currentTimeMillis())
        }
    }

    @Synchronized
    fun cancel(context: Context, id: String) {
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.CANCELED,
                stage = "已取消",
                message = "任务已取消",
                updatedAt = System.currentTimeMillis()
            )
        }
    }

    @Synchronized
    fun pause(context: Context, id: String) {
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.PAUSED,
                stage = "已暂停",
                message = "任务已暂停，点继续可接着处理。",
                updatedAt = System.currentTimeMillis()
            )
        }
    }

    @Synchronized
    fun resume(context: Context, id: String): CaptionTask? {
        var resumed: CaptionTask? = null
        update(context, id) {
            it.copy(
                status = CaptionTaskStatus.QUEUED,
                stage = "等待继续",
                message = "已加入队列，准备继续处理。",
                updatedAt = System.currentTimeMillis(),
                error = null
            ).also { task -> resumed = task }
        }
        return resumed
    }

    @Synchronized
    fun delete(context: Context, id: String) {
        write(context, read(context).filterNot { it.id == id })
    }

    @Synchronized
    fun queued(context: Context): CaptionTask? =
        read(context).firstOrNull { it.status == CaptionTaskStatus.QUEUED }

    @Synchronized
    fun recoverable(context: Context): CaptionTask? =
        read(context).let { tasks ->
            tasks.firstOrNull { it.status == CaptionTaskStatus.RUNNING }
                ?: tasks.firstOrNull { it.status == CaptionTaskStatus.QUEUED }
        }

    fun stableId(uri: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(uri.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun update(context: Context, id: String, mapper: (CaptionTask) -> CaptionTask) {
        val tasks = read(context).toMutableList()
        val index = tasks.indexOfFirst { it.id == id }
        if (index < 0) return
        tasks[index] = mapper(tasks[index])
        write(context, tasks)
    }

    private fun read(context: Context): List<CaptionTask> {
        val file = storeFile(context)
        if (!file.exists()) return emptyList()
        return runCatching {
            val array = JSONArray(file.readText(Charsets.UTF_8))
            (0 until array.length()).mapNotNull { index ->
                val item = array.optJSONObject(index) ?: return@mapNotNull null
                CaptionTask(
                    id = item.optString("id"),
                    uri = item.optString("uri"),
                    title = item.optString("title"),
                    status = CaptionTaskStatus.from(item.optString("status")),
                    taskKind = item.optString("taskKind", TASK_GENERATE).ifBlank { TASK_GENERATE },
                    stage = item.optString("stage"),
                    progress = item.optInt("progress", 0).coerceIn(0, 100),
                    message = item.optString("message"),
                    connectionLabel = item.optString("connectionLabel"),
                    subtitleCount = item.optInt("subtitleCount", 0),
                    bilingual = item.optBoolean("bilingual", false),
                    failureCount = item.optInt("failureCount", 0).coerceAtLeast(0),
                    createdAt = item.optLong("createdAt", 0L),
                    updatedAt = item.optLong("updatedAt", 0L),
                    completedAt = item.optLong("completedAt", 0L),
                    error = item.optString("error").takeIf { value -> value.isNotBlank() && value != "null" },
                    audioHash = item.optString("audioHash"),
                    uploadId = item.optString("uploadId"),
                    uploadedBytes = item.optLong("uploadedBytes", 0L).coerceAtLeast(0L),
                    totalBytes = item.optLong("totalBytes", 0L).coerceAtLeast(0L),
                    remoteJobId = item.optString("remoteJobId"),
                    remoteUpdatedAt = item.optLong("remoteUpdatedAt", 0L),
                    forceTranscribe = item.optBoolean("forceTranscribe", false)
                )
            }
        }.getOrDefault(emptyList())
    }

    private fun write(context: Context, tasks: List<CaptionTask>) {
        val array = JSONArray()
        tasks.forEach { task ->
            array.put(JSONObject().apply {
                put("id", task.id)
                put("uri", task.uri)
                put("title", task.title)
                put("status", task.status.id)
                put("taskKind", task.taskKind)
                put("stage", task.stage)
                put("progress", task.progress)
                put("message", task.message)
                put("connectionLabel", task.connectionLabel)
                put("subtitleCount", task.subtitleCount)
                put("bilingual", task.bilingual)
                put("failureCount", task.failureCount)
                put("createdAt", task.createdAt)
                put("updatedAt", task.updatedAt)
                put("completedAt", task.completedAt)
                put("error", task.error ?: JSONObject.NULL)
                put("audioHash", task.audioHash)
                put("uploadId", task.uploadId)
                put("uploadedBytes", task.uploadedBytes)
                put("totalBytes", task.totalBytes)
                put("remoteJobId", task.remoteJobId)
                put("remoteUpdatedAt", task.remoteUpdatedAt)
                put("forceTranscribe", task.forceTranscribe)
            })
        }
        storeFile(context).writeText(array.toString(), Charsets.UTF_8)
    }

    private fun storeFile(context: Context): File =
        File(context.filesDir, FILE_NAME)

    private fun displayNameFromUri(uri: Uri): String =
        uri.lastPathSegment?.substringAfterLast('/')?.ifBlank { null } ?: "未命名视频"

    private fun percentFromMessage(message: String): Int? {
        Regex("""(\d{1,3})%""").find(message)?.let { match ->
            return match.groupValues[1].toIntOrNull()?.coerceIn(0, 100)
        }
        Regex("""(\d+)\s*/\s*(\d+)""").find(message)?.let { match ->
            val current = match.groupValues[1].toIntOrNull() ?: return null
            val total = match.groupValues[2].toIntOrNull()?.takeIf { it > 0 } ?: return null
            val fraction = current.toDouble() / total.toDouble()
            return if (message.contains("翻译")) {
                (92 + (fraction * 7).toInt()).coerceIn(92, 99)
            } else {
                (current * 100 / total).coerceIn(0, 100)
            }
        }
        return null
    }

    private fun isConnectionOnlyMessage(message: String): Boolean =
        message.startsWith("已选择 Whisper 服务") ||
            message.startsWith("检测到更稳定的连接") ||
            message.startsWith("轮询连接中断") ||
            message.startsWith("上传连接中断")

    private fun stableDisplayMessage(message: String): String =
        when {
            message.startsWith("正在生成字幕") && message.contains("Translating subtitles") -> {
                val batch = Regex("""(\d+)\s*/\s*(\d+)""").find(message)?.value.orEmpty()
                if (batch.isNotBlank()) "正在翻译字幕：$batch" else "正在翻译字幕"
            }
            message.startsWith("正在生成字幕") && message.contains("Translating English subtitles") -> "正在准备翻译英文字幕"
            message.contains("翻译模型已加载") -> message.replace("翻译模型已加载，", "")
            else -> message
        }

    private fun connectionFromMessage(message: String): String {
        return when {
            message.contains("USB", ignoreCase = true) -> "USB"
            message.contains("局域网") -> "局域网"
            message.contains("公网") -> "公网"
            message.contains("模拟器") -> "模拟器"
            else -> ""
        }
    }

    private fun stageFromMessage(message: String): String {
        return when {
            message.contains("提取音频") -> "提取音频"
            message.contains("压缩音频") -> "提取音频"
            message.contains("上传") -> "上传中"
            message.contains("生成字幕") -> "识别中"
            message.contains("Whisper") -> "识别中"
            message.contains("翻译") -> "翻译中"
            message.contains("保存") -> "保存中"
            message.contains("连接") -> "连接中"
            else -> "处理中"
        }
    }
}
