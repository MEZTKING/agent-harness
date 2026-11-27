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
 * An event's kind is `kind`, `type` or `event`; its words `line`, `text` or `summary`. Several tasks run at once: a
 * line carrying `task` goes to that task, one without it to the task started last. Lines may carry `ms` (and
 * `first_ms`, `waited_ms`, token counts): where each task's time went, as on the PC; untimed lines are left out.
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

    private fun l(o: JsonObject, key: String): Long? = (o[key] as? JsonPrimitive)?.let { it.contentOrNull?.toDoubleOrNull() }?.toLong()?.coerceAtLeast(0)

    /** One task's lines while reading: its steps, cost, and what the lines say about its time and tokens. */
    private class Building(var task: SessionTask) {
        var steps = mutableListOf<SessionStep>()
        var cost = 0.0
        var status = task.status
        var summary = ""
        val ms = linkedMapOf<String, Long>()
        var last: JsonObject? = null
        var prompt = 0L
        var cached = 0L

        fun add(key: String, v: Long) { if (v > 0) ms[key] = (ms[key] ?: 0) + v }

        fun build(keep: Int): SessionTask {
            val parts = PARTS.mapNotNull { (k, label) -> ms[k]?.takeIf { it > 0 }?.let { TimePart(k, label, it) } }
            val time = if (parts.isEmpty()) null else TaskTime(parts, parts.sumOf { it.ms })
            val ctx = last?.let { o ->
                val used = listOf("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens").sumOf { (o[it] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()?.toLong() ?: 0L }
                val window = (o["context_window"] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()?.toLong()
                TaskContext(used, window, window?.let { (used.toDouble() / it).coerceAtMost(1.0) },
                    (o["model"] as? JsonPrimitive)?.contentOrNull.orEmpty(), if (prompt > 0) cached.toDouble() / prompt else null)
            }
            val now = if (status == "running") steps.lastOrNull { it.kind != "note" }?.line?.removePrefix("● ")?.take(140) ?: "Starting" else summary.take(140)
            return task.copy(steps = steps.takeLast(keep), cost = cost, status = status, summary = summary, now = now, time = time, context = ctx)
        }
    }

    /** The parts of a task's time, as the PC names them (harness/session.py TIME_PARTS). */
    val PARTS = listOf("first" to "Waiting for the first word", "writing" to "The model writing", "model" to "The model thinking and writing",
        "tools" to "Tools", "you" to "Waiting for you", "other" to "Roundtable's own work")

    fun events(list: List<JsonObject>, project: String = ""): Result? {
        if (list.isEmpty()) return null
        val all = mutableListOf<Building>()
        val byId = mutableMapOf<String, Building>()
        var current: Building? = null
        var loose: Building? = null  // lines before any task started
        var index = 0
        var total = 0
        var running = false
        var at = ""
        var proj = project
        for (e in list) {
            val kind = s(e, "kind", "type", "event").lowercase()
            val words = s(e, "line", "text", "summary")
            at = s(e, "at", "time").ifBlank { at }
            proj = proj.ifBlank { s(e, "project") }
            if (kind in setOf("task_started", "task_start", "task", "start")) {
                val b = Building(SessionTask(s(e, "task", "id"), s(e, "title"), s(e, "role"), "running"))
                all += b; current = b
                if (b.task.id.isNotBlank()) byId[b.task.id] = b
                i(e, "index", "number")?.let { index = it }
                i(e, "total", "of", "tasks")?.let { total = it }
                running = true
                continue
            }
            val tid = s(e, "task")
            val b = (if (tid.isNotBlank()) byId[tid] else null) ?: current ?: loose ?: Building(SessionTask(steps = emptyList())).also { loose = it }
            val steps = b.steps
            when (kind) {
                "turn", "model_turn", "say" -> {
                    val ms = l(e, "ms"); val first = l(e, "first_ms")
                    if (ms == null) Unit  // not timed (an older line): left out, never counted as zero
                    else if (first != null) { b.add("first", minOf(first, ms)); b.add("writing", ms - minOf(first, ms)) }
                    else b.add("model", ms)
                    if (listOf("input_tokens", "output_tokens", "cache_read_tokens").any { it in e }) {
                        val tok = { k: String -> l(e, k) ?: 0L }
                        b.prompt += tok("input_tokens") + tok("cache_read_tokens") + tok("cache_write_tokens")
                        b.cached += tok("cache_read_tokens")
                        if (s(e, "role") != "reviewer" || b.last == null) b.last = e
                    }
                    if (words.isNotBlank()) steps += SessionStep("say", words)
                }
                "tool", "tool_call" -> {
                    timeTool(b, e)
                    if (words.isNotBlank()) steps += SessionStep("tool", if (words.startsWith("●")) words else "● $words",
                        error = (e["error"] as? JsonPrimitive)?.booleanOrNull == true || s(e, "status") == "failed")
                }
                "change", "file", "files", "file_change" -> {
                    timeTool(b, e)
                    val w = words.ifBlank { s(e, "path") }
                    if (w.isNotBlank()) steps += SessionStep("tool", if (w.startsWith("●")) w else "● $w")
                }
                "agent_done" -> b.add("other", l(e, "other_ms") ?: 0)
                "review", "verdict" -> {
                    val v = s(e, "verdict", "outcome").lowercase()
                    val ok = (e["approved"] as? JsonPrimitive)?.booleanOrNull ?: (v in setOf("approved", "approve", "pass", "passed", "ok"))
                    steps += SessionStep("review", (if (ok) "✓ Approved" else "✗ Sent back") + if (words.isNotBlank()) ": $words" else "")
                }
                "cost", "spend" -> n(e, "usd", "cost_usd", "cost")?.let { b.cost += it }
                "error" -> steps += SessionStep("error", words.ifBlank { "Something went wrong" }, error = true)
                "task_done", "task_finished", "finished", "task_end", "done" -> {
                    val st = s(e, "status").ifBlank { "done" }
                    n(e, "cost_usd", "usd")?.let { b.cost = maxOf(b.cost, it) }
                    steps += SessionStep("finish", "Finished: ${b.task.id.ifBlank { tid }} $st" + if (words.isNotBlank()) ", $words" else "")
                    b.status = st; b.summary = words
                    if (b.task.id.isBlank() && tid.isNotBlank()) b.task = b.task.copy(id = tid)
                    running = all.any { it.status == "running" }
                }
                "run_done", "run_finished", "run_end" -> running = false
                else -> if (words.isNotBlank()) steps += SessionStep(kind.ifBlank { "note" }, words)
            }
            n(e, "cost_usd").takeIf { kind !in setOf("cost", "spend", "task_done", "task_finished", "finished", "task_end", "done") }?.let { b.cost += it }
        }
        val latest = current ?: loose ?: return null
        val live = if (running) all.filter { it.status == "running" && byId[it.task.id].let { n -> n == null || n === it } } else emptyList()
        val keep = if (live.size > 1) maxOf(20, KEEP / live.size) else KEEP
        val task = latest.build(KEEP)
        val tasks = if (live.isEmpty()) listOf(task) else live.map { if (it === latest) task.copy(steps = task.steps.takeLast(keep)) else it.build(keep) }
        return Result(SessionSummary(proj, at, task, tasks), index, total, running)
    }

    private fun timeTool(b: Building, e: JsonObject) {
        val ms = l(e, "ms") ?: return
        val waited = minOf(l(e, "waited_ms") ?: 0, ms)
        b.add("tools", ms - waited); b.add("you", waited)
    }

    /** "T3 of 7" from the run's own events, when they say. */
    fun progressLine(r: Result): String = if (r.total > 0 && r.index > 0) "T${r.index} of ${r.total}" else ""
}
