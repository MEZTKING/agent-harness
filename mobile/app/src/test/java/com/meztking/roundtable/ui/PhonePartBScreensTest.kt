package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskOption
import com.meztking.roundtable.data.Asks
import com.meztking.roundtable.data.FilePreview
import com.meztking.roundtable.data.FollowItem
import com.meztking.roundtable.data.FollowReply
import com.meztking.roundtable.data.Preview
import com.meztking.roundtable.data.QueueItem
import com.meztking.roundtable.data.QueueView
import com.meztking.roundtable.data.RecallAnswer
import com.meztking.roundtable.data.SlashCommand
import com.meztking.roundtable.data.SlashReply
import com.meztking.roundtable.data.StreamRead
import com.meztking.roundtable.data.StreamText
import com.meztking.roundtable.data.Team
import com.meztking.roundtable.data.WizardFlow
import com.meztking.roundtable.net.ChatMessage
import com.meztking.roundtable.ui.theme.RoundtableTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** Part B's screens on the phone, against made-up states and the PC's real answers (the conformance fixtures). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class PhonePartBScreensTest {
    @get:Rule val rule = createComposeRule()

    private fun fixture(name: String) = javaClass.getResource("/conformance/$name.json")!!.readText()

    @Test fun wordsShowAsTheyAreWrittenWithTheThinkingFolded() {
        val s = StreamText().plus(StreamRead(text = "Making the menu page now.", thinking = "first the prices", at = 1, done = false))
        rule.setContent { RoundtableTheme { StreamWordsView(s) } }
        rule.onNodeWithText("WORDS AS THEY ARE WRITTEN").assertIsDisplayed()
        rule.onNodeWithText("Making the menu page now.").assertIsDisplayed()
        rule.onAllNodesWithText("first the prices").assertCountEquals(0)
        rule.onNodeWithText("Its thinking (3 words)").performClick()
        rule.onNodeWithText("first the prices").assertIsDisplayed()
    }

    @Test fun theStreamIsReadUntilTheReplyIsDone() {
        val reads = ArrayDeque(listOf(StreamRead(text = "Hello ", at = 6, done = false), StreamRead(text = "there.", at = 12, done = true)))
        val asked = mutableListOf<Long>()
        rule.setContent { RoundtableTheme { StreamWords("T1", { since -> asked += since; reads.removeFirstOrNull() ?: StreamRead(at = since) }) } }
        rule.mainClock.advanceTimeBy(5_000)
        rule.waitForIdle()
        rule.onNodeWithText("Hello there.").assertIsDisplayed()
        rule.onNodeWithText("WHAT IT WROTE").assertIsDisplayed()
        assertEquals(listOf(0L, 6L), asked)
    }

    private val commands = listOf(SlashCommand("run", "Build: carry on with the plan's tasks", confirm = true),
        SlashCommand("retry", "Try a task again", "[task id]"))

    @Test fun typingASlashOpensTheCommands() {
        var text = ""
        rule.setContent { RoundtableTheme { ChatView(ChatUi(com.meztking.roundtable.ui.Load(emptyList()), commands, text = "/r"), onText = { text = it }) } }
        rule.onNodeWithText("COMMANDS").assertIsDisplayed()
        rule.onNodeWithText("Build: carry on with the plan's tasks · asks first").assertIsDisplayed()
        rule.onNodeWithText("/retry").performClick()
        assertEquals("/retry ", text)
        rule.onNodeWithText("Do it").assertIsDisplayed()
    }

    private class FakeChat(val reply: SlashReply) : ChatSource {
        val lines = mutableListOf<Pair<String, Boolean>>()
        override suspend fun messages() = listOf(ChatMessage("owner", "how is it going?", "a"), ChatMessage("orchestrator", "**Fine**, two tasks left.", "b"))
        override suspend fun commands() = listOf(SlashCommand("run", "Build", confirm = true))
        override suspend fun queue() = QueueView(listOf(QueueItem("q1", "", "make the logo bigger")), running = true)
        override suspend fun changeQueue(action: String, id: String, text: String?) = QueueView(reply = "Removed. No task will read it.")
        override suspend fun ask(text: String) = "ok"
        override suspend fun command(line: String, confirmed: Boolean): SlashReply { lines += line to confirmed; return if (confirmed) SlashReply("Building.") else reply }
        override suspend fun stream(task: String, since: Long) = StreamRead()
    }

    @Test fun aCommandThatSpendsAsksFirst() {
        val chat = FakeChat(SlashReply(confirm = "It spends about $0.41. Build it?", command = "/run"))
        rule.setContent { RoundtableTheme { ChatTab(chat) } }
        rule.waitForIdle()
        rule.onNodeWithText("Fine, two tasks left.", substring = true).assertIsDisplayed()
        rule.onNodeWithText("make the logo bigger").assertIsDisplayed()
        rule.onNodeWithText("Send it now").assertIsDisplayed()
        rule.onNodeWithText("Ask the planner, or type / for commands").performTextInput("/run")
        rule.onNodeWithText("Do it").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("It spends about $0.41. Build it?").assertIsDisplayed()
        rule.onAllNodesWithText("Do it")[1].performClick()
        rule.waitForIdle()
        assertEquals(listOf("/run" to false, "/run" to true), chat.lines)
        rule.onNodeWithText("Building.").assertIsDisplayed()
    }

    @Test fun theQueueCanBeChangedOrRemoved() {
        val done = mutableListOf<String>()
        rule.setContent { RoundtableTheme { QueueCard(QueueView(listOf(QueueItem("q1", "", "use blue")), running = false)) { a, _, _ -> done += a } } }
        rule.onNodeWithText("1 message waits for the next task").assertIsDisplayed()
        rule.onAllNodesWithText("Send it now").assertCountEquals(0)
        rule.onNodeWithText("Remove").performClick()
        assertEquals(listOf("remove"), done)
    }

    @Test fun aFollowUpShowsThePriceFirst() {
        val sent = mutableListOf<Boolean>()
        val src = object : FollowSource {
            override suspend fun earlier() = listOf(FollowItem(question = "why blue?", answer = "The brief asked for calm colours."))
            override suspend fun send(text: String, mode: String, confirmed: Boolean): FollowReply {
                sent += confirmed
                return if (confirmed) FollowReply(reply = "Asking the model that built T1.") else FollowReply(confirm = "Asking the model that built T1 costs about $0.00. Ask it?")
            }
        }
        rule.setContent { RoundtableTheme { FollowBox("T1", src) {} } }
        rule.waitForIdle()
        rule.onNodeWithText("The brief asked for calm colours.").assertIsDisplayed()
        rule.onNodeWithText("Ask about T1, or say what to change").performTextInput("why this font?")
        rule.onNodeWithText("Ask").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Asking the model that built T1 costs about $0.00. Ask it?").assertIsDisplayed()
        rule.onAllNodesWithText("Ask")[1].performClick()
        rule.waitForIdle()
        assertEquals(listOf(false, true), sent)
        rule.onNodeWithText("Asking the model that built T1.").assertIsDisplayed()
    }

    @Test fun theChecksTheBoardAndTheTeamReadTheirRealAnswers() {
        val board = Team.board(fixture("board"))
        val agents = Team.agents(fixture("agents"))
        val usage = Team.usage(fixture("usage"))
        val listening = Team.listening(fixture("listening"))
        rule.setContent { RoundtableTheme { Column {
            ChecksChipView(com.meztking.roundtable.data.CiView(state = "failing", words = "1 check failing",
                failing = listOf(com.meztking.roundtable.data.CiRun("tests"))))
            BoardFoldView(board); ListeningLine(listening); AgentsCard(agents); UsageCard(usage)
        } } }
        rule.onNodeWithText("1 check failing: tests").assertIsDisplayed()
        rule.onNodeWithText("The board · ${board.summary}").performClick()
        rule.onNodeWithText("T1 · hello module").assertIsDisplayed()
        rule.onNodeWithText(listening.words).assertIsDisplayed()
        rule.onNodeWithText("Maelin").assertIsDisplayed()
        rule.onNodeWithText("Who does which job is changed on your PC.").assertIsDisplayed()
        rule.onNodeWithText(Team.usageLine(usage)).assertIsDisplayed()
    }

    @Test fun askingYourDocumentsShowsThePriceFirst() {
        val price = com.meztking.roundtable.data.Recall.answer(fixture("recall_ask"))
        rule.setContent { RoundtableTheme { DocumentsView("what does the bakery sell?", null, price, null, false, null) } }
        rule.onNodeWithText("About $0.0011 to answer from 2 pieces.").assertIsDisplayed()
        rule.onNodeWithText("Ask it").assertIsDisplayed()
    }

    @Test fun theNewProjectCardsComeOneByOne() {
        val asks = Asks.parse(fixture("wizard_asks"))
        var f = WizardFlow.of(asks)
        val answered = mutableListOf<String>()
        rule.setContent { RoundtableTheme { WizardContent(f, null, onBack = {}, onAnswer = { a, _ -> answered += a.id }) { androidx.compose.material3.Text("THE BOX") } } }
        rule.onNodeWithText("What do you want to make?").assertIsDisplayed()
        rule.onNodeWithText("Web app").performClick()
        assertEquals(listOf("kind"), answered)
    }

    @Test fun aQuestionWithATimerSaysSo() {
        val a = Ask("q", "question", header = "Question", question = "Which colour?", options = listOf(AskOption("blue", "Blue")),
            expires_at = "2026-11-28T14:05:00Z", on_expire = "nothing")
        rule.setContent { RoundtableTheme { AskCard(a, {}) } }
        rule.onNodeWithText("it keeps waiting and nothing is done", substring = true).assertIsDisplayed()
    }

    @Test fun aNotebookAnArchiveAndAVideoArePreviewed() {
        var played = 0
        val nb = Preview.parse("""{"preview": "notebook", "language": "python", "cells": [{"type": "code", "source": "print(2)", "count": 3,
            "outputs": [{"kind": "text", "text": "2"}]}]}""")
        val zip = Preview.parse("""{"preview": "archive", "count": 1, "total": 10, "entries": [{"name": "../evil", "size": 10, "unsafe": true}], "unsafe": 1}""")
        val video = FilePreview(name = "clip.mp4", preview = "video", mime = "video/mp4")
        rule.setContent { RoundtableTheme { Column { PreviewBody(nb) {}; PreviewBody(zip) {}; PreviewBody(video) { played++ } } } }
        rule.onNodeWithText("[3]").assertIsDisplayed()
        rule.onNodeWithText("../evil  (outside the folder)").assertIsDisplayed()
        rule.onNodeWithText("Play").performClick()
        assertEquals(1, played)
    }

    @Test fun findInAFileShowsTheLines() {
        rule.setContent { RoundtableTheme { FindInFileBar("alpha\nbeta gamma\ngamma", "gamma") {} } }
        rule.onNodeWithText("Found on 2 lines.").assertIsDisplayed()
        rule.onNodeWithText("beta gamma").assertIsDisplayed()
    }

    @Test fun noRawErrorReachesTheNewScreens() {
        // every new screen's failures go through friendly(): a raw exception's words never show
        val words = friendly(java.io.IOException("java.net.SocketException: Broken pipe at okhttp3.internal"))
        assertTrue(words, "okhttp3" !in words && "Exception" !in words)
        val sources = File("src/main/java/com/meztking/roundtable/ui").listFiles()!!.filter {
            it.name in setOf("ChatTab.kt", "FollowBox.kt", "TeamViews.kt", "WizardScreen.kt", "PreviewViews.kt", "StreamWords.kt")
        }
        assertEquals(6, sources.size)
        val raw = Regex("\\b(e|it)\\.message\\b")
        for (f in sources) assertTrue(f.name, !raw.containsMatchIn(f.readText()))
    }
}
