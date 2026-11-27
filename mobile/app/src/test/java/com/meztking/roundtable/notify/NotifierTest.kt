package com.meztking.roundtable.notify

import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskOption
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.AutopilotState
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.PlanView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.Progress
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class NotifierTest {
    private val approve = Ask("approve", "approve", "bakery", path = "/lab/bakery", question = "Is the plan right? Start building?", stamp = "v2",
        options = listOf(AskOption("approve", "Approve and start"), AskOption("not_now", "Not now")))

    private fun hall(status: String = "running", vararg needs: NeedView) = HallState(
        seats = listOf(SeatView("bakery-site", status = status, statusText = "$status · T2", progress = Progress(2, 5), lastActivity = "2026-11-27T10:00:00Z")),
        needs = needs.toList(),
    )

    @Test fun snapshotFromWhatThePhoneReads() {
        val s = Classifier.snapshot(hall("waiting",
            NeedView("ask:bakery-site:approve:v2", "ask", "bakery-site", approve.question, ask = approve),
            NeedView("pc:run:bakery-site:T2", "run", "bakery-site", "A task failed", "T2 didn't work", listOf("retry", "skip"), task = "T2"),
            NeedView("pc:run:bakery-site:x", "run", "bakery-site", "Budget reached", "at the limit", listOf("budget")),
        ), at = "2026-11-27T10:01:00Z")
        assertEquals("Bakery Site", s.projects.single().name)
        assertEquals(5, s.projects.single().total)
        assertEquals(listOf(NewsKind.NEEDS_YOU, NewsKind.FAILED, NewsKind.MONEY), s.needs.map { it.kind })
        assertEquals(listOf("Is the plan right? Start building?", "T2 didn't work", "at the limit"), s.needs.map { it.text })
        val paused = Classifier.snapshot(HallState(listOf(SeatView("kite", status = "idle", statusText = "idle · stopped part-way: resume when ready"))))
        assertTrue(paused.projects.single().paused)
        // a hub project's plan says it's done
        assertEquals("done", Classifier.snapshot(hall("idle"), plans = mapOf("bakery-site" to "done")).projects.single().status)
        assertEquals("done", Classifier.planStatus("Building", finished = true))
        assertEquals("running", Classifier.planStatus("Building: T3 of 7", finished = false))
        assertEquals(null, Classifier.planStatus("Planned", finished = false))
    }

    @Test fun sameNewsTwiceIsOneNotification() {
        val a = Classifier.snapshot(hall("running"), at = "2026-11-27T10:00:00Z")
        val b = Classifier.snapshot(hall("done"), at = "2026-11-27T10:15:00Z")
        val news = Classifier.classify(a, b)
        assertEquals(listOf(NewsKind.FINISHED), news.map { it.kind })
        val seen = mutableListOf<String>()
        val first = Notifier.fresh(news, seen, emptySet()) { true }
        seen += first.map { it.key }
        assertEquals(1, first.size)
        // the classifier gives it again (an old snapshot lost, a restart): still only once
        assertEquals(emptyList<News>(), Notifier.fresh(news + news, seen, emptySet()) { true })
        assertEquals(1, Notifier.fresh(news + news, emptyList(), emptySet()) { true }.size)
    }

    @Test fun switchedOffKindsAndWhatTheAppAlreadyShowedStayQuiet() {
        val need = NeedView("todo:kite:7", "todo", "kite", "To do: Pick a name")
        val news = Classifier.classify(null, Classifier.snapshot(HallState(needs = listOf(need)), at = "2026-11-27T10:00:00Z"))
        assertEquals("needs_you:todo:kite:7", news.single().key)
        assertEquals(emptyList<News>(), Notifier.fresh(news, emptyList(), emptySet()) { it != NewsKind.NEEDS_YOU })
        assertEquals(emptyList<News>(), Notifier.fresh(news, emptyList(), setOf("todo:kite:7")) { true })
        assertEquals(1, Notifier.fresh(news, emptyList(), emptySet()) { true }.size)
    }

    @Test fun eachKindHasItsOwnChannel() {
        assertEquals(5, NewsKind.ALL.map { Notifier.channel(it) }.toSet().size)
        assertEquals("needs_you", Notifier.channel(NewsKind.NEEDS_YOU))  // the old channel keeps the owner's choice
    }

    /** Records what the notification's button sends. */
    private class Fake : Backend {
        val answers = mutableListOf<Pair<Ask, AskReply>>()
        override val mode = Mode.PC
        override val identity = "me"
        override suspend fun hall() = HallState()
        override suspend fun projects() = emptyList<String>()
        override suspend fun status(project: String) = StatusDoc()
        override suspend fun plan(seat: SeatView) = PlanView()
        override suspend fun inbox(project: String) = emptyList<Message>()
        override suspend fun letters() = emptyList<Message>()
        override suspend fun send(to: String, subject: String, body: String) {}
        override suspend fun reply(original: Message, body: String) {}
        override suspend fun markRead(messages: List<Message>) {}
        override suspend fun act(need: NeedView, action: String) = ""
        override suspend fun asks(seat: SeatView) = emptyList<Ask>()
        override suspend fun answer(ask: Ask, reply: AskReply): String { answers += ask to reply; return "Approved: building has started" }
        override suspend fun command(project: String, action: String, fields: Map<String, Any?>) = ""
        override suspend fun autopilot(): AutopilotState? = null
        override suspend fun setAutopilot(on: Boolean, until: String, cap: Double?) = ""
        override suspend fun live(seat: SeatView) = LiveView()
    }

    @Test fun buttonsSendTheSameAnswerAsTheCard() = runTest {
        val news = Classifier.classify(null, Classifier.snapshot(HallState(needs = listOf(
            NeedView("ask:bakery:approve:v2", "ask", "bakery", approve.question, ask = approve))), at = "2026-11-27T10:00:00Z")).single()
        assertEquals(listOf(NewsButton("approve", "Approve plan")), news.buttons)
        val fake = Fake()
        assertEquals("Approved: building has started", NotifyAnswer.send(fake, news.ask!!, "approve"))
        assertEquals(approve, fake.answers.single().first)
        assertEquals(AskReply(listOf("approve")), fake.answers.single().second)
        // what a hub machine gets: the `answer` command with this card's id, stamp and choice (remote.py)
        val fields = com.meztking.roundtable.data.Asks.commandFields(news.ask!!, fake.answers.single().second)
        assertEquals("approve", fields["id"]); assertEquals(listOf("approve"), fields["chosen"]); assertEquals("v2", fields["stamp"])
        // an answer the notification doesn't offer is refused, never sent
        try { NotifyAnswer.send(fake, approve, "not_now"); fail("sent an answer that has no button") } catch (_: IllegalArgumentException) {}
        val command = Ask("command:c1", "command", "kite", question = "Run npm install?", options = listOf(AskOption("allow", "Allow"), AskOption("deny", "Don't allow")))
        NotifyAnswer.send(fake, command, "deny")
        assertEquals(AskReply(listOf("deny")), fake.answers.last().second)
        val money = Ask("money", "money", "kite", question = "Carry on?", options = listOf(AskOption("more", "More", confirm = "Sure?"), AskOption("stop", "Stop")))
        assertEquals(emptyList<NewsButton>(), Classifier.buttons(money))
    }
}
