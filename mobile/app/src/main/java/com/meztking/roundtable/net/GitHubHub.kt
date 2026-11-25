package com.meztking.roundtable.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Base64
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/**
 * Hub only: reads and writes the hub repository on GitHub directly, for when the PC is off.
 * Each project's status page (status/<project>.md, kept up to date by every journal write),
 * the inbox, and sending messages in the same file format the hub itself uses.
 */
class GitHubHub(
    private val token: String,
    val repo: String,
    private val base: String = "https://api.github.com",
    private val client: OkHttpClient = OkHttpClient.Builder().readTimeout(20, TimeUnit.SECONDS).build(),
) {
    @Serializable
    private data class Entry(val name: String, val path: String, val type: String)

    private suspend fun get(path: String, raw: Boolean): String = withContext(Dispatchers.IO) {
        val r = Request.Builder().url("$base/repos/$repo/contents/$path")
            .header("Authorization", "Bearer $token")
            .header("Accept", if (raw) "application/vnd.github.raw+json" else "application/vnd.github+json")
            .header("X-GitHub-Api-Version", "2022-11-28").build()
        client.newCall(r).execute().use {
            val text = it.body?.string().orEmpty()
            if (it.code == 404) throw ApiException("not found: $path", 404)
            if (!it.isSuccessful) throw ApiException(errorText(it.code), it.code)
            text
        }
    }

    private fun errorText(code: Int) = when (code) {
        401 -> "GitHub refused the token: check it in Settings"
        403 -> "GitHub refused access: the token needs read and write access to $repo's contents"
        else -> "GitHub answered $code"
    }

    /** Project ids from hub.yaml (the `agents:` block). */
    suspend fun projects(): List<String> = agentsIn(get("hub.yaml", raw = true))

    suspend fun status(project: String): String =
        runCatching { get("status/$project.md", raw = true) }.getOrElse { if ((it as? ApiException)?.status == 404) "" else throw it }

    suspend fun inbox(project: String): List<Message> {
        val read = runCatching {
            ApiJson.decodeFromString<ReadState>(get("state/$project.json", raw = true)).read.toSet()
        }.getOrDefault(emptySet())
        val files = runCatching { ApiJson.decodeFromString<List<Entry>>(get("inbox/$project", raw = false)) }
            .getOrElse { if ((it as? ApiException)?.status == 404) emptyList() else throw it }
        return files.filter { it.type == "file" && it.name.endsWith(".json") }.sortedByDescending { it.name }.take(30).map {
            ApiJson.decodeFromString<Message>(get(it.path, raw = true)).copy(read = it.name.removeSuffix(".json") in read)
        }
    }

    suspend fun send(from: String, to: String, subject: String, body: String, inReplyTo: Message? = null): Message {
        val now = Instant.now()
        val id = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSSSSS'Z'").withZone(ZoneOffset.UTC).format(now) +
            "-" + "%06x".format(Random.nextInt(0x1000000))
        val msg = OutMessage(
            id = id, sender = from, recipient = to, kind = if (inReplyTo != null) "reply" else "ask",
            subject = if (inReplyTo != null && !subject.startsWith("Re:")) "Re: ${inReplyTo.subject}" else subject,
            body = body, created_at = DateTimeFormatter.ISO_INSTANT.format(now.truncatedTo(java.time.temporal.ChronoUnit.SECONDS)),
            in_reply_to = inReplyTo?.id, thread_id = inReplyTo?.thread_id?.ifBlank { inReplyTo.id } ?: id,
        )
        val content = Base64.getEncoder().encodeToString((ApiJson.encodeToString(msg) + "\n").toByteArray())
        val payload = buildJsonObject {
            put("message", "$from -> $to: ${msg.subject.take(60)} (Roundtable Mobile)")
            put("content", content)
        }.toString()
        withContext(Dispatchers.IO) {
            val r = Request.Builder().url("$base/repos/$repo/contents/inbox/$to/$id.json")
                .header("Authorization", "Bearer $token").header("Accept", "application/vnd.github+json")
                .put(payload.toRequestBody("application/json".toMediaType())).build()
            client.newCall(r).execute().use { if (!it.isSuccessful) throw ApiException(errorText(it.code), it.code) }
        }
        return Message(id, from, to, msg.kind, msg.subject, body, msg.created_at, msg.thread_id)
    }

    @Serializable
    private data class ReadState(val read: List<String> = emptyList())

    @Serializable
    private data class OutMessage(
        val body: String, val created_at: String, val id: String, val in_reply_to: String?, val kind: String,
        val recipient: String, val sender: String, val subject: String, val thread_id: String,
    )

    companion object {
        fun agentsIn(yaml: String): List<String> {
            val lines = yaml.lines()
            val start = lines.indexOfFirst { it.trimEnd() == "agents:" || it.startsWith("agents:") }
            if (start < 0) return emptyList()
            val out = mutableListOf<String>()
            var indent: Int? = null
            for (ln in lines.drop(start + 1)) {
                if (ln.isBlank() || ln.trimStart().startsWith("#")) continue
                if (!ln[0].isWhitespace()) break
                val lead = ln.length - ln.trimStart().length
                if (indent == null) indent = lead
                if (lead == indent) out += ln.trim().substringBefore(":").trim('"', '\'')
            }
            return out
        }
    }
}
