package com.meztking.roundtable.data

import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.net.URLEncoder

/*
 * Undo a task, go back to before it, put it back, try another way (the PC's /api/rewind, ui/rewindapi.py).
 * The files that change are always shown first; nothing is ever deleted. Pure data and pure functions, so
 * the sheet can be drawn in tests.
 */

@Serializable
data class RewindFile(val path: String = "", val change: String = "changed", val words: String = "", val from: String = "")

/** What an undo would do: [words] the one sentence to lead with, [blocked] why it can't ("" when it can). */
@Serializable
data class RewindPreview(
    val mode: String = UNDO_TASK,
    val task: String = "",
    val title: String = "",
    val words: String = "",
    val files: List<RewindFile> = emptyList(),
    val back_to_todo: List<String> = emptyList(),
    val hand_edits: List<RewindFile> = emptyList(),
    val hand_edits_kept: Boolean = true,
    val blocked: String = "",
    val offer: String = "",
    val stamp: String = "",
)

/** One finished task in the history: what it changed, and whether it went to GitHub already. */
@Serializable
data class RewindRow(
    val id: String = "",
    val title: String = "",
    val status: String = "",
    val words: String = "",
    val at: String = "",
    val files: List<RewindFile> = emptyList(),
    val pushed: Boolean = false,
    val undone: Boolean = false,
    val can_undo: Boolean = false,
    val can_go_back: Boolean = false,
)

@Serializable
data class LastRewind(val id: String = "", val at: String = "", val mode: String = "", val task: String = "", val title: String = "",
                      val words: String = "", val can_put_back: Boolean = false, val why_not: String = "")

@Serializable
data class RewindHistory(val rows: List<RewindRow> = emptyList(), val last: LastRewind? = null, val can_change: Boolean = false,
                         val why_not: String = "")

/** The answer to an undo, a put-back or a copy: [words] to show. */
@Serializable
data class RewindDone(val ok: Boolean = false, val words: String = "", val path: String = "", val name: String = "")

const val UNDO_TASK = "undo_task"
const val BACK_TO_BEFORE = "back_to_before"

/** Where the sheet reads from and writes to: the PC (PC mode), or a stand-in in tests. */
interface RewindSource {
    suspend fun history(): RewindHistory
    suspend fun preview(task: String, mode: String): RewindPreview
    suspend fun apply(task: String, mode: String, stamp: String): RewindDone
    suspend fun putBack(): RewindDone
    suspend fun fork(task: String, name: String): RewindDone
}

/** The PC's answers, through the phone server's guarded feature calls. */
class ApiRewind(private val api: Api, private val path: String) : RewindSource {
    private fun e(v: String) = URLEncoder.encode(v, "UTF-8")
    private fun body(vararg pairs: Pair<String, String>) = buildJsonObject { pairs.forEach { (k, v) -> put(k, JsonPrimitive(v)) } }.toString()

    override suspend fun history() = Rewind.history(api.feature("GET", "/api/rewind?path=${e(path)}"))
    override suspend fun preview(task: String, mode: String) =
        Rewind.preview(api.feature("GET", "/api/rewind/preview?path=${e(path)}&task=${e(task)}&mode=${e(mode)}"))
    override suspend fun apply(task: String, mode: String, stamp: String) =
        Rewind.done(api.feature("POST", "/api/rewind", body("path" to path, "task" to task, "mode" to mode, "stamp" to stamp)))
    override suspend fun putBack() = Rewind.done(api.feature("POST", "/api/rewind/undo", body("path" to path)))
    override suspend fun fork(task: String, name: String) =
        Rewind.done(api.feature("POST", "/api/rewind/fork", body("path" to path, "task" to task, "name" to name)))
}

object Rewind {
    fun preview(json: String): RewindPreview = ApiJson.decodeFromString(RewindPreview.serializer(), json)
    fun history(json: String): RewindHistory = ApiJson.decodeFromString(RewindHistory.serializer(), json)
    fun done(json: String): RewindDone = ApiJson.decodeFromString(RewindDone.serializer(), json)

    /** The two ways back: (mode, label, the plain line under it). */
    val MODES = listOf(
        Triple(UNDO_TASK, "Undo just this task", "Takes back only what this task changed. Later work stays."),
        Triple(BACK_TO_BEFORE, "Go back to before it", "The project as it was before this task started. Later tasks go back to to-do."),
    )

    /** A file's line: its path and what happens to it ("goes", "comes back"…). */
    fun fileLine(f: RewindFile): String = "${f.path} – ${f.words.ifBlank { f.change }}"

    /** The files to show before "More", and how many are folded. */
    fun firstFiles(files: List<RewindFile>, max: Int = 6): Pair<List<RewindFile>, Int> = files.take(max) to (files.size - max).coerceAtLeast(0)

    /** The line about the owner's own edits, or null when there are none. */
    fun handEdits(p: RewindPreview): String? {
        val n = p.hand_edits.size
        if (n == 0) return null
        val files = "$n file${if (n == 1) "" else "s"}"
        return if (p.hand_edits_kept) "Your own edits to $files stay as they are."
        else "Your own edits to $files are kept safe and come back with Put it back."
    }

    /** Whether the Undo it button can be pressed. */
    fun canApply(p: RewindPreview?): Boolean = p != null && p.blocked.isBlank() && p.stamp.isNotBlank()

    /** The project's folder name from its path on the PC (either kind of slash). */
    fun folderName(path: String): String = path.trimEnd('/', '\\').substringAfterLast('/').substringAfterLast('\\')

    /** A name for a copy made to try another way. */
    fun copyName(project: String): String = "${project.ifBlank { "project" }}-another-way"
}
