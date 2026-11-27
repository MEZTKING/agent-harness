package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * What the harness learned, from the PC (or this phone's own harness): GET /api/learned (ui/learnedapi.py,
 * improve/ledger.py). One plain line per change, each with an Undo; what waits for the owner is counted only, as
 * using or turning down a change stays on the PC. The phone may only undo (POST /api/learned/undo).
 */
@Serializable
data class LearnedLine(
    val id: String = "",
    val `when`: String = "",
    val words: String = "",
    val what: String = "",
    val why: String = "",
    val state: String = "on",
    val by: String = "",
    val can_undo: Boolean = false,
    val can_put_back: Boolean = false,
    val kind: String = "",
    val role: String = "",
)

@Serializable
data class LearnedWaiting(val id: String = "", val words: String = "", val why: String = "", val from: String = "")

@Serializable
data class LearnedWallet(val on: Boolean = false, val allowance: Double = 0.0, val left: Double = 0.0, val words: String = "")

@Serializable
data class LearnedView(
    val lines: List<LearnedLine> = emptyList(),
    val waiting: List<LearnedWaiting> = emptyList(),
    val never: List<String> = emptyList(),
    val wallet: LearnedWallet = LearnedWallet(),
)

object Learned {
    const val URL = "/api/learned"
    const val UNDO_URL = "/api/learned/undo"
    private val STATES = mapOf("on" to "In use", "watching" to "Being watched", "undone" to "Undone", "put_back" to "Put back")

    fun parse(json: String?): LearnedView? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(LearnedView.serializer(), it) }.getOrNull() }

    /** The body of an undo: only the change's id (the phone can't do anything else). */
    fun undoBody(id: String): String = buildJsonObject { put("id", id) }.toString()

    fun stateWords(state: String): String = STATES[state] ?: state.replace('_', ' ').replaceFirstChar { it.uppercase() }

    /** The line as the card shows it: the PC's words, or the change and why when an older PC left them out. */
    fun line(l: LearnedLine): String = l.words.ifBlank {
        listOf(l.what, l.why).filter { it.isNotBlank() }.joinToString(": ").let { if (it.isBlank()) "A change" else "$it." }
    }

    fun byWords(l: LearnedLine): String = listOf(l.by, stateWords(l.state)).filter { it.isNotBlank() }.joinToString(" · ")

    /** One sentence at the top: how many changes are in use and how many wait on the PC. */
    fun summary(v: LearnedView): String {
        val on = v.lines.count { it.state != "undone" }
        val head = when (on) { 0 -> "Nothing learned in use yet."; 1 -> "1 change learned is in use."; else -> "$on changes learned are in use." }
        val wait = when (v.waiting.size) { 0 -> ""; 1 -> " 1 waits for you on the PC."; else -> " ${v.waiting.size} wait for you on the PC." }
        return head + wait
    }
}
