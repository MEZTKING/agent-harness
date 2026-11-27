package com.meztking.roundtable.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.random.Random
import com.meztking.roundtable.Brand

/** One project from hub.yaml's `agents:` block. */
@Serializable
data class HubProject(val id: String, val description: String = "", val repo: String = "")

/** Everything the table needs from the hub in one go (message bodies are fetched only when needed). */
data class HubSnapshot(
    val projects: List<HubProject>,
    /** project -> status page markdown ("" when the project has no status page yet) */
    val status: Map<String, String>,
    /** project -> message file names (ids) in its inbox, newest first */
    val inboxIds: Map<String, List<String>>,
    /** project -> ids marked read in state/<project>.json */
    val readIds: Map<String, Set<String>>,
    /** projects that have a plans/<project>.md */
    val plans: Set<String>,
) {
    fun unread(project: String): List<String> = inboxIds[project].orEmpty().filter { it !in readIds[project].orEmpty() }
}

/**
 * Hub only: reads and writes the hub repository on GitHub directly, for when the PC is off.
 * Each project's status page (status/<project>.md, kept up to date by every journal write),
 * its plan (plans/<project>.md), the inbox, and sending messages in the same file format the
 * hub itself uses.
 */
class GitHubHub(
    private val token: String,
    val repo: String,
    private val base: String = "https://api.github.com",
    private val client: OkHttpClient = defaultClient,
) {
    @Serializable
    private data class Entry(val name: String, val path: String, val type: String, val sha: String = "")

    @Serializable
    private data class TreeItem(val path: String, val type: String, val sha: String = "")

    @Serializable
    private data class Tree(val tree: List<TreeItem> = emptyList(), val truncated: Boolean = false)

    @Serializable
    private data class FileJson(val sha: String = "", val content: String = "")

    private fun request(path: String, accept: String) = Request.Builder().url("$base/repos/$repo/$path")
        .header("Authorization", "Bearer $token")
        .header("Accept", accept)
        .header("X-GitHub-Api-Version", "2022-11-28")

    private suspend fun execute(r: Request, what: String): String = withContext(Dispatchers.IO) {
        try {
            client.newCall(r).execute().use {
                val text = it.body?.string().orEmpty()
                if (it.code == 404) throw ApiException("not found: $what", 404)
                if (!it.isSuccessful) throw ApiException(errorText(it.code, text), it.code)
                text
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            throw ApiException(networkText(e), 0)
        }
    }

    private suspend fun get(path: String, raw: Boolean): String = execute(
        request("contents/$path", if (raw) "application/vnd.github.raw+json" else "application/vnd.github+json").build(), path)

    private suspend fun getOrNull(path: String, raw: Boolean = true): String? =
        runCatching { get(path, raw) }.getOrElse { if ((it as? ApiException)?.status == 404) null else throw it }

    private fun errorText(code: Int, body: String) = when {
        code == 401 -> "GitHub refused the token. It may have expired: make a new one and paste it in Settings."
        code == 403 && "rate limit" in body.lowercase() -> "GitHub says we've asked too often. Wait a few minutes and try again."
        code == 403 -> "GitHub refused access: the token needs Contents: Read and write on $repo."
        code == 409 -> "The hub repository $repo is empty."
        code == 422 -> "GitHub didn't accept the change (it may have changed at the same time). Try again."
        code >= 500 -> "GitHub is having trouble ($code). Try again in a minute."
        else -> "GitHub answered $code."
    }

    /** Project ids from hub.yaml (the `agents:` block). */
    suspend fun projects(): List<String> = projectInfo().map { it.id }

    /** Projects with their description and repository, from hub.yaml. */
    suspend fun projectInfo(): List<HubProject> {
        val yaml = getOrNull("hub.yaml")
            ?: throw ApiException("Couldn't find hub.yaml in $repo. Check the repository name, and that the token can see it.", 404)
        return projectsIn(yaml)
    }

    suspend fun status(project: String): String = getOrNull("status/$project.md").orEmpty()

    /** The project's current plan as markdown, or null when it has none. */
    suspend fun plan(project: String): String? = getOrNull("plans/$project.md")

    /** The project's questions to tap (plans/<project>.asks.json, written next to the plan); null when there's none. */
    suspend fun asks(project: String): String? = getOrNull("plans/$project.asks.json")

    /** Autopilot's switch and its newest log lines (plans/autopilot.json, written by the PC); null when there's none. */
    suspend fun autopilot(): String? = getOrNull("plans/autopilot.json")

    /** The newest pictures of the project's app (plans/shots/<project>/latest.json); null when there are none. */
    suspend fun shots(project: String): String? = getOrNull("plans/shots/$project/latest.json")

    /** The latest task's steps as short lines (plans/shots/<project>/session.json); null when there are none. */
    suspend fun session(project: String): String? = getOrNull("plans/shots/$project/session.json")

    /** A picture from plans/shots/<project>/ as bytes; null when it isn't there. */
    suspend fun shot(project: String, name: String): ByteArray? = withContext(Dispatchers.IO) {
        val path = "plans/shots/$project/$name"
        try {
            client.newCall(request("contents/$path", "application/vnd.github.raw+json").build()).execute().use {
                if (it.code == 404) return@withContext null
                if (!it.isSuccessful) throw ApiException(errorText(it.code, it.body?.string().orEmpty()), it.code)
                it.body?.bytes()
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            throw ApiException(networkText(e), 0)
        }
    }

    /** Every file path in the repository with its blob sha (one call). Null when GitHub cut the list short. */
    private suspend fun tree(): Map<String, String>? {
        val t = ApiJson.decodeFromString<Tree>(execute(
            request("git/trees/HEAD?recursive=1", "application/vnd.github+json").build(), "the file list"))
        if (t.truncated) return null
        return t.tree.filter { it.type == "blob" }.associate { it.path to it.sha }
    }

    private suspend fun listDir(path: String): List<Entry> =
        getOrNull(path, raw = false)?.let { ApiJson.decodeFromString<List<Entry>>(it) }.orEmpty()

    /** Files directly inside [dir] with their sha, from the tree when we have it. */
    private suspend fun filesIn(tree: Map<String, String>?, dir: String): Map<String, String> =
        if (tree != null) {
            tree.filterKeys { it.startsWith("$dir/") && '/' !in it.removePrefix("$dir/") }
                .mapKeys { it.key.removePrefix("$dir/") }
        } else listDir(dir).filter { it.type == "file" }.associate { it.name to it.sha }

    private suspend fun readState(project: String): Set<String> = getOrNull("state/$project.json")?.let { txt ->
        runCatching { ApiJson.decodeFromString<ReadState>(txt).read.toSet() }.getOrDefault(emptySet())
    }.orEmpty()

    /** Projects, status pages, inbox ids and read state: about 3 + 2 per project calls, run in parallel. */
    suspend fun snapshot(): HubSnapshot = coroutineScope {
        val treeJob = async { runCatching { tree() }.getOrNull() }
        val projects = projectInfo()
        val tree = treeJob.await()
        val ids = projects.map { it.id }
        val gate = Semaphore(6)
        val statusJob = ids.map { p -> async { gate.withPermit { p to status(p) } } }
        val inboxJob = ids.map { p ->
            async {
                gate.withPermit {
                    p to filesIn(tree, "inbox/$p").keys.filter { it.endsWith(".json") }
                        .map { it.removeSuffix(".json") }.sortedDescending()
                }
            }
        }
        val inbox = inboxJob.awaitAll().toMap()
        val readJob = ids.filter { inbox[it].orEmpty().isNotEmpty() }.map { p -> async { gate.withPermit { p to readState(p) } } }
        val plans = filesIn(tree, "plans").keys.filter { it.endsWith(".md") }.map { it.removeSuffix(".md") }.toSet()
        HubSnapshot(projects, statusJob.awaitAll().toMap(), inbox, readJob.awaitAll().toMap(), plans)
    }

    /** The messages with these ids from [project]'s inbox (bodies cached: a message never changes). */
    suspend fun messages(project: String, ids: List<String>, read: Set<String>): List<Message> = coroutineScope {
        val gate = Semaphore(6)
        ids.map { id ->
            async {
                gate.withPermit {
                    val key = "$repo/$project/$id"
                    val m = cache[key] ?: runCatching {
                        ApiJson.decodeFromString<Message>(get("inbox/$project/$id.json", raw = true))
                    }.getOrNull()?.also { cache[key] = it }
                    m?.copy(read = id in read)
                }
            }
        }.awaitAll().filterNotNull()
    }

    suspend fun inbox(project: String, limit: Int = 30): List<Message> = coroutineScope {
        val readJob = async { readState(project) }
        val files = runCatching { listDir("inbox/$project") }.getOrDefault(emptyList())
        val ids = files.filter { it.type == "file" && it.name.endsWith(".json") }
            .map { it.name.removeSuffix(".json") }.sortedDescending().take(limit)
        messages(project, ids, readJob.await())
    }

    /** Marks messages read in state/<project>.json, keeping whatever else the file holds. */
    @OptIn(ExperimentalSerializationApi::class)
    suspend fun markRead(project: String, ids: List<String>, attempt: Int = 0) {
        if (ids.isEmpty()) return
        val current = getOrNull("state/$project.json", raw = false)?.let { ApiJson.decodeFromString<FileJson>(it) }
        val obj = current?.let {
            runCatching {
                ApiJson.parseToJsonElement(String(Base64.getMimeDecoder().decode(it.content))).jsonObject
            }.getOrNull()
        } ?: JsonObject(mapOf("read" to JsonArray(emptyList()), "subscriptions" to JsonArray(emptyList())))
        val read = obj["read"]?.let { runCatching { it.jsonArray.map { e -> e.jsonPrimitive.content } }.getOrNull() }.orEmpty()
        val merged = (read + ids.filter { it !in read })
        if (merged.size == read.size) return
        val out = JsonObject((obj + ("read" to JsonArray(merged.map { JsonPrimitive(it) }))).toSortedMap())
        val text = PrettyJson.encodeToString(JsonElement.serializer(), out) + "\n"
        try {
            put("state/$project.json", text, "$project: read ${ids.size} message(s) (${Brand.SHORT} phone app)", current?.sha)
        } catch (e: ApiException) {
            // someone else wrote the file in between: read it again and retry once
            if ((e.status == 409 || e.status == 422) && attempt == 0) markRead(project, ids, 1) else throw e
        }
    }

    private suspend fun put(path: String, text: String, message: String, sha: String?) {
        val payload = buildJsonObject {
            put("message", message)
            put("content", Base64.getEncoder().encodeToString(text.toByteArray()))
            if (sha != null) put("sha", sha)
        }.toString()
        execute(request("contents/$path", "application/vnd.github+json")
            .put(payload.toRequestBody("application/json".toMediaType())).build(), path)
    }

    suspend fun send(
        from: String, to: String, subject: String, body: String,
        inReplyTo: Message? = null, kind: String = if (inReplyTo != null) "reply" else "ask",
    ): Message {
        val now = Instant.now()
        val id = newId(now)
        val subj = when {
            inReplyTo == null -> subject
            subject.isNotBlank() && subject.lowercase().startsWith("re:") -> subject
            inReplyTo.subject.lowercase().startsWith("re:") -> inReplyTo.subject
            else -> "Re: ${inReplyTo.subject}"
        }
        val msg = OutMessage(
            id = id, sender = from, recipient = to, kind = kind, subject = subj, body = body,
            created_at = DateTimeFormatter.ISO_INSTANT.format(now.truncatedTo(ChronoUnit.SECONDS)),
            in_reply_to = inReplyTo?.id, thread_id = inReplyTo?.let { it.thread_id.ifBlank { it.id } } ?: id,
        )
        put("inbox/$to/$id.json", PrettyJson.encodeToString(msg) + "\n", "msg $from -> $to: ${subj.take(60)} (${Brand.SHORT} phone app)", null)
        return Message(id, from, to, kind, subj, body, msg.created_at, msg.thread_id, msg.in_reply_to, read = false)
    }

    /**
     * A command through the hub: the Roundtable Hold that runs [project] does it and replies in the
     * owner's inbox. [fields] are the action's own fields, e.g. "decision" and "option" for "choose".
     */
    suspend fun command(from: String, project: String, action: String, fields: Map<String, Any?> = emptyMap()): Message {
        val body = buildJsonObject {
            put("action", action)
            for ((k, v) in fields) if (v != null) put(k, Api.jsonOf(v))
        }.toString()
        return send(from, project, "roundtable: $action", body, kind = "request")
    }

    /** Every .json file directly in [dir] (machines/, claims/), name -> text; at most [limit], newest names first. */
    suspend fun jsonFiles(dir: String, limit: Int = 40): Map<String, String> = coroutineScope {
        val names = listDir(dir).filter { it.type == "file" && it.name.endsWith(".json") }.map { it.name }.sortedDescending().take(limit)
        val gate = Semaphore(6)
        names.map { n -> async { gate.withPermit { getOrNull("$dir/$n")?.let { n to it } } } }.awaitAll().filterNotNull().toMap()
    }

    /** The live sessions published for a project (sessions/<key>/<run_id>.jsonl), newest run first. */
    suspend fun sessionRuns(key: String): List<String> =
        listDir("sessions/$key").filter { it.type == "file" && it.name.endsWith(".jsonl") }.map { it.name.removeSuffix(".jsonl") }.sortedDescending()

    /** One run's session, one JSON line per event; null when it isn't there. */
    suspend fun sessionLog(key: String, run: String): String? = getOrNull("sessions/$key/$run.jsonl")

    /** The owner's saved documents (the notes folder) as name -> markdown; the list needs each one's heading. */
    suspend fun notes(): Map<String, String> = coroutineScope {
        val names = listDir("notes").filter { it.type == "file" && it.name.endsWith(".md") && !it.name.startsWith(".") }.map { it.name }.take(60)
        val gate = Semaphore(6)
        names.map { n -> async { gate.withPermit { getOrNull("notes/$n")?.let { n to it } } } }.awaitAll().filterNotNull().toMap()
    }

    /** One saved document (notes/<name>), or null. */
    suspend fun note(name: String): String? = getOrNull("notes/$name")

    /** The settings every machine shares (settings/shared.yaml); null when there's none yet. */
    suspend fun sharedSettings(): String? = getOrNull("settings/shared.yaml")

    @Serializable
    private data class ReadState(val read: List<String> = emptyList())

    @Serializable
    private data class OutMessage(
        val body: String, val created_at: String, val id: String, val in_reply_to: String?, val kind: String,
        val recipient: String, val sender: String, val subject: String, val thread_id: String,
    )

    companion object {
        private val defaultClient: OkHttpClient by lazy {
            OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
        }
        private val cache = ConcurrentHashMap<String, Message>()

        @OptIn(ExperimentalSerializationApi::class)
        private val PrettyJson = Json { prettyPrint = true; prettyPrintIndent = "  "; explicitNulls = true }

        /** The hub's message id: UTC time to the microsecond plus 6 random hex digits, so ids sort by time. */
        fun newId(now: Instant = Instant.now()): String =
            DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSSSSS'Z'").withZone(ZoneOffset.UTC).format(now) +
                "-" + "%06x".format(Random.nextInt(0x1000000))

        fun networkText(e: IOException): String = when (e) {
            is java.net.UnknownHostException -> "Can't reach GitHub. Is the phone online?"
            is java.net.SocketTimeoutException -> "GitHub took too long to answer. Try again."
            is javax.net.ssl.SSLException -> "Couldn't make a secure connection to GitHub. Check the phone's date and network."
            else -> "Couldn't reach GitHub (${e.message ?: e.javaClass.simpleName})."
        }

        fun agentsIn(yaml: String): List<String> = projectsIn(yaml).map { it.id }

        /** The `agents:` block of hub.yaml: each project id with its description and repo. */
        fun projectsIn(yaml: String): List<HubProject> {
            val lines = yaml.lines()
            val start = lines.indexOfFirst { Regex("^agents:\\s*(#.*)?$").matches(it.trimEnd()) }
            if (start < 0) return emptyList()
            val out = mutableListOf<HubProject>()
            var indent: Int? = null
            var cur: MutableMap<String, String>? = null
            var curId = ""
            fun flush() {
                if (curId.isNotEmpty()) out += HubProject(curId, cur?.get("description").orEmpty(), cur?.get("repo").orEmpty())
                curId = ""; cur = null
            }
            for (ln in lines.drop(start + 1)) {
                if (ln.isBlank() || ln.trimStart().startsWith("#")) continue
                if (!ln[0].isWhitespace()) break
                val lead = ln.length - ln.trimStart().length
                if (indent == null) indent = lead
                val body = stripComment(ln.trim())
                if (lead == indent) {
                    flush()
                    curId = unquote(body.substringBefore(":").trim())
                    cur = mutableMapOf()
                    val rest = body.substringAfter(":", "").trim()
                    if (rest.startsWith("{") && rest.endsWith("}")) { // inline map: me: {description: x}
                        rest.removeSurrounding("{", "}").split(",").forEach { kv ->
                            if (':' in kv) cur!![kv.substringBefore(":").trim()] = unquote(kv.substringAfter(":").trim())
                        }
                    }
                } else if (lead > indent && cur != null && ':' in body) {
                    val k = body.substringBefore(":").trim()
                    if (k == "description" || k == "repo") cur!![k] = unquote(body.substringAfter(":").trim())
                }
            }
            flush()
            return out.filter { it.id.isNotEmpty() }
        }

        private fun stripComment(s: String): String {
            var q: Char? = null
            for ((i, c) in s.withIndex()) {
                if (q != null) { if (c == q) q = null; continue }
                if (c == '"' || c == '\'') q = c
                else if (c == '#' && (i == 0 || s[i - 1].isWhitespace())) return s.substring(0, i).trimEnd()
            }
            return s
        }

        private fun unquote(v: String): String {
            val t = v.trim()
            return when {
                t.length >= 2 && t.startsWith('"') && t.endsWith('"') -> t.substring(1, t.length - 1).replace("\\\"", "\"")
                t.length >= 2 && t.startsWith('\'') && t.endsWith('\'') -> t.substring(1, t.length - 1).replace("''", "'")
                else -> t
            }
        }
    }
}
