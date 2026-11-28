package com.meztking.roundtable.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import com.meztking.roundtable.Brand

class ApiException(message: String, val status: Int = 0) : IOException(message)

/** A paired PC: where to reach it, which certificate to trust, and this phone's token. */
data class PcLink(val name: String, val hosts: List<String>, val port: Int, val fingerprint: String, val token: String)

/**
 * Talks to the Roundtable Hold phone server. Tries the PC's addresses in turn (Wi-Fi first,
 * then Tailscale) and remembers the one that answered.
 *
 * With [local] it talks to Roundtable on this phone instead ("This phone", [thisPhone]): plain HTTP to
 * 127.0.0.1 with the launch token, the same API calls.
 */
class Api(var link: PcLink, private val client: OkHttpClient = pinnedClient(link.fingerprint), private val local: LocalAccess? = null) {
    @Volatile var activeHost: String = link.hosts.first()

    private fun url(host: String, path: String): String {
        val h = if (':' in host) "[$host]" else host // IPv6
        return "https://$h:${link.port}$path"
    }

    private suspend fun call(method: String, path: String, body: String? = null, client: OkHttpClient = this.client): String =
        withContext(Dispatchers.IO) {
            if (local != null) return@withContext localCall(local, method, path, body, client)
            val order = listOf(activeHost) + link.hosts.filter { it != activeHost }
            var last: IOException? = null
            for (host in order) {
                val b = Request.Builder().url(url(host, path)).header("Authorization", "Bearer ${link.token}")
                if (method == "POST") b.post((body ?: "{}").toRequestBody(JSON)) else b.get()
                try {
                    client.newCall(b.build()).execute().use { r ->
                        val text = r.body?.string().orEmpty()
                        activeHost = host
                        if (!r.isSuccessful) {
                            val msg = runCatching { ApiJson.parseToJsonElement(text) as JsonObject }.getOrNull()
                                ?.get("error")?.let { (it as? JsonPrimitive)?.content } ?: "HTTP ${r.code}"
                            throw ApiException(msg, r.code)
                        }
                        return@withContext text
                    }
                } catch (e: ApiException) {
                    throw e // the PC answered: no point trying other addresses
                } catch (e: IOException) {
                    last = e
                }
            }
            throw ApiException(friendly(last), 0)
        }

    private suspend fun localCall(local: LocalAccess, method: String, path: String, body: String?, client: OkHttpClient): String {
        try {
            val token = local.token()
            val b = Request.Builder().url("http://127.0.0.1:${local.port()}$path").header("Authorization", "Bearer $token")
            if (method == "POST") b.post((body ?: "{}").toRequestBody(JSON)) else b.get()
            client.newCall(b.build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                if (!r.isSuccessful) {
                    val msg = runCatching { ApiJson.parseToJsonElement(text) as JsonObject }.getOrNull()
                        ?.get("error")?.let { (it as? JsonPrimitive)?.content } ?: "HTTP ${r.code}"
                    throw ApiException(msg, r.code)
                }
                return text
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            throw ApiException(if (e.message?.startsWith("refused") == true || e.message?.startsWith("Roundtable") == true || e.message?.startsWith("Darkness") == true) e.message!!
                else "${Brand.NAME} on this phone isn't answering. Open Settings, Harness on this phone, and press Restart.", 0)
        }
    }

    private fun q(v: String) = URLEncoder.encode(v, "UTF-8")

    /** This phone: give Roundtable an API key (it keeps it; this app doesn't). */
    suspend fun saveKey(provider: String, key: String) {
        call("POST", "/api/keys", obj { put("provider", provider); put("key", key) })
    }

    suspend fun ping(): Ping = ApiJson.decodeFromString(call("GET", "/api/ping"))
    suspend fun roundtable(): RoundtableData = ApiJson.decodeFromString(call("GET", "/api/roundtable"))
    suspend fun activity(limit: Int = 120): List<FeedItem> = ApiJson.decodeFromString(call("GET", "/api/activity?limit=$limit"))
    suspend fun project(path: String): ProjectDetail = ApiJson.decodeFromString(call("GET", "/api/project?path=${q(path)}"))
    suspend fun chat(path: String): List<ChatMessage> = ApiJson.decodeFromString(call("GET", "/api/chat?path=${q(path)}"))
    suspend fun inbox(agent: String, all: Boolean = false): List<Message> =
        ApiJson.decodeFromString(call("GET", "/api/inbox/${q(agent)}" + if (all) "?all=1" else ""))
    suspend fun journal(agent: String): List<JournalEntry> = ApiJson.decodeFromString(call("GET", "/api/journal/${q(agent)}"))
    suspend fun jobs(): List<JobView> = ApiJson.decodeFromString(call("GET", "/api/jobs"))

    /** Long-poll: returns when anything on the Roundtable changed (or after [waitS] seconds). */
    suspend fun changes(since: String, waitS: Int = 25): Changes =
        ApiJson.decodeFromString(call("GET", "/api/changes?since=${q(since)}&wait=$waitS", client = longPoll))

    /** A question to the planner: it waits for the model's answer, so it gets the slow client's time. */
    suspend fun ask(path: String, message: String, steer: Boolean): ChatReply = ApiJson.decodeFromString(
        call("POST", "/api/chat", obj { put("path", path); put("message", message); put("steer", steer) }, client = slow))

    suspend fun projectAction(path: String, action: String, task: String? = null, maxCost: Double? = null) {
        call("POST", "/api/project", obj {
            put("path", path); put("action", action)
            if (task != null) put("task", task)
            if (maxCost != null) put("max_cost_usd", maxCost)
        })
    }

    /** The questions waiting on one project, as cards (asks.py). */
    suspend fun asks(path: String): List<com.meztking.roundtable.data.Ask> =
        com.meztking.roundtable.data.Asks.parse(call("GET", "/api/asks?path=${q(path)}"))

    /** Answer a card; returns Roundtable's reply in plain words. */
    suspend fun answer(ask: com.meztking.roundtable.data.Ask, r: com.meztking.roundtable.data.AskReply): String {
        val text = call("POST", "/api/asks", com.meztking.roundtable.data.Asks.requestBody(ask, r))
        return runCatching { (ApiJson.parseToJsonElement(text) as JsonObject)["reply"]?.let { (it as JsonPrimitive).content } }
            .getOrNull() ?: "Done"
    }

    /** Autopilot's switch and what it did lately. */
    /** The newest pictures of a run's app, as data addresses (Show it). */
    @kotlinx.serialization.Serializable
    private data class NoteList(val notes: List<com.meztking.roundtable.data.Note> = emptyList())

    @kotlinx.serialization.Serializable
    private data class NoteText(val markdown: String = "")

    suspend fun notes(): List<com.meztking.roundtable.data.Note> = ApiJson.decodeFromString(NoteList.serializer(), call("GET", "/api/notes")).notes

    suspend fun note(name: String): String = ApiJson.decodeFromString(NoteText.serializer(), call("GET", "/api/note?name=${q(name)}")).markdown

    /** The plan in the owner's words (title, where it stands, the estimate), from /api/plan. */
    suspend fun planWords(path: String): com.meztking.roundtable.data.PlanWords? {
        val o = ApiJson.parseToJsonElement(call("GET", "/api/plan?path=${q(path)}")) as? kotlinx.serialization.json.JsonObject ?: return null
        fun str(e: kotlinx.serialization.json.JsonElement?) = (e as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty()
        val w = o["words"] as? kotlinx.serialization.json.JsonObject ?: return null
        val doc = o["doc"] as? kotlinx.serialization.json.JsonObject
        return com.meztking.roundtable.data.PlanWords(str(w["title"]), str(doc?.get("summary")), str(w["state"]), emptyList(), str(w["estimate"]))
            .takeIf { it.title.isNotBlank() }
    }

    /** The plan's kind card (kinds), or null when the plan has none. */
    suspend fun planKind(path: String): com.meztking.roundtable.data.PlanKind? {
        val o = ApiJson.parseToJsonElement(call("GET", "/api/plan?path=${q(path)}")) as? kotlinx.serialization.json.JsonObject ?: return null
        val doc = o["doc"] as? kotlinx.serialization.json.JsonObject ?: return null
        return com.meztking.roundtable.data.Kinds.planKind(doc.toString())
    }

    suspend fun live(path: String): String = call("GET", "/api/project/live?inline=1&path=${q(path)}")
    /** The latest task's steps as short lines. */
    suspend fun session(path: String): String = call("GET", "/api/project/session?compact=1&path=${q(path)}")

    // -- Files in the app (ui/filesapi.py): the folder, one file, a copy, the command log, Run the tests ---------------
    suspend fun files(path: String, dir: String): String = call("GET", "/api/files?path=${q(path)}&dir=${q(dir)}")
    suspend fun fileOpen(path: String, file: String, copy: Boolean = false): String =
        call("GET", "/api/files/open?path=${q(path)}&file=${q(file)}&" + if (copy) "copy=1" else "inline=1")
    suspend fun commandLog(path: String): String = call("GET", "/api/files/log?path=${q(path)}")
    suspend fun runTests(path: String): String = call("POST", "/api/files/run_tests", obj { put("path", path) })
    suspend fun job(id: String): String = call("GET", "/api/jobs/${q(id)}")

    // -- keeping the phone and the PC in step (slice 2) ---------------------------------------------------------

    /** This phone: which hub Roundtable here uses. */
    suspend fun hub(): HubLink = ApiJson.decodeFromString(call("GET", "/api/hub"))

    /** This phone: join the hub repository (its git address and a token that can write it). */
    suspend fun joinHub(url: String, token: String): HubLink =
        ApiJson.decodeFromString(call("POST", "/api/hub", obj { put("url", url); put("token", token) }))

    /** The machines in the hub and who builds what (raw: Sync.parseMachines reads it). */
    suspend fun machines(): String = call("GET", "/api/machines")

    // search and memory (ui/searchapi.py): raw JSON, read by data/Search.kt
    suspend fun search(query: String, kinds: String = ""): String = call("GET", "/api/search?q=${q(query)}&kinds=${q(kinds)}")
    suspend fun peek(path: String, file: String, line: Int): String = call("GET", "/api/search/peek?path=${q(path)}&file=${q(file)}&line=$line")
    suspend fun memory(path: String, machine: Boolean, archive: Boolean): String =
        call("GET", "/api/memory?" + (if (machine) "machine=1" else "path=${q(path)}") + (if (archive) "&archive=1" else ""))

    /** A live session published to the hub, read by this machine (raw: SessionLog reads it). */
    suspend fun hubSession(name: String, run: String = ""): String =
        call("GET", "/api/hub/session?name=${q(name)}" + if (run.isNotBlank()) "&run=${q(run)}" else "")

    /** A command for a project another machine runs, sent on through the hub by this machine. */
    suspend fun hubCommand(agent: String, folder: String, action: String, fields: Map<String, Any?>, machine: String = ""): String {
        val text = call("POST", "/api/hub/command", obj {
            put("agent", agent); if (folder.isNotBlank()) put("folder", folder); put("action", action)
            if (machine.isNotBlank()) put("machine", machine)
            put("fields", jsonOf(fields))
        })
        return runCatching { ((ApiJson.parseToJsonElement(text) as JsonObject)["reply"] as JsonPrimitive).content }.getOrNull() ?: "Sent."
    }

    /** The settings every machine shares (settings/shared.yaml in the hub), raw: SharedSettings reads it. */
    suspend fun sharedSettings(): String = call("GET", "/api/settings/shared")
    suspend fun saveSharedSettings(changes: JsonObject): String =
        call("POST", "/api/settings/shared", buildJsonObject { put("changes", changes) }.toString())

    /** Who does which job: each role with its models (raw). */
    suspend fun roles(): String = call("GET", "/api/roles")

    /** One project's own settings, each with what it does, its type and choices (raw: ProjectSettings reads it). */
    suspend fun projectSettings(path: String): String = call("GET", "/api/project/settings?project=${q(path)}")
    suspend fun saveProjectSettings(path: String, changes: JsonObject): String =
        call("POST", "/api/project/settings", buildJsonObject { put("project", path); put("changes", changes) }.toString())

    suspend fun autopilot(): com.meztking.roundtable.data.AutopilotState =
        ApiJson.decodeFromString(call("GET", "/api/autopilot?limit=30"))

    suspend fun setAutopilot(on: Boolean, until: String = "", cap: Double? = null): com.meztking.roundtable.data.AutopilotState =
        ApiJson.decodeFromString(call("POST", "/api/autopilot", obj {
            put("action", if (on) "on" else "off"); put("until", until); if (cap != null) put("cap", cap)
        }))

    suspend fun newProject(dir: String, goal: String, approveFirst: Boolean = true) {
        call("POST", "/api/projects", obj { put("dir", dir); put("goal", goal); put("approve", approveFirst) })
    }

    /** The message box's calls (ui/attachapi.py: drafts, files in parts, start, send, @ files); nothing else. */
    suspend fun attach(method: String, path: String, body: String? = null): String {
        require(path.startsWith("/api/attach/")) { "not a message-box call" }
        return call(method, path, body)
    }

    /** Calls of the newer features (rewind, proof, kinds and gallery, rates, a task's live command); nothing else. */
    suspend fun feature(method: String, path: String, body: String? = null): String {
        require(FEATURE_PREFIXES.any { path.startsWith(it) }) { "not a feature call" }
        return call(method, path, body)
    }

    /** A feature call that may wait for a model or a job to finish (a / command, a follow-up, Ask): it doesn't give up
     *  after the usual 40 seconds but waits up to [SLOW_S]. */
    suspend fun slowFeature(method: String, path: String, body: String? = null): String {
        require(FEATURE_PREFIXES.any { path.startsWith(it) }) { "not a feature call" }
        return call(method, path, body, client = slow)
    }

    /** The new-project cards (asks.py wizard_asks), asked one by one on the phone. */
    suspend fun wizardAsks(): List<com.meztking.roundtable.data.Ask> =
        com.meztking.roundtable.data.Asks.parse(call("GET", com.meztking.roundtable.data.WizardFlow.URL))

    suspend fun closeTodo(agent: String, id: String) { call("POST", "/api/journal/${q(agent)}/${q(id)}/close", "{}") }
    suspend fun logEntry(agent: String, kind: String, text: String, priority: String = "normal") {
        call("POST", "/api/journal/${q(agent)}", obj { put("kind", kind); put("text", text); put("priority", priority) })
    }
    suspend fun markRead(agent: String, ids: List<String>) {
        call("POST", "/api/inbox/${q(agent)}/read", ApiJson.encodeToString(mapOf("ids" to ids)))
    }
    suspend fun send(from: String, to: String, subject: String, body: String) {
        call("POST", "/api/send", obj { put("from", from); put("to", to); put("subject", subject); put("body", body) })
    }
    suspend fun reply(from: String, messageId: String, body: String) {
        call("POST", "/api/reply", obj { put("as", from); put("message_id", messageId); put("body", body) })
    }

    private val slow: OkHttpClient by lazy {
        client.newBuilder().readTimeout(SLOW_S, java.util.concurrent.TimeUnit.SECONDS).callTimeout(SLOW_S + 20, java.util.concurrent.TimeUnit.SECONDS).build()
    }

    private val longPoll: OkHttpClient by lazy {
        client.newBuilder().readTimeout(40, java.util.concurrent.TimeUnit.SECONDS).build()
    }

    companion object {
        val FEATURE_PREFIXES = listOf("/api/rewind", "/api/proof", "/api/kinds", "/api/gallery", "/api/rates", "/api/terminal/task",
            "/api/done", "/api/stages", "/api/tandem", "/api/usage", "/api/agents", "/api/learned", "/api/recall",
            "/api/learning", "/api/style", "/api/charter", "/api/market",
            "/api/board", "/api/stream", "/api/commands", "/api/ci", "/api/documents", "/api/projects",
            // wave 8, read only: follow-ups, the queue, what each job may do, the services, who listens, git history
            "/api/follow", "/api/queue", "/api/perms", "/api/integrations", "/api/listening", "/api/git/log",
            // the phone's own views of them: previews of notebooks, archives and media
            "/api/files/preview")
        /** How long a slow call may take: a model's answer or a job's first reply. */
        const val SLOW_S = 300L
        private val JSON = "application/json".toMediaType()
        private fun obj(build: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) = buildJsonObject(build).toString()

        /** A command's fields as JSON: text, numbers, yes/no, lists and maps (nested). */
        fun jsonOf(v: Any?): kotlinx.serialization.json.JsonElement = when (v) {
            null -> kotlinx.serialization.json.JsonNull
            is kotlinx.serialization.json.JsonElement -> v
            is Boolean -> JsonPrimitive(v)
            is Number -> JsonPrimitive(v)
            is Map<*, *> -> JsonObject(v.entries.filter { it.key != null }.associate { it.key.toString() to jsonOf(it.value) })
            is List<*> -> kotlinx.serialization.json.JsonArray(v.map { jsonOf(it) })
            else -> JsonPrimitive(v.toString())
        }

        fun friendly(e: IOException?): String = when {
            e == null -> "couldn't reach your PC"
            e is javax.net.ssl.SSLHandshakeException || e.cause is java.security.cert.CertificateException ->
                "this isn't your PC: its certificate doesn't match. Pair again if you reinstalled ${Brand.NAME}."
            e is java.net.SocketTimeoutException || e is java.net.ConnectException || e is java.net.NoRouteToHostException ->
                "can't reach your PC. Is it on, with ${Brand.NAME} open and phone access on? Away from home, turn on Tailscale."
            else -> e.message ?: "couldn't reach your PC"
        }

        /** Roundtable on this phone ("This phone"): 127.0.0.1 only, with the launch token, no pairing. */
        fun thisPhone(access: LocalAccess, client: OkHttpClient = localClient()): Api =
            Api(PcLink(THIS_PHONE, listOf("127.0.0.1"), 0, "", ""), client, access)

        const val THIS_PHONE = "This phone"

        /** Pair with a PC using the offer from its QR code (or typed code). */
        suspend fun pair(offer: PairingOffer, deviceName: String, code: String = offer.code): PcLink {
            // a PC found on the Wi-Fi: its code must belong to the certificate about to be pinned, checked before
            // the code is sent, so a stand-in on the same Wi-Fi never sees it (discovery.py bound_code)
            if (offer.found) Discovery.requireCode(code, offer.fingerprint)
            val tmp = Api(PcLink(offer.pcName, offer.hosts, offer.port, offer.fingerprint, ""))
            val body = obj { put("code", code); put("device_name", deviceName) }
            val r: PairResult = ApiJson.decodeFromString(tmp.call("POST", "/api/pair/claim", body))
            return PcLink(r.name.ifBlank { offer.pcName }, listOf(tmp.activeHost) + offer.hosts.filter { it != tmp.activeHost },
                offer.port, offer.fingerprint, r.token)
        }
    }
}
