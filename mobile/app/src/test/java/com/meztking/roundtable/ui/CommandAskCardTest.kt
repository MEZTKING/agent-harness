package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskOption
import com.meztking.roundtable.data.AskTask
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Draws a command card ("Ask me first"), short and folded. With -Pscreenshots they're saved as PNGs. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class CommandAskCardTest {
    private fun card(command: String, folded: Boolean) = Ask(
        "command:1", "command", "lantern-app", header = "Command", question = "Task T3 “Add the timer” wants to run a command. Allow it?",
        detail = "Why it asks: It sends your code to GitHub or another server.",
        options = listOf(AskOption("allow", "Allow once", "It runs this time. Next time it asks again."),
            AskOption("always", "Always allow in this project", "It runs now, and “git push” runs without asking in this project from now on."),
            AskOption("deny", "Don't allow", "It doesn't run. The builder is told and carries on without it.")),
        other_hint = "Don't allow, and tell it what to do instead", stamp = "s",
        command = command, preview = command.lines().take(12).joinToString("\n"), folded = folded, lines = command.lines().size,
        task = AskTask("T3", "Add the timer"), remember = "“git push”", expires_at = "2026-11-27T10:30:00Z")

    private fun shot(name: String, ask: Ask) =
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { AskCard(ask, {}, Modifier.padding(16.dp)) } }
        }

    @Test fun shortCommand() = shot("command-card", card("git push origin roundtable/timer", folded = false))

    @Test fun longCommandFolded() = shot("command-card-folded", card((1..40).joinToString("\n") { "echo step $it" }, folded = true))
}
