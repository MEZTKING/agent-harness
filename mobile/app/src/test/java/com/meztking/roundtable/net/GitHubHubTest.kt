package com.meztking.roundtable.net

import com.meztking.roundtable.data.HubBackend
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList

class GitHubHubTest {
    private lateinit var server: MockWebServer
    private val puts = CopyOnWriteArrayList<RecordedRequest>()
    private val files = mutableMapOf<String, String>()
    private var treeTruncated = false
    private var status: Int? = null

    private val yaml = """
        # a made-up hub
        storage:
          type: git

        agents:
          me:
            description: My own notes
          lantern-app:
            repo: example/lantern-app
            role: coder
            description: "Lantern: a made-up project # not a comment"
          quiet: {description: A quiet one, repo: example/quiet}   # inline
        # Checked in order
        rules:
          - {from: "*", to: "*", allow: [message]}
    """.trimIndent()

    private fun msg(id: String, to: String, from: String = "lantern-app", subject: String = "Hello") =
        """{"body":"Body of $id","created_at":"2026-11-25T21:19:12Z","id":"$id","in_reply_to":null,"kind":"notify","recipient":"$to","sender":"$from","subject":"$subject","thread_id":"$id"}"""

    @Before fun setUp() {
        files["hub.yaml"] = yaml
        files["status/lantern-app.md"] = "# lantern-app\n\n_Updated 2026-11-25T18:59:39Z - x_\n\n## To do\n\n- [ ] **(high)** Fix the wick `abc123`\n- [ ] Polish `def456`\n"
        files["status/me.md"] = "# me\n\n## To do\n\n_Nothing open._\n"
        files["inbox/me/20261125T100000000000Z-aaaaaa.json"] = msg("20261125T100000000000Z-aaaaaa", "me")
        files["inbox/me/20261125T110000000000Z-bbbbbb.json"] = msg("20261125T110000000000Z-bbbbbb", "me", subject = "Second")
        files["inbox/lantern-app/20261125T090000000000Z-cccccc.json"] = msg("20261125T090000000000Z-cccccc", "lantern-app", from = "me")
        files["state/me.json"] = "{\n  \"read\": [\n    \"20261125T100000000000Z-aaaaaa\"\n  ],\n  \"subscriptions\": [\"quiet\"]\n}\n"
        files["plans/lantern-app.md"] = "_Plan status: waiting for the owner · x · updated 2026-11-25T22:41:05Z by Roundtable Hold_\n\n# Plan v1: Light it\n"
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                status?.let { return MockResponse().setResponseCode(it).setBody("""{"message":"nope"}""") }
                assertEquals("Bearer t0k", request.getHeader("Authorization"))
                val path = request.requestUrl!!.encodedPath.removePrefix("/repos/o/hub/")
                if (request.method == "PUT") {
                    puts += request
                    return MockResponse().setResponseCode(201).setBody("{}")
                }
                if (path == "git/trees/HEAD") {
                    val items = files.keys.joinToString(",") { """{"path":"$it","type":"blob","sha":"s-${it.hashCode()}"}""" }
                    return MockResponse().setBody("""{"sha":"x","tree":[{"path":"inbox","type":"tree","sha":"t"},$items],"truncated":$treeTruncated}""")
                }
                val rel = path.removePrefix("contents/")
                val raw = request.getHeader("Accept")!!.contains("raw")
                files[rel]?.let { body ->
                    return if (raw) MockResponse().setBody(body)
                    else MockResponse().setBody("""{"sha":"sha-$rel","content":"${Base64.getMimeEncoder().encodeToString(body.toByteArray()).replace("\r\n", "\\n")}"}""")
                }
                val dir = files.keys.filter { it.startsWith("$rel/") }
                if (dir.isNotEmpty() && !raw) {
                    val entries = dir.map { it.removePrefix("$rel/").substringBefore("/") }.distinct().joinToString(",") { n ->
                        val full = "$rel/$n"
                        """{"name":"$n","path":"$full","type":"${if (full in files) "file" else "dir"}","sha":"s"}"""
                    }
                    return MockResponse().setBody("[$entries]")
                }
                return MockResponse().setResponseCode(404).setBody("""{"message":"Not Found"}""")
            }
        }
        server.start()
    }

    @After fun tearDown() = server.shutdown()

    private fun hub() = GitHubHub("t0k", "o/hub", base = server.url("/").toString().trimEnd('/'))

    @Test fun agentsIn() {
        assertEquals(listOf("me", "lantern-app", "quiet"), GitHubHub.agentsIn(yaml))
        val p = GitHubHub.projectsIn(yaml)
        assertEquals("Lantern: a made-up project # not a comment", p[1].description)
        assertEquals("example/lantern-app", p[1].repo)
        assertEquals("A quiet one", p[2].description)
        assertEquals("example/quiet", p[2].repo)
        assertEquals(emptyList<String>(), GitHubHub.agentsIn("storage:\n  type: git\n"))
        assertEquals(emptyList<String>(), GitHubHub.agentsIn("agents:\n"))
        assertEquals(listOf("a", "b"), GitHubHub.agentsIn("agents:\r\n  a:\r\n    repo: x\r\n  'b':\r\nother: 1\r\n"))
    }

    @Test fun projectsAndStatus() = runTest {
        val h = hub()
        assertEquals(listOf("me", "lantern-app", "quiet"), h.projects())
        assertTrue(h.status("lantern-app").contains("Fix the wick"))
        assertEquals("", h.status("quiet")) // no status page: empty, not an error
        assertNotNull(h.plan("lantern-app"))
        assertNull(h.plan("me"))
    }

    @Test fun inboxWithReadState() = runTest {
        val m = hub().inbox("me")
        assertEquals(listOf("20261125T110000000000Z-bbbbbb", "20261125T100000000000Z-aaaaaa"), m.map { it.id }) // newest first
        assertFalse(m[0].read)
        assertTrue(m[1].read)
        assertEquals("Second", m[0].subject)
        assertEquals(emptyList<Message>(), hub().inbox("quiet")) // no inbox folder
    }

    @Test fun snapshotFromTheTree() = runTest {
        val s = hub().snapshot()
        assertEquals(listOf("me", "lantern-app", "quiet"), s.projects.map { it.id })
        assertEquals(listOf("20261125T110000000000Z-bbbbbb"), s.unread("me"))
        assertEquals(listOf("20261125T090000000000Z-cccccc"), s.unread("lantern-app"))
        assertEquals(setOf("lantern-app"), s.plans)
        assertEquals("", s.status["quiet"])
    }

    @Test fun snapshotWhenTheTreeIsTruncated() = runTest {
        treeTruncated = true
        val s = hub().snapshot()
        assertEquals(listOf("20261125T110000000000Z-bbbbbb"), s.unread("me"))
        assertEquals(setOf("lantern-app"), s.plans)
    }

    @Test fun hallInHubMode() = runTest {
        val hall = HubBackend(hub(), "me").hall()
        val lantern = hall.seats.first { it.id == "lantern-app" }
        assertEquals("waiting", lantern.status) // a high-priority to-do
        assertEquals(2, lantern.openTodos)
        assertEquals(1, lantern.high)
        assertEquals(1, lantern.unread)
        assertTrue(lantern.hasPlan)
        assertEquals("example/lantern-app", lantern.repo)
        assertEquals(setOf("msg:20261125T110000000000Z-bbbbbb", "todo:lantern-app:abc123"), hall.needs.map { it.key }.toSet())
        assertEquals("no status page yet", hall.seats.first { it.id == "quiet" }.statusText)
    }

    @Test fun emptyHubDoesNotCrash() = runTest {
        files.clear()
        files["hub.yaml"] = "storage:\n  type: git\n"
        val hall = HubBackend(hub(), "me").hall()
        assertEquals(0, hall.seats.size)
        assertEquals(0, hall.needs.size)
    }

    @Test fun sendWritesAHubMessage() = runTest {
        val sent = hub().send("me", "lantern-app", "Hi", "Please trim the wick")
        val r = puts.single()
        assertEquals("/repos/o/hub/contents/inbox/lantern-app/${sent.id}.json", r.requestUrl!!.encodedPath)
        val payload = Json.parseToJsonElement(r.body.readUtf8()).jsonObject
        assertTrue(payload["message"]!!.jsonPrimitive.content.startsWith("msg me -> lantern-app: Hi"))
        assertNull(payload["sha"])
        val content = String(Base64.getDecoder().decode(payload["content"]!!.jsonPrimitive.content))
        val m = Json.parseToJsonElement(content).jsonObject
        assertEquals(setOf("body", "created_at", "id", "in_reply_to", "kind", "recipient", "sender", "subject", "thread_id"), m.keys)
        assertEquals("me", m["sender"]!!.jsonPrimitive.content)
        assertEquals("lantern-app", m["recipient"]!!.jsonPrimitive.content)
        assertEquals("ask", m["kind"]!!.jsonPrimitive.content)
        assertEquals("Please trim the wick", m["body"]!!.jsonPrimitive.content)
        assertEquals(sent.id, m["thread_id"]!!.jsonPrimitive.content)
        assertEquals("null", m["in_reply_to"].toString())
        assertTrue(Regex("^\\d{8}T\\d{12}Z-[0-9a-f]{6}$").matches(sent.id))
        assertTrue(Regex("^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\dZ$").matches(m["created_at"]!!.jsonPrimitive.content))
        assertTrue(content.endsWith("}\n"))
    }

    @Test fun replyKeepsTheThread() = runTest {
        val original = Message("20261125T110000000000Z-bbbbbb", "lantern-app", "me", "ask", "Re: Second", "x", thread_id = "T0")
        val sent = hub().send("me", "lantern-app", "", "yes", inReplyTo = original)
        val m = Json.parseToJsonElement(String(Base64.getDecoder().decode(
            Json.parseToJsonElement(puts.single().body.readUtf8()).jsonObject["content"]!!.jsonPrimitive.content))).jsonObject
        assertEquals("reply", m["kind"]!!.jsonPrimitive.content)
        assertEquals("Re: Second", m["subject"]!!.jsonPrimitive.content) // no "Re: Re:"
        assertEquals("T0", m["thread_id"]!!.jsonPrimitive.content)
        assertEquals(original.id, m["in_reply_to"]!!.jsonPrimitive.content)
        assertEquals("T0", sent.thread_id)
    }

    @Test fun commandIsARequest() = runTest {
        hub().command("me", "lantern-app", "choose", mapOf("decision" to "C4", "option" to "A", "skip" to null))
        hub().command("me", "lantern-app", "idea", mapOf("id" to "I1", "accept" to true))
        val bodies = puts.map {
            Json.parseToJsonElement(String(Base64.getDecoder().decode(
                Json.parseToJsonElement(it.body.readUtf8()).jsonObject["content"]!!.jsonPrimitive.content))).jsonObject
        }
        assertEquals("request", bodies[0]["kind"]!!.jsonPrimitive.content)
        assertEquals("roundtable: choose", bodies[0]["subject"]!!.jsonPrimitive.content)
        assertEquals("""{"action":"choose","decision":"C4","option":"A"}""", bodies[0]["body"]!!.jsonPrimitive.content)
        assertEquals("""{"action":"idea","id":"I1","accept":true}""", bodies[1]["body"]!!.jsonPrimitive.content)
    }

    @Test fun markReadKeepsTheRestOfTheStateFile() = runTest {
        hub().markRead("me", listOf("20261125T110000000000Z-bbbbbb", "20261125T100000000000Z-aaaaaa"))
        val payload = Json.parseToJsonElement(puts.single().body.readUtf8()).jsonObject
        assertEquals("sha-state/me.json", payload["sha"]!!.jsonPrimitive.content)
        val state = Json.parseToJsonElement(String(Base64.getDecoder().decode(payload["content"]!!.jsonPrimitive.content))).jsonObject
        assertEquals("""["20261125T100000000000Z-aaaaaa","20261125T110000000000Z-bbbbbb"]""", state["read"].toString())
        assertEquals("""["quiet"]""", state["subscriptions"].toString())
        // nothing new to mark: no write
        puts.clear()
        hub().markRead("me", listOf("20261125T100000000000Z-aaaaaa"))
        assertTrue(puts.isEmpty())
    }

    @Test fun friendlyErrors() = runTest {
        status = 401
        try { hub().projects(); fail() } catch (e: ApiException) { assertTrue(e.message!!.contains("token")) }
        status = null
        files.remove("hub.yaml")
        try { hub().projects(); fail() } catch (e: ApiException) { assertTrue(e.message!!.contains("hub.yaml")) }
    }
}
