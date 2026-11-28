package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.security.MessageDigest
import java.util.Base64

/**
 * The message box's own data, with no Android in it (the box itself is ui/Composer.kt): drafts kept on the
 * phone, the @word being typed, picture sizes, and sending a draft to Roundtable (your PC or This phone)
 * through ui/attachapi.py. Ideas learned from DSH Mobile's composer (attachments, dictation, queue or steer);
 * no code copied.
 */

/** When a note arrives at a project that is working: at the next task (default) or into the one working now. */
enum class Delivery(val id: String, val label: String, val tip: String) {
    QUEUE("queue", "Next task", "The planner and the next task read it. The task working now isn't stopped."),
    STEER("steer", "Now", "The task working now reads it at its next step, and every task after it."),
    ;

    companion object {
        fun of(id: String?): Delivery = entries.firstOrNull { it.id == id } ?: QUEUE
    }
}

@Serializable
data class DraftFile(val id: String, val name: String, val mime: String, val size: Long, val file: String) {
    val isPicture: Boolean get() = mime.startsWith("image/")
}

@Serializable
data class ComposerDraft(val key: String, val text: String = "", val mode: String = "queue", val files: List<DraftFile> = emptyList()) {
    val empty: Boolean get() = text.isBlank() && files.isEmpty()
}

class ComposerProblem(message: String) : Exception(message)

/** The caps (the PC checks them again): one file, all files, how many. */
data class Caps(val maxBytes: Long = 10L shl 20, val maxTotal: Long = 25L shl 20, val maxFiles: Int = 10, val maxPx: Int = 1568)

/**
 * Drafts on the phone: `<dir>/<hash of key>/draft.json` and its files. They survive closing the app and are
 * only sent (and then emptied) when the owner presses the button.
 */
class DraftStore(private val dir: File, private val caps: Caps = Caps()) {
    private fun folder(key: String): File = File(dir, sha(key).take(20))
    private fun meta(key: String) = File(folder(key), "draft.json")

    @Synchronized
    fun load(key: String): ComposerDraft =
        runCatching { ApiJson.decodeFromString<ComposerDraft>(meta(key).readText()) }.getOrNull()?.copy(key = key)
            ?.let { d -> d.copy(files = d.files.filter { File(folder(key), it.file).isFile }) } ?: ComposerDraft(key)

    @Synchronized
    fun save(draft: ComposerDraft): ComposerDraft {
        val f = meta(draft.key)
        f.parentFile?.mkdirs()
        val tmp = File(f.parentFile, ".draft.json.tmp")
        tmp.writeText(ApiJson.encodeToString(draft.copy(text = draft.text.take(20000))))
        if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
        return draft
    }

    fun setText(key: String, text: String, mode: Delivery? = null): ComposerDraft =
        load(key).let { save(it.copy(text = text, mode = mode?.id ?: it.mode)) }

    @Synchronized
    fun addFile(key: String, name: String, mime: String, bytes: ByteArray): ComposerDraft {
        val d = load(key)
        val clean = ComposerText.safeName(name)
        if (bytes.isEmpty()) throw ComposerProblem("$clean is empty.")
        if (bytes.size > caps.maxBytes) throw ComposerProblem("$clean is too big (${ComposerText.sizeWords(bytes.size.toLong())}). " +
            "The most is ${caps.maxBytes shr 20} MB: make it smaller or send part of it.")
        if (d.files.size >= caps.maxFiles) throw ComposerProblem("That's the most files for one message (${caps.maxFiles}). Remove one first.")
        val total = d.files.sumOf { it.size } + bytes.size
        if (total > caps.maxTotal) throw ComposerProblem("Together these are too big (${ComposerText.sizeWords(total)}). " +
            "The most for one message is ${caps.maxTotal shr 20} MB: remove one or send it on its own.")
        val id = sha(System.nanoTime().toString() + clean).take(8)
        val file = "$id-$clean"
        File(folder(key), "files").mkdirs()
        File(folder(key), "files/$file").writeBytes(bytes)
        return save(d.copy(files = d.files + DraftFile(id, clean, mime, bytes.size.toLong(), "files/$file")))
    }

    @Synchronized
    fun remove(key: String, id: String): ComposerDraft {
        val d = load(key)
        d.files.filter { it.id == id }.forEach { File(folder(key), it.file).delete() }
        return save(d.copy(files = d.files.filter { it.id != id }))
    }

    fun read(key: String, f: DraftFile): ByteArray = File(folder(key), f.file).readBytes()

    @Synchronized
    fun clear(key: String) { folder(key).deleteRecursively() }

    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
}

/** The @word being typed just before the caret: where it starts (the @) and the letters so far. */
data class AtWord(val start: Int, val word: String)

object ComposerText {
    private val AT = Regex("(^|[\\s(])@([\\w./\\\\-]*)$")

    fun atWord(text: String, caret: Int): AtWord? {
        val before = text.take(caret.coerceIn(0, text.length))
        val m = AT.find(before) ?: return null
        val word = m.groupValues[2]
        return AtWord(before.length - word.length - 1, word)
    }

    /** The text with the @word replaced by @path and a space, and where the caret goes. */
    fun pick(text: String, at: AtWord, caret: Int, path: String): Pair<String, Int> {
        val out = text.take(at.start) + "@" + path + " " + text.drop(caret.coerceIn(0, text.length))
        return out to at.start + path.length + 2
    }

    /** The size a picture is made (longest side at most [max]); smaller ones stay as they are. */
    fun scaled(w: Int, h: Int, max: Int = 1568): Pair<Int, Int> {
        if (w <= 0 || h <= 0 || maxOf(w, h) <= max) return w to h
        val s = max.toDouble() / maxOf(w, h)
        return maxOf(1, Math.round(w * s).toInt()) to maxOf(1, Math.round(h * s).toInt())
    }

    /** Android's sample size: the largest power of two that keeps the picture at least [max] long. */
    fun sampleSize(w: Int, h: Int, max: Int = 1568): Int {
        var n = 1
        while (maxOf(w, h) / (n * 2) >= max) n *= 2
        return n
    }

    /** A file's bytes in base64 parts small enough for one request each. */
    fun parts(bytes: ByteArray, size: Int = 1_000_000): List<String> {
        val all = Base64.getEncoder().encodeToString(bytes)
        return if (all.isEmpty()) listOf("") else all.chunked(size)
    }

    fun sizeWords(n: Long): String = when {
        n >= 1L shl 20 -> "%.1f MB".format(n / 1048576.0)
        n >= 1024 -> "${maxOf(1, Math.round(n / 1024.0))} KB"
        else -> "$n bytes"
    }

    fun safeName(name: String): String {
        val base = name.split('/', '\\').last().trim().trim('.')
        return base.replace(Regex("[^\\w.\\- ()]+"), "_").take(80).trim().ifEmpty { "file" }
    }
}

/**
 * Sends a draft to Roundtable (the PC or This phone) through `/api/attach/…`: its files in parts, its text and
 * Next task or Now, then the message itself. [call] is the app's API call (method, path, body).
 */
class ComposerSender(private val call: suspend (String, String, String?) -> String) {
    /** The PC's own draft key for one of the phone's boxes (the PC's desktop drafts stay apart). */
    fun serverKey(key: String) = "phone:$key"

    private suspend fun post(path: String, body: JsonObject) = call("POST", path, body.toString())

    suspend fun upload(draft: ComposerDraft, read: (DraftFile) -> ByteArray) {
        val k = serverKey(draft.key)
        post("/api/attach/clear", buildJsonObject { put("key", k) })
        for (f in draft.files) {
            val parts = ComposerText.parts(read(f))
            var id = ""
            parts.forEachIndexed { i, p ->
                val r = post("/api/attach/upload", buildJsonObject {
                    put("key", k); put("name", f.name); put("data", p); put("upload_id", id); put("last", i == parts.lastIndex)
                })
                id = (ApiJson.parseToJsonElement(r).jsonObject["upload_id"] as? JsonPrimitive)?.content ?: id
            }
        }
        post("/api/attach/draft", buildJsonObject { put("key", k); put("text", draft.text); put("mode", draft.mode) })
    }

    /** A new project from an idea (the wizard's idea answer); the planner sees the pictures. Returns the reply. */
    suspend fun startIdea(draft: ComposerDraft, read: (DraftFile) -> ByteArray): String {
        if (draft.text.isBlank()) throw ComposerProblem("Write your idea in a few words first.")
        upload(draft, read)
        val r = post("/api/attach/start", buildJsonObject {
            put("key", serverKey(draft.key))
            put("wizard", buildJsonObject { put("idea", buildJsonObject { put("other", draft.text.trim()) }) })
        })
        return reply(r)
    }

    /** A new project from every card of the wizard ([flow]), the idea's words, photos and files from the box. */
    suspend fun startWizard(draft: ComposerDraft, flow: WizardFlow, read: (DraftFile) -> ByteArray): String {
        if (draft.text.isBlank()) throw ComposerProblem("Write your idea in a few words first.")
        upload(draft, read)
        return reply(post("/api/attach/start", buildJsonObject {
            put("key", serverKey(draft.key))
            put("wizard", flow.body(draft.text))
        }))
    }

    /** A note ("note", with Next task or Now), a question ("chat") or a new goal ("goal") for a project. */
    suspend fun send(draft: ComposerDraft, project: String, kind: String, read: (DraftFile) -> ByteArray): String {
        if (draft.text.isBlank()) throw ComposerProblem("Write something first.")
        upload(draft, read)
        return reply(post("/api/attach/send", buildJsonObject {
            put("key", serverKey(draft.key)); put("path", project); put("as", kind); put("mode", draft.mode)
        }))
    }

    /** The project's files whose path holds [query], for @. */
    suspend fun files(project: String, query: String): List<String> {
        val r = call("GET", "/api/attach/files?project=${enc(project)}&q=${enc(query)}", null)
        return ((ApiJson.parseToJsonElement(r).jsonObject["files"] as? JsonArray) ?: JsonArray(emptyList()))
            .mapNotNull { (it as? JsonPrimitive)?.content }
    }

    private fun reply(r: String) = (runCatching { ApiJson.parseToJsonElement(r).jsonObject["reply"] as? JsonPrimitive }.getOrNull())?.content ?: "Sent."
    private fun enc(s: String) = java.net.URLEncoder.encode(s, "UTF-8")
}
