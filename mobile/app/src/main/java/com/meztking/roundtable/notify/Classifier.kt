package com.meztking.roundtable.notify

import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.NeedView
import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset

/**
 * What's news for the owner: the twin of Roundtable Hold's `notify.py`, the same rules and the same shared
 * cases (src/test/resources/notify_cases.json). No Android here, so it is tested on its own.
 *
 * Five kinds, each with its own channel: finished, needs you, failed, money and idle.
 */
object NewsKind {
    const val FINISHED = "finished"
    const val NEEDS_YOU = "needs_you"
    const val FAILED = "failed"
    const val MONEY = "money"
    const val IDLE = "idle"
    val ALL = listOf(FINISHED, NEEDS_YOU, FAILED, MONEY, IDLE)

    fun name(kind: String) = when (kind) {
        FINISHED -> "Finished"
        NEEDS_YOU -> "Needs you"
        FAILED -> "Something stopped"
        MONEY -> "Money"
        IDLE -> "Paused for a while"
        else -> kind
    }

    fun hint(kind: String) = when (kind) {
        FINISHED -> "A project has built everything in its plan."
        NEEDS_YOU -> "A question, a plan to approve, a command to allow, a to-do or letters."
        FAILED -> "A task didn't work and waits for you to say what to do."
        MONEY -> "A spending limit was reached, or an account ran out of credit."
        IDLE -> "A run stopped part-way and nothing has happened for a while."
        else -> ""
    }
}

@Serializable
data class ProjectSnap(
    val id: String,
    val name: String = id,
    /** running | waiting | idle | done */
    val status: String = "idle",
    val state: String = "",
    val done: Int = 0,
    val total: Int = 0,
    val last_activity: String = "",
    /** Stopped part-way (it can be resumed). */
    val paused: Boolean = false,
)

@Serializable
data class NeedSnap(
    val key: String,
    val project: String,
    val name: String = project,
    /** needs_you | failed | money */
    val kind: String = NewsKind.NEEDS_YOU,
    val text: String = "",
    val ask: Ask? = null,
)

@Serializable
data class Snapshot(val at: String = "", val projects: List<ProjectSnap> = emptyList(), val needs: List<NeedSnap> = emptyList())

@Serializable
data class NewsButton(val id: String, val label: String)

@Serializable
data class News(
    val key: String,
    val kind: String,
    val project: String,
    val name: String,
    val title: String,
    val text: String = "",
    val at: String = "",
    val group: String = "",
    val quiet: Boolean = false,
    val buttons: List<NewsButton> = emptyList(),
    val ask: Ask? = null,
)

object Classifier {
    const val IDLE_AFTER_S = 30 * 60L
    private val BUTTON_KINDS = setOf("approve", "command", "decision", "question", "idea")
    private const val SHORT_QUESTION = 160
    private const val SHORT_LABEL = 30

    fun needKind(askKind: String?, actions: List<String>): String = when {
        askKind == "money" || "budget" in actions -> NewsKind.MONEY
        askKind == "failed" || "retry" in actions -> NewsKind.FAILED
        else -> NewsKind.NEEDS_YOU
    }

    /** Answers safe to give from the notification: never one that spends, needs "Are you sure?", several picks or a picture. */
    fun buttons(ask: Ask?): List<NewsButton> {
        if (ask == null || ask.multi || ask.kind !in BUTTON_KINDS) return emptyList()
        if (ask.options.any { it.confirm != null || it.picture != null }) return emptyList()
        if (ask.kind == "approve") return if (ask.options.any { it.id == "approve" }) listOf(NewsButton("approve", "Approve plan")) else emptyList()
        if (ask.options.size != 2 || ask.question.length > SHORT_QUESTION || ask.options.any { it.label.length > SHORT_LABEL }) return emptyList()
        return ask.options.map { NewsButton(it.id, it.label) }
    }

    fun seconds(ts: String): Long? {
        val s = ts.trim()
        if (s.isEmpty()) return null
        return runCatching { Instant.parse(s).epochSecond }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(s).toEpochSecond() }.getOrNull()
            ?: runCatching { LocalDateTime.parse(s).toEpochSecond(ZoneOffset.UTC) }.getOrNull()
    }

    private fun idleFor(p: ProjectSnap, at: String): Long? {
        if (!p.paused) return null
        val then = seconds(p.last_activity) ?: return null
        val now = seconds(at) ?: return null
        return (now - then).takeIf { it >= IDLE_AFTER_S }
    }

    private fun forAWhile(secs: Long): String {
        val mins = secs / 60
        if (mins < 120) return "$mins minutes"
        val hours = mins / 60
        return if (hours < 48) "$hours hours" else "${hours / 24} days"
    }

    private fun words(n: NeedSnap): Pair<String, String> = when {
        n.kind == NewsKind.MONEY && "credit" in n.text && "ran out" in n.text -> "${n.name}: an account is out of credit" to n.text
        n.kind == NewsKind.MONEY -> "${n.name} reached its money limit" to n.text
        n.kind == NewsKind.FAILED -> "${n.name}: a task stopped" to n.text
        n.ask?.kind == "approve" -> "${n.name}: the plan is ready" to "Look at it, then approve it to start building."
        n.ask?.kind == "command" -> "${n.name} wants to run a command" to n.text
        else -> "${n.name} needs you" to n.text
    }

    /** The news between two snapshots. With no old one (the first look), only what waits now is news. */
    fun classify(old: Snapshot?, new: Snapshot, openProject: String? = null): List<News> {
        val at = new.at
        val out = mutableListOf<News>()
        val before = old?.projects.orEmpty().associateBy { it.id }
        val had = old?.needs.orEmpty().map { it.key }.toSet()
        for (p in new.projects) {
            val was = before[p.id]
            if (was != null && was.status != "done" && p.status == "done") {
                out += News("finished:${p.id}:${p.last_activity}", NewsKind.FINISHED, p.id, p.name, "${p.name} is finished",
                    if (p.total > 0) "All ${p.total} tasks done. Open it to try it." else "Everything is done. Open it to try it.")
            }
            val quiet = idleFor(p, at)
            if (quiet != null && was != null && idleFor(was, old?.at.orEmpty()) == null) {
                out += News("idle:${p.id}:${p.last_activity}", NewsKind.IDLE, p.id, p.name, "${p.name} has been paused a while",
                    "Nothing has happened for ${forAWhile(quiet)}. Open it to carry on.")
            }
        }
        val seen = mutableSetOf<String>()
        for (n in new.needs) {
            if (n.key in had || !seen.add(n.key)) continue
            val (title, text) = words(n)
            out += News("${n.kind}:${n.key}", n.kind, n.project, n.name, title, text, buttons = buttons(n.ask), ask = n.ask)
        }
        return out.map { it.copy(at = at, group = it.project, quiet = openProject != null && it.project == openProject) }
    }

    /** A project's id in words ("bakery-site" -> "Bakery Site"), as the desktop shows it. */
    fun readable(id: String): String =
        id.split('-', '_', '.', ' ').filter { it.isNotEmpty() }.joinToString(" ") { w -> w.replaceFirstChar { it.uppercase() } }.ifBlank { id }

    /**
     * The few facts the classifier needs, from what the phone already reads (any connection). [plans] gives
     * a hub project's state from its plan ("done", "running", "waiting"), which the hub's seats don't carry.
     */
    fun snapshot(hall: HallState, at: String = Instant.now().toString(), plans: Map<String, String> = emptyMap()): Snapshot {
        val projects = hall.seats.map { s ->
            ProjectSnap(
                id = s.id, name = readable(s.id), status = plans[s.id] ?: s.status, state = s.statusText,
                done = s.progress?.done ?: 0, total = s.progress?.total ?: 0, last_activity = s.lastActivity,
                paused = s.status == "idle" && s.statusText.contains("part-way", ignoreCase = true),
            )
        }
        return Snapshot(at, projects, hall.needs.map { need(it) })
    }

    /** A hub plan's published state as a seat's status (the hub's seats only say waiting or idle). */
    fun planStatus(state: String, finished: Boolean): String? = when {
        finished -> "done"
        state.contains("building", ignoreCase = true) -> "running"
        state.contains("waiting", ignoreCase = true) -> "waiting"
        else -> null
    }

    fun need(n: NeedView): NeedSnap {
        val text = n.ask?.question?.ifBlank { null } ?: if (n.kind == "run") n.text.ifBlank { n.title } else n.title
        return NeedSnap(n.key, n.project, readable(n.project), needKind(n.ask?.kind, n.actions), text, n.ask)
    }
}
