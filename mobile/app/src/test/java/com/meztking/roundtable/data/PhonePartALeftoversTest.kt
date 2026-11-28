package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Wave 9, Part A: what the phone's Part B left (timers, Answer these, look pictures, documents, hiring, Talk, sounds, settings). */
class PhonePartALeftoversTest {
    private fun fixture(name: String) = javaClass.getResource("/conformance/$name.json")!!.readText()

    private fun card(id: String, confirm: String? = null, kind: String = "decision", stamp: String = "s-$id", rec: String? = "a",
                     path: String? = "/home/owner/lab/made-up-kites") =
        Ask(id, kind, "Made-up kites", path = path, question = "Question $id?", stamp = stamp, recommended = rec,
            options = listOf(AskOption("a", "The usual", confirm = confirm), AskOption("b", "Something else")))

    // -- timers -------------------------------------------------------------------------------------------------------
    @Test fun aHoldGoesAtMostOnceEveryTwentySecondsACard() {
        var now = 0L
        val t = HoldThrottle(now = { now })
        assertTrue(t.shouldSend("p#q1"))
        now = 5_000; assertFalse(t.shouldSend("p#q1"))
        assertTrue(t.shouldSend("p#q2"))  // another card has its own clock
        now = 19_999; assertFalse(t.shouldSend("p#q1"))
        now = 20_000; assertTrue(t.shouldSend("p#q1"))
        now = 30_000; assertFalse(t.shouldSend("p#q1"))
    }

    @Test fun theCountdownSaysWhatIsLeftAndNothingWithoutATimer() {
        val at = java.time.Instant.parse("2026-11-28T10:00:00Z").toEpochMilli()
        val a = card("q").copy(expires_at = "2026-11-28T10:04:05Z", on_expire = "recommended")
        assertEquals("4 min 05 s left", TimerHold.countdown(a, at))
        assertEquals("40 s left", TimerHold.countdown(a.copy(expires_at = "2026-11-28T10:00:40Z"), at))
        assertEquals("25 min left", TimerHold.countdown(a.copy(expires_at = "2026-11-28T10:25:00Z"), at))
        assertEquals("", TimerHold.countdown(a.copy(held = true), at))
        assertEquals("", TimerHold.countdown(a.copy(on_expire = ""), at))
        assertEquals("", TimerHold.countdown(a.copy(kind = "command"), at))
        assertTrue(TimerHold.holdable(a))
        assertFalse(TimerHold.holdable(a.copy(path = null)))
        assertFalse(TimerHold.holdable(card("q")))  // no timer: no hold is ever sent
    }

    // -- Answer these -------------------------------------------------------------------------------------------------
    @Test fun answerTheseNeverTicksACardThatSpendsDeletesOrAsksAlone() {
        val cards = listOf(card("q1"), card("q2", confirm = "This spends about $1.20 more."), card("command:7", kind = "command"),
            card("q4", rec = null), card("shipoffer-1"), card("q6"))
        assertTrue(AnswerThese.shown(cards))
        assertFalse(AnswerThese.shown(cards.take(2)))
        assertEquals(setOf("q1", "q6"), AnswerThese.ticked(cards))
        // even if a greyed card were ticked by hand, it never goes
        val items = AnswerThese.items(cards, cards.map { it.id }.toSet())
        assertEquals(listOf("q1", "q6"), items.map { it.second })
        assertEquals(Triple("/home/owner/lab/made-up-kites", "q1", "s-q1"), items.first())
        assertTrue(AnswerThese.alone(cards[1]).contains("spends money"))
        assertTrue(AnswerThese.alone(card("q7", stamp = "")).isNotEmpty())
        assertTrue(AnswerThese.alone(card("q8").copy(local = true)).isNotEmpty())
    }

    @Test fun whatWasLeftIsListedWithWhy() {
        val r = AnswerThese.parse(fixture("answer_several"))
        assertEquals("Nothing answered; 1 left for you to answer on their own.", r.reply)
        val lines = AnswerThese.leftLines(r, listOf(card("no-such-card")))
        assertEquals(1, lines.size)
        assertTrue(lines[0].startsWith("Question no-such-card? · That question has been answered already"))
    }

    // -- the look's pictures ------------------------------------------------------------------------------------------
    @Test fun lookPicturesComeOnlyFromDataAddresses() {
        val png = "data:image/png;base64,iVBORw0KGgo="
        val json = """{"pictures": {"A": {"desktop": "$png", "phone": "https://example.invalid/a.png"},
            "B": {"desktop": "http://192.168.1.5/b.png"}, "C": {"phone": "file:///sdcard/c.png"}}}"""
        val p = Looks.parse(json)
        assertEquals(setOf("A"), p.keys)
        assertEquals(listOf(png), p.getValue("A").shown)
        assertFalse(Looks.safe("http://example.invalid/x.png"))
        assertFalse(Looks.safe("data:text/html;base64,PGI+"))
        assertNull(Looks.bytes("https://example.invalid/x.png"))
        assertTrue(Looks.parse(fixture("plan_looks")).isEmpty())
        val look = Ask("looks", "look", options = listOf(AskOption("A", "A · Calm", picture = "A"), AskOption("B", "B · Bright", picture = "B")))
        assertEquals(listOf("A · Calm" to png), Looks.forCard(look, p))
        // a new-project card's own options may carry a picture, but only as a data address
        val wiz = Ask("look", "wizard", options = listOf(AskOption("x", "X", picture = png), AskOption("y", "Y", picture = "http://x.invalid/y.png")))
        assertEquals(listOf("X" to png), Looks.forCard(wiz, emptyMap()))
    }

    // -- documents, hiring, talk, sounds, settings -------------------------------------------------------------------
    @Test fun documentsAreReadOnlyWithTheirWords() {
        val d = Documents.parse(fixture("documents"))
        assertTrue(d.documents.isEmpty())
        assertEquals("No documents yet. Drop files here, or link a folder.", d.words)
        val one = Documents.parse("""{"documents": [{"id": "d1", "name": "recipes.pdf", "kind_words": "PDF", "who": "All projects",
            "private_words": "Never leaves this computer"}], "words": "1 document your agents can look up."}""").documents.single()
        assertEquals("recipes.pdf", one.heading)
        assertEquals("PDF · All projects · Never leaves this computer", one.line)
    }

    @Test fun aHireSaysWhatThePcSaid() {
        val h = Team.hired(fixture("agent_hire"))
        assertEquals("Saved Maelin.", h.reply)
        assertEquals("planner", h.agent?.job)
        val v = Team.agents(fixture("agents"))
        val job = v.jobs.first().job
        assertTrue(Team.canTake(v, job).none { it.job == job && it.hired })
    }

    @Test fun talkNeverRunsAnActionWithoutATap() {
        val r = Talk.parseReply(fixture("talk"))
        assertNull(r.action)
        assertEquals("Final report: all done.", r.reply)  // the PC answers Talk through the chat since 1.5.0 (the scripted brain's words)
        val withAction = Talk.parseReply("""{"reply": "I can try it again.", "action": {"line": "/retry T1", "words": "Try a task again", "confirm": false}}""")
        val a = withAction.action!!
        assertFalse(Talk.mayRun(a, tapped = false, sure = false))
        assertTrue(Talk.mayRun(a, tapped = true, sure = false))
        val spends = a.copy(line = "/run", confirm = true)
        assertFalse(Talk.mayRun(spends, tapped = true, sure = false))
        assertTrue(Talk.mayRun(spends, tapped = true, sure = true))
        assertFalse(Talk.mayRun(a.copy(line = "rm -rf"), tapped = true, sure = true))
        assertTrue(Talk.actionLine(spends).contains("spends"))
    }

    @Test fun theSoundsCardSaysWhatWasSpentOfTheCap() {
        val v = Sounds.parse("""{"sounds": [{"title": "Coin", "file": "assets/sounds/coin.mp3", "made": "bought", "service": "ElevenLabs", "usd": 0.08, "licence": {"commercial": true, "words": "Paid plan"}},
            {"title": "Jump", "file": "", "made": "code", "why": "no service"}, {"title": "Odd", "file": "../../etc/x.mp3"}],
            "spent": 0.42, "cap": 2.0, "owner_cap": 2.0}""")
        assertEquals("$0.42 of $2 used", Sounds.spendLine(v))
        assertEquals("Made by ElevenLabs · $0.08", v.sounds[0].line)
        assertEquals("Made in code", v.sounds[1].line)
        assertTrue(Sounds.playable(v.sounds[0]))
        assertFalse(Sounds.playable(v.sounds[2]))
        assertEquals("$0 used", Sounds.spendLine(SoundsView()))
    }

    @Test fun theMoneyAndCheckingComeFirstInAProjectsSettings() {
        val v = ProjectSettings.parse(fixture("project_settings"))
        val (first, rest) = ProjectSettings.split(v)
        assertEquals(listOf("limits", "checking"), first.map { it.key })
        assertEquals(v.items.size, first.size + rest.size)
        assertEquals("How carefully it's checked", first[1].label)
    }
}
