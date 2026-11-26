package com.meztking.roundtable.data

import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.ui.ConnInputs
import com.meztking.roundtable.ui.connectionRows
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** Several connections at once: merging seats and Needs you, routing commands, the connections' wording. */
class SyncTest {
    private val now = Instant.parse("2026-11-26T12:00:00Z")
    private val selves = Selves(phone = "pixel-phone", pc = "desk-pc")

    @Test fun theSameProjectSeenThreeWaysIsOneSeatFromTheMostDirect() {
        val hub = listOf(SeatView("lantern-app", "idle", "idle · 2 h ago", description = "A lantern", openTodos = 3), SeatView("tide-clock"))
        val pc = listOf(SeatView("lantern", "running", "running", hubName = "lantern-app", progress = Progress(2, 7), path = "C:/lab/lantern", holder = "pc"))
        val phone = listOf(SeatView("quill-notes", "idle", holder = "phone", path = "/workspaces/quill-notes"))
        val seats = Sync.mergeSeats(listOf(Source.HUB to hub, Source.PC to pc, Source.PHONE to phone), selves = selves)
        assertEquals(3, seats.size)
        val lantern = seats.first { it.id == "lantern" }
        assertEquals("pc", lantern.source)
        assertEquals(listOf("hub"), lantern.seenIn)
        assertEquals("A lantern", lantern.description) // filled in from the hub
        assertEquals(3, lantern.openTodos)
        assertEquals("on your PC", lantern.lives)
        assertEquals("Building T3 of 7 on your PC", lantern.building)
        assertEquals(lantern.building, lantern.statusText)
        assertEquals("on this phone", seats.first { it.id == "quill-notes" }.lives)
        assertEquals("in the cloud", seats.first { it.id == "tide-clock" }.lives)
    }

    @Test fun thisPhoneWinsOverThePcAndThePcOverTheHub() {
        val seats = Sync.mergeSeats(listOf(
            Source.HUB to listOf(SeatView("a", statusText = "from hub")),
            Source.PC to listOf(SeatView("a", statusText = "from pc")),
            Source.PHONE to listOf(SeatView("a", statusText = "from phone")),
        ))
        assertEquals(1, seats.size)
        assertEquals("from phone", seats[0].statusText)
        assertEquals(listOf("pc", "hub"), seats[0].seenIn)
    }

    @Test fun aClaimSaysWhichMachineBuilds() {
        val claims = Sync.claimsByProject(listOf(
            Claim("lantern-app", "desk-pc", "Desk PC", heartbeat = "2026-11-26T11:58:00Z"),
            Claim("tide-clock", "laptop", "Laptop", heartbeat = "2026-11-26T11:59:00Z"),
            Claim("old-one", "desk-pc", heartbeat = "2026-11-26T09:00:00Z"), // stale: forgotten
        ), now)
        assertEquals(setOf("lantern-app", "tide-clock"), claims.keys)
        val seats = Sync.mergeSeats(listOf(Source.HUB to listOf(
            SeatView("lantern-app", "running", progress = Progress(4, 9)), SeatView("tide-clock", "running"), SeatView("old-one", "running"),
        )), claims, selves)
        assertEquals("Building T5 of 9 on your PC", seats[0].building)
        assertEquals("on your PC", seats[0].lives)
        assertEquals("pc", seats[0].holder)
        assertEquals("Building on Laptop", seats[1].building)
        assertEquals("on Laptop", seats[1].lives)
        assertEquals("Building", seats[2].building)
    }

    @Test fun needsYouHasEachThingOnce() {
        val ask = Ask("answer:Q1", "question", "lantern-app", question = "Which colour?")
        val letter = Message("m1", "lantern-app", "me", subject = "Hi")
        val hub = listOf(askNeed("lantern-app", listOf(ask)), letterNeed(letter),
            NeedView("todo:lantern-app:t1", "todo", "lantern-app", "To do: a", id = "t1"))
        val pc = listOf(askNeed("lantern", listOf(ask.copy(project = "lantern"))), letterNeed(letter).copy(key = "pc:messages"),
            NeedView("pc:todo:lantern:t1", "todo", "lantern", "To do: a", id = "t1"),
            NeedView("pc:run:lantern", "run", "lantern", "A task failed", actions = listOf("retry", "skip")))
        val seats = listOf(SeatView("lantern", hubName = "lantern-app"))
        val needs = Sync.mergeNeeds(listOf(Source.HUB to hub, Source.PC to pc), seats)
        assertEquals(4, needs.size)
        assertTrue(needs.take(4).all { it.source == "pc" })
    }

    @Test fun aCommandGoesToTheMachineThatHasTheProject() {
        val seat = SeatView("lantern", source = "pc", holder = "pc")
        val all = setOf(Source.PHONE, Source.PC, Source.HUB)
        assertEquals(Route(Source.PC, true, Source.PC, "desk-pc"), Sync.route(seat, all, all, selves))
        // the PC is off: through the hub, addressed to it
        val r = Sync.route(seat, setOf(Source.PHONE, Source.HUB), all, selves)!!
        assertEquals(Source.HUB, r.via)
        assertFalse(r.direct)
        assertEquals("desk-pc", r.machine)
        assertEquals("Sent: your PC picks it up when it's on.", Sync.sentLine(r, selves))
        // no hub set up: this phone passes it on
        assertEquals(Source.PHONE, Sync.route(seat, setOf(Source.PHONE), setOf(Source.PHONE, Source.PC), selves)!!.via)
        assertNull(Sync.route(seat, emptySet(), setOf(Source.PC), selves))
        // a project on another machine, seen only through the hub
        val far = SeatView("tide", source = "hub", machine = "laptop", machineName = "Laptop")
        val rf = Sync.route(far, all, all, selves)!!
        assertEquals(Source.HUB, rf.via)
        assertEquals("Sent: Laptop picks it up when it's on.", Sync.sentLine(rf, selves))
    }

    @Test fun eachConnectionInPlainWords() {
        assertEquals("Your PC – connected on Wi-Fi", Sync.connectionLine(Source.PC, true, "", "192.168.1.20", now = now))
        assertEquals("Your PC – connected through Tailscale", Sync.connectionLine(Source.PC, true, "", "100.101.4.2", now = now))
        assertEquals("Your PC – off, last seen 2 h ago", Sync.connectionLine(Source.PC, false, "2026-11-26T10:00:00Z", "192.168.1.20", now = now))
        assertEquals("Hub – synced 1 min ago", Sync.connectionLine(Source.HUB, true, "2026-11-26T11:59:00Z", now = now))
        assertEquals("This phone – running", Sync.connectionLine(Source.PHONE, true, "", phoneState = "running", now = now))
        val rows = connectionRows(ConnInputs(
            phoneSet = true, phoneState = "running", phoneRunning = true,
            pcSet = true, pcName = "Desk PC", pc = ConnHealth(false, "2026-11-26T09:00:00Z", "can't reach your PC"), pcBeat = "2026-11-26T10:00:00Z",
            hubSet = false,
        ), now)
        assertEquals("This phone – running", rows[0].line)
        assertEquals("Your PC – off, last seen 2 h ago", rows[1].line) // the hub's heartbeat is newer than ours
        assertEquals("Hub – not set up", rows[2].line)
        assertFalse(rows[2].set)
    }

    @Test fun machinesAndClaimsFromEitherShape() {
        val a = Sync.parseMachines("""[{"seat":"desk-pc","name":"Desk PC","last_seen":"2026-11-26T11:00:00Z","version":"0.9","listening":true}]""")
        assertEquals("Desk PC", a.machines.single().name)
        assertTrue(a.machines.single().listening)
        val b = Sync.parseMachines("""{"machines":[{"id":"phone-1","machine_name":"Pixel"}],"claims":[{"project":"lantern","machine":"phone-1","machine_name":"Pixel","since":"x","heartbeat":"y"}]}""")
        assertEquals("phone-1", b.machines.single().seat)
        assertEquals("lantern", b.claims.single().project)
        assertEquals(SyncInfo(), Sync.parseMachines("not json"))
        assertEquals("lantern", Sync.claim(Sync.parseFile("""{"machine":"desk-pc"}""")!!, "lantern.json")!!.project)
    }

    @Test fun aSessionFromTheHub() {
        val jsonl = """
            {"kind":"task_started","at":"2026-11-26T11:00:00Z","task":"T2","title":"Old task","index":2,"total":7}
            {"kind":"task_done","task":"T2","status":"done"}
            {"kind":"task_started","at":"2026-11-26T11:10:00Z","task":"T3","title":"Dark mode","role":"coder","index":3,"total":7}
            {"kind":"turn","text":"The colours live in four variables."}
            {"kind":"tool","line":"Edit style.css · +3 −0"}
            {"type":"file_change","path":"style.css"}
            {"kind":"cost","usd":0.0012}
            {"kind":"review","verdict":"approved","text":"every check met"}
            not json
        """.trimIndent()
        val r = SessionLog.parse(jsonl, "lantern")!!
        val t = r.summary.task!!
        assertEquals("T3", t.id)
        assertEquals("Dark mode", t.title)
        assertEquals("running", t.status)
        assertTrue(r.running)
        assertEquals("T3 of 7", SessionLog.progressLine(r))
        assertEquals(listOf("say", "tool", "tool", "review"), t.steps.map { it.kind })
        assertEquals("● Edit style.css · +3 −0", t.steps[1].line)
        assertEquals("✓ Approved: every check met", t.steps[3].line)
        assertEquals(0.0012, t.cost, 1e-9)
        val done = SessionLog.parse(jsonl + "\n{\"kind\":\"task_done\",\"status\":\"done\",\"summary\":\"dark mode works\"}")!!
        assertFalse(done.running)
        assertEquals("done", done.summary.task!!.status)
        // the older one-task summary still reads
        val old = SessionLog.parseAny("""{"project":"x","task":{"id":"T1","title":"A","status":"done","steps":[{"kind":"say","line":"hi"}]}}""")!!
        assertEquals("T1", old.summary.task!!.id)
        assertNull(SessionLog.parseAny(""))
    }

    @Test fun sharedSettingsRoundTrip() {
        val yaml = """
            # written by Roundtable
            limits:
              max_real_usd_per_run: 2
              max_cost_usd: 5.5
            autopilot:
              on: false
              cap: 1.5
            default_profile: balanced
            profiles: [budget, balanced, quality]
            roles:
              coder: deepseek/deepseek-v4-flash
              reviewer:
                - openai/gpt-x
                - deepseek/deepseek-v4-flash
            updated_at: "2026-11-26T10:00:00Z"
            updated_by: desk-pc
        """.trimIndent()
        val s = SharedSettings.parseYaml(yaml)!!
        assertEquals(2.0, s.limits["max_real_usd_per_run"]!!, 0.0)
        assertEquals(1.5, s.autopilotCap!!, 0.0)
        assertEquals(listOf("budget", "balanced", "quality"), s.profiles)
        assertEquals("openai/gpt-x", s.roles.first { it.role == "reviewer" }.model)
        assertEquals("Checks each task", s.roles.first { it.role == "reviewer" }.label)
        assertEquals("desk-pc", s.updatedBy)
        val after = s.copy(limits = s.limits + ("max_attempts_per_task" to 4.0), autopilot = true, defaultProfile = "quality",
            roles = s.roles.map { if (it.role == "coder") it.copy(model = "anthropic/claude-x") else it })
        val c = SharedSettings.changes(s, after)
        assertEquals(JsonPrimitive(4L), c["limits"]!!.jsonObject["max_attempts_per_task"])
        assertEquals(JsonPrimitive(true), c["autopilot"]!!.jsonObject["on"])
        assertEquals(JsonPrimitive("quality"), c["default_profile"])
        assertEquals(setOf("coder"), c["roles"]!!.jsonObject.keys)
        assertTrue(SharedSettings.changes(s, s).isEmpty())
        // the same, as a machine's JSON
        val j = SharedSettings.parseJson("""{"settings":{"default_profile":"budget","autopilot":true,"roles":{"coder":"a/b"}}}""")!!
        assertTrue(j.autopilot)
        assertEquals("a/b", j.roles.single().model)
    }

    @Test fun projectSettingsFromTheApi() {
        val v = ProjectSettings.parse("""{"path":"/p","settings":[
            {"key":"test","value":"","source":"default","default":"","description":"The command that checks the app.","type":"text","choices":[]},
            {"key":"timeout","value":900,"source":"default","default":900,"description":"Seconds.","type":"int","choices":[]},
            {"key":"profile","value":"","source":"default","default":"","description":"Set of models.","type":"choice","choices":["","Budget","Quality"]},
            {"key":"rules_files","value":["CLAUDE.md","AGENTS.md"],"source":"default","type":"lines","choices":[]},
            {"key":"limits","value":{},"source":"default","type":"number-map","choices":[],"keys":["max_real_usd_per_run","max_attempts_per_task"]},
            {"key":"env","value":{"QT_QPA_PLATFORM":"offscreen"},"source":".harness/project.yaml","type":"map","choices":[]}
        ],"warnings":[],"errors":[]}""")
        assertEquals(6, v.items.size)
        assertEquals("Test command", v.items[0].label)
        val drafts = v.items.associate { it.key to ProjectSettings.draft(it) }.toMutableMap()
        assertEquals("CLAUDE.md\nAGENTS.md", drafts["rules_files"])
        assertEquals("QT_QPA_PLATFORM: offscreen", drafts["env"])
        assertTrue(ProjectSettings.changes(v, drafts).getOrThrow().isEmpty())
        drafts["test"] = "python -m pytest -q"
        drafts["timeout"] = "1200"
        drafts["profile"] = "Quality"
        drafts["limits"] = "max_real_usd_per_run: 2.5\nmax_attempts_per_task: 4"
        val c = ProjectSettings.changes(v, drafts).getOrThrow()
        assertEquals(JsonPrimitive("python -m pytest -q"), c["test"])
        assertEquals(JsonPrimitive(1200L), c["timeout"])
        assertEquals(JsonPrimitive(4L), (c["limits"] as JsonObject)["max_attempts_per_task"])
        drafts["timeout"] = "soon"
        assertTrue(ProjectSettings.changes(v, drafts).isFailure)
        assertEquals("the usual setting", v.items[0].sourceWords)
        assertEquals("set for this project", v.items[5].sourceWords)
    }

    @Test fun askMeFirstIsHandedToTheRuntime() {
        assertEquals(mapOf("ROUNDTABLE_ASK_FIRST" to "1"), com.meztking.roundtable.askFirstEnv("ask"))
        assertTrue(com.meztking.roundtable.askFirstEnv("run").isEmpty())
    }

    // -- MultiBackend with made-up connections -------------------------------------------------------------------

    private class Fake(val name: String, val seatsOut: List<SeatView>, val needsOut: List<NeedView> = emptyList(), var fail: Boolean = false,
                       override val seatId: String? = null) : Backend {
        val calls = mutableListOf<String>()
        override val mode = Mode.PC
        override val identity = "me"
        override suspend fun hall(): HallState { if (fail) throw java.io.IOException("$name is off"); return HallState(seatsOut, needsOut) }
        override suspend fun projects() = seatsOut.map { it.id }
        override suspend fun status(project: String) = StatusDoc()
        override suspend fun plan(seat: SeatView) = PlanView()
        override suspend fun inbox(project: String) = emptyList<Message>()
        override suspend fun letters() = emptyList<Message>()
        override suspend fun send(to: String, subject: String, body: String) { calls += "send $to" }
        override suspend fun reply(original: Message, body: String) {}
        override suspend fun markRead(messages: List<Message>) {}
        override suspend fun act(need: NeedView, action: String): String { calls += "act $action ${need.project}"; return "$name did it" }
        override suspend fun asks(seat: SeatView) = emptyList<Ask>()
        override suspend fun answer(ask: Ask, reply: AskReply): String { calls += "answer ${ask.project}"; return "$name answered" }
        override suspend fun command(project: String, action: String, fields: Map<String, Any?>): String {
            calls += "command $project $action ${fields.toSortedMap()}"; return "$name sent"
        }
        override suspend fun autopilot(): AutopilotState? = null
        override suspend fun setAutopilot(on: Boolean, until: String, cap: Double?) = ""
        override suspend fun live(seat: SeatView) = LiveView()
    }

    @Test fun theTableMergesEveryConnectionAndCommandsFindTheirMachine() = runBlocking {
        val pc = Fake("pc", listOf(SeatView("lantern", "waiting", holder = "pc", hubName = "lantern-app", hubAgent = "harness", path = "C:/lab/lantern")),
            listOf(NeedView("pc:run:lantern", "run", "lantern", "A task failed", actions = listOf("retry"), task = "T3", path = "C:/lab/lantern")),
            seatId = "desk-pc")
        val hub = Fake("hub", listOf(SeatView("lantern-app"), SeatView("tide-clock")))
        val phone = Fake("phone", listOf(SeatView("quill", holder = "phone")), seatId = "pixel")
        val m = MultiBackend(mapOf(Source.PC to pc, Source.HUB to hub, Source.PHONE to phone), "me", now = { now })
        val h = m.hall()
        assertEquals(listOf("lantern", "quill", "tide-clock").sorted(), h.seats.map { it.id }.sorted())
        assertEquals(setOf(Source.PC, Source.HUB, Source.PHONE), m.connected)
        // the PC answers: its own button goes straight to it
        assertEquals("pc did it", m.act(h.needs.single(), "retry"))
        // plan commands go through the hub, addressed to the PC and to the project's folder
        m.command("lantern", "revise", mapOf("text" to "x"))
        assertEquals("command harness revise {machine=desk-pc, project_folder=lantern, text=x}", hub.calls.last())

        // the PC goes off: its seat stays (from the hub), and its button goes through the hub to it
        pc.fail = true
        val h2 = m.hall()
        assertEquals(setOf(Source.HUB, Source.PHONE), m.connected)
        assertEquals("Your PC – off, last seen just now", Sync.connectionLine(Source.PC, m.health(Source.PC).ok, m.health(Source.PC).lastOk, now = now))
        assertNotNull(h2.seats.firstOrNull { it.id == "lantern-app" })
        val said = m.act(h.needs.single(), "retry")
        assertEquals("Sent: your PC picks it up when it's on.", said)
        assertEquals("command harness retry {machine=desk-pc, project_folder=lantern, task=T3}", hub.calls.last())
    }

    @Test fun withNothingAnsweringTheTableSaysWhy() {
        val m = MultiBackend(mapOf(Source.PC to Fake("pc", emptyList(), fail = true)), "me")
        val e = runCatching { runBlocking { m.hall() } }.exceptionOrNull()
        assertEquals("pc is off", e?.message)
    }
}
