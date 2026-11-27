package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/**
 * The plan's stages (the PC's GET /api/stages?path, harness/stages.py): a working slice first, then the rest. Each
 * stage says what the owner can try at the end of it and where it stands (done, now, stuck, waiting).
 */
@Serializable
data class StageRow(val id: String = "", val title: String = "", val shows: String = "", val done: Int = 0,
                    val total: Int = 0, val state: String = "waiting", val tasks: List<String> = emptyList(),
                    val ready_at: String = "")

@Serializable
data class StagePart(val id: String = "", val name: String = "", val folder: String = ".", val kind: String = "")

@Serializable
data class StageWarning(val id: String = "", val by: String = "", val kind: String = "", val text: String = "",
                        val tasks: List<String> = emptyList())

@Serializable
data class StageStray(val task: String = "", val files: List<String> = emptyList())

@Serializable
data class StagesView(
    val stages: List<StageRow> = emptyList(),
    val parts: List<StagePart> = emptyList(),
    val words: String = "",
    val warnings: List<StageWarning> = emptyList(),
    val strayed: List<StageStray> = emptyList(),
    val files: Map<String, List<String>> = emptyMap(),
) {
    /** The stage being built now (or stuck), null when every stage is built or there are none. */
    val current: StageRow? get() = stages.firstOrNull { it.state != "done" }
}

object Stages {
    /** The PC's address for a project's stages (for Api.feature("GET", ...)). */
    fun url(path: String): String = "/api/stages?path=${URLEncoder.encode(path, "UTF-8")}"

    fun parse(json: String?): StagesView? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(StagesView.serializer(), it) }.getOrNull() }

    /** A stage's state in plain words. */
    fun stateWords(state: String): String = when (state) {
        "done" -> "Built"
        "now" -> "Being built"
        "stuck" -> "Something didn't pass"
        else -> "Waiting"
    }

    /** The line read out for a stage chip. */
    fun chipWords(index: Int, s: StageRow): String =
        "Stage ${index + 1}, ${s.title}: ${stateWords(s.state)}, ${s.done} of ${s.total} done" +
            (if (s.shows.isNotBlank()) ". At the end you can try ${s.shows}" else "")

    /** Folded under "More": the parts, the warnings and the files changed outside the plan. */
    fun moreLines(v: StagesView): List<String> = buildList {
        if (v.parts.isNotEmpty()) add("Parts: " + v.parts.joinToString("; ") { "${it.name.ifBlank { it.id }} (in ${it.folder}/)" })
        v.warnings.forEach { if (it.text.isNotBlank()) add(it.text) }
        v.strayed.forEach { add("${it.task} also changed ${it.files.joinToString(", ")}") }
    }

    /** Task ids grouped by stage, in the stages' order; ids no stage names come last under "". */
    fun group(v: StagesView, taskIds: List<String>): List<Pair<String, List<String>>> {
        val out = v.stages.map { s -> s.id to taskIds.filter { it in s.tasks } }.filter { it.second.isNotEmpty() }
        val named = v.stages.flatMap { it.tasks }.toSet()
        val rest = taskIds.filter { it !in named }
        return if (rest.isEmpty()) out else out + ("" to rest)
    }
}
