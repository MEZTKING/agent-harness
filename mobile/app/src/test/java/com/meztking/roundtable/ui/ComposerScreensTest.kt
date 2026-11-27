package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.Delivery
import com.meztking.roundtable.data.DraftFile
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The message box with made-up drafts (-Pscreenshots saves them as PNGs). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class ComposerScreensTest {
    private fun shot(name: String, dark: Boolean = true, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme(dark = dark) { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private val files = listOf(DraftFile("a", "sketch-of-the-shop.jpg", "image/jpeg", 312_000, "x"),
        DraftFile("b", "menu.txt", "text/plain", 1_400, "y"))

    @Test fun newIdea() = shot("40-new-idea") {
        NewIdeaContent(connected = true, notice = null, onBack = {}) {
            ComposerBox(ComposerUi(TextFieldValue("A small site for a bakery: the menu, opening hours and a map. Like my sketch."), files, saved = true),
                sendLabel = "Make the plan")
        }
    }

    @Test fun newIdeaLight() = shot("41-new-idea-light", dark = false) {
        NewIdeaContent(connected = true, notice = null, onBack = {}) {
            ComposerBox(ComposerUi(TextFieldValue("A small site for a bakery"), files.take(1), saved = true), sendLabel = "Make the plan")
        }
    }

    @Test fun noteWithAtAndNow() = shot("42-note-steer") {
        Column(Modifier.padding(16.dp)) {
            val t = "Make the prices in @src/me"
            ComposerBox(ComposerUi(TextFieldValue(t, TextRange(t.length)), emptyList(), Delivery.STEER, showDelivery = true,
                atFiles = listOf("src/menu.py", "src/menu_test.py")), sendLabel = "Tell the planner")
        }
    }

    @Test fun notConnected() = shot("43-new-idea-no-pc") {
        NewIdeaContent(connected = false, notice = null, onBack = {}) {}
    }
}
