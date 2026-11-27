package com.meztking.roundtable.net

import com.meztking.roundtable.data.DoneList
import com.meztking.roundtable.data.Stages
import com.meztking.roundtable.data.Asks
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.ComposerDraft
import com.meztking.roundtable.data.ComposerSender
import com.meztking.roundtable.data.ApiRewind
import com.meztking.roundtable.data.Files
import com.meztking.roundtable.data.Kinds
import com.meztking.roundtable.data.Pounds
import com.meztking.roundtable.data.Proof
import com.meztking.roundtable.data.Live
import com.meztking.roundtable.data.ProjectSettings
import com.meztking.roundtable.data.Search
import com.meztking.roundtable.data.SessionLog
import com.meztking.roundtable.data.SharedSettings
import com.meztking.roundtable.data.Sync
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.net.InetAddress

/**
 * The phone's calls against the answers a real PC gave (tests/conformance/test_phone_calls.py wrote them to
 * src/test/resources/conformance/). Each request the app's own [Api] makes is matched to its entry in
 * tests/conformance/calls.json – method, path, query and body keys – and answered with that call's fixture;
 * the app's own decoders then read it. Every call in calls.json must be made here at least once.
 */
class ConformanceTest {
    private class Call(val name: String, val method: String, val path: Regex, val query: Set<String>, val body: Set<String>)

    private val calls: List<Call> by lazy {
        val spec = ApiJson.parseToJsonElement(specFile().readText()).jsonObject
        (spec["calls"] as JsonArray).map { it.jsonObject }.filter { (it["local"] as? JsonPrimitive)?.content != "true" }.map { c ->
            fun str(k: String) = (c[k] as JsonPrimitive).content
            val pattern = Regex.escape(str("path")).replace(Regex("\\{\\w+\\}"), "\\\\E[^/]+\\\\Q")
            Call(str("name"), str("method"), Regex(pattern), (c["query"] as? JsonObject)?.keys.orEmpty(), (c["body"] as? JsonObject)?.keys.orEmpty())
        }
    }

    private fun specFile(): File = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "tests/conformance/calls.json") }.firstOrNull { it.isFile }
        ?: error("tests/conformance/calls.json not found above ${File("").absolutePath}")

    private fun fixture(name: String): String =
        javaClass.getResource("/conformance/$name.json")?.readText() ?: error("no fixture for $name: run the conformance pytest with ROUNDTABLE_WRITE_FIXTURES=1")

    private val server = MockWebServer()
    private val served = mutableListOf<String>()
    private val problems = mutableListOf<String>()

    @Before fun start() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val url = request.requestUrl!!
                val keys = url.queryParameterNames
                val body = if (request.method == "POST") runCatching {
                    ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject.keys
                }.getOrDefault(emptySet()) else emptySet()
                val c = calls.firstOrNull { it.method == request.method && it.path.matches(url.encodedPath) && it.query == keys && body.containsAll(it.body) }
                if (c == null) {
                    synchronized(problems) { problems += "${request.method} ${url.encodedPath} ?$keys body $body isn't in calls.json" }
                    return MockResponse().setResponseCode(404).setBody("""{"error": "not in calls.json"}""")
                }
                synchronized(served) { served += c.name }
                return MockResponse().setHeader("Content-Type", "application/json").setBody(fixture(c.name))
            }
        }
        server.start(InetAddress.getByName("127.0.0.1"), 0)
    }

    @After fun stop() = server.shutdown()

    private fun api() = Api.thisPhone(object : LocalAccess {
        override fun port() = server.port
        override suspend fun token() = "conformance-token"
    })

    private val project = "/home/owner/lab/proj"

    @Test
    fun `every call the phone makes reads the PC's real answer`() = runBlocking {
        val api = api()
        assertEquals("made-up-pc", api.ping().name)
        assertTrue(api.changes("", 0).version.isNotBlank())
        val rt = api.roundtable()
        assertTrue(rt.seats.any { it.id == "proj" })
        assertTrue(rt.needs_you.isNotEmpty())
        assertTrue(api.activity().isNotEmpty())
        val p = api.project(project)
        assertEquals("awaiting_approval", p.meta.status)
        assertTrue(p.tasks.isNotEmpty())
        api.chat(project)
        assertTrue(api.inbox("proj").any { it.subject == "hello" })
        api.inbox("proj", all = true)
        assertTrue(api.journal("proj").isNotEmpty())
        api.jobs()

        val asks = api.asks(project)
        val approve = asks.first { it.id == "approve" }
        val notes = api.notes()
        assertEquals("Garden ideas", notes.single().title)
        assertTrue(api.note(notes.single().name).contains("made-up"))
        assertNotNull(api.planWords(project))
        Live.parsePc(api.live(project))
        assertNotNull(Live.parseSession(api.session(project)))

        assertTrue(Files.folder(api.files(project, "")).items.any { it.name == "README.md" })
        assertTrue(Files.opened(api.fileOpen(project, "README.md")).text.orEmpty().contains("bakery"))
        assertNotNull(Files.opened(api.fileOpen(project, "README.md", copy = true)).bytes())
        Files.log(api.commandLog(project))
        Sync.parseMachines(api.machines())
        assertTrue(Search.parse(api.search("bakery")).hits.isNotEmpty())
        assertEquals(listOf("# A made-up bakery"), Search.parsePeek(api.peek(project, "README.md", 1)).lines)
        assertTrue(Search.parseMemory(api.memory(project, machine = false, archive = false)).markdown.isNotBlank())
        Search.parseMemory(api.memory("", machine = true, archive = true))
        SessionLog.parseAny(api.hubSession("proj"), "proj")
        assertNotNull(SharedSettings.parseJson(api.sharedSettings()))
        assertTrue(SharedSettings.roleChoices(api.roles()).isNotEmpty())
        assertTrue(ProjectSettings.parse(api.projectSettings(project)).items.any { it.key == "test" })
        assertFalse(api.autopilot().on)

        val composer = ComposerSender { m, path, b -> api.attach(m, path, b) }
        assertTrue(composer.files(project, "").contains("README.md"))
        val draft = ComposerDraft("conformance", "a note from the phone", "next")
        assertTrue(composer.send(draft, project, "note") { ByteArray(0) }.startsWith("Noted"))
        composer.startIdea(ComposerDraft("conformance", "a made-up kite shop")) { ByteArray(0) }
        // a file in one part: clear, upload, draft
        composer.upload(draft.copy(files = listOf(com.meztking.roundtable.data.DraftFile("f1", "note.txt", "text/plain", 5, "f1")))) { "hello".toByteArray() }

        ProjectSettings.parse(api.saveProjectSettings(project, buildJsonObject { put("test", "python --version") }))
        SharedSettings.parseJson(api.saveSharedSettings(buildJsonObject { put("autopilot", buildJsonObject { put("cap", 2.0) }) }))
        assertFalse(api.setAutopilot(false).on)
        api.logEntry("proj", "todo", "check the made-up logo")
        api.closeTodo("proj", "abc123")
        api.markRead("proj", listOf("m1"))
        api.send("proj", "frontend", "hello", "a made-up message")
        api.reply("proj", "m1", "thanks")
        assertTrue(api.hubCommand("frontend", "", "run", emptyMap()).startsWith("Sent"))
        api.projectAction(project, "feedback", task = "T1")
        val job = Files.jobId(api.runTests(project))
        assertTrue(job.isNotBlank())
        assertTrue(Files.job(api.job(job)).third)
        assertTrue(api.ask(project, "how is it going?", steer = false).reply.isNotBlank())
        api.newProject("made-up-garden", "a garden planner")
        assertTrue(api.answer(approve, AskReply(chosen = listOf("approve"))).isNotBlank())

        // wave 3: kinds and the Gallery, pounds, rewind, proof and a task's live command (Api.feature)
        val kinds = Kinds.parseList(api.feature("GET", "/api/kinds"))
        assertTrue(kinds.groups.any { g -> g.kinds.any { it.id == "website" } })
        assertTrue(api.feature("GET", "/api/kinds/one?id=website").contains("\"website\""))
        assertTrue(api.feature("POST", "/api/kinds/propose", buildJsonObject { put("goal", "a made-up bakery site") }.toString()).contains("choices"))
        assertEquals("website", Kinds.planKind(api.feature("POST", "/api/kinds/set", Kinds.setKindBody(project, "website")))?.id)
        val rate = Pounds.parse(api.feature("GET", "/api/rates"))
        assertEquals("≈ £0.80", Pounds.beside(1.0, rate))
        assertTrue(Kinds.parseGallery(api.feature("GET", Kinds.galleryPath())).entries.isEmpty())
        val tile = Kinds.parseGallery(api.feature("GET", Kinds.galleryPath(hidden = true))).entries.single()
        val entry = Kinds.parseEntry(api.feature("GET", Kinds.entryPath(tile.project, tile.goal)))
        assertEquals("Website", entry?.kindName)
        api.feature("POST", "/api/gallery/star", Kinds.flagBody(tile.project, tile.goal, "starred", true))
        api.feature("POST", "/api/gallery/hide", Kinds.flagBody(tile.project, tile.goal, "hidden", false))
        assertTrue(api.feature("POST", "/api/gallery/again", Kinds.flagBody(tile.project, tile.goal, "starred", false)).contains("wizard"))
        val rw = ApiRewind(api, project)
        assertTrue(rw.history().rows.any { it.id == "T1" })
        val pre = rw.preview("T1", "undo_task")
        assertTrue(pre.stamp.isNotBlank() && pre.files.isNotEmpty())
        assertTrue(rw.apply("T1", "undo_task", pre.stamp).ok)
        assertTrue(rw.putBack().ok)
        assertTrue(rw.fork("T1", "made-up-another-way").ok)
        assertTrue(Proof.parse(api.feature("GET", Proof.url(project, "T1")))!!.found)
        assertTrue(api.feature("GET", "/api/proof/list?path=$project").contains("items"))
        assertTrue(api.feature("GET", "/api/terminal/task?path=$project&task=T1&since=0").contains("words"))
        assertTrue(api.feature("POST", "/api/terminal/task/stop", buildJsonObject { put("path", project); put("task", "T1") }.toString()).contains("words"))
        // wave 5: the done list with its evidence, and the plan's stages
        val done = DoneList.parse(api.feature("GET", DoneList.url(project)))
        assertNotNull(done)
        assertTrue(done!!.words.isNotBlank())
        assertEquals("D1", DoneList.parseEvidence(api.feature("GET", DoneList.evidenceUrl(project, "D1")))?.item)
        assertNotNull(Stages.parse(api.feature("GET", Stages.url(project))))

        synchronized(problems) { assertTrue(problems.joinToString("\n"), problems.isEmpty()) }
        val missed = calls.map { it.name }.filter { it !in served }
        assertTrue("calls.json lists calls this test doesn't make: $missed", missed.isEmpty())
    }

    @Test
    fun `an unlisted call is caught`() = runBlocking {
        try { api().feature("GET", "/api/rewind/never-listed") } catch (_: ApiException) {}
        assertTrue(problems.single().contains("/api/rewind/never-listed"))
    }

    @Test
    fun `the questions decode with their options`() {
        val asks = Asks.parse(fixture("asks"))
        assertTrue(asks.first { it.id == "approve" }.options.any { it.id == "approve" })
    }
}
