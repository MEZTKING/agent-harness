package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/** The phone's part B, without a screen: the words as written, / commands, Talk, the new-project cards, previews. */
class PhonePartBTest {
    private val G = StreamText.GEN

    @Test fun wordsAddUpAndANewConversationStartsAgain() {
        var s = StreamText()
        s = s.plus(StreamRead(text = "Making the ", thinking = "the menu first", at = G + 11, done = false))
        s = s.plus(StreamRead(text = "menu page. ", at = G + 22, done = false))
        assertEquals("Making the menu page. ", s.text)
        assertEquals("the menu first", s.thinking)
        assertEquals(G + 22, s.at)
        // the checker starts: a newer conversation (gen 2) begins again from its start
        s = s.plus(StreamRead(text = "Looks right.", at = 2 * G + 12, done = true))
        assertEquals("Looks right.", s.text)
        assertEquals("", s.thinking)
        assertTrue(s.done)
    }

    @Test fun wordsKeepOnlyTheNewestPartAndSaySo() {
        val s = StreamText().plus(StreamRead(text = "x".repeat(StreamText.KEEP + 50), at = G + 1, skipped = 10))
        assertEquals(StreamText.KEEP, s.text.length)
        assertTrue(s.cut)
    }

    @Test fun readsComeSoonerWhileWordsCome() {
        assertEquals(1_200L, Stream.pauseMs(StreamRead(text = "a ", done = false), 0))
        assertEquals(6_000L, Stream.pauseMs(StreamRead(done = false), 20))
        assertEquals(0L, Stream.pauseMs(StreamRead(done = true), 0))
    }

    private val cmds = listOf(
        SlashCommand("run", "Build: carry on", confirm = true),
        SlashCommand("retry", "Try a task again", "[task id]"),
        SlashCommand("stop", "Stop what a task is running"),
        SlashCommand("accessible-forms", "Use the skill", "[anything]", kind = "skill"),
        SlashCommand("test", "Run the tests", pc_only = true),
    )

    @Test fun theMenuFollowsWhatIsTyped() {
        assertEquals(listOf("run", "retry", "stop", "test", "accessible-forms"), Slash.menu("/", cmds).map { it.name })
        assertEquals(listOf("run", "retry"), Slash.menu("/r", cmds).map { it.name })
        assertTrue(Slash.menu("/retry T2", cmds).isEmpty())
        assertTrue(Slash.menu("hello", cmds).isEmpty())
        assertEquals("/retry ", Slash.pick(cmds[1]))
        assertEquals("/stop", Slash.pick(cmds[2]))
    }

    @Test fun pcOnlyCommandsAreLeftOffThePhone() {
        val json = """{"commands": [{"name": "run", "confirm": true}, {"name": "test", "pc_only": true}]}"""
        assertEquals(listOf("run"), Slash.parse(json).map { it.name })
    }

    @Test fun aSpokenCommandIsFoundAndOnlyOneWithoutConfirmMayStartBySaying() {
        assertEquals("/retry T2", Talk.commandFrom("Slash retry t2", cmds))
        assertEquals("/accessible-forms on the sign-up page", Talk.commandFrom("command accessible forms on the sign-up page", cmds))
        assertNull(Talk.commandFrom("retry the second task", cmds))
        assertFalse(Talk.mayStartBySaying(Talk.commandOf("/run", cmds)))
        assertTrue(Talk.mayStartBySaying(Talk.commandOf("/stop", cmds)))
        assertTrue(Talk.isYes("Yes."))
        assertFalse(Talk.isYes("yes but later"))
        val spoken = Talk.forSpeaking("**It works.** Some code.\n```\nx = 1\n```")
        assertTrue(spoken, spoken.startsWith("It works.") && "x = 1" !in spoken && "**" !in spoken)
    }

    @Test fun theWizardSendsEveryAnswerWithTheIdeaFromTheBox() {
        val asks = listOf(
            Ask("kind", "wizard", header = "Make", options = listOf(AskOption("web-app", "Web app"), AskOption("game", "Game", disabled = true))),
            Ask("idea", "wizard", header = "Idea"),
            Ask("like", "wizard", header = "Like this", options = listOf(AskOption("no", "No"))),
        )
        var f = WizardFlow.of(asks)
        f = f.answer("kind", AskReply(listOf("web-app")))
        assertEquals("idea", f.current?.id)
        f = f.answer("like", AskReply(emptyList(), "https://example.org/a-shop\n\nA made-up cafe"))
        assertTrue(f.done)
        val body = f.body("a kite shop").toString()
        assertTrue(body, body.contains("\"kind\":{\"chosen\":[\"web-app\"],\"other\":\"\"}"))
        assertTrue(body, body.contains("\"idea\":{\"chosen\":[],\"other\":\"a kite shop\"}"))
        assertEquals("Web app", f.said("kind"))
        assertEquals(listOf("https://example.org/a-shop", "A made-up cafe"), WizardFlow.likes(f.answers["like"]!!.other))
        assertEquals("kind", f.back().back().back().current?.id)
    }

    @Test fun aTimerSaysWhatHappensWhenItRunsOut() {
        val utc = ZoneId.of("UTC")
        val a = Ask("q1", "question", expires_at = "2026-11-28T14:05:00Z", on_expire = "recommended")
        assertEquals("If nobody answers by 14:05, it takes the recommended answer.", Asks.timerLine(a, utc))
        assertEquals("The clock is stopped while you write.", Asks.timerLine(a.copy(held = true), utc))
        assertEquals("The time ran out at 14:05: it took the recommended answer (Blue). You can still change it.",
            Asks.timerLine(a.copy(timed_out = AskTimedOut("2026-11-28T14:05:00Z", "recommended", "Blue")), utc))
        assertEquals("", Asks.timerLine(a.copy(kind = "command"), utc))
        assertEquals("", Asks.timerLine(Ask("q2"), utc))
    }

    @Test fun aNotebookAndAnArchiveAreRead() {
        val nb = Preview.parse("""{"file": "a.ipynb", "name": "a.ipynb", "preview": "notebook", "language": "python",
            "cells": [{"type": "markdown", "source": "# Sums"}, {"type": "code", "source": "1 + 1", "count": 1,
            "outputs": [{"kind": "text", "text": "2"}]}]}""")
        assertEquals(2, nb.cells.size)
        assertEquals("2", nb.cells[1].outputs.single().text)
        val zip = Preview.parse("""{"preview": "archive", "format": "zip", "count": 3, "total": 2048, "unsafe": 1,
            "entries": [{"name": "a/", "folder": true}, {"name": "a/b.txt", "size": 2048}, {"name": "../evil", "unsafe": true}]}""")
        assertEquals("3 items, 2.0 KB in all. 1 would land outside the folder: never unpacked here.", Preview.archiveLine(zip))
        val broken = Preview.parse("""{"preview": "archive", "failed": true, "words": "This archive can't be read ([Errno 5] raw)."}""")
        assertFalse(broken.note.contains("Errno"))
        assertTrue(Preview.worthAsking("song.MP3") && Preview.worthAsking("x.tar.gz") && !Preview.worthAsking("main.kt"))
    }

    @Test fun findInFileListsTheLines() {
        val hits = FindInFile.hits("one\nTwo two\nthree\ntwo", "two")
        assertEquals(listOf(2, 4), hits.map { it.number })
        assertEquals(0, hits.first().start)
        assertEquals("Found on 2 lines.", FindInFile.countLine(hits, "two"))
        assertEquals("Not found in this file.", FindInFile.countLine(emptyList(), "x"))
    }

    @Test fun moneyAndUsageInPlainWords() {
        assertEquals("$0.0013", Money.usd(0.00132))
        assertEquals("$0.41", Money.usd(0.41))
        val v = UsageView(services = listOf(UsageService("a", used = UsageUsed(month_usd = 0.4)), UsageService("b", reached = "day")))
        assertEquals("$0.40 this month across 2 services. 1 reached a limit.", Team.usageLine(v))
    }

    @Test fun fencedCodeKeepsItsLanguage() {
        val md = Markdown.parse("```kotlin\nval x = 1\n```")
        assertEquals(Md.Code("val x = 1", "kotlin"), md.single())
    }
}
