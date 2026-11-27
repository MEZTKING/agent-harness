package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable

/**
 * A plan in the owner's words, short first (plandoc.plan_words on the PC, next to the cards in
 * plans/<project>.asks.json, or the "words" of the PC's /api/plan): its title, a plain summary,
 * one sentence of where it stands, what waits for the owner, and the estimate while it waits.
 */
@Serializable
data class PlanWords(
    val title: String = "",
    val summary: String = "",
    val state: String = "",
    val waiting: List<String> = emptyList(),
    val estimate: String = "",
) {
    /** Changes the owner made that the planner hasn't put in yet ("2 changes to apply"). */
    val pendingChanges: Boolean get() = waiting.any { "change" in it }

    companion object {
        fun parse(json: String?): PlanWords? =
            json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(serializer(), it) }.getOrNull() }
                ?.takeIf { it.title.isNotBlank() || it.state.isNotBlank() }

        private val bracketed = Regex("\\([^)]*\\)")
        private val fileName = Regex("\\S+\\.(?:html|css|js|json|py|kt|md|ts|yaml|yml|txt|png|exe|apk)\\b|\\S*/\\S+")
        private val tech = Regex("\\b(?:APK|EXE|Electron|Kotlin|WebView\\w*|Capacitor|npm|node|React|Vue|API|SDK|JSON|HTML|CSS|JS|" +
            "TypeScript|Python|Gradle|PyInstaller|v?\\d+\\.\\d+(?:\\.\\d+)?)\\b", RegexOption.IGNORE_CASE)
        private val dangling = Regex("(?:\\s+|^)(?:and|or|with|as|an?|the|for|to|of|in|on|by|from|using)$", RegexOption.IGNORE_CASE)
        private val article = Regex("^(?:a|an|the)\\s+", RegexOption.IGNORE_CASE)
        private val sentenceEnd = Regex("(?<=[.!?])\\s|[:;](?:\\s|$)")

        private fun tidyEnd(s: String): String {
            var t = s
            while (true) {
                val next = dangling.replace(t.trimEnd(' ', ',', '-', '–', '—', ':', ';'), "").trimEnd(' ', ',', '-', '–', '—', ':', ';')
                if (next == t) return t
                t = next
            }
        }

        /**
         * A title for a plan that has none (the same rule as plandoc.short_title): the first sentence, without
         * bracketed asides, file names and tool names where that still leaves something, at most 60 characters.
         */
        fun shortTitle(text: String): String {
            val flat = text.split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
            val first = sentenceEnd.find(flat)?.let { flat.substring(0, it.range.first) } ?: flat
            val plain = fileName.replace(bracketed.replace(first.trimEnd('.', '!', '?', ':', ';', ' '), ""), "")
                .split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").trim(' ', ',', '-', '–', '—')
            val cleaner = tech.replace(plain, "").split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").trim(' ', ',', '-', '–', '—')
            var pick = tidyEnd(if (cleaner.split(" ").size >= 3) cleaner else plain.ifBlank { first })
            pick = article.replace(pick, "")
            if (pick.isBlank()) return "The plan"
            pick = pick.replaceFirstChar { it.uppercase() }
            if (pick.length > 60) pick = tidyEnd(pick.take(60).substringBeforeLast(' ')).ifBlank { pick.take(60) }
            return pick
        }
    }
}
