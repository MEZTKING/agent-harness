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
    /** Built on the phone from the plan's markdown (the hub has no asks file): answered with the plan's own commands. */
    val local: Boolean = false,
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
     * Cards from the plan's own markdown, for a hub that has no asks file (a plan published by an older
     * Roundtable Hold): the choices not made yet, the questions not answered (with their ready answers, if
     * any) and the ideas still open. They are always tappable, whatever the plan's state: the answers are the
     * plan's own commands (see [planCommands]) and wait for Update plan.
     */
    fun fromPlan(doc: PlanDoc, project: String): List<Ask> {
        val out = mutableListOf<Ask>()
        doc.decisions.filter { d -> d.id != null && d.options.none { it.chosen } && d.options.count { it.id != null } >= 2 }.forEach { d ->
            val opts = d.options.filter { it.id != null }.sortedBy { !it.recommended }
                .map { AskOption(it.id!!, Markdown.plain(it.label), Markdown.plain(listOf(it.detail, it.cost).filter(String::isNotBlank).joinToString(" · "))) }
            out += Ask("choose:${d.id}", "decision", project, header = "Choice", question = Markdown.plain(d.question),
                detail = if (d.why.isNotBlank()) "Recommended because: ${Markdown.plain(d.why)}" else "", options = opts,
                recommended = d.options.firstOrNull { it.recommended }?.id, other_hint = "Something else? Say what you want", local = true)
        }
        doc.questions.filter { it.id != null && it.answer.isBlank() }.forEach { q ->
            val opts = q.options.filter { it.id != null }.sortedBy { !it.recommended }.map { AskOption(it.id!!, Markdown.plain(it.label)) }
            out += Ask("answer:${q.id}", "question", project, header = "Question", question = Markdown.plain(q.text), options = opts,
                recommended = q.options.firstOrNull { it.recommended }?.id, multi = q.multi && opts.size > 1,
                other_hint = if (opts.isEmpty()) "Type your answer" else "Type your own answer", local = true)
        }
        doc.ideas.filter { it.id != null && it.state == "open" }.forEach { i ->
            out += Ask("idea:${i.id}", "idea", project, header = "Idea", question = "Add this? ${Markdown.plain(i.text)}", detail = Markdown.plain(i.why),
                options = listOf(AskOption("yes", "Yes, add it", "The planner adds it to the plan."),
                    AskOption("no", "No thanks", "It won't be suggested again.")), recommended = "yes",
                other_hint = "Yes, but… (say what to change)", local = true)
        }
        return out
    }

    /**
     * The hub commands that answer a card built from the plan ([Ask.local]): exactly the plan actions
     * remote.py does (choose, answer by question, idea, note). Something typed beside a choice or an idea
     * goes in as a note for the planner.
     */
    fun planCommands(ask: Ask, r: AskReply): List<Pair<String, Map<String, Any?>>> {
        val item = ask.id.substringAfter(':')
        val other = r.other.trim()
        val out = mutableListOf<Pair<String, Map<String, Any?>>>()
        when (ask.kind) {
            "decision" -> {
                r.chosen.firstOrNull()?.let { out += "choose" to mapOf("decision" to item, "option" to it) }
                if (other.isNotBlank()) out += "note" to mapOf("text" to "For '${ask.question}' the owner says: $other")
            }
            "question" -> {
                val labels = r.chosen.mapNotNull { id -> ask.options.firstOrNull { it.id == id }?.label }
                val text = (labels + listOfNotNull(other.ifBlank { null })).joinToString("; ")
                out += "answer" to mapOf("question" to item, "text" to text, "chosen" to r.chosen.ifEmpty { null })
            }
            "idea" -> {
                out += "idea" to mapOf("id" to item, "accept" to (r.chosen != listOf("no")))
                if (other.isNotBlank()) out += "note" to mapOf("text" to "About the idea '${ask.question.removePrefix("Add this? ")}', the owner says: $other")
            }
        }
        return out
    }

    /** One line under every card: what tapping it does, in plain words. */
    fun hint(ask: Ask, planAgreed: Boolean = false): String {
        val later = if (planAgreed) " The plan is already agreed: pressing Update plan changes what's still to build."
            else ""
        return when (ask.kind) {
            "decision" -> "Tap the choice you want. It waits until you press Update plan.$later"
            "question" -> (if (ask.options.isEmpty()) "Type your answer and tap Send." else "Tap an answer, or Other… to type your own.") +
                " It waits until you press Update plan.$later"
            "idea" -> "Yes adds it to the plan, No thanks leaves it out. It waits until you press Update plan.$later"
            "look" -> "Tap the look you like: every screen then follows it."
            "profile" -> "Tap the setting to use: it changes which models do the work and what it costs."
            "approve" -> "Tap to start building, or Not now to keep the plan as it is."
            "money" -> "Tap to carry on (it spends more of your credit) or to stop here."
            "failed" -> "Tap what to do with this task: try again, accept it or skip it."
            else -> "Tap an answer, or Other… to type your own."
        }
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
