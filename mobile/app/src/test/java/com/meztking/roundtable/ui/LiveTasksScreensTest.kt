package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.FileChange
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.SessionStep
import com.meztking.roundtable.data.SessionSummary
import com.meztking.roundtable.data.SessionTask
import com.meztking.roundtable.data.TaskContext
import com.meztking.roundtable.data.TaskTime
import com.meztking.roundtable.data.TimePart
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The Live tab with two tasks running at once (made-up project), and one older task without times. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class LiveTasksScreensTest {
    @org.junit.Before fun steadyCandles() {
        android.provider.Settings.Global.putFloat(org.robolectric.RuntimeEnvironment.getApplication().contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
    }

    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private fun part(key: String, ms: Long) = TimePart(key, com.meztking.roundtable.data.SessionLog.PARTS.toMap().getValue(key), ms)

    private val menu = SessionTask("T4", "Opening hours card", "coder", "running", 0.0029, steps = listOf(
        SessionStep("say", "I'll add a card with the week's opening hours."), SessionStep("tool", "● Write hours.html · +3 −0"),
        SessionStep("tool", "● Run `npm test` · passed"), SessionStep("say", "The tests pass. Making the hours read well on a phone.")),
        now = "The tests pass. Making the hours read well on a phone.",
        time = TaskTime(listOf(part("first", 5300), part("writing", 17000), part("tools", 14055), part("you", 84000))),
        context = TaskContext(11360, 128000, 0.089, "deepseek/deepseek-chat", 0.62),
        changes = listOf(FileChange("hours.html", 3, 0, true), FileChange("index.html", 2, 1)))
    private val map = SessionTask("T5", "Map of the shop", "designer", "running", 0.002, steps = listOf(
        SessionStep("say", "A small map with a pin on the shop."), SessionStep("tool", "● Write map.svg · +18 −0"), SessionStep("tool", "● Read style.css")),
        now = "Read style.css", time = TaskTime(listOf(part("first", 3100), part("writing", 9500), part("tools", 52))),
        context = TaskContext(9280, 128000, 0.072, "deepseek/deepseek-chat", 0.45), changes = listOf(FileChange("map.svg", 18, 0, true)))

    private val two = LiveView(session = SessionSummary("bakery-site", "", map, listOf(menu, map)), from = "From your PC", running = true, progress = "T5 of 6")

    @Test fun twoTasksAtOnce() = shot("11-live-two-tasks") { LiveTab(Load(two), Mode.PC, {}) }

    @Config(qualifiers = "+night")
    @Test fun twoTasksAtOnceDark() = shot("11-live-two-tasks-dark") { LiveTab(Load(two), Mode.PC, {}) }

    @Test fun oneTaskWithTimes() = shot("11b-live-one-task") {
        LiveTab(Load(LiveView(session = SessionSummary("bakery-site", "", menu), from = "From your PC", running = true, progress = "T4 of 6")), Mode.PC, {})
    }

    @Test fun anOldTaskWithoutTimes() = shot("11c-live-old-task") {
        LiveTab(Load(LiveView(session = SessionSummary("bakery-site", "", SessionTask("T1", "Menu page", "coder", "done", 0.001, "done",
            listOf(SessionStep("tool", "● Edit menu.html · +4 −1")))))), Mode.HUB, {}, finished = true)
    }
}
