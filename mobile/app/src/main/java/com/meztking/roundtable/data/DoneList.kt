package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/**
 * The done list (the PC's GET /api/done?path, harness/donelist.py): what a person can do with the finished thing,
 * and whether each was shown to work. An item nobody could check never shows a tick.
 */
@Serializable
data class DoneItem(val id: String = "", val text: String = "", val how: String = "look", val must: Boolean = true,
                    val by: String = "planner", val state: String = "open", val words: String = "")

@Serializable
data class DoneSummary(val items: List<DoneItem> = emptyList(), val checked: Int = 0, val passed: Int = 0,
                       val failed: Int = 0, val unchecked: Int = 0, val words: String = "", val finished: Boolean = false)

@Serializable
data class DonePicture(val name: String = "", val data: String = "")

@Serializable
data class DoneEvidence(val found: Boolean = false, val item: String = "", val text: String = "", val state: String = "open",
                        val words: String = "", val texts: Map<String, String> = emptyMap(),
                        val pictures: List<DonePicture> = emptyList())

object DoneList {
    fun url(path: String): String = "/api/done?path=${URLEncoder.encode(path, "UTF-8")}"

    fun evidenceUrl(path: String, item: String): String =
        "/api/done/evidence?path=${URLEncoder.encode(path, "UTF-8")}&item=${URLEncoder.encode(item, "UTF-8")}"

    fun parse(json: String?): DoneSummary? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(DoneSummary.serializer(), it) }.getOrNull() }

    fun parseEvidence(json: String?): DoneEvidence? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(DoneEvidence.serializer(), it) }.getOrNull() }

    /** The mark beside an item: ✓ only when it was really shown to work. */
    fun mark(state: String): String = when (state) { "passed" -> "✓"; "failed" -> "✗"; "unchecked" -> "?"; else -> "·" }

    fun markWords(state: String): String = when (state) {
        "passed" -> "It was shown to work"
        "failed" -> "It was tried and doesn't work yet"
        "unchecked" -> "It couldn't be checked here, so it has no tick"
        else -> "Not checked yet"
    }

    /** The small labels after an item's words. */
    fun tags(i: DoneItem): List<String> = buildList {
        if (!i.must) add("nice to have")
        if (i.by == "owner") add("yours")
        if (i.by == "kind") add("for its kind")
    }

    /** The one line, made here when an older PC sends none. */
    fun line(s: DoneSummary): String = s.words.ifBlank {
        val n = s.items.size
        when {
            n == 0 -> "No done list yet."
            s.failed > 0 -> "Done when: ${s.passed} of $n ✓ · ${s.failed} ${if (s.failed == 1) "doesn’t" else "don’t"} work yet"
            else -> "Done when: ${s.passed} of $n ✓"
        }
    }

    /** Each picture's bytes, from its data address. */
    fun pictureBytes(e: DoneEvidence): List<Pair<String, ByteArray>> =
        e.pictures.mapNotNull { p -> Live.dataUrl(p.data)?.let { p.name to it } }
}
