package com.meztking.roundtable.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The new-project cards (GET /api/asks?wizard=1, asks.py wizard_asks), asked one at a time: what to make, the idea,
 * "Make it like this", the set of models and the look. The idea's card is the message box (its words, photos and
 * files); the others are ordinary cards. The answers go to POST /api/attach/start as `{wizard: {id: {chosen, other}}}`.
 */
data class WizardFlow(val asks: List<Ask>, val answers: Map<String, AskReply> = emptyMap(), val at: Int = 0) {
    val current: Ask? get() = asks.getOrNull(at)
    val done: Boolean get() = at >= asks.size
    /** "2 of 5". */
    val step: String get() = "${(at + 1).coerceAtMost(asks.size)} of ${asks.size}"

    /** The idea card is the message box, not a card. */
    fun isIdea(a: Ask? = current) = a?.id == IDEA

    fun answer(id: String, r: AskReply): WizardFlow {
        val i = asks.indexOfFirst { it.id == id }.takeIf { it >= 0 } ?: return this
        return copy(answers = answers + (id to r), at = maxOf(at, i + 1))
    }

    fun back(): WizardFlow = copy(at = (at - 1).coerceAtLeast(0))

    /** What the owner chose on one card, in words ("Web app", "your own words"). */
    fun said(id: String): String {
        val a = asks.firstOrNull { it.id == id } ?: return ""
        val r = answers[id] ?: return ""
        val labels = r.chosen.mapNotNull { c -> a.options.firstOrNull { it.id == c }?.label }
        return (labels + listOfNotNull(r.other.trim().ifBlank { null })).joinToString(", ")
    }

    /** The `wizard` object of POST /api/attach/start, the idea's words from the box ([idea]). */
    fun body(idea: String): JsonObject = buildJsonObject {
        for (a in asks) {
            val r = if (a.id == IDEA) AskReply(emptyList(), idea) else answers[a.id] ?: continue
            put(a.id, buildJsonObject {
                put("chosen", JsonArray(r.chosen.map { JsonPrimitive(it) }))
                put("other", r.other.trim())
            })
        }
    }

    companion object {
        const val IDEA = "idea"
        const val LIKE = "like"
        const val URL = "/api/asks?wizard=1"

        /** The cards to ask; a card whose options are all "Coming" (disabled) keeps its typed answer. */
        fun of(asks: List<Ask>) = WizardFlow(asks.filter { it.kind == "wizard" || it.id in setOf("profile", "look") })

        /** "Make it like this": the links or names typed, one per line, without blanks. */
        fun likes(text: String): List<String> = text.lines().map { it.trim() }.filter { it.isNotEmpty() }
    }
}
