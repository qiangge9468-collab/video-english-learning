package com.codex.videolearnenglish

object ProcessingTaskListPolicy {
    private val visibleStatuses = setOf(
        CaptionTaskStatus.QUEUED,
        CaptionTaskStatus.RUNNING,
        CaptionTaskStatus.PAUSED,
        CaptionTaskStatus.FAILED
    )

    fun visibleTasks(tasks: List<CaptionTask>): List<CaptionTask> = tasks
        .asSequence()
        .filter { it.status in visibleStatuses }
        .sortedBy { it.createdAt }
        .toList()
}
