package com.meztking.roundtable.ui

import android.content.Context
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.TripOrigin
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.Accent
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.data.Detail
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.SentItem
import com.meztking.roundtable.data.SessionStep
import com.meztking.roundtable.data.SessionSummary
import com.meztking.roundtable.data.SessionTask
import com.meztking.roundtable.data.TaskTime
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.ui.adaptive.AdaptiveShell
import com.meztking.roundtable.ui.adaptive.LocalShellPlan
import com.meztking.roundtable.ui.adaptive.ShellPlace
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Comfort on screen (made-up projects): the Comfort page, the Table with a pinned and a put-away project, the
 * project's sent history, Live at each detail level and the two-pane shell, at 390 dp and 840 dp, in dark and true
 * black, at text size 130%. With -Pscreenshots each is saved as a PNG under app/build/screenshots.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-xhdpi", application = android.app.Application::class)
class ComfortScreensTest {
    @get:Rule val rule = createComposeRule()
    private val ctx: Context get() = RuntimeEnvironment.getApplication()
    private val comfort: Comfort get() = Comfort.get(ctx)
    private fun ago(h: Long) = Instant.now().minus(h, ChronoUnit.HOURS).toString()

    @Before fun steady() {
        android.provider.Settings.Global.putFloat(ctx.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
        clean()
    }

    @After fun clean() {
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().clear().commit()
        Comfort.reset()
    }

    private fun shot(name: String, dark: Boolean = true, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/comfort-$name.png") {
            RoundtableTheme(dark = dark) { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private fun blackAndBig() { comfort.pickTrueBlack(true); comfort.pickTextScale(1.3f) }

    private val seats = listOf(
        SeatView("lantern-app", "running", "running · T5 of 9", "A made-up lantern app", lastActivity = ago(0), progress = Progress(5, 9), openTodos = 3),
        SeatView("quill-notes", "waiting", "1 high-priority to-do", "Notes with a quill", lastActivity = ago(3), openTodos = 4, high = 1, hasPlan = true),
        SeatView("stone-bridge", "idle", "idle · 2 days ago", lastActivity = ago(50), openTodos = 1),
        SeatView("ember-forge", "done", "done · 6 of 6", progress = Progress(6, 6), lastActivity = ago(20)),
        SeatView("old-sketch", "idle", "idle · 3 weeks ago", lastActivity = ago(500)),
    )
    private val needs = listOf(
        NeedView("run:x", "run", "lantern-app", "Plan waits for your seal", "plan ready: 7 tasks, about \$0.85", listOf("approve")),
        NeedView("todo:a", "todo", "quill-notes", "To do: Check the Windows build", "quill-notes · high priority · from the journal"),
    )
    private val hall = HallState(seats, needs)

    private fun pins() = TablePins(comfort.pinned, comfort.putAway, comfort::pin, comfort::putAwayProject)

    @Test fun comfortPage() = shot("1-page-dark") { ComfortScreen(comfort, onBack = {}, dark = true) }

    @Test fun comfortPageLight() = shot("1b-page-light", dark = false) {
        comfort.pickAccent(Accent.MOSS)
        ComfortScreen(comfort, onBack = {}, dark = false)
    }

    @Test fun comfortPageBlackAndBig() {
        blackAndBig(); comfort.pickAccent(Accent.SEA); comfort.pickDetail(Detail.COMPACT)
        shot("1c-page-black-130") { ComfortScreen(comfort, onBack = {}, dark = true) }
    }

    @Test fun tablePinnedAndPutAway() {
        comfort.pin("ember-forge", true); comfort.putAwayProject("old-sketch", true)
        shot("2-table-pinned") {
            TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins())
        }
    }

    @Test fun tableListPinnedBlackAndBig() {
        blackAndBig()
        val many = seats + (1..5).map { SeatView("sketch-$it", "idle", "idle") }
        comfort.pin("stone-bridge", true); comfort.putAwayProject("old-sketch", true)
        shot("2b-table-list-black-130") {
            TableScreen(Load(HallState(many, needs)), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins())
        }
    }

    /** The owner's screenshot (27 Nov): every header button on, big text – the title must stay on one line. */
    @Test fun tableHeaderAllButtonsBig() {
        blackAndBig()
        shot("2c-table-header-all-buttons-130") {
            TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins(),
                onNotes = {}, onSearch = {}, onNewIdea = {})
        }
    }

    @Composable
    private fun shell(content: @Composable () -> Unit) {
        AdaptiveShell(listOf(ShellPlace("Table", Icons.Filled.TripOrigin, needs.size), ShellPlace("Chat", Icons.AutoMirrored.Filled.Chat, 2),
            ShellPlace("Settings", Icons.Filled.Settings)), selected = 0, onSelect = {},
            beside = { NeedsList(needs, Mode.HUB, emptySet(), { _, _ -> }, {}, Modifier.padding(16.dp)) }) { content() }
    }

    @Test fun phoneShell() = shot("3-shell-390") {
        shell { TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins()) }
    }

    @Config(qualifiers = "w840dp-h1000dp-xhdpi")
    @Test fun tabletShellTwoPanes() = shot("4-shell-840-dark") {
        shell {
            val two = LocalShellPlan.current.twoPanes
            TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins(), needsBeside = two)
        }
    }

    @Config(qualifiers = "w840dp-h1000dp-xhdpi")
    @Test fun tabletShellBlackAndBig() {
        blackAndBig()
        shot("4b-shell-840-black-130") {
            shell {
                TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins(),
                    needsBeside = LocalShellPlan.current.twoPanes)
            }
        }
    }

    @Config(qualifiers = "w844dp-h390dp-xhdpi")
    @Test fun phoneOnItsSide() = shot("4c-shell-side") {
        shell { TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins()) }
    }

    private val letters = listOf(Message("20261125T110000000000Z-bbbbbb", "quill-notes", "me", "ask", "Export presets: which three first?",
        "Which three presets first?", ago(1)))

    private fun withHistory() {
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "Make the paper look a little warmer", at = ago(30)))
        comfort.remember("quill-notes", SentItem(SentItem.LETTER, "Paper, Slate and Vellum, please.", "Re: Export presets", at = ago(5)))
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "Keep the quill icon", at = ago(2)))
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "One more check on the small phone", at = ago(1)))
    }

    @Test fun projectSentHistory() {
        withHistory()
        shot("5-sent-history") {
            Column(Modifier.padding(16.dp)) { SentHistory(comfort.sent("quill-notes"), onResend = {}) }
        }
    }

    @Test fun projectChatBlackAndBig() {
        blackAndBig(); withHistory()
        shot("5b-project-chat-black-130") {
            ProjectScreen(ProjectUi("quill-notes", seats[1], Mode.HUB, "me", Load(), Load(), Load(letters)), ProjectActions(), initialTab = 2)
        }
    }

    private val live = LiveView(session = SessionSummary("lantern-app", ago(0), SessionTask("T5", "The glow", "coder", "running", 0.0021,
        now = "Editing glow.css", time = TaskTime(listOf(com.meztking.roundtable.data.TimePart("model", "Thinking", 42_000),
            com.meztking.roundtable.data.TimePart("tools", "Tools", 18_000)), 60_000),
        steps = listOf(SessionStep("say", "The glow lives in one variable."), SessionStep("tool", "● Edit glow.css · +3 −1"),
            SessionStep("tool", "● Run `npm test` · passed")))), from = "From your PC", running = true)

    @Test fun liveCompact() = shot("6-live-compact") { LiveTab(Load(live), Mode.PC, {}, detail = Detail.COMPACT) }
    @Test fun liveStandard() = shot("6b-live-standard") { LiveTab(Load(live), Mode.PC, {}, detail = Detail.STANDARD) }
    @Test fun liveDetailedBlackAndBig() {
        blackAndBig()
        shot("6c-live-detailed-black-130") { LiveTab(Load(live), Mode.PC, {}, detail = Detail.DETAILED) }
    }

    @Test fun settingsPanels() = shot("7-settings-panels") {
        Column(Modifier.padding(16.dp)) {
            ComfortEntry(comfort) {}
            androidx.compose.foundation.layout.Spacer(Modifier.padding(6.dp))
            BatteryPanel(BatteryChecklist.checks(unrestricted = false, notifications = true, dataSaverBlocks = false), onOpen = {})
        }
    }
}

/**
 * What the owner does with a finger: press and hold to pin, put away and bring back; to copy and send again.
 * At Robolectric's default screen size (a dialog never settles there under a fixed w390dp qualifier).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ComfortTouchTest {
    @get:Rule val rule = createComposeRule()
    private val ctx: Context get() = RuntimeEnvironment.getApplication()
    private val comfort: Comfort get() = Comfort.get(ctx)
    private fun ago(h: Long) = Instant.now().minus(h, ChronoUnit.HOURS).toString()

    @Before @After fun clean() {
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().clear().commit()
        Comfort.reset()
    }

    private val seats = listOf("lantern-app", "quill-notes", "stone-bridge", "ember-forge", "old-sketch").map { SeatView(it, "idle", "idle") }
    private val needs = listOf(NeedView("todo:a", "todo", "quill-notes", "To do: Check the Windows build", "from the journal"))
    private fun pins() = TablePins(comfort.pinned, comfort.putAway, comfort::pin, comfort::putAwayProject)

    private fun withHistory() {
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "Make the paper look a little warmer", at = ago(30)))
        comfort.remember("quill-notes", SentItem(SentItem.LETTER, "Paper, Slate and Vellum, please.", "Re: Export presets", at = ago(5)))
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "Keep the quill icon", at = ago(2)))
        comfort.remember("quill-notes", SentItem(SentItem.NOTE, "One more check on the small phone", at = ago(1)))
    }

    // what the owner does with a finger

    @Test fun pressAndHoldPinsAProject() {
        rule.setContent {
            RoundtableTheme(dark = true) {
                val many = seats + (1..5).map { SeatView("sketch-$it", "idle", "idle") }
                TableScreen(Load(HallState(many, needs)), Mode.HUB, "Hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {}, pins = pins())
            }
        }
        rule.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(androidx.compose.ui.test.hasText("stone-bridge"))
        rule.onNodeWithText("stone-bridge").performTouchInput { longClick() }
        rule.onNodeWithText("Pin to the top").performClick()
        assertEquals(setOf("stone-bridge"), comfort.pinned)
        rule.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(androidx.compose.ui.test.hasText("ember-forge"))
        rule.onNodeWithText("ember-forge").performTouchInput { longClick() }
        rule.onNodeWithText("Put away").performClick()
        assertTrue("ember-forge" in comfort.putAway)
        // it waits behind the fold, and comes back with one tap
        rule.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(androidx.compose.ui.test.hasText("Put away (1)"))
        rule.onNodeWithText("Put away (1)").performClick()
        rule.onNode(androidx.compose.ui.test.hasScrollAction()).performScrollToNode(androidx.compose.ui.test.hasText("Bring back"))
        // the needs peek floats over the list's bottom, so tap it the way a screen reader would
        rule.onNodeWithText("Bring back").performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)
        assertTrue(comfort.putAway.isEmpty())
    }

    @Test fun pressAndHoldSendsAgain() {
        withHistory()
        val resent = mutableListOf<SentItem>()
        rule.setContent { RoundtableTheme(dark = true) { SentHistory(comfort.sent("quill-notes"), onResend = { resent += it }) } }
        rule.onNodeWithText("What you sent from this phone (4)").performClick()
        rule.onNodeWithText("Keep the quill icon").performTouchInput { longClick() }
        rule.onNodeWithText("Edit and send again").performClick()
        rule.onNodeWithText("Send again").performClick()
        assertEquals("Keep the quill icon", resent.single().text)
        assertEquals(SentItem.NOTE, resent.single().kind)
    }

    @Test fun copyPutsItOnTheClipboard() {
        withHistory()
        rule.setContent { RoundtableTheme(dark = true) { SentHistory(comfort.sent("quill-notes"), onResend = null) } }
        rule.onNodeWithText("What you sent from this phone (4)").performClick()
        rule.onNodeWithText("Keep the quill icon").performTouchInput { longClick() }
        rule.onNodeWithText("Copy").performClick()
        val clip = ctx.getSystemService(android.content.ClipboardManager::class.java).primaryClip
        assertEquals("Keep the quill icon", clip?.getItemAt(0)?.text?.toString())
        // nowhere to send it from here: no "Edit and send again"
        rule.onNodeWithText("Keep the quill icon").performTouchInput { longClick() }
        assertEquals(0, rule.onAllNodes(androidx.compose.ui.test.hasText("Edit and send again")).fetchSemanticsNodes().size)
    }
}
