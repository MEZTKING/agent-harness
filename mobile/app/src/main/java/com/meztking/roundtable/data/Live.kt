package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.util.Base64

/** One earlier task's picture in the hub (plans/shots/<project>/<task>-desktop.jpg). */
@Serializable
data class ShotHistory(val task: String = "", val at: String = "", val title: String = "", val picture: String = "")

/**
 * The newest pictures of a project's app (Show it): the hub's plans/shots/<project>/latest.json,
 * or the "latest" part of the PC's /api/project/live. [pictures]: kind (desktop, phone, dark) -> file name.
 */
@Serializable
data class LiveShots(
    val task: String = "",
    val at: String = "",
    val title: String = "",
    val pictures: Map<String, String> = emptyMap(),
    val errors: List<String> = emptyList(),
    val note: String = "",
    val failed: String = "",
    val history: List<ShotHistory> = emptyList(),
)

/** One step of the latest task as one short line (no file contents). */
@Serializable
data class SessionStep(val kind: String = "", val line: String = "", val error: Boolean = false)

@Serializable
data class SessionTask(
    val id: String = "", val title: String = "", val role: String = "", val status: String = "",
    val cost: Double = 0.0, val summary: String = "", val steps: List<SessionStep> = emptyList(),
    /** What it is doing now, in one line. */
    val now: String = "",
    /** Where its time went; null when nothing was timed (an older log): never shown as zero. */
    val time: TaskTime? = null,
    /** How full the newest model call's context was, and the cache-hit rate. */
    val context: TaskContext? = null,
    /** The files it changed. */
    val changes: List<FileChange> = emptyList(),
)

/** One part of a task's time: key first, writing, model, tools, you or other. */
@Serializable
data class TimePart(val key: String = "", val label: String = "", val ms: Long = 0)

@Serializable
data class TaskTime(val parts: List<TimePart> = emptyList(), val total_ms: Long = 0, val unrecorded: Int = 0) {
    val total: Long get() = if (total_ms > 0) total_ms else parts.sumOf { it.ms }
}

/** Tokens of the newest model call against the model's window (window and share null when unknown). */
@Serializable
data class TaskContext(val used: Long = 0, val window: Long? = null, val share: Double? = null, val model: String = "",
                       val cache_hit: Double? = null)

@Serializable
data class FileChange(val path: String = "", val added: Int = 0, val removed: Int = 0, val new: Boolean = false)

/** The latest task's steps: the hub's plans/shots/<project>/session.json, or /api/project/session?compact=1.
 * [tasks]: every task still running (several run at once), else the latest alone; older sources send only [task]. */
@Serializable
data class SessionSummary(val project: String = "", val at: String = "", val task: SessionTask? = null,
                          val tasks: List<SessionTask> = emptyList()) {
    /** The tasks to show: [tasks], or the one [task] from an older source. */
    val shown: List<SessionTask> get() = tasks.ifEmpty { listOfNotNull(task) }
}

/** What the Live tab shows: the newest pictures (as bytes, by kind) and the latest task's steps. */
data class LiveView(
    val shots: LiveShots? = null,
    val images: Map<String, ByteArray> = emptyMap(),
    val session: SessionSummary? = null,
    /** Where the steps came from, in words ("From your PC", "Through the hub"). */
    val from: String = "",
    /** The run is still going (the screen keeps refreshing). */
    val running: Boolean = false,
    /** "T3 of 7", when the run's events say. */
    val progress: String = "",
) {
    val kinds: List<String> get() = KINDS.filter { it in images }

    companion object {
        val KINDS = listOf("desktop", "phone", "dark")
        val NAMES = mapOf("desktop" to "Computer", "phone" to "Phone", "dark" to "Dark mode")
    }
}

@Serializable
private data class PcLive(val latest: LiveShots? = null, val images: Map<String, String> = emptyMap())

object Live {
    fun parseShots(json: String?): LiveShots? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(LiveShots.serializer(), it) }.getOrNull() }

    fun parseSession(json: String?): SessionSummary? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(SessionSummary.serializer(), it) }.getOrNull() }

    /** The PC's /api/project/live?inline=1: the newest pictures come as data addresses. */
    fun parsePc(json: String): Pair<LiveShots?, Map<String, ByteArray>> {
        val pc = ApiJson.decodeFromString(PcLive.serializer(), json)
        return pc.latest to pc.images.mapNotNull { (k, v) -> dataUrl(v)?.let { k to it } }.toMap()
    }

    /** The bytes of a data:image/...;base64,... address, or null. */
    fun dataUrl(url: String): ByteArray? {
        if (!url.startsWith("data:")) return null
        val comma = url.indexOf(',')
        if (comma < 0 || !url.substring(0, comma).endsWith(";base64")) return null
        return runCatching { Base64.getDecoder().decode(url.substring(comma + 1)) }.getOrNull()
    }
}
