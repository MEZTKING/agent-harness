package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.runtime.RuntimeFailure
import com.meztking.roundtable.runtime.RuntimeState
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The "This phone" pieces drawn with made-up states (-Pscreenshots saves them as PNGs). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class ThisPhoneScreensTest {
    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    @Test fun card() = shot("20-this-phone-card") {
        Column(Modifier.padding(16.dp)) { ThisPhoneCard(onSetUp = {}) }
    }

    @Test fun downloading() = shot("21-this-phone-downloading") {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            TestBadge()
            SetupSteps(RuntimeState.Downloading(120L shl 20, 250L shl 20), 0, 250L shl 20)
        }
    }

    @Test fun addKey() = shot("22-this-phone-key") {
        Column(Modifier.padding(16.dp)) { KeyForm(RuntimeViewModel.Ui(), {}, {}) }
    }

    @Test fun stepsFollowTheState() {
        assertEquals(0, setupStep(RuntimeState.Downloading(1, 2), 0))
        assertEquals(1, setupStep(RuntimeState.Verifying, 0))
        assertEquals(2, setupStep(RuntimeState.Unpacking(1, 9), 1))
        assertEquals(4, setupStep(RuntimeState.Running(TODO_RECORD, 8765), 3))
        // A failure stays on the step it happened in.
        assertEquals(2, setupStep(RuntimeState.Failed(RuntimeFailure.BadSignature, null), 2))
    }

    @Test fun plainWordsSayWhatToDoNext() {
        val all = listOf(RuntimeFailure.Network("x"), RuntimeFailure.BadSignature, RuntimeFailure.NoSpace(300L shl 20, 100L shl 20),
            RuntimeFailure.WrongChannel("test"), RuntimeFailure.StartFailed("x"), RuntimeFailure.AppTooOld("0.8.0"))
        for (f in all) assertTrue(f.plain(), f.plain().endsWith("."))
        assertTrue(RuntimeFailure.NoSpace(300L shl 20, 100L shl 20).plain().contains("300 MB"))
        assertTrue(strictMaker("OPPO"))
        assertFalse(strictMaker("Google"))
    }

    private companion object {
        val TODO_RECORD = com.meztking.roundtable.runtime.InstalledRecord(
            "r", 1, "arm64-v8a", "test", "0.7.3",
            com.meztking.roundtable.runtime.LayerRecord("b", "b", "0".repeat(64)),
            com.meztking.roundtable.runtime.LayerRecord("r", "r", "0".repeat(64)),
            "/opt/roundtable/venv/bin/roundtable", emptyList(), "/etc/resolv.conf",
        )
    }
}
