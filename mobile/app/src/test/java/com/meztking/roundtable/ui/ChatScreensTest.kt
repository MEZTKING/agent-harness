package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.CardButton
import com.meztking.roundtable.data.ChatCard
import com.meztking.roundtable.data.ChatFile
import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.ChatSummary
import com.meztking.roundtable.data.ChatWords
import com.meztking.roundtable.data.Piece
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.ui.theme.RoundtableTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** The phone's chat with made-up states: a project's answer and its card, the key form, the list, earlier letters. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-xhdpi", application = android.app.Application::class)
class ChatScreensTest {
    @get:Rule val rule = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/chat-$name.png") {
            RoundtableTheme(dark = true) { Box(Modifier.fillMaxSize()) { content() } }
        }
    }

    private val owner = ChatLine(id = "o1", at = "2026-11-28T10:00:00.000Z", who = "owner", seat = "phone-me", text = "Build the five accepted ideas, at most \$2")
    private val card = ChatCard(id = "c1", title = "Build the accepted ideas", line = "About \$1.40, stops at \$2.00.", priceUsd = 1.4, capUsd = 2.0,
        command = "/build accepted at most \$2.00", buttons = listOf(CardButton("do", "Build", true), CardButton("not_now", "Not now")),
        more = "Sent to the computer that has the project as the command /build accepted at most \$2.00.")
    private val answer = ChatLine(id = "a1", at = "2026-11-28T10:00:02.000Z", who = "chat", seat = "phone-me", device = "This phone",
        text = "Five ideas are accepted. Building them costs about \$1.40.", thinking = "The board shows five accepted.", costUsd = 0.0009,
        model = "deepseek-v4-flash", answers = "o1", card = card)
    private val agents = ChatLine(id = "g1", at = "2026-11-28T09:00:00.000Z", who = "agent", seat = "pc", from = "lantern-app", to = "quill-notes",
        text = "The menu API moved to /v2.")

    @Test fun anAnswerShowsItsFootItsCardAndFoldsTheRest() {
        var tapped = ""
        rule.setContent { RoundtableTheme { ChatContent(ChatUiState(listOf(agents, owner, answer), seat = "phone-me"), onTap = { _, b, ok -> tapped = "$b:$ok" }) } }
        rule.onNodeWithText("Build the accepted ideas").assertIsDisplayed()
        rule.onNodeWithText("About \$1.40, stops at \$2.00.").assertIsDisplayed()
        rule.onNodeWithText("This phone · 0.1¢").assertIsDisplayed()
        // the model and the thinking are behind More; the agents' line is folded
        assertEquals(0, rule.onAllNodesWithText("Model: deepseek-v4-flash", substring = true).fetchSemanticsNodes().size)
        assertEquals(0, rule.onAllNodesWithText("The menu API moved to /v2.").fetchSemanticsNodes().size)
        rule.onNodeWithText("Build").performClick()
        assertEquals("do:false", tapped)
    }

    @Test fun somethingThatCantBeUndoneAsksBeforeTheTapGoes() {
        var tapped = ""
        val skip = card.copy(id = "c2", title = "Leave T3 out", line = "Free.", confirm = "This can't be undone. Are you sure?",
            buttons = listOf(CardButton("do", "Leave it out", true), CardButton("not_now", "Not now")))
        rule.setContent { RoundtableTheme { ChatCardView(skip, { b, ok -> tapped = "$b:$ok" }) } }
        rule.onNodeWithText("Leave it out").performClick()
        assertEquals("", tapped)
        rule.onNodeWithText("This can't be undone. Are you sure?").assertIsDisplayed()
        rule.onNodeWithText("Do it").performClick()
        assertEquals("do:true", tapped)
    }

    @Test fun aQueuedCardSaysWhoItWaitsFor() {
        val q = card.copy(state = "queued", queuedFor = "PC-Desk · last listened 3 h ago",
            buttons = listOf(ChatWords.button("here", true), ChatWords.button("cancel")))
        rule.setContent { RoundtableTheme { ChatCardView(q, { _, _ -> }) } }
        rule.onNodeWithText("Queued for PC-Desk · last listened 3 h ago").assertIsDisplayed()
        rule.onNodeWithText("Run it on This phone instead").assertIsDisplayed()
        rule.onNodeWithText("Cancel").assertIsDisplayed()
    }

    @Test fun nothingCanAnswerSaysSoWithAddAKey() {
        val waiting = owner.copy(state = "waiting")
        val app = ChatWords.cannot("no_machine", "ago" to "3 h ago", answers = "o1", seat = "phone-me")
        rule.setContent { RoundtableTheme { ChatContent(ChatUiState(listOf(waiting, app), seat = "phone-me")) } }
        rule.onNodeWithText("Waiting for your PC").assertIsDisplayed()
        rule.onNodeWithText("Add a DeepSeek key").assertIsDisplayed()
        rule.onNodeWithText("your PC last listened 3 h ago", substring = true).assertIsDisplayed()
    }

    @Test fun theKeyShowsOnlyItsLastFourAndCanBeRemoved() {
        var removed = false
        var saved: String? = null
        rule.setContent { RoundtableTheme { ChatKeyCard("x9Z2", onSave = { saved = it }, onRemove = { removed = true }, check = { "" }) } }
        rule.onNodeWithText("Saved: the key ending x9Z2.").assertIsDisplayed()
        rule.onNodeWithText("Paste a new key").performTextInput("sk-madeupkey000000000000")
        // the field hides what was pasted
        assertEquals(0, rule.onAllNodesWithText("sk-madeupkey000000000000", substring = true).fetchSemanticsNodes().size)
        rule.onNodeWithText("Save and check").performClick()
        rule.waitUntil(3000) { saved != null }
        assertEquals("sk-madeupkey000000000000", saved)
        rule.onNodeWithText("Remove key").performClick()
        assertTrue(removed)
    }

    @Test fun aRefusedKeyIsNotSaved() {
        var saved: String? = null
        rule.setContent { RoundtableTheme { ChatKeyCard(null, onSave = { saved = it }, onRemove = {}, check = { "key_refused" }) } }
        rule.onNodeWithText("Paste your DeepSeek key").performTextInput("sk-wrongwrongwrong0000")
        rule.onNodeWithText("Save and check").performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithText("DeepSeek refused that key", substring = true).fetchSemanticsNodes().isNotEmpty() }
        assertNull(saved)
    }

    @Test fun theListPutsHallFirst() {
        var opened = ""
        rule.setContent { RoundtableTheme { ChatListContent(listOf(ChatSummary("hall", "Hall", "Two projects are idle."),
            ChatSummary("lantern-app", "lantern-app", "Five ideas are ready.", waiting = 1)), onOpen = { opened = it.id }) } }
        rule.onNodeWithText("1 waiting").assertIsDisplayed()
        rule.onNodeWithText("Hall").performClick()
        assertEquals("hall", opened)
    }

    @Test fun earlierLettersAreFoldedAndReadOnly() {
        val ms = listOf(
            Message("m1", "me", "lantern-app", "request", "roundtable: run", "{\"action\": \"run\"}", "2026-11-20T10:00:00Z"),
            Message("m2", "lantern-app", "me", "notify", "Glow is done", "T1 finished.", "2026-11-20T11:00:00Z"),
            Message("m3", "quill-notes", "lantern-app", "notify", "API moved", "Use /v2.", "2026-11-20T12:00:00Z"),
        )
        val lines = Earlier.lines(ms, "me")
        assertEquals(listOf("command", "letter", "agent"), lines.map { it.kind })
        assertEquals("You asked it to build.", lines[0].text)
        assertEquals("quill-notes told lantern-app: API moved", lines[2].text)
        rule.setContent { RoundtableTheme { Column { EarlierMessages(lines) } } }
        rule.onNodeWithText("Earlier messages (3)").performClick()
        rule.onNodeWithText("You asked it to build.").assertIsDisplayed()
    }

    @Test fun piecesBuildTheAnswerAsItIsWritten() {
        var s = ChatUiState(seat = "phone-me")
        s = ChatThread.piece(s, Piece.Sent(owner, "o1"))
        s = ChatThread.piece(s, Piece.Words("Five "))
        s = ChatThread.piece(s, Piece.Thinking("board"))
        s = ChatThread.piece(s, Piece.Words("ideas"))
        assertEquals("Five ideas", s.writing); assertEquals("board", s.thinking); assertEquals("o1", s.turn)
        s = ChatThread.piece(s, Piece.Answer(answer))
        assertNull(s.writing); assertNull(s.turn)
        assertEquals(listOf("o1", "a1"), s.lines.map { it.id })
        // a model's link or picture is never drawn
        assertFalse(ChatThread.shown("![x](https://e.example/p.png) [y](https://e.example)").contains("https"))
        assertEquals("0.1¢", ChatThread.cost(0.0009))
        assertEquals("3¢", ChatThread.cost(0.03))
    }

    @Test fun theChatScreensUseNoRawErrorsOrRemotePictures() {
        val dir = File("src/main/java/com/meztking/roundtable/ui")
        for (n in listOf("ChatScreen.kt", "ChatCards.kt", "ChatKeyCard.kt")) {
            val src = File(dir, n).readText()
            assertFalse(n, Regex("\\b(e|it)\\.message\\b").containsMatchIn(src))
            assertFalse(n, src.contains("AsyncImage") || src.contains("MdBlocks") || src.contains("LinkAnnotation"))
            assertFalse(n, src.contains("rememberSaveable { mutableStateOf(\"\") }")) // no typed key in saved state
        }
    }

    @Test fun screenshots() {
        shot("answer") { ChatContent(ChatUiState(listOf(agents, owner, answer), seat = "phone-me")) }
        shot("waiting") { ChatContent(ChatUiState(listOf(owner.copy(state = "waiting", files = listOf(ChatFile("sketch.png", "ab", "png", 120000, "picture"))),
            ChatWords.cannot("no_machine", "ago" to "3 h ago", seat = "phone-me")), seat = "phone-me")) }
        shot("writing") { ChatContent(ChatUiState(listOf(owner), writing = "Five ideas are accepted and", thinking = "board", turn = "o1", seat = "phone-me")) }
        shot("key") { ChatKeyCard("x9Z2", {}, {}, { "" }) }
        shot("list") { ChatListContent(listOf(ChatSummary("hall", "Hall", "Two projects are idle."), ChatSummary("lantern-app", "lantern-app", "Ready.", waiting = 1)), {}, {}, "x9Z2") }
    }
}
