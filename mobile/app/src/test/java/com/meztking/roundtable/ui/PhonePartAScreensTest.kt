package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskOption
import com.meztking.roundtable.data.Documents
import com.meztking.roundtable.data.ProjectSettings
import com.meztking.roundtable.data.Sounds
import com.meztking.roundtable.data.TalkAction
import com.meztking.roundtable.data.Team
import com.meztking.roundtable.ui.theme.RoundtableTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Wave 9, Part A on the phone's screens: made-up cards and the PC's real answers (the conformance fixtures). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class PhonePartAScreensTest {
    @get:Rule val rule = createComposeRule()

    private fun fixture(name: String) = javaClass.getResource("/conformance/$name.json")!!.readText()

    private fun card(id: String, q: String, confirm: String? = null) = Ask(id, "decision", "Made-up kites", path = "/home/owner/lab/kites",
        question = q, stamp = "s-$id", recommended = "a", options = listOf(AskOption("a", "The usual", confirm = confirm), AskOption("b", "Other")))

    private val cards = listOf(card("q1", "Which colours?"), card("q2", "Build the shop now?", confirm = "This spends about $1.20."),
        card("q3", "Keep the menu short?"))

    @Test fun answerTheseSendsOnlyTheTickedOnesAndListsWhatWasLeft() {
        val sent = mutableListOf<List<Triple<String, String, String>>>()
        val alone = mutableListOf<String>()
        rule.setContent {
            RoundtableTheme {
                AnswerTheseBar(cards, send = { items -> sent += items
                    """{"answered": [{"id": "q1", "reply": "Saved."}], "left": [{"id": "q3", "why": "Something is running on this project: answer it once that finishes."}],
                       "reply": "1 answered with the recommended answer; 1 left for you to answer on their own."}""" },
                    onAlone = { alone += it.id })
            }
        }
        rule.onNodeWithText("3 questions wait. Tick the ones to answer with the recommended answer.").assertIsDisplayed()
        rule.onNodeWithText("Answer these").performClick()
        // the card that spends is greyed with its own way out; it can't be ticked
        rule.onNodeWithText("Its recommended answer spends money or can't be undone, so it's answered on its own.").assertIsDisplayed()
        rule.onNodeWithText("Answer this one by itself").performClick()
        assertEquals(listOf("q2"), alone)
        rule.onNodeWithText("Build the shop now?").performClick()  // a tap on the greyed one does nothing
        rule.onNodeWithText("Use the recommended answer for the ticked ones (2)").performClick()
        rule.waitForIdle()
        assertEquals(listOf(listOf(Triple("/home/owner/lab/kites", "q1", "s-q1"), Triple("/home/owner/lab/kites", "q3", "s-q3"))), sent)
        rule.onNodeWithText("1 answered with the recommended answer; 1 left for you to answer on their own.").assertIsDisplayed()
        rule.onNodeWithText("• Keep the menu short? · Something is running on this project: answer it once that finishes.").assertIsDisplayed()
    }

    @Test fun answerTheseDoesNotShowForTwoCards() {
        rule.setContent { RoundtableTheme { AnswerTheseBar(cards.take(2), send = { "{}" }) } }
        rule.onAllNodesWithText("Answer these").assertCountEquals(0)
    }

    @Test fun typingOnACardWithATimerAsksForAHold() {
        rule.mainClock.autoAdvance = false  // the countdown ticks every second
        val far = java.time.Instant.now().plusSeconds(1800).toString()
        val ask = card("q1", "Which colours?").copy(expires_at = far, on_expire = "recommended")
        var typed = 0
        rule.setContent { RoundtableTheme { AskCard(ask, {}, onTyping = { typed++ }) } }
        rule.mainClock.advanceTimeByFrame()
        rule.onNodeWithText("29 min left").assertIsDisplayed()
        rule.onNodeWithText("Other…").performClick()
        rule.mainClock.advanceTimeByFrame()
        rule.onNodeWithText(ask.other_hint).performTextInput("red")
        assertTrue(typed >= 1)
    }

    @Test fun aHoldIsSentAtMostOnceInTwentySecondsWhileTyping() {
        val holds = mutableListOf<String>()
        val help = object : CardHelp {
            override suspend fun hold(path: String, id: String) { holds += id }
            override suspend fun looks(path: String) = emptyMap<String, com.meztking.roundtable.data.LookPictures>()
        }
        rule.mainClock.autoAdvance = false
        val far = java.time.Instant.now().plusSeconds(1800).toString()
        val ask = card("q1", "Which colours?").copy(expires_at = far, on_expire = "recommended")
        rule.setContent { RoundtableTheme { AskCard(ask, {}, onTyping = rememberHold(help)?.let { h -> { h(ask) } }) } }
        rule.mainClock.advanceTimeByFrame()
        rule.onNodeWithText("Other…").performClick()
        rule.mainClock.advanceTimeByFrame()
        rule.onNodeWithText(ask.other_hint).performTextInput("red and blue")
        rule.mainClock.advanceTimeByFrame()
        rule.onNodeWithText("red and blue").performTextInput(" kites")
        rule.mainClock.advanceTimeByFrame()
        assertEquals(listOf("q1"), holds)
    }

    @Test fun theLooksPicturesShowTwoARowAndOnlyFromDataAddresses() {
        val png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
        rule.setContent { RoundtableTheme { Column { LookPictureGrid(listOf("A · Calm" to png, "B · Bright" to "https://example.invalid/b.png")) } } }
        rule.onNodeWithContentDescription("How A · Calm looks").assertIsDisplayed()
        rule.onAllNodesWithText("B · Bright").assertCountEquals(0)
        rule.onNodeWithText("A · Calm").performClick()
        rule.onNodeWithText("Close · A · Calm").assertIsDisplayed()
    }

    @Test fun aHireRefusedByThePcShowsItsSentence() {
        val v = Team.agents(fixture("agents"))
        val hired = mutableListOf<Pair<String, String>>()
        rule.setContent {
            RoundtableTheme { AgentsCard(v, onHire = { a, job -> hired += a.id to job }, hireSaid = "That can only be done on the PC itself.") }
        }
        rule.onAllNodesWithText("Give this job to…")[0].performClick()
        val who = Team.canTake(v, v.jobs.first().job).first()
        rule.onAllNodesWithText(who.name, substring = true)[0].performClick()
        assertEquals(listOf(who.id to v.jobs.first().job), hired)
        rule.onNodeWithText("That can only be done on the PC itself.").assertIsDisplayed()
    }

    @Test fun talksActionWaitsForATap() {
        var done = 0
        var not = 0
        rule.setContent { RoundtableTheme { TalkActionCard(TalkAction("/retry T1", "Try a task again"), onDo = { done++ }, onNot = { not++ }) } }
        rule.onNodeWithText("The planner suggests").assertIsDisplayed()
        rule.onNodeWithText("/retry T1").assertIsDisplayed()
        assertEquals(0, done)
        rule.onNodeWithText("Do it").performClick()
        assertEquals(1, done)
    }

    @Test fun documentsAreListedReadOnly() {
        val d = Documents.parse("""{"documents": [{"id": "d1", "name": "recipes.pdf", "kind_words": "PDF", "who": "All projects"}],
            "words": "1 document your agents can look up."}""")
        rule.setContent { RoundtableTheme { DocumentsListCard(d) } }
        rule.onNodeWithText("recipes.pdf").assertIsDisplayed()
        rule.onNodeWithText(Documents.ADD_ON_PC).assertIsDisplayed()
    }

    @Test fun theSoundsCardShowsWhatWasSpent() {
        val v = Sounds.parse("""{"sounds": [{"name": "Coin", "file": "assets/sounds/coin.mp3", "service": "ElevenLabs", "cost_usd": 0.08}],
            "spent_usd": 0.42, "cap_usd": 2}""")
        val played = mutableListOf<String>()
        rule.setContent { RoundtableTheme { SoundsCardView(v) { played += it.file } } }
        rule.onNodeWithText("1 sound · $0.42 of $2 used").assertIsDisplayed()
        rule.onNodeWithText("Play").performClick()
        assertEquals(listOf("assets/sounds/coin.mp3"), played)
    }

    @Test fun aProjectsSettingsLeadWithMoneyAndChecking() {
        val v = ProjectSettings.parse(fixture("project_settings"))
        rule.setContent { RoundtableTheme { ProjectSettingsContent("kites", Load(v), false, {}, {}, {}) } }
        rule.onNodeWithText("Money and effort limits").assertIsDisplayed()
        rule.onNodeWithText("How carefully it's checked").performScrollTo().assertIsDisplayed()
        rule.onAllNodesWithText("Test command").assertCountEquals(0)
        rule.onNodeWithText("More (${v.items.size - 2})").performScrollTo().performClick()
        rule.onNodeWithText("Test command").performScrollTo().assertIsDisplayed()
    }
}
