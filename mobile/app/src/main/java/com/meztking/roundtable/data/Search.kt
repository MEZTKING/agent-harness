package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable

/** Where a hit opens: room is project, file, memory, journal, letter, note or hub_plan (ui/searchapi.py). */
@Serializable
data class SearchOpen(
    val room: String = "",
    val path: String = "",
    val tab: String = "",
    val task: String = "",
    val file: String = "",
    val line: Int = 0,
    val machine: Boolean = false,
    val archive: Boolean = false,
    val agent: String = "",
    val id: String = "",
    val thread: String = "",
    val name: String = "",
)

@Serializable
data class SearchHit(
    val kind: String = "",
    val title: String = "",
    val where: String = "",
    val snippet: String = "",
    val at: String = "",
    val open: SearchOpen = SearchOpen(),
)

@Serializable
data class SearchResult(val query: String = "", val hits: List<SearchHit> = emptyList(), val total: Int = 0, val words: String = "")

@Serializable
data class FilePeek(val file: String = "", val from: Int = 1, val line: Int = 0, val lines: List<String> = emptyList(), val words: String = "")

@Serializable
data class MemoryText(val markdown: String = "", val where: String = "", val words: String = "", val archive: Boolean = false)

/** The phone's side of search: reading the PC's answers, the places to look, and which words to mark. */
object Search {
    /** The chips above the results: label, what they look in (empty: everywhere), tooltip-ish words. */
    val places = listOf(
        Triple("Everything", "", "Every place"),
        Triple("Plans and tasks", "plan,task", "The plans and every task"),
        Triple("Memory", "memory", "What Roundtable remembers"),
        Triple("Journal and letters", "journal,letter,note", "The journal, your letters and saved notes"),
        Triple("Files", "file", "The projects' own files"),
    )

    fun parse(json: String): SearchResult = runCatching { ApiJson.decodeFromString(SearchResult.serializer(), json) }.getOrDefault(SearchResult())
    fun parsePeek(json: String): FilePeek = runCatching { ApiJson.decodeFromString(FilePeek.serializer(), json) }.getOrDefault(FilePeek())
    fun parseMemory(json: String): MemoryText = runCatching { ApiJson.decodeFromString(MemoryText.serializer(), json) }.getOrDefault(MemoryText())

    /** The words the PC looked for: "quoted words" together, the rest one by one, lower case. */
    fun terms(query: String): List<String> {
        val q = query.lowercase()
        val quoted = Regex("\"([^\"]+)\"").findAll(q).map { it.groupValues[1].trim() }.filter { it.isNotEmpty() }.toList()
        val rest = q.replace(Regex("\"[^\"]*\"?"), " ")
        val single = Regex("[\\w.+#/-]+").findAll(rest).map { it.value }.toList()
        return (quoted + single).distinct()
    }

    /** Where each word appears in [text], as (start, end) pairs in order, never overlapping. */
    fun marks(text: String, query: String): List<Pair<Int, Int>> {
        val words = terms(query)
        if (words.isEmpty()) return emptyList()
        val low = text.lowercase()
        val out = mutableListOf<Pair<Int, Int>>()
        var i = 0
        while (i < low.length) {
            var best = -1
            var len = 0
            for (w in words) {
                val at = low.indexOf(w, i)
                if (at >= 0 && (best < 0 || at < best)) { best = at; len = w.length }
            }
            if (best < 0) break
            out += best to best + len
            i = best + len
        }
        return out
    }

    /** What tapping a hit does, in words (shown under it). */
    fun openWords(hit: SearchHit): String = when (hit.open.room) {
        "project", "hub_plan" -> "Opens the plan"
        "journal" -> "Opens the journal"
        "letter" -> "Opens your letters"
        "note" -> "Opens the saved note"
        "memory" -> if (hit.open.archive) "Shows the older memory" else "Shows the memory"
        "file" -> "Shows the file"
        else -> ""
    }
}
