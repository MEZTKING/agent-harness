package com.meztking.roundtable.net

import com.meztking.roundtable.data.ChatLayout
import com.meztking.roundtable.data.FakeDeepSeek
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** The phone's one DeepSeek call, against a made-up DeepSeek: no real key, nothing spent. */
class DeepSeekChatTest {
    private val ds = FakeDeepSeek()
    private val key = "sk-madeup0000000000000000test"

    @After fun close() = ds.close()

    @Test fun theAnswerStreamsWithItsThinkingAndIsPricedFromTheReportedTokens() = runBlocking {
        val events = ds.client(key).stream(listOf(DeepSeekChat.Message("user", "Where does it stand?"))).toList()
        val words = events.filterIsInstance<DeepSeekChat.Event.Words>().joinToString("") { it.text }
        assertEquals("Five ideas are ready to build.", words)
        assertTrue(events.filterIsInstance<DeepSeekChat.Event.Words>().size > 1) // in pieces, as written
        assertEquals("Reading the board.", events.filterIsInstance<DeepSeekChat.Event.Thinking>().single().text)
        val done = events.last() as DeepSeekChat.Event.Done
        // 1,000 fresh in, 5,000 cached, 300 out at the listed prices: about a tenth of a cent
        assertEquals(0.000906, done.usage.usd, 1e-9)
        val r = ds.requests.single()
        assertEquals("/chat/completions", r.path)
        assertEquals("Bearer $key", r.getHeader("Authorization"))
        val body = r.body.readUtf8()
        assertTrue(body, "\"model\":\"deepseek-v4-flash\"" in body)
        assertTrue(body, "\"max_tokens\":700" in body)
    }

    @Test fun theModelIsFixedAndV4ProIsRefused() = runBlocking {
        try { ds.client(key).stream(emptyList(), model = "deepseek-v4-pro").toList(); fail("V4 Pro was allowed") } catch (e: IllegalArgumentException) {}
        try { ds.client(key).stream(emptyList(), model = "deepseek-chat").toList(); fail("another model was allowed") } catch (e: IllegalArgumentException) {}
        assertEquals(0, ds.requests.size)
        // DeepSeek answering as V4 Pro is refused too
        ds.reply = FakeDeepSeek.sse("hi", model = "deepseek-v4-pro")
        try { ds.client(key).stream(emptyList()).toList(); fail() } catch (e: DeepSeekChat.Refused) { assertEquals("key_refused", e.why) }
        assertEquals(ChatLayout.MODEL, "deepseek-v4-flash")
    }

    @Test fun refusalsAreTheChatsReasonsAndNeverCarryTheKey() = runBlocking {
        for ((code, why) in listOf(401 to "key_refused", 402 to "no_credit", 500 to "offline")) {
            ds.status = code
            try { ds.client(key).stream(emptyList()).toList(); fail() } catch (e: DeepSeekChat.Refused) {
                assertEquals(why, e.why); assertFalse(e.message!!.contains(key))
            }
            assertEquals(why, ds.client(key).check())
        }
        ds.status = 200
        assertEquals("", ds.client(key).check())
    }

    @Test fun redirectsAreNeverFollowed() = runBlocking {
        val other = MockWebServer().apply { enqueue(MockResponse().setBody("{}")); start() }
        val s = MockWebServer().apply { enqueue(MockResponse().setResponseCode(302).setHeader("Location", other.url("/stolen").toString())); start() }
        try {
            val c = DeepSeekChat(key, s.url("/"), OkHttpClient())
            assertFalse(c.client.followRedirects); assertFalse(c.client.followSslRedirects)
            try { c.stream(emptyList()).toList(); fail() } catch (e: DeepSeekChat.Refused) { assertEquals("offline", e.why) }
            assertEquals(0, other.requestCount) // the key never went anywhere else
        } finally { s.shutdown(); other.shutdown() }
    }

    @Test fun onlyTheOneHostMayBeCalledAndNothingLogs() = runBlocking {
        val made = DeepSeekChat.create(key)
        // the app's own client: no logging interceptor, only the host pin; no network interceptors at all
        assertEquals(1, made.client.interceptors.size)
        assertTrue(made.client.networkInterceptors.isEmpty())
        // a client pinned to api.deepseek.com refuses the made-up server's host before sending anything
        val pinned = OkHttpClient.Builder().addInterceptor(DeepSeekChat.pin(DeepSeekChat.HOST)).build()
        try { pinned.newCall(okhttp3.Request.Builder().url(ds.server.url("/chat/completions")).build()).execute(); fail() }
        catch (e: java.io.IOException) { assertTrue(e.message!!.startsWith("refused")) }
        assertEquals(0, ds.requests.size)
        // and no HTTP logging library is in the app at all, so release builds can't log a request
        assertFalse(java.io.File("build.gradle.kts").readText().contains("logging-interceptor"))
    }
}
