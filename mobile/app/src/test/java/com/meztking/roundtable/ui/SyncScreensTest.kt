package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.Claim
import com.meztking.roundtable.data.ConnHealth
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.ProjectSettings
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.Selves
import com.meztking.roundtable.data.SessionLog
import com.meztking.roundtable.data.SharedSettings
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.data.Sync
import com.meztking.roundtable.net.HubLink
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Instant
import java.time.temporal.ChronoUnit

/** The phone and PC in step: the merged Table, Your computers, a session through the hub, and the settings screens (made-up data). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class SyncScreensTest {
    private fun ago(m: Long) = Instant.now().minus(m, ChronoUnit.MINUTES).toString()

    @org.junit.Before fun steadyCandles() {
        android.provider.Settings.Global.putFloat(org.robolectric.RuntimeEnvironment.getApplication().contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
    }

    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private val selves = Selves(phone = "pixel", pc = "desk-pc")
    private val seats = Sync.mergeSeats(listOf(
        Source.PHONE to listOf(SeatView("quill-notes", "idle", "idle · 20 min ago", "Notes with a quill", lastActivity = ago(20), holder = "phone", openTodos = 2)),
        Source.PC to listOf(
            SeatView("lantern-app", "running", "running", "A made-up lantern app", lastActivity = ago(1), progress = Progress(2, 7), holder = "pc", path = "C:/lab/lantern-app"),
            SeatView("stone-bridge", "waiting", "waiting · plan ready", lastActivity = ago(90), holder = "pc", hasPlan = true),
        ),
        Source.HUB to listOf(
            SeatView("lantern-app", "idle", openTodos = 3),
            SeatView("tide-clock", "running", "running", "A tide clock", lastActivity = ago(4), progress = Progress(4, 9)),
            SeatView("ember-forge", "idle", "idle · 2 days ago", lastActivity = ago(3000)),
        ),
    ), Sync.claimsByProject(listOf(Claim("tide-clock", "laptop", "Laptop", heartbeat = ago(1)))), selves)

    @Test fun tableFromThreeSources() = shot("30-table-three-sources") {
        val needs = listOf(NeedView("run:x", "run", "stone-bridge", "Plan waits for your seal", "plan ready: 5 tasks, about \$0.60", listOf("approve"), source = "pc"))
        TableScreen(Load(HallState(com.meztking.roundtable.data.sortSeats(seats), needs)), Mode.PC, "This phone · Your PC · Hub", emptySet(),
            {}, {}, { _, _ -> }, {}, false, {})
    }

    @Test fun seatCardSaysWhereItLives() = shot("30b-seat-card-where") {
        Column(Modifier.padding(16.dp)) {
            SeatSummary(seats.first { it.id == "lantern-app" }, null) {}
            SeatSummary(seats.first { it.id == "tide-clock" }, null) {}
        }
    }

    @Test fun connections() = shot("31-your-computers") {
        val rows = connectionRows(ConnInputs(
            phoneSet = true, phoneState = "running", phoneRunning = true, phoneHub = HubLink("local"),
            pcSet = true, pcName = "Desk PC", pc = ConnHealth(true, ago(0)), pcHost = "192.168.1.20",
            hubSet = true, hubRepo = "example/hub", hub = ConnHealth(true, ago(1)),
        ))
        ConnectionsContent(rows, hubSet = true, phoneJoined = false, busy = null, onBack = {}) {}
    }

    @Test fun connectionsPcOff() = shot("31b-your-computers-pc-off") {
        val rows = connectionRows(ConnInputs(
            phoneSet = false, pcSet = true, pcName = "Desk PC", pc = ConnHealth(false, ago(130), "can't reach your PC. Is it on?"),
            hubSet = true, hubRepo = "example/hub", hub = ConnHealth(true, ago(1)),
        ))
        ConnectionsContent(rows, hubSet = true, phoneJoined = false, busy = null, onBack = {}) {}
    }

    private val jsonl = """
        {"kind":"task_started","at":"${ago(3)}","task":"T5","title":"The tide table","role":"coder","index":5,"total":9}
        {"kind":"turn","text":"The tides come from one small table, so the page reads it once and draws the week."}
        {"kind":"tool","line":"Read tides.json"}
        {"kind":"change","line":"Edit app.js · +24 −3"}
        {"kind":"tool","line":"Run `npm test` · failed (exit 1)","error":true}
        {"kind":"change","line":"Edit app.js · +2 −2"}
        {"kind":"tool","line":"Run `npm test` · passed"}
        {"kind":"cost","usd":0.0031}
    """.trimIndent()

    @Test fun sessionThroughTheHub() = shot("32-session-from-hub") {
        val r = SessionLog.parse(jsonl, "tide-clock")!!
        val live = LiveView(session = r.summary, from = "Through the hub", running = r.running, progress = SessionLog.progressLine(r))
        ProjectScreen(ProjectUi("tide-clock", seats.first { it.id == "tide-clock" }, Mode.HUB, "me", Load(StatusDoc()), Load(), Load(), live = Load(live)),
            ProjectActions(), initialTab = 3)
    }

    private val shared = SharedSettings.parseYaml("""
        limits:
          max_real_usd_per_run: 2
          max_cost_usd: 5
          max_attempts_per_task: 3
          max_steps_per_task: 40
        autopilot: {on: false, cap: 1.5}
        default_profile: balanced
        profiles: [budget, balanced, quality]
        roles:
          orchestrator: [anthropic/planner-model, deepseek/deepseek-v4-flash]
          coder: [deepseek/deepseek-v4-flash, anthropic/coder-model]
          critic: [openai/critic-model, deepseek/deepseek-v4-flash]
          reviewer: [openai/critic-model, deepseek/deepseek-v4-flash]
        updated_at: "${ago(45)}"
        updated_by: desk-pc
    """.trimIndent())!!

    @Test fun sharedSettings() = shot("33-shared-settings") {
        SharedSettingsContent(Load(shared), "Read from your PC", false, {}, {}, {})
    }

    @Config(qualifiers = "w400dp-h1600dp-xhdpi")
    @Test fun sharedSettingsWhole() = shot("33b-shared-settings-whole") {
        SharedSettingsContent(Load(shared), "Read through the hub", false, {}, {}, {})
    }

    @Config(qualifiers = "w400dp-h1600dp-xhdpi")
    @Test fun projectSettings() = shot("34-project-settings") {
        val v = ProjectSettings.parse("""{"path":"C:/lab/lantern-app","settings":[
            {"key":"test","value":"npm test","source":".harness/project.yaml","description":"The command that checks the app (e.g. python -m pytest tests -q). A task that makes a test fail that passed before is sent back.","type":"text","choices":[]},
            {"key":"timeout","value":900,"source":"default","description":"How many seconds the test or setup command may take.","type":"int","choices":[]},
            {"key":"profile","value":"","source":"default","description":"Which set of models builds it (e.g. Budget, Balanced, Quality). Empty: the app's own choice.","type":"choice","choices":["","Budget","Balanced","Quality"]},
            {"key":"limits","value":{"max_real_usd_per_run":2},"source":"roundtable.yaml","description":"Money and effort limits for this project only.","type":"number-map","choices":[],"keys":["max_real_usd_per_run","max_cost_usd","max_attempts_per_task","max_steps_per_task"]},
            {"key":"show_it","value":"auto","source":"default","description":"Take pictures of the app's screens after each task. auto: when it has screens Roundtable can open.","type":"choice","choices":["auto","on","off"]},
            {"key":"notes","value":"","source":"default","description":"Anything the planner should know about this project, in your own words.","type":"text","choices":[]}
        ],"warnings":[],"errors":[]}""")
        ProjectSettingsContent("lantern-app", Load(v), false, {}, {}, {})
    }

    @Test fun runtimeUpdate() = shot("35-runtime-update") {
        Column(Modifier.padding(16.dp)) {
            RuntimeUpdate(RuntimeCheck.Newer("0.9.4", 48_000_000), busy = false, onCheck = {}, onUpdate = {})
            RuntimeUpdate(RuntimeCheck.UpToDate("0.9.4"), busy = false, onCheck = {}, onUpdate = {})
        }
    }
}
