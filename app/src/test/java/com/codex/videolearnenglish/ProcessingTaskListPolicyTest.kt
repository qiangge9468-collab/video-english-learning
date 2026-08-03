package com.codex.videolearnenglish

import org.junit.Assert.assertEquals
import org.junit.Test

class ProcessingTaskListPolicyTest {
    @Test
    fun progressUpdatesDoNotReorderTasks() {
        val oldest = task("oldest", createdAt = 100, updatedAt = 900)
        val middle = task("middle", createdAt = 200, updatedAt = 800)
        val newest = task("newest", createdAt = 300, updatedAt = 700)
        assertEquals(
            listOf("oldest", "middle", "newest"),
            ProcessingTaskListPolicy.visibleTasks(listOf(newest, oldest, middle)).map { it.id }
        )

        val newestProgressUpdate = newest.copy(progress = 80, updatedAt = 10_000)
        assertEquals(
            listOf("oldest", "middle", "newest"),
            ProcessingTaskListPolicy.visibleTasks(listOf(newestProgressUpdate, oldest, middle)).map { it.id }
        )
    }

    @Test
    fun completedAndCanceledTasksLeaveProcessingList() {
        val tasks = listOf(
            task("queued", status = CaptionTaskStatus.QUEUED),
            task("running", status = CaptionTaskStatus.RUNNING),
            task("paused", status = CaptionTaskStatus.PAUSED),
            task("failed", status = CaptionTaskStatus.FAILED),
            task("done", status = CaptionTaskStatus.DONE),
            task("canceled", status = CaptionTaskStatus.CANCELED)
        )
        assertEquals(
            listOf("queued", "running", "paused", "failed"),
            ProcessingTaskListPolicy.visibleTasks(tasks).map { it.id }
        )
    }

    private fun task(
        id: String,
        status: CaptionTaskStatus = CaptionTaskStatus.QUEUED,
        createdAt: Long = 1,
        updatedAt: Long = 1
    ) = CaptionTask(
        id = id, uri = "content://video/$id", title = id, status = status,
        taskKind = CaptionTaskStore.TASK_GENERATE, stage = "等待中", progress = 30,
        message = "等待", connectionLabel = "USB", subtitleCount = 0, bilingual = false,
        failureCount = 0, createdAt = createdAt, updatedAt = updatedAt, completedAt = 0,
        error = null, audioHash = "", uploadId = "", uploadedBytes = 0, totalBytes = 0,
        uploadPrepared = false, remoteJobId = "", remoteUpdatedAt = 0, forceTranscribe = false
    )
}
