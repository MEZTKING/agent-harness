package com.meztking.roundtable.net

import com.meztking.roundtable.data.Preview
import com.meztking.roundtable.data.Recall
import com.meztking.roundtable.data.Team
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.InetAddress

/**
 * This phone answers like the PC (wave 9, item 7): Roundtable on the phone itself (`resources/thisphone/`, written from
 * `onphone.make_local_server` over a made-up bakery) and the PC (`resources/conformance/`) give answers the phone's own
 * decoders read the same way, with the same keys, for a file's preview, Ask (the price first), usage and the agents.
 */
class ThisPhoneSameAnswersTest {
    private val server = MockWebServer()

    @Before fun start() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val p = request.path.orEmpty().substringBefore('?')
                val name = mapOf("/api/files/preview" to "file_preview", "/api/recall/ask" to "recall_ask",
                    "/api/usage" to "usage", "/api/agents" to "agents")[p] ?: return MockResponse().setResponseCode(404)
                return MockResponse().setBody(phone(name))
            }
        }
        server.start(InetAddress.getByName("127.0.0.1"), 0)
    }

    @After fun stop() = server.shutdown()

    private val api get() = Api.thisPhone(object : LocalAccess {
        override fun port() = server.port
        override suspend fun token() = "launch-token-0123456789abcdefghijklmnopqrstu"
    })

    private fun phone(name: String) = javaClass.getResource("/thisphone/$name.json")?.readText() ?: error("no This-phone fixture $name")
    private fun pc(name: String) = javaClass.getResource("/conformance/$name.json")?.readText() ?: error("no PC fixture $name")

    /** The keys and kinds of an answer, two levels down (as tests/test_onphone_same_answers.py's shape). */
    private fun shape(e: JsonElement, depth: Int = 0): Any = when (e) {
        is JsonObject -> if (depth < 2) e.entries.sortedBy { it.key }.associate { it.key to shape(it.value, depth + 1) } else "object"
        is JsonArray -> "list"
        JsonNull -> "null"
        is JsonPrimitive -> if (e.isString) "text" else if (e.content == "true" || e.content == "false") "bool" else "number"
    }

    private fun keys(text: String) = (ApiJson.parseToJsonElement(text) as JsonObject).keys

    @Test
    fun `a file's preview reads the same on this phone`() = runBlocking {
        val p = Preview.parse(api.feature("GET", Preview.url("/home/owner/lab/made-up-bakery", "menu.zip")))
        assertEquals("archive", p.preview)
        assertTrue(p.entries.any { it.name == "bread.txt" })
        assertTrue(keys(pc("file_preview")).all { it in keys(phone("file_preview")) || it in OPTIONAL })
    }

    @Test
    fun `Ask on this phone gives the price first and spends nothing`() = runBlocking {
        val a = Recall.answer(api.slowFeature("POST", Recall.ASK, Recall.askBody("what does the bakery sell?", confirm = false)))
        assertEquals("", a.answer)
        assertEquals(0.0, a.cost_usd, 0.0)
        assertEquals(keys(pc("recall_ask")), keys(phone("recall_ask")))
    }

    @Test
    fun `usage and the agents have the PC's shape`() = runBlocking {
        val u = Team.usage(api.feature("GET", Team.USAGE))
        assertTrue(u.services.isNotEmpty())
        val ag = Team.agents(api.feature("GET", Team.AGENTS))
        assertTrue(ag.agents.isNotEmpty() && ag.jobs.isNotEmpty())
        for (name in listOf("usage", "agents")) {
            assertEquals("$name differs between this phone and the PC",
                shape(ApiJson.parseToJsonElement(pc(name))), shape(ApiJson.parseToJsonElement(phone(name))))
        }
    }

    private companion object {
        /** Keys only an answer about another kind of file carries (the PC's fixture previews a different file). */
        val OPTIONAL = setOf("cells", "language", "more", "blocks", "office", "sheets", "slides", "mime")
    }
}
