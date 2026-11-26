package com.meztking.roundtable.data

import com.meztking.roundtable.net.Message
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/** A letter as the owner reads it: a short title and one plain sentence; [details] is the raw text, shown only on request. */
data class PlainLetter(
    val title: String,
    val text: String,
    val details: String? = null,
    /** The owner's own command to Roundtable (subject "roundtable: …"). */
    val command: Boolean = false,
    /** Roundtable's automatic answer to such a command. */
    val reply: Boolean = false,
    /** That answer reports a refusal or a failure: the owner should see it. */
    val trouble: Boolean = false,
) {
    val receipt: Boolean get() = reply && !trouble
}

/** Roundtable's receipts for one project, as one line: "music-player: 12 of your changes done – latest: …". */
data class ReceiptGroup(val project: String, val messages: List<Message>, val latest: String, val at: String) {
    val count: Int get() = messages.size
    val line: String
        get() = "$project: " + (if (count == 1) "1 of your changes done" else "$count of your changes done") +
            if (latest.isNotBlank()) " – latest: $latest" else ""
}

/**
 * Letters in plain words. The phone's commands to Roundtable are letters with a subject "roundtable: <action>"
 * and a JSON body (remote.py); Roundtable answers each with "Re: roundtable: …". Neither is shown as JSON:
 * a command reads as what the owner did ("You chose …"), an answer as "Roundtable: Done. …".
 */
object Letters {
    private const val PREFIX = "roundtable:"
    // the same words as remote.py's TROUBLE: a reply with one of them needs the owner
    private val trouble = Regex("\\b(couldn'?t|could not|can'?t|cannot|refused|failed|blocked|unknown action|isn't|not allowed|error|are you sure)\\b",
        RegexOption.IGNORE_CASE)

    fun isCommand(subject: String): Boolean = subject.trim().startsWith(PREFIX, ignoreCase = true)

    fun isReply(subject: String): Boolean {
        val s = subject.trim()
        return s.startsWith("re:", ignoreCase = true) && isCommand(s.substring(3))
    }

    fun isTrouble(text: String): Boolean = trouble.containsMatchIn(text)

    /** Roundtable's automatic answer that only confirms what the owner did: it never needs the owner. */
    fun isReceipt(m: Message): Boolean = isReply(m.subject) && !isTrouble(m.body)

    fun plain(m: Message, plan: PlanDoc? = null): PlainLetter = when {
        isReply(m.subject) -> {
            val bad = isTrouble(m.body)
            PlainLetter(if (bad) "Roundtable couldn't do it" else "Roundtable replied", "Roundtable: " + replyText(m.body),
                m.body, reply = true, trouble = bad)
        }
        isCommand(m.subject) -> PlainLetter("Sent to Roundtable", commandText(m.body, plan, m.subject.trim().substring(PREFIX.length).trim()),
            m.body, command = true)
        else -> PlainLetter(m.subject.ifBlank { "(no subject)" }, Markdown.plain(m.body).replace("\n", " ").trim())
    }

    /** Roundtable's reply with the old technical bits put plainly. */
    fun replyText(body: String): String = body.trim()
        .replace(Regex("(\\d+) change\\(s\\) waiting: send 'revise' \\(Update plan\\) to apply them\\.?")) { m ->
            val n = m.groupValues[1].toInt()
            "$n change${if (n != 1) "s" else ""} wait${if (n == 1) "s" else ""} for you to press Update plan."
        }
        .replace("The new plan is in plans/ in the hub.", "The new plan is ready to look at.")
        .replace(Regex("They're in the plan in the hub; send 'look' with your pick\\.?"), "Pick the one you like in the plan.")
        .replace(Regex("Couldn't do '[\\w-]+':"), "Couldn't do that:")
        .let { StatusText.tidy(it) }

    /** The sentence for one command's JSON ("You chose …"); never the JSON itself. */
    fun commandText(body: String, plan: PlanDoc? = null, subjectAction: String = ""): String {
        val o = runCatching { com.meztking.roundtable.net.ApiJson.parseToJsonElement(body) as? JsonObject }.getOrNull()
            ?: return "A command for Roundtable" + if (subjectAction.isNotBlank()) " ($subjectAction)" else ""
        fun s(k: String) = (o[k] as? JsonPrimitive)?.contentOrNull?.trim().orEmpty()
        fun b(k: String) = (o[k] as? JsonPrimitive)?.booleanOrNull
        fun list(k: String) = when (val v = o[k]) {
            is JsonArray -> v.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            is JsonPrimitive -> v.contentOrNull?.split(",")?.map { it.trim() }?.filter { it.isNotEmpty() }.orEmpty()
            else -> emptyList()
        }
        val text = s("text")
        return when (val action = s("action")) {
            "choose" -> chose(s("decision"), s("option"), plan)
            "answer" -> if (s("id").isNotBlank()) tapped(s("id"), list("chosen"), s("other"), plan)
                else "You answered: ${text.ifBlank { list("chosen").joinToString(", ") }}"
            "idea" -> when {
                text.isNotBlank() -> "You suggested: $text"
                else -> {
                    val idea = plan?.ideas?.firstOrNull { it.id == s("id") }?.text?.let { Markdown.plain(it) } ?: "idea ${s("id")}"
                    if (b("accept") == false) "You said no to the idea: $idea" else "You said yes to the idea: $idea"
                }
            }
            "note" -> "You added a note: $text"
            "revise" -> "You asked for the plan to be updated"
            "approve" -> "You approved the plan"
            "run" -> "You asked Roundtable to start building"
            "scope_add" -> if (b("out") == true) "You left out of the plan: $text" else "You added to the plan: $text"
            "scope_remove" -> "You took out of the plan: $text"
            "dont_add" -> "You said not to: $text"
            "dont_remove" -> "You allowed something again"
            "section" -> "You rewrote part of the plan"
            "look" -> "You chose look ${s("id").ifBlank { s("look") }}".trim()
            "looks" -> "You asked for new looks to choose from"
            "reference_add" -> "You added something to make it like: $text"
            "reference_remove" -> "You took out one of the things to make it like"
            "retry" -> "You asked Roundtable to try ${s("task").ifBlank { "the task" }} again"
            "skip" -> "You asked Roundtable to skip ${s("task").ifBlank { "the task" }}"
            "accept" -> "You accepted ${s("task").ifBlank { "the task" }} as it is"
            "steer" -> "You told Roundtable: $text"
            "ask" -> "You asked: $text"
            "profile" -> "You picked the ${s("name")} setting"
            "autopilot" -> when {
                s("state") == "on" || b("on") == true -> "You turned autopilot on"
                s("state") == "off" || b("on") == false -> "You turned autopilot off"
                else -> "You asked whether autopilot is on"
            }
            "" -> "A command for Roundtable"
            else -> "A command for Roundtable ($action)"
        }.trim().removeSuffix(":").trim()
    }

    private fun chose(decision: String, option: String, plan: PlanDoc?): String {
        val d = plan?.decisions?.firstOrNull { it.id == decision }
        val o = d?.options?.firstOrNull { it.id == option }
        return when {
            d != null && o != null -> "You chose “${Markdown.plain(o.label)}” for “${Markdown.plain(d.question)}”"
            d != null -> "You chose option $option for “${Markdown.plain(d.question)}”"
            else -> "You chose option $option for decision $decision"
        }
    }

    /** A tapped card (asks.py ids: choose:C1, answer:Q1, idea:I1, approve, look, profile, money, task:T1). */
    private fun tapped(id: String, chosen: List<String>, other: String, plan: PlanDoc?): String {
        val first = chosen.firstOrNull().orEmpty()
        val item = id.substringAfter(':', "")
        return when {
            id.startsWith("choose:") -> if (first.isNotBlank()) chose(item, first, plan) else "You said: $other"
            id.startsWith("answer:") -> {
                val q = plan?.questions?.firstOrNull { it.id == item }
                val labels = chosen.map { c -> q?.options?.firstOrNull { it.id == c }?.label ?: c }
                "You answered: " + (labels + listOfNotNull(other.ifBlank { null })).joinToString("; ")
            }
            id.startsWith("idea:") -> {
                val idea = plan?.ideas?.firstOrNull { it.id == item }?.text?.let { Markdown.plain(it) } ?: "idea $item"
                if (first == "no") "You said no to the idea: $idea" else "You said yes to the idea: $idea"
            }
            id.startsWith("task:") -> when (first) {
                "retry" -> "You asked Roundtable to try $item again"
                "stronger" -> "You asked Roundtable to try $item again with the stronger model"
                "accept" -> "You accepted $item as it is"
                "skip" -> "You asked Roundtable to skip $item"
                else -> "You told Roundtable about $item: $other"
            }
            id == "approve" -> when (first) {
                "approve" -> "You approved the plan"
                "approve_cheap" -> "You approved the plan, to start when it's cheaper"
                "revise" -> "You asked for the plan to be updated"
                "not_now" -> "You said not now"
                else -> "You said about the plan: $other"
            }
            id == "money" -> when (first) {
                "more" -> "You said carry on and spend a little more"
                "stop" -> "You said stop here"
                "budget" -> "You switched to the Budget setting"
                else -> "You said: $other"
            }
            id == "look" -> "You chose look $first" + if (other.isNotBlank()) ": $other" else ""
            id == "profile" -> "You picked the $first setting"
            else -> "You answered a question" + if (other.isNotBlank()) ": $other" else ""
        }
    }

    /** Roundtable's receipts, one group per project, newest first; [identity] is the owner (receipts are sent to them). */
    fun receipts(letters: List<Message>, identity: String? = null): List<ReceiptGroup> =
        letters.filter { isReceipt(it) && (identity == null || it.recipient == identity) }
            .groupBy { it.sender }
            .map { (project, ms) ->
                val sorted = ms.sortedByDescending { it.created_at.ifBlank { it.id } }
                ReceiptGroup(project, sorted, latestOf(sorted.first().body), sorted.first().created_at)
            }
            .sortedByDescending { it.at }

    /** The gist of a receipt: its first real sentence, short ("Plan v3, 3 tasks added"). */
    fun latestOf(body: String): String {
        val sentences = replyText(body).split(Regex("(?<=[.!?])\\s+")).map { it.trim().removeSuffix(".") }.filter { it.isNotBlank() }
        val pick = sentences.firstOrNull { !it.equals("Done", ignoreCase = true) } ?: sentences.firstOrNull().orEmpty()
        return if (pick.length > 80) pick.take(79).trimEnd() + "…" else pick
    }
}

/** Next steps and to-dos as the owner reads them: no file paths and no command lines (they live in the details). */
object StatusText {
    // a Windows or absolute path, a path with .harness in it, or a `roundtable <command> …` line
    private val backticked = Regex("`[^`]*(?:roundtable\\s+[a-z]|/\\.harness/|[A-Za-z]:\\\\|(?:^|\\s)/[\\w.~-]+/)[^`]*`")
    private val command = Regex("(?<![\\w-])roundtable\\s+[a-z][a-z-]*\\b.*$", RegexOption.MULTILINE)
    private val absolute = Regex("(?<=^|[\\s(\"'])(?:[A-Za-z]:\\\\[^\\s\"')]*|/(?:[\\w.~-]+/)+[\\w.~-]*|\\S*/\\.harness/\\S*)")
    private val seeFile = Regex("\\s*\\((?:see\\s+)?[\\w.-]+(?:/[\\w.-]+)+\\.\\w+\\)")

    fun tidy(text: String): String {
        if (text.isBlank()) return text
        val out = text.replace(backticked, "…").replace(command, "…").replace(absolute, "…").replace(seeFile, "")
            .replace(Regex("…(\\s*…)+"), "…").replace(Regex("[ \\t]{2,}"), " ").trim()
        return out
    }
}

/**
 * What waits for the owner, organised: one heading per project (with its count), and inside it by kind,
 * in this order: decisions and questions to answer now, money and stopped runs, to-dos, ideas, letters.
 * Newest first inside each group.
 */
object NeedsOrder {
    enum class Group(val label: String, private val one: String, private val many: String) {
        ANSWER("Decisions and questions", "question", "questions"),
        MONEY("Money and stopped runs", "stopped run", "stopped runs"),
        TODO("To-dos", "to-do", "to-dos"),
        IDEA("Ideas", "idea", "ideas"),
        LETTER("Letters", "letter", "letters");

        fun count(n: Int): String = "$n ${if (n == 1) one else many}"
    }

    data class Section(val group: Group, val items: List<NeedView>)
    data class ProjectNeeds(val project: String, val sections: List<Section>) {
        val count: Int get() = sections.sumOf { it.items.size }
        val summary: String get() = sections.joinToString(", ") { it.group.count(it.items.size) }
    }

    fun groupOf(n: NeedView): Group {
        val ask = n.ask
        return when {
            ask != null -> when (ask.kind) {
                "money", "failed" -> Group.MONEY
                "idea" -> Group.IDEA
                else -> Group.ANSWER
            }
            n.kind == "todo" -> Group.TODO
            n.kind == "message" -> Group.LETTER
            "approve" in n.actions -> Group.ANSWER
            else -> Group.MONEY
        }
    }

    private fun newest(n: NeedView): Long = parseInstant(n.at)?.toEpochMilli() ?: 0L

    fun organise(needs: List<NeedView>): List<ProjectNeeds> =
        needs.groupBy { it.project }.map { (project, ns) ->
            ProjectNeeds(project, ns.groupBy { groupOf(it) }.toSortedMap()
                .map { (g, items) -> Section(g, items.sortedByDescending { newest(it) }) })
        }.sortedWith(compareBy<ProjectNeeds> { p -> p.sections.first().group.ordinal }
            .thenByDescending { p -> p.sections.flatMap { it.items }.maxOf { newest(it) } })

    /** "2 questions, 1 to-do" for one project (the seat's badge). */
    fun summary(needs: List<NeedView>, project: String): String =
        organise(needs.filter { it.project == project }).firstOrNull()?.summary.orEmpty()
}
