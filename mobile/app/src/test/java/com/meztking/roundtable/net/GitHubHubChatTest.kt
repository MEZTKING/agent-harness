package com.meztking.roundtable.net

import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.GitHubChatFiles
import com.meztking.roundtable.data.HubChat
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

/** The chat through a made-up GitHub (the contents API): list, read, write over, make only once (claims). */
class GitHubHubChatTest {
    private val files = ConcurrentHashMap<String, ByteArray>()
    private val server = MockWebServer().apply {
        dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.path!!.substringAfter("/repos/me/hub/contents/").substringBefore('?')
                return when (request.method) {
                    "GET" -> {
                        val raw = request.getHeader("Accept")!!.contains("raw")
                        val f = files[path]
                        when {
                            f != null && raw -> MockResponse().setBody(okio.Buffer().write(f))
                            f != null -> MockResponse().setBody("""{"sha": "${f.contentHashCode()}", "content": "${Base64.getEncoder().encodeToString(f)}"}""")
                            files.keys.any { it.startsWith("$path/") } -> MockResponse().setBody(files.keys.filter { it.startsWith("$path/") && '/' !in it.removePrefix("$path/") }
                                .joinToString(",", "[", "]") { """{"name": "${it.substringAfterLast('/')}", "path": "$it", "type": "file", "sha": "x"}""" })
                            else -> MockResponse().setResponseCode(404)
                        }
                    }
                    "PUT" -> synchronized(files) {
                        val o = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject
                        val sha = o["sha"]?.jsonPrimitive?.content
                        val have = files[path]
                        if (have != null && sha != have.contentHashCode().toString()) MockResponse().setResponseCode(422)
                        else { files[path] = Base64.getDecoder().decode(o["content"]!!.jsonPrimitive.content); MockResponse().setResponseCode(201).setBody("{}") }
                    }
                    else -> MockResponse().setResponseCode(405)
                }
            }
        }
        start()
    }
    private val hub = GitHubHub("proxy-injected", "me/hub", server.url("/").toString().trimEnd('/'))

    @After fun close() = server.shutdown()

    @Test fun theChatsFilesGoThroughTheContentsApi() = runBlocking {
        hub.writeBytes("chats/hall/2026-11-28.phone-a.jsonl", "one\n".toByteArray(), "m")
        hub.writeBytes("chats/hall/2026-11-28.phone-a.jsonl", "one\ntwo\n".toByteArray(), "m") // over its own file
        assertEquals("one\ntwo\n", hub.text("chats/hall/2026-11-28.phone-a.jsonl"))
        assertEquals(listOf("2026-11-28.phone-a.jsonl"), hub.names("chats/hall"))
        assertEquals(emptyList<String>(), hub.names("chats/nothing"))
        assertTrue(hub.createOnly("chats/hall/claims/t1.json", "{}".toByteArray(), "m"))
        assertFalse(hub.createOnly("chats/hall/claims/t1.json", "{}".toByteArray(), "m")) // the first to reach the hub wins
    }

    @Test fun twoPhonesThroughTheHubMergeInOrderAndOnlyOneClaimWins() = runBlocking {
        var t = java.time.Instant.parse("2026-11-28T10:00:00Z")
        val a = HubChat(GitHubChatFiles(hub), "phone-a", clock = { t })
        val b = HubChat(GitHubChatFiles(hub), "phone-b", clock = { t })
        a.append("hall", ChatLine(who = "owner", text = "from a")); t = t.plusSeconds(1)
        b.append("hall", ChatLine(who = "owner", text = "from b")); t = t.plusSeconds(1)
        a.append("hall", ChatLine(who = "owner", text = "a again"))
        assertEquals(listOf("from a", "from b", "a again"), b.lines("hall").map { it.text })
        val wins = listOf(a, b).map { c -> async { c.claim("hall", "turn1") } }.awaitAll()
        assertEquals(1, wins.count { it })
    }
}
