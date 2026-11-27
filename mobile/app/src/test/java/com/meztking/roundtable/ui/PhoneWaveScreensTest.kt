package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Failure
import com.meztking.roundtable.data.FailureAction
import com.meztking.roundtable.data.PhoneProjects
import com.meztking.roundtable.runtime.UpdateNotice
import com.meztking.roundtable.ui.browser.BrowserScreen
import com.meztking.roundtable.data.browser.BrowserConnection
import com.meztking.roundtable.ui.theme.RoundtableTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Wave 8's phone pieces on screen: going back, a named failure's button, projects, the browser's plain words. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class PhoneWaveScreensTest {
    @get:Rule val rule = createComposeRule()

    @Test fun anUpdateThatWentBackSaysSoWithOneButton() {
        var tried = 0
        rule.setContent { RoundtableTheme { RuntimeUpdate(null, busy = false, onCheck = {}, onUpdate = {},
            notice = UpdateNotice("0.9.1", "0.9.0").plain(), onTryAgain = { tried++ }) } }
        rule.onNodeWithText(UpdateNotice("0.9.1", "0.9.0").plain()).assertIsDisplayed()
        rule.onNodeWithText("Try the new one again").performClick()
        assertEquals(1, tried)
    }

    @Test fun aNamedFailureHasItsOwnButton() {
        var asked: FailureAction? = null
        var retried = 0
        rule.setContent {
            RoundtableTheme {
                androidx.compose.runtime.CompositionLocalProvider(LocalFailureActions provides { a -> asked = a; true }) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        ErrorLine(Failure.NOT_PAIRED.sentence) { retried++ }
                        ErrorLine(Failure.OFFLINE.sentence) { retried++ }
                    }
                }
            }
        }
        rule.onNodeWithText("Pair again").performClick()
        assertEquals(FailureAction.PAIR_AGAIN, asked)
        rule.onNodeWithText("Try again").performClick()
        assertEquals(1, retried)
    }

    @Test fun projectsWaitForTheHarness() {
        rule.setContent { RoundtableTheme { PhoneProjectsCard(PhoneProjects { _, _, _ -> "{}" }, { listOf("tiny-game") }, running = false) } }
        rule.onNodeWithText("Start the harness on this phone to add or share projects.").assertIsDisplayed()
    }

    @Test fun projectsCardOffersCloneImportAndShare() {
        rule.setContent { RoundtableTheme { PhoneProjectsCard(PhoneProjects { _, _, _ -> "{}" }, { listOf("tiny-game") }, running = true) } }
        rule.onNodeWithText("Import a zip").assertIsDisplayed()
        rule.onNodeWithText("Import a folder").assertIsDisplayed()
        rule.onNodeWithText("tiny-game").assertIsDisplayed()
    }

    @Test fun thePcsLocalhostIsSaidPlainly() {
        rule.setContent { RoundtableTheme { BrowserScreen("localhost:5173", BrowserConnection.Pc("192.168.1.20", 8766), emptyList(), onBack = {}) } }
        rule.onNodeWithText("Try http://192.168.1.20:5173/").assertIsDisplayed()
    }
}
