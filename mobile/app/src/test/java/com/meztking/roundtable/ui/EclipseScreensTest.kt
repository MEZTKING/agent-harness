package com.meztking.roundtable.ui

import android.content.Context
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.TripOrigin
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.BuildConfig
import com.meztking.roundtable.Brand
import com.meztking.roundtable.R
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.Look
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.ui.adaptive.AdaptiveShell
import com.meztking.roundtable.ui.adaptive.LocalShellPlan
import com.meztking.roundtable.ui.adaptive.ShellPlace
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import com.meztking.roundtable.ui.theme.paletteFor
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Darkness Harness's phone look, Eclipse: the Ring on the Table and the Look choice, in the three looks (Eclipse,
 * Pitch, Ash) at text size 130%, on a phone (390 dp) and a tablet (840 dp). With -Pscreenshots each is saved under
 * app/build/screenshots as eclipse-*.png. Also: the app is still the same app underneath (it updates in place and
 * stays paired).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-xhdpi", application = android.app.Application::class)
class EclipseScreensTest {
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

    // -- the same app underneath ------------------------------------------------------------------------------

    @Test fun theAppIsStillTheSameAppUnderneath() {
        // the id Android knows the app by never changes: 1.0.0 installs over 0.12.0 and keeps its pairing
        assertEquals("com.meztking.roundtable", BuildConfig.APPLICATION_ID.removeSuffix(".debug"))
        val gradle = File("build.gradle.kts").takeIf { it.exists() } ?: File("app/build.gradle.kts")
        val text = gradle.readText()
        assertTrue("applicationId in build.gradle.kts", "applicationId = \"com.meztking.roundtable\"" in text)
        assertTrue("namespace in build.gradle.kts", "namespace = \"com.meztking.roundtable\"" in text)
        // only the name the owner reads changed
        assertEquals("Darkness", ctx.getString(R.string.app_name))
        assertEquals(Brand.SHORT, ctx.getString(R.string.app_name))
        assertEquals("Darkness Harness", Brand.NAME)
    }

    // -- the looks ---------------------------------------------------------------------------------------------

    @Test fun eclipseIsTheUsualLookWhateverThePhoneSays() {
        rule.setContent { RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) {} } }
        rule.waitForIdle()
        assertSame(paletteFor(Look.ECLIPSE), Hall.palette)
    }

    @Test fun ashOnlyWhenChosen() {
        comfort.pickLook(Look.ASH)
        rule.setContent { RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) {} } }
        rule.waitForIdle()
        assertSame(paletteFor(Look.ASH), Hall.palette)
    }

    // -- the pictures ------------------------------------------------------------------------------------------

    private val seats = listOf(
        SeatView("lantern-app", "running", "running · T5 of 9", "A made-up lantern app", lastActivity = ago(0), progress = Progress(5, 9), openTodos = 3),
        SeatView("quill-notes", "waiting", "1 high-priority to-do", "Notes with a quill", lastActivity = ago(3), openTodos = 4, high = 1, hasPlan = true),
        SeatView("stone-bridge", "idle", "idle · 2 days ago", lastActivity = ago(50), openTodos = 1),
        SeatView("ember-forge", "done", "done · 6 of 6", progress = Progress(6, 6), lastActivity = ago(20)),
        SeatView("kite-shop", "running", "running · T2 of 4", progress = Progress(2, 4), lastActivity = ago(1)),
        SeatView("old-sketch", "idle", "idle · 3 weeks ago", lastActivity = ago(500)),
    )
    private val needs = listOf(
        NeedView("run:x", "run", "quill-notes", "Plan waits for your seal", "plan ready: 7 tasks, about \$0.85", listOf("approve")),
        NeedView("todo:a", "todo", "quill-notes", "To do: Check the Windows build", "quill-notes · high priority · from the journal"),
    )
    private val hall = HallState(seats, needs)

    private fun shot(name: String, look: Look, content: @Composable () -> Unit) {
        comfort.pickLook(look); comfort.pickTextScale(1.3f)
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/eclipse-$name-${look.name.lowercase()}.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    @Composable
    private fun table(beside: Boolean = false) {
        TableScreen(Load(hall), Mode.HUB, "Hub on GitHub · example/hub", emptySet(), {}, {}, { _, _ -> }, {}, false, {},
            onNotes = {}, onSearch = {}, onNewIdea = {}, onGallery = {}, needsBeside = beside)
    }

    @Composable
    private fun shell() {
        AdaptiveShell(listOf(ShellPlace("Table", Icons.Filled.TripOrigin, needs.size), ShellPlace("Chat", Icons.AutoMirrored.Filled.Chat, 2),
            ShellPlace("Settings", Icons.Filled.Settings)), selected = 0, onSelect = {},
            beside = { NeedsList(needs, Mode.HUB, emptySet(), { _, _ -> }, {}, Modifier.padding(16.dp)) }) {
            table(beside = LocalShellPlan.current.twoPanes)
        }
    }

    @Test fun tableEclipse() = shot("table-390", Look.ECLIPSE) { table() }
    @Test fun tablePitch() = shot("table-390", Look.PITCH) { table() }
    @Test fun tableAsh() = shot("table-390", Look.ASH) { table() }

    @Config(qualifiers = "w840dp-h1000dp-xhdpi")
    @Test fun shellEclipse() = shot("shell-840", Look.ECLIPSE) { shell() }
    @Config(qualifiers = "w840dp-h1000dp-xhdpi")
    @Test fun shellPitch() = shot("shell-840", Look.PITCH) { shell() }
    @Config(qualifiers = "w840dp-h1000dp-xhdpi")
    @Test fun shellAsh() = shot("shell-840", Look.ASH) { shell() }

    @Test fun comfortEclipse() = shot("comfort-390", Look.ECLIPSE) { ComfortScreen(comfort, onBack = {}) }
    @Test fun comfortAsh() = shot("comfort-390", Look.ASH) { ComfortScreen(comfort, onBack = {}) }

    @Test fun theRingSaysWhatNeedsYouInWords() {
        comfort.pickTextScale(1.3f)
        rule.setContent { RoundtableTheme { table() } }
        rule.onNodeWithText("need you").assertExists()
        rule.onNodeWithContentDescription("2 things need you. Open the list.").assertExists()
        // the one that needs the owner is named, not only lit
        rule.onNodeWithContentDescription("quill-notes, 1 high-priority to-do, waiting: ", substring = true).assertExists()
        rule.onNodeWithText(Brand.NAME).assertExists()
    }
}
