package com.meztking.roundtable.net

import com.meztking.roundtable.data.ChatLayout
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The phone's own answers in Hub mode (1.5.0): one streaming call to DeepSeek, with the key the owner pasted into
 * the phone. Nothing else.
 *
 * Locked down (Fable's list): the host is api.deepseek.com and nothing else (an interceptor refuses any other host,
 * and redirects are never followed); there is no HTTP logging at all; the model is [ChatLayout.MODEL], fixed in
 * code, and anything matching [ChatLayout.NEVER] is refused; the key goes only in the Authorization header and never
 * in an error's words.
 */
class DeepSeekChat internal constructor(
    private val key: String,
    private val base: HttpUrl,
    client: OkHttpClient,
) {
    /** What one answer cost, from the tokens DeepSeek reported. */
    data class Usage(val promptTokens: Int = 0, val completionTokens: Int = 0, val cacheHit: Int = 0, val cacheMiss: Int = 0) {
        /** Dollars at DeepSeek's listed peak prices (the dearer half: the count never says less than the bill). */
        val usd: Double get() {
            val miss = if (cacheHit + cacheMiss > 0) cacheMiss else promptTokens
            return (miss * IN_USD + cacheHit * CACHED_USD + completionTokens * OUT_USD) / 1_000_000.0
        }
    }

    /** What arrives while DeepSeek answers. */
    sealed interface Event {
        data class Words(val text: String) : Event
        data class Thinking(val text: String) : Event
        data class Done(val usage: Usage, val model: String) : Event
    }

    /** Why DeepSeek gave no answer: one of the chat's "never silence" codes ([ChatLayout.CANNOT]). */
    class Refused(val why: String) : IOException("DeepSeek: $why")

    internal val client: OkHttpClient = client.newBuilder()
        .followRedirects(false).followSslRedirects(false)
        .addInterceptor(pin(base.host))
        .build()

    /** A message for the call: role "system", "user" or "assistant". */
    data class Message(val role: String, val content: String)

    /** The answer, streamed. [maxTokens] is capped at the chat's 700. */
    fun stream(messages: List<Message>, maxTokens: Int = ChatLayout.REPLY_TOKENS, model: String = ChatLayout.MODEL): Flow<Event> = flow {
        require(!ChatLayout.never(model) && model == ChatLayout.MODEL) { "That model can't answer the chat." }
        val body = buildJsonObject {
            put("model", model)
            put("stream", true)
            put("max_tokens", maxTokens.coerceIn(1, ChatLayout.REPLY_TOKENS))
            put("stream_options", buildJsonObject { put("include_usage", true) })
            put("messages", buildJsonArray {
                messages.forEach { m -> add(buildJsonObject { put("role", m.role); put("content", m.content) }) }
            })
        }.toString()
        val req = Request.Builder().url(base.newBuilder().addPathSegments("chat/completions").build())
            .header("Authorization", "Bearer $key").header("Accept", "text/event-stream")
            .post(body.toRequestBody(JSON)).build()
        val call = client.newCall(req)
        val response = try { call.execute() } catch (e: IOException) { throw Refused("offline") }
        response.use { r ->
            if (!r.isSuccessful) throw Refused(refusal(r.code, r.body?.string().orEmpty()))
            val source = r.body?.source() ?: throw Refused("offline")
            var usage = Usage()
            var answered = model
            try {
                while (true) {
                    val line = source.readUtf8Line() ?: break
                    if (!line.startsWith("data:")) continue
                    val data = line.removePrefix("data:").trim()
                    if (data == "[DONE]") break
                    val o = runCatching { ApiJson.parseToJsonElement(data) as JsonObject }.getOrNull() ?: continue
                    (o["model"] as? JsonPrimitive)?.content?.let { answered = it }
                    val delta = ((o["choices"] as? JsonArray)?.firstOrNull() as? JsonObject)?.get("delta") as? JsonObject
                    str(delta?.get("reasoning_content"))?.takeIf { it.isNotEmpty() }?.let { emit(Event.Thinking(it)) }
                    str(delta?.get("content"))?.takeIf { it.isNotEmpty() }?.let { emit(Event.Words(it)) }
                    (o["usage"] as? JsonObject)?.let { u -> usage = Usage(int(u["prompt_tokens"]), int(u["completion_tokens"]),
                        int(u["prompt_cache_hit_tokens"]), int(u["prompt_cache_miss_tokens"])) }
                }
            } catch (e: IOException) {
                throw Refused("offline")
            }
            if (ChatLayout.never(answered)) throw Refused("key_refused")
            emit(Event.Done(usage, answered))
        }
    }.flowOn(Dispatchers.IO)

    /** Save and check: DeepSeek's balance page (free, no model call). "" when the key works and there is credit,
     *  else the reason ("key_refused", "no_credit", "offline"). */
    suspend fun check(): String = kotlinx.coroutines.withContext(Dispatchers.IO) {
        val req = Request.Builder().url(base.newBuilder().addPathSegments("user/balance").build())
            .header("Authorization", "Bearer $key").header("Accept", "application/json").get().build()
        try {
            client.newCall(req).execute().use { r ->
                val text = r.body?.string().orEmpty()
                if (!r.isSuccessful) return@withContext refusal(r.code, text)
                val o = runCatching { ApiJson.parseToJsonElement(text) as JsonObject }.getOrNull()
                val available = (o?.get("is_available") as? JsonPrimitive)?.content
                if (available == "false") "no_credit" else ""
            }
        } catch (e: IOException) {
            "offline"
        }
    }

    companion object {
        const val HOST = "api.deepseek.com"
        /** DeepSeek's listed prices for deepseek-v4-flash, dollars per million tokens (checked 26 November 2026). */
        const val IN_USD = 0.44
        const val OUT_USD = 1.32
        const val CACHED_USD = 0.014
        private val JSON = "application/json".toMediaType()

        private val shared: OkHttpClient by lazy {
            OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS)
                .callTimeout(120, TimeUnit.SECONDS).build()
        }

        /** The only way the app makes one: always api.deepseek.com. */
        fun create(key: String): DeepSeekChat = DeepSeekChat(key, "https://$HOST/".toHttpUrl(), shared)

        /** Refuses any request (a redirect included) to another host than [host]. */
        internal fun pin(host: String) = Interceptor { chain ->
            val url = chain.request().url
            if (url.host != host) throw IOException("refused: only $host may be called")
            chain.proceed(chain.request())
        }

        /** DeepSeek's answer codes as the chat's reasons. */
        fun refusal(code: Int, body: String): String = when {
            code == 401 || code == 403 -> "key_refused"
            code == 402 -> "no_credit"
            "insufficient" in body.lowercase() && "balance" in body.lowercase() -> "no_credit"
            else -> "offline"
        }

        private fun str(e: kotlinx.serialization.json.JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content
        private fun int(e: kotlinx.serialization.json.JsonElement?): Int = (e as? JsonPrimitive)?.content?.toIntOrNull() ?: 0
    }
}
