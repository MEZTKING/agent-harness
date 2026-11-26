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

class ApiException(message: String, val status: Int = 0) : IOException(message)

/** A paired PC: where to reach it, which certificate to trust, and this phone's token. */
data class PcLink(val name: String, val hosts: List<String>, val port: Int, val fingerprint: String, val token: String)

/**
 * Talks to the Roundtable Hold phone server. Tries the PC's addresses in turn (Wi-Fi first,
 * then Tailscale) and remembers the one that answered.
 */
class Api(var link: PcLink, private val client: OkHttpClient = pinnedClient(link.fingerprint)) {
    @Volatile var activeHost: String = link.hosts.first()

    private fun url(host: String, path: String): String {
        val h = if (':' in host) "[$host]" else host // IPv6
        return "https://$h:${link.port}$path"
    }

    private suspend fun call(method: String, path: String, body: String? = null, client: OkHttpClient = this.client): String =
        withContext(Dispatchers.IO) {
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

    private fun q(v: String) = URLEncoder.encode(v, "UTF-8")

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

    suspend fun ask(path: String, message: String, steer: Boolean): ChatReply = ApiJson.decodeFromString(
        call("POST", "/api/chat", obj { put("path", path); put("message", message); put("steer", steer) }))

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
    suspend fun autopilot(): com.meztking.roundtable.data.AutopilotState =
        ApiJson.decodeFromString(call("GET", "/api/autopilot?limit=30"))

    suspend fun setAutopilot(on: Boolean, until: String = "", cap: Double? = null): com.meztking.roundtable.data.AutopilotState =
        ApiJson.decodeFromString(call("POST", "/api/autopilot", obj {
            put("action", if (on) "on" else "off"); put("until", until); if (cap != null) put("cap", cap)
        }))

    suspend fun newProject(dir: String, goal: String, approveFirst: Boolean = true) {
        call("POST", "/api/projects", obj { put("dir", dir); put("goal", goal); put("approve", approveFirst) })
    }

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

    private val longPoll: OkHttpClient by lazy {
        client.newBuilder().readTimeout(40, java.util.concurrent.TimeUnit.SECONDS).build()
    }

    companion object {
        private val JSON = "application/json".toMediaType()
        private fun obj(build: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) = buildJsonObject(build).toString()

        fun friendly(e: IOException?): String = when {
            e == null -> "couldn't reach your PC"
            e is javax.net.ssl.SSLHandshakeException || e.cause is java.security.cert.CertificateException ->
                "this isn't your PC: its certificate doesn't match. Pair again if you reinstalled Roundtable Hold."
            e is java.net.SocketTimeoutException || e is java.net.ConnectException || e is java.net.NoRouteToHostException ->
                "can't reach your PC. Is it on, with Roundtable Hold open and phone access on? Away from home, turn on Tailscale."
            else -> e.message ?: "couldn't reach your PC"
        }

        /** Pair with a PC using the offer from its QR code (or typed code). */
        suspend fun pair(offer: PairingOffer, deviceName: String, code: String = offer.code): PcLink {
            val tmp = Api(PcLink(offer.pcName, offer.hosts, offer.port, offer.fingerprint, ""))
            val body = obj { put("code", code); put("device_name", deviceName) }
            val r: PairResult = ApiJson.decodeFromString(tmp.call("POST", "/api/pair/claim", body))
            return PcLink(r.name.ifBlank { offer.pcName }, listOf(tmp.activeHost) + offer.hosts.filter { it != tmp.activeHost },
                offer.port, offer.fingerprint, r.token)
        }
    }
}
