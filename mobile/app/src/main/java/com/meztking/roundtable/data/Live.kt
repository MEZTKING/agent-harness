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
)

/** The latest task's steps: the hub's plans/shots/<project>/session.json, or /api/project/session?compact=1. */
@Serializable
data class SessionSummary(val project: String = "", val at: String = "", val task: SessionTask? = null)

/** What the Live tab shows: the newest pictures (as bytes, by kind) and the latest task's steps. */
data class LiveView(
    val shots: LiveShots? = null,
    val images: Map<String, ByteArray> = emptyMap(),
    val session: SessionSummary? = null,
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
