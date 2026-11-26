package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/**
 * A live session as published to the hub: `sessions/<project-key>/<run_id>.jsonl`, one JSON line per event (task
 * started, a model turn's summary, a tool call's one-liner, a file change, the review's verdict, cost). Everything
 * about the event format is read here only, so it is easy to line up with Roundtable's side.
 *
 * An event's kind is `kind`, `type` or `event`; its words `line`, `text` or `summary`.
 */
object SessionLog {
    /** The latest task's steps, and how far the run has got. */
    data class Result(val summary: SessionSummary, val index: Int = 0, val total: Int = 0, val running: Boolean = false)

    private const val KEEP = 80

    /** Reads the jsonl text, a JSON list of events, {events: [...]}, or the older one-task summary. */
    fun parseAny(text: String?, project: String = ""): Result? {
        val t = text?.trim().orEmpty()
        if (t.isEmpty()) return null
        if (t.startsWith("[")) return events(runCatching { ApiJson.parseToJsonElement(t) as JsonArray }.getOrNull()?.mapNotNull { it as? JsonObject }.orEmpty(), project)
        if (t.startsWith("{") && '\n' !in t.trimEnd()) {
            val o = runCatching { ApiJson.parseToJsonElement(t) as JsonObject }.getOrNull() ?: return null
            (o["events"] as? JsonArray)?.let { return events(it.mapNotNull { e -> e as? JsonObject }, project) }
            if ("task" in o && o["task"] is JsonObject) return Live.parseSession(t)?.let { Result(it, running = it.task?.status == "running") }
            return events(listOf(o), project)
        }
        return parse(t, project)
    }

    fun parse(jsonl: String, project: String = ""): Result? =
        events(jsonl.lineSequence().map { it.trim() }.filter { it.startsWith("{") }
            .mapNotNull { runCatching { ApiJson.parseToJsonElement(it) as JsonObject }.getOrNull() }.toList(), project)

    private fun s(o: JsonObject, vararg keys: String): String =
        keys.firstNotNullOfOrNull { (o[it] as? JsonPrimitive)?.contentOrNull?.takeIf { v -> v.isNotBlank() } }.orEmpty()

    private fun n(o: JsonObject, vararg keys: String): Double? = keys.firstNotNullOfOrNull { (o[it] as? JsonPrimitive)?.doubleOrNull }
    private fun i(o: JsonObject, vararg keys: String): Int? = keys.firstNotNullOfOrNull { (o[it] as? JsonPrimitive)?.intOrNull }

    fun events(list: List<JsonObject>, project: String = ""): Result? {
        if (list.isEmpty()) return null
        var task: SessionTask? = null
        var steps = mutableListOf<SessionStep>()
        var cost = 0.0
        var index = 0
        var total = 0
        var running = false
        var at = ""
        var proj = project
        fun close() { task = task?.copy(steps = steps.takeLast(KEEP), cost = cost) }
        for (e in list) {
            val kind = s(e, "kind", "type", "event").lowercase()
            val words = s(e, "line", "text", "summary")
            at = s(e, "at", "time").ifBlank { at }
            proj = proj.ifBlank { s(e, "project") }
            when (kind) {
                "task_started", "task_start", "task", "start" -> {
                    steps = mutableListOf(); cost = 0.0
                    task = SessionTask(s(e, "task", "id"), s(e, "title"), s(e, "role"), "running")
                    i(e, "index", "number")?.let { index = it }
                    i(e, "total", "of", "tasks")?.let { total = it }
                    running = true
                }
                "turn", "model_turn", "say" -> if (words.isNotBlank()) steps += SessionStep("say", words)
                "tool", "tool_call" -> if (words.isNotBlank()) steps += SessionStep("tool", if (words.startsWith("●")) words else "● $words",
                    error = (e["error"] as? JsonPrimitive)?.booleanOrNull == true || s(e, "status") == "failed")
                "change", "file", "files", "file_change" -> {
                    val w = words.ifBlank { s(e, "path") }
                    if (w.isNotBlank()) steps += SessionStep("tool", if (w.startsWith("●")) w else "● $w")
                }
                "review", "verdict" -> {
                    val v = s(e, "verdict", "outcome").lowercase()
                    val ok = (e["approved"] as? JsonPrimitive)?.booleanOrNull ?: (v in setOf("approved", "approve", "pass", "passed", "ok"))
                    steps += SessionStep("review", (if (ok) "✓ Approved" else "✗ Sent back") + if (words.isNotBlank()) ": $words" else "")
                }
                "cost", "spend" -> n(e, "usd", "cost_usd", "cost")?.let { cost += it }
                "error" -> steps += SessionStep("error", words.ifBlank { "Something went wrong" }, error = true)
                "task_done", "task_finished", "finished", "task_end", "done" -> {
                    val st = s(e, "status").ifBlank { "done" }
                    n(e, "cost_usd", "usd")?.let { cost = maxOf(cost, it) }
                    steps += SessionStep("finish", "Finished: ${task?.id ?: s(e, "task")} $st" + if (words.isNotBlank()) ", $words" else "")
                    task = (task ?: SessionTask(s(e, "task"))).copy(status = st, summary = words)
                    running = false
                }
                "run_done", "run_finished", "run_end" -> running = false
                else -> if (words.isNotBlank()) steps += SessionStep(kind.ifBlank { "note" }, words)
            }
            n(e, "cost_usd").takeIf { kind !in setOf("cost", "spend", "task_done", "task_finished", "finished", "task_end", "done") }?.let { cost += it }
        }
        close()
        val t = task ?: SessionTask(steps = steps.takeLast(KEEP), cost = cost)
        return Result(SessionSummary(proj, at, t), index, total, running)
    }

    /** "T3 of 7" from the run's own events, when they say. */
    fun progressLine(r: Result): String = if (r.total > 0 && r.index > 0) "T${r.index} of ${r.total}" else ""
}
