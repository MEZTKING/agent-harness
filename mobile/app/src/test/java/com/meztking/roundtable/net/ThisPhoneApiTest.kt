package com.meztking.roundtable.net

import kotlinx.coroutines.runBlocking
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.net.InetAddress

class ThisPhoneApiTest {
    private val server = MockWebServer()
    private val token = "launch-token-0123456789abcdefghijklmnopqrstu"

    @Before fun start() = server.start(InetAddress.getByName("127.0.0.1"), 0)
    @After fun stop() = server.shutdown()

    private fun access(t: String = token) = object : LocalAccess {
        override fun port() = server.port
        override suspend fun token() = t
    }

    @Test
    fun `every call goes to 127_0_0_1 over plain HTTP with the bearer token`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"seats": []}"""))
        Api.thisPhone(access()).roundtable()
        val r = server.takeRequest()
        assertEquals("Bearer $token", r.getHeader("Authorization"))
        assertEquals("/api/roundtable", r.path)
        assertEquals("127.0.0.1:${server.port}", r.getHeader("Host"))
        assertEquals("http", r.requestUrl!!.scheme)
    }

    @Test
    fun `the key goes to api keys and nowhere else`() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"ok": true}"""))
        Api.thisPhone(access()).saveKey("deepseek", "sk-test-not-a-real-key")
        val r = server.takeRequest()
        assertEquals("POST", r.method)
        assertEquals("/api/keys", r.path)
        val body = r.body.readUtf8()
        assertTrue(body.contains("\"provider\":\"deepseek\""))
        assertTrue(body.contains("\"key\":\"sk-test-not-a-real-key\""))
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `the server's error is shown in its own words`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"error": "wrong token"}"""))
        try {
            Api.thisPhone(access("stale")).roundtable()
            fail("expected an error")
        } catch (e: ApiException) {
            assertEquals("wrong token", e.message)
            assertEquals(401, e.status)
        }
    }

    @Test
    fun `the local client refuses any host that isn't the phone's own loopback`() {
        val client = localClient()
        for (url in listOf("http://example.com/api/health", "http://192.168.1.10:8765/api/health", "https://127.0.0.1:8765/api/health")) {
            try {
                client.newCall(Request.Builder().url(url).header("Authorization", "Bearer $token").build()).execute().close()
                fail("$url should be refused")
            } catch (e: IOException) {
                assertTrue(e.message!!.startsWith("refused"))
            }
        }
        assertTrue(LoopbackOnly.allowed("http", "127.0.0.1"))
        assertFalse(LoopbackOnly.allowed("http", "10.0.0.2"))
        assertFalse(LoopbackOnly.allowed("https", "127.0.0.1"))
        // Nothing reached the test server either.
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `when Roundtable on this phone isn't running the message says what to do`() = runBlocking {
        val notRunning = object : LocalAccess {
            override fun port() = server.port
            override suspend fun token(): String = throw com.meztking.roundtable.runtime.RuntimeController.NotRunningException()
        }
        try {
            Api.thisPhone(notRunning).roundtable()
            fail("expected an error")
        } catch (e: ApiException) {
            assertTrue(e.message!!.contains("press Start"))
        }
        assertEquals(0, server.requestCount)
    }
}
