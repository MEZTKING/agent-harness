package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * A question for the owner to answer by tapping: the same shape as Roundtable Hold's asks.py, on the
 * desktop, the phone and through the hub. The recommended option comes first; "Other…" opens a text box.
 */
@Serializable
data class AskOption(
    val id: String,
    val label: String,
    val description: String = "",
    /** Set when choosing it spends beyond the estimate or can't be undone: ask "Are you sure?" first. */
    val confirm: String? = null,
    val picture: String? = null,
)

@Serializable
data class AskAnswer(val chosen: List<String> = emptyList(), val other: String = "")

@Serializable
data class Ask(
    val id: String,
    val kind: String = "",
    val project: String = "",
    val path: String? = null,
    /** At most 12 characters, shown as a chip. */
    val header: String = "",
    val question: String = "",
    val detail: String = "",
    val options: List<AskOption> = emptyList(),
    val recommended: String? = null,
    val multi: Boolean = false,
    val allow_other: Boolean = true,
    val other_hint: String = "Type your own answer",
    val stamp: String = "",
    val answer: AskAnswer? = null,
    val required: Boolean = false,
)

@Serializable
private data class AskList(val asks: List<Ask> = emptyList())

/** What the owner tapped (and typed) on a card. */
data class AskReply(val chosen: List<String>, val other: String = "", val confirmed: Boolean = false) {
    /** The option that needs an "Are you sure?" first, unless already confirmed. */
    fun needsConfirm(ask: Ask): AskOption? =
        if (confirmed) null else ask.options.firstOrNull { it.id in chosen && it.confirm != null }

    val empty: Boolean get() = chosen.isEmpty() && other.isBlank()
}

object Asks {
    /** `{"asks": [...]}` from /api/asks or plans/<project>.asks.json; nothing usable gives an empty list. */
    fun parse(json: String?): List<Ask> =
        if (json.isNullOrBlank()) emptyList()
        else runCatching { ApiJson.decodeFromString(AskList.serializer(), json).asks }.getOrDefault(emptyList())

    /**
     * Cards from the plan's own markdown, for a hub that has no asks file yet (an older Roundtable Hold):
     * the choices, the questions (only a text box) and the ideas still open.
     */
    fun fromPlan(doc: PlanDoc, project: String): List<Ask> {
        if (!doc.waitingForOwner) return emptyList()
        val out = mutableListOf<Ask>()
        doc.decisions.filter { d -> d.id != null && d.options.none { it.chosen } }.forEach { d ->
            val opts = d.options.filter { it.id != null }.sortedBy { !it.recommended }
                .map { AskOption(it.id!!, it.label, listOf(it.detail, it.cost).filter(String::isNotBlank).joinToString(" · ")) }
            out += Ask("choose:${d.id}", "decision", project, header = "Choice", question = d.question,
                detail = if (d.why.isNotBlank()) "Recommended because: ${d.why}" else "", options = opts,
                recommended = d.options.firstOrNull { it.recommended }?.id)
        }
        doc.questions.filter { it.id != null && it.answer.isBlank() }.forEach { q ->
            out += Ask("answer:${q.id}", "question", project, header = "Question", question = q.text, other_hint = "Type your answer")
        }
        doc.ideas.filter { it.id != null && it.state == "open" }.forEach { i ->
            out += Ask("idea:${i.id}", "idea", project, header = "Idea", question = "Add this? ${i.text}", detail = i.why,
                options = listOf(AskOption("yes", "Yes, add it", "The planner adds it to the plan."),
                    AskOption("no", "No thanks", "It won't be suggested again.")), recommended = "yes",
                other_hint = "Yes, but… (say what to change)")
        }
        return out
    }

    /** The hub command's fields for the `answer` action (remote.py). */
    fun commandFields(ask: Ask, r: AskReply): Map<String, Any?> = mapOf(
        "id" to ask.id, "chosen" to r.chosen, "other" to r.other.trim().ifBlank { null },
        "confirmed" to if (r.confirmed) true else null, "stamp" to ask.stamp.ifBlank { null },
    )

    /** The body for POST /api/asks on the paired PC. */
    fun requestBody(ask: Ask, r: AskReply): String = buildJsonObject {
        put("path", ask.path.orEmpty())
        put("id", ask.id)
        put("chosen", JsonArray(r.chosen.map { JsonPrimitive(it) }))
        put("other", r.other.trim())
        put("confirmed", r.confirmed)
        if (ask.stamp.isNotBlank()) put("stamp", ask.stamp)
    }.toString()
}
