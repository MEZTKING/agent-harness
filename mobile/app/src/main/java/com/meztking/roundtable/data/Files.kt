package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.Base64

/*
 * Files in the app (the PC's or this phone's /api/files, ui/filesapi.py): a project's folder, one file opened,
 * and the commands its tasks ran. Pure data and pure functions, so the screen can be drawn in tests.
 */

@Serializable
data class FileItem(val name: String = "", val path: String = "", val folder: Boolean = false, val size: Long = 0, val kind: String = "other")

@Serializable
data class Crumb(val name: String = "", val dir: String = "")

/** One folder of the project, or ([here] false) where the files are instead, in [words]. */
@Serializable
data class FolderView(
    val here: Boolean = true,
    val words: String = "",
    val dir: String = "",
    val crumbs: List<Crumb> = emptyList(),
    val items: List<FileItem> = emptyList(),
    val more: Int = 0,
    val test_command: String = "",
)

/** One file opened: [kind] text, code, markdown, csv, json, image, pdf or other; [data] is base64 (pictures, PDFs, copies). */
@Serializable
data class OpenedFile(
    val here: Boolean = true,
    val file: String = "",
    val name: String = "",
    val size: Long = 0,
    val kind: String = "other",
    val lang: String = "",
    val text: String? = null,
    val rows: List<List<String>> = emptyList(),
    val data: String? = null,
    val mime: String = "",
    val too_big: Boolean = false,
    val words: String = "",
) {
    fun bytes(): ByteArray? = data?.let { runCatching { Base64.getDecoder().decode(it) }.getOrNull() }
}

/** One command a task ran (or the checks, or the owner's own Run the tests). */
@Serializable
data class CommandRun(
    val at: String = "",
    val task: String = "",
    val task_title: String = "",
    val who: String = "",
    val kind: String = "task",
    val command: String = "",
    val exit_code: Int? = null,
    val passed: Boolean? = null,
    val timed_out: Boolean = false,
    val refused: Boolean = false,
    val words: String = "",
    val output: String = "",
)

@Serializable
data class CommandLog(
    val here: Boolean = true,
    val words: String = "",
    val commands: List<CommandRun> = emptyList(),
    val test_command: String = "",
    val can_run: Boolean = false,
    val why_not: String = "",
)

/** Where the Files screen reads from: the PC (PC mode) or Roundtable on this phone. */
interface FilesSource {
    suspend fun list(dir: String): FolderView
    suspend fun open(file: String): OpenedFile
    suspend fun copy(file: String): OpenedFile
    suspend fun log(): CommandLog
    /** Starts the project's own test command; returns the background job's id. */
    suspend fun runTests(): String
    /** A job's state: (still running, the words to show when it ended, it worked). */
    suspend fun job(id: String): Triple<Boolean, String, Boolean>
    /** A richer look at a notebook, an archive, an office file or a video or song; null where the machine has none. */
    suspend fun preview(file: String): FilePreview? = null
}

object Files {
    fun folder(json: String): FolderView = ApiJson.decodeFromString(FolderView.serializer(), json)
    fun opened(json: String): OpenedFile = ApiJson.decodeFromString(OpenedFile.serializer(), json)
    fun log(json: String): CommandLog = ApiJson.decodeFromString(CommandLog.serializer(), json)

    /** The id of the background job a POST started ({id, status, ...}). */
    fun jobId(json: String): String = runCatching {
        ((ApiJson.parseToJsonElement(json) as JsonObject)["id"] as JsonPrimitive).content
    }.getOrDefault("")

    /** A background job's answer (/api/jobs/<id>): still running?, the words, worked? */
    fun job(json: String): Triple<Boolean, String, Boolean> {
        val o = runCatching { ApiJson.parseToJsonElement(json) as JsonObject }.getOrNull() ?: return Triple(false, "Finished.", false)
        val status = (o["status"] as? JsonPrimitive)?.content.orEmpty()
        val result = o["result"] as? JsonObject
        val words = (result?.get("words") as? JsonPrimitive)?.content ?: (o["error"] as? JsonPrimitive)?.content ?: "Finished."
        val ok = status == "done" && (result?.get("ok") as? JsonPrimitive)?.content == "true"
        return Triple(status == "running", words, ok)
    }

    /** "12 commands, 2 didn't work." — the one line the Commands part leads with. */
    fun summary(log: CommandLog): String {
        val n = log.commands.size
        if (n == 0) return "No commands yet: they show here as the tasks run them."
        val bad = log.commands.count { it.passed == false }
        return "$n command${if (n == 1) "" else "s"}" + if (bad > 0) ", $bad didn't work." else ", all worked."
    }

    /** The folded line of one command: a mark, the command, then what happened and when. */
    fun mark(c: CommandRun): String = when (c.passed) { true -> "✓"; false -> "✗"; null -> "·" }

    fun detail(c: CommandRun): String = listOfNotNull(
        c.words.ifBlank { null },
        when (c.kind) { "checks", "baseline" -> "Checks"; "setup" -> "Set-up"; "tests" -> "You"; else -> if (c.who == "reviewer") "Reviewer" else null },
        c.task.ifBlank { null }?.let { if (c.task_title.isNotBlank()) "$it ${c.task_title}" else it },
        c.at.ifBlank { null }?.let { ago(it) },
    ).joinToString(" · ")

    val KIND_WORDS = mapOf("image" to "Picture", "pdf" to "PDF", "markdown" to "Document", "csv" to "Table", "json" to "Data (JSON)",
        "code" to "Code", "text" to "Text", "other" to "File", "folder" to "Folder")

    fun size(n: Long): String {
        if (n < 1024) return "$n bytes"
        var v = n.toDouble()
        for (u in listOf("KB", "MB", "GB")) { v /= 1024; if (v < 1024 || u == "GB") return "%.1f %s".format(java.util.Locale.UK, v, u) }
        return "$n bytes"
    }

    fun mimeOf(f: OpenedFile): String = f.mime.ifBlank {
        when (f.kind) {
            "pdf" -> "application/pdf"
            "image" -> when (f.name.substringAfterLast('.', "").lowercase()) { "png" -> "image/png"; "gif" -> "image/gif"; "webp" -> "image/webp"; "svg" -> "image/svg+xml"; else -> "image/jpeg" }
            "markdown", "text", "code", "csv", "json" -> "text/plain"
            else -> "application/octet-stream"
        }
    }

    /** A file name safe to save in the app's share folder (no folders, no dots at the start). */
    fun safeName(name: String): String = name.substringAfterLast('/').substringAfterLast('\\')
        .replace(Regex("[^A-Za-z0-9._ -]"), "_").trimStart('.').ifBlank { "file" }.take(120)
}

/** One line of a JSON value as a tree: the top level open, everything deeper folded. */
data class JsonNode(val key: String?, val summary: String, val leaf: String?, val kind: String, val kids: List<JsonNode>)

object JsonTree {
    fun parse(text: String): JsonNode? = runCatching { node(null, ApiJson.parseToJsonElement(text), intArrayOf(4000)) }.getOrNull()

    private fun node(key: String?, e: JsonElement, budget: IntArray): JsonNode = when (e) {
        is JsonObject -> {
            budget[0]--
            JsonNode(key, "{ ${e.size} field${if (e.size == 1) "" else "s"} }", null, "object",
                if (budget[0] < 0) emptyList() else e.entries.map { (k, v) -> node(k, v, budget) })
        }
        is JsonArray -> {
            budget[0]--
            JsonNode(key, "[ ${e.size} item${if (e.size == 1) "" else "s"} ]", null, "array",
                if (budget[0] < 0) emptyList() else e.map { node(null, it, budget) })
        }
        is JsonNull -> JsonNode(key, "", "null", "null", emptyList())
        is JsonPrimitive -> JsonNode(key, "", e.toString(), if (e.isString) "string" else if (e.content == "true" || e.content == "false") "bool" else "number", emptyList())
    }
}

/** Light colouring of code: which parts are comments, strings, numbers and keywords. */
object CodeColours {
    enum class Part { COMMENT, STRING, NUMBER, KEYWORD }
    data class Span(val start: Int, val end: Int, val part: Part)

    private val keywords = ("and as async await break case catch class const continue def default del do elif else enum export extends " +
        "false final finally fn for from fun func function if import in interface is lambda let match new nil none not null " +
        "object or package pass private protected public raise return self static struct super switch this throw true try " +
        "type typeof val var void when while with yield True False None").split(" ").toSet()
    private val hash = setOf("python", "shell", "yaml", "toml", "ruby", "gdscript", "powershell", "ini")
    private val token = Regex("//[^\\n]*|/\\*[\\s\\S]*?\\*/|<!--[\\s\\S]*?-->|#[^\\n]*|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'|`(?:\\\\.|[^`\\\\])*`|\\b\\d+(?:\\.\\d+)?\\b|\\b[A-Za-z_]\\w*\\b")

    fun spans(text: String, lang: String): List<Span> {
        if (lang.isBlank() || text.length > 300_000) return emptyList()
        val out = mutableListOf<Span>()
        var at = 0
        while (at < text.length) {
            val m = token.find(text, at) ?: break
            val t = m.value
            val c = t[0]
            if ((c == '#' && lang !in hash) || (t.startsWith("//") && lang in hash)) { at = m.range.first + 1; continue }
            val part = when {
                c == '#' || t.startsWith("//") || t.startsWith("/*") || t.startsWith("<!--") -> Part.COMMENT
                c == '"' || c == '\'' || c == '`' -> Part.STRING
                c.isDigit() -> Part.NUMBER
                t in keywords -> Part.KEYWORD
                else -> null
            }
            if (part != null) out += Span(m.range.first, m.range.last + 1, part)
            at = m.range.last + 1
        }
        return out
    }
}
