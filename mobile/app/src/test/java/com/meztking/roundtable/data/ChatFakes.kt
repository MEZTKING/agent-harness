package com.meztking.roundtable.data

import com.meztking.roundtable.net.DeepSeekChat
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList

/** A made-up hub in memory: the chat's files, with every write kept so tests can look for leaks. */
class FakeHubFiles(val files: MutableMap<String, ByteArray> = java.util.concurrent.ConcurrentHashMap()) : ChatFiles {
    @Volatile var offline = false
    val writes = CopyOnWriteArrayList<Pair<String, ByteArray>>()

    private fun up() { if (offline) throw IOException("offline") }
    fun put(path: String, text: String) { files[path] = text.toByteArray() }
    fun everything(): String = writes.joinToString("\n") { it.first + "\n" + String(it.second) }

    override suspend fun names(dir: String): List<String> { up(); return files.keys.filter { it.startsWith("$dir/") && '/' !in it.removePrefix("$dir/") }.map { it.removePrefix("$dir/") } }
    override suspend fun text(path: String): String? { up(); return files[path]?.let { String(it) } }
    override suspend fun bytes(path: String): ByteArray? { up(); return files[path] }
    override suspend fun write(path: String, data: ByteArray, message: String) { up(); files[path] = data; writes += path to data }
    override suspend fun createOnly(path: String, data: ByteArray, message: String): Boolean {
        up(); synchronized(files) { if (files.containsKey(path)) return false; files[path] = data }; writes += path to data; return true
    }

    companion object {
        /** A made-up hub with one project, its plan and status, and a PC that last listened three hours ago. */
        fun sample(now: java.time.Instant = java.time.Instant.now()): FakeHubFiles = FakeHubFiles().apply {
            put("hub.yaml", "agents:\n  me:\n    description: My notes\n  lantern-app:\n    description: A made-up lantern app\n")
            put("status/lantern-app.md", "# lantern-app\n\n## Left off\n\nFive ideas accepted, ready to build.\n")
            put("plans/lantern-app.md", "# Lantern app\n\nEstimate: about \$1.40\n\n## Tasks\n\n- T1 Glow\n")
            put("machines/pc-desk-1a2b.json", """{"seat": "pc-desk-1a2b", "name": "PC-Desk", "last_seen": "${now.minusSeconds(3 * 3600)}"}""")
        }
    }
}

/** A made-up DeepSeek: answers each call with [reply] (an SSE body) or [status]; keeps the requests. */
class FakeDeepSeek {
    val server = MockWebServer()
    val requests = CopyOnWriteArrayList<RecordedRequest>()
    @Volatile var status = 200
    @Volatile var reply: String = sse("Five ideas are ready to build.")

    init {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests += request
                if (status != 200) return MockResponse().setResponseCode(status).setBody("""{"error": {"message": "no"}}""")
                if (request.path!!.endsWith("/user/balance")) return MockResponse().setBody("""{"is_available": true, "balance_infos": []}""")
                return MockResponse().setHeader("Content-Type", "text/event-stream").setBody(reply)
            }
        }
        server.start()
    }

    fun client(key: String): DeepSeekChat = DeepSeekChat(key, server.url("/"), OkHttpClient())
    fun bodies(): String = requests.joinToString("\n") { it.body.clone().readUtf8() }
    fun close() = server.shutdown()

    companion object {
        fun sse(words: String, thinking: String = "Reading the board.", promptTokens: Int = 6000, out: Int = 300,
                hit: Int = 5000, miss: Int = 1000, model: String = "deepseek-v4-flash"): String = buildString {
            fun esc(s: String) = kotlinx.serialization.json.JsonPrimitive(s).toString()
            append("data: {\"model\": \"$model\", \"choices\": [{\"delta\": {\"reasoning_content\": ${esc(thinking)}}}]}\n\n")
            words.chunked(12).forEach { append("data: {\"choices\": [{\"delta\": {\"content\": ${esc(it)}}}]}\n\n") }
            append("data: {\"choices\": [], \"usage\": {\"prompt_tokens\": $promptTokens, \"completion_tokens\": $out, " +
                "\"prompt_cache_hit_tokens\": $hit, \"prompt_cache_miss_tokens\": $miss}}\n\n")
            append("data: [DONE]\n\n")
        }
    }
}
