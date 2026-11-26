package com.meztking.roundtable.data

import com.meztking.roundtable.net.Message
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlainTest {
    private fun cmd(body: String, action: String = "x") = Message("1", "me", "music-box", "request", "roundtable: $action", body)
    private fun re(body: String, id: String = "2", at: String = "2026-11-25T10:00:00Z", from: String = "music-box") =
        Message(id, from, "me", "reply", "Re: roundtable: choose", body, at)

    private val plan = PlanDoc.parse("""
        _Plan status: waiting for the owner · updated 2026-11-25T22:41:05Z by Roundtable Hold_

        # Plan v2: A made-up music box

        ## Decisions
        ### Which screen first? [C6]
        - The library (recommended): Your songs. {A}
        - The player {B}

        ## Ideas
        - [open] A sleep timer {I1}
    """.trimIndent())

    @Test fun commandsReadAsWhatTheOwnerDid() {
        val t = { body: String -> Letters.commandText(body) }
        assertEquals("You chose option A for decision C6", t("""{"action": "choose", "decision": "C6", "option": "A"}"""))
        assertEquals("You chose “The library” for “Which screen first?”",
            Letters.commandText("""{"action": "choose", "decision": "C6", "option": "A"}""", plan))
        assertEquals("You asked for the plan to be updated", t("""{"action": "revise", "text": "Apply the owner's answers"}"""))
        assertEquals("You added a note: Look: clean and modern", t("""{"action":"note","text":"Look: clean and modern"}"""))
        assertEquals("You suggested: a dark mode", t("""{"action": "idea", "text": "a dark mode"}"""))
        assertEquals("You said yes to the idea: A sleep timer", Letters.commandText("""{"action": "idea", "id": "I1", "accept": true}""", plan))
        assertEquals("You took out of the plan: the shop", t("""{"action": "scope_remove", "text": "the shop"}"""))
        assertEquals("You answered: Amber", t("""{"action": "answer", "question": "Q1", "text": "Amber"}"""))
        assertEquals("You chose “The player” for “Which screen first?”",
            Letters.commandText("""{"action": "answer", "id": "choose:C6", "chosen": ["B"]}""", plan))
        assertEquals("You approved the plan", t("""{"action": "approve"}"""))
        assertEquals("You approved the plan", t("""{"action": "answer", "id": "approve", "chosen": ["approve"]}"""))
        assertEquals("You asked Roundtable to start building", t("""{"action": "run"}"""))
        assertEquals("A command for Roundtable (teleport)", t("""{"action": "teleport"}"""))
        assertEquals("A command for Roundtable (choose)", Letters.commandText("not json", subjectAction = "choose"))
    }

    @Test fun lettersNeverShowJsonByDefault() {
        val p = Letters.plain(cmd("""{"action": "choose", "decision": "C6", "option": "A"}""", "choose"), plan)
        assertTrue(p.command)
        assertEquals("Sent to Roundtable", p.title)
        assertFalse(p.text.contains("{"))
        assertTrue(p.details!!.contains("\"decision\"")) // "Show details" reveals it
        val r = Letters.plain(re("Done. 1 change(s) waiting: send 'revise' (Update plan) to apply them."))
        assertTrue(r.receipt)
        assertEquals("Roundtable: Done. 1 change waits for you to press Update plan.", r.text)
        val plainLetter = Letters.plain(Message("3", "music-box", "me", "message", "Hello", "**Bold** words"))
        assertEquals("Hello", plainLetter.title)
        assertEquals("Bold words", plainLetter.text)
    }

    @Test fun receiptsAndTrouble() {
        assertTrue(Letters.isReceipt(re("Done. 2 changes wait for you to press Update plan.")))
        assertFalse(Letters.isReceipt(re("Couldn't do 'run': there's no plan")))
        assertFalse(Letters.isReceipt(re("The run ended as: failed.")))
        assertFalse(Letters.isReceipt(Message("4", "music-box", "me", "message", "Re: lunch", "Done.")))
        val bad = Letters.plain(re("Couldn't do 'run': there's no plan"))
        assertTrue(bad.trouble)
        assertEquals("Roundtable: Couldn't do that: there's no plan", bad.text)
    }

    @Test fun receiptsGroupPerProject() {
        val ms = (1..12).map { re("Done. 1 change waits for you to press Update plan.", "m$it", "2026-11-25T10:%02d:00Z".format(it)) } +
            re("Plan v3: 3 tasks added. The new plan is ready to look at.", "m13", "2026-11-25T11:00:00Z") +
            re("Done.", "o1", "2026-11-24T09:00:00Z", from = "garden-app") +
            re("Couldn't do 'run': no plan", "bad", "2026-11-25T12:00:00Z") +
            Message("x", "music-box", "someone-else", "reply", "Re: roundtable: note", "Done.", "2026-11-25T12:00:00Z")
        val groups = Letters.receipts(ms, "me")
        assertEquals(listOf("music-box", "garden-app"), groups.map { it.project })
        assertEquals(13, groups[0].count)
        assertEquals("music-box: 13 of your changes done – latest: Plan v3: 3 tasks added", groups[0].line)
        assertEquals("garden-app: 1 of your changes done – latest: Done", groups[1].line)
    }

    @Test fun statusHidesPathsAndCommands() {
        assertEquals("review the result and report: …", StatusText.tidy("review the result and report: /tmp/claude-0/lab/music/.harness/summary.md"))
        assertEquals("rate tasks: …", StatusText.tidy("rate tasks: roundtable feedback /tmp/lab/music TASK --good/--bad"))
        assertEquals("open …", StatusText.tidy("open C:\\Users\\someone\\lab\\music"))
        assertEquals("task T1 failed; check …, then retry or skip it",
            StatusText.tidy("task T1 failed; check `roundtable status /tmp/x`, then retry or skip it"))
        assertEquals("goal: Make a music box. Plan v2 waits for the owner's choices",
            StatusText.tidy("goal: Make a music box. Plan v2 waits for the owner's choices (see plans/music-box.md)"))
        assertEquals("Rate the tasks (good or bad)", StatusText.tidy("Rate the tasks (good or bad)"))
        val doc = StatusDoc.parse("""
            # music-box

            ## Where we left off

            **2026-11-25T10:00:00Z**: finished the goal

            - [ ] review the result and report: /tmp/claude-0/x/.harness/summary.md
            - [ ] Look at what was built
        """.trimIndent())
        assertEquals(listOf("review the result and report: …", "Look at what was built"), doc.nextSteps)
    }

    private fun need(project: String, kind: String, at: String, ask: String? = null, actions: List<String> = emptyList()) =
        NeedView("$project:$kind:$at:$ask", if (ask != null) "ask" else kind, project, "t", at = at, actions = actions,
            ask = ask?.let { Ask("a$at", it, project) })

    @Test fun needsAreOrganisedByProjectThenKind() {
        val needs = listOf(
            need("garden", "message", "2026-11-25T09:00:00Z"),
            need("garden", "todo", "2026-11-25T08:00:00Z"),
            need("music", "ask", "2026-11-25T07:00:00Z", ask = "idea"),
            need("music", "message", "2026-11-25T12:00:00Z"),
            need("music", "todo", "2026-11-25T06:00:00Z"),
            need("music", "ask", "2026-11-25T05:00:00Z", ask = "decision"),
            need("music", "ask", "2026-11-25T11:00:00Z", ask = "question"),
            need("music", "ask", "2026-11-25T04:00:00Z", ask = "money"),
            need("music", "run", "2026-11-25T03:00:00Z", actions = listOf("retry")),
            need("music", "run", "2026-11-25T02:00:00Z", actions = listOf("approve")),
        )
        val out = NeedsOrder.organise(needs)
        assertEquals(listOf("music", "garden"), out.map { it.project }) // music has something to answer now
        val music = out[0]
        assertEquals(listOf(NeedsOrder.Group.ANSWER, NeedsOrder.Group.MONEY, NeedsOrder.Group.TODO, NeedsOrder.Group.IDEA, NeedsOrder.Group.LETTER),
            music.sections.map { it.group })
        // newest first inside a group
        assertEquals(listOf("2026-11-25T11:00:00Z", "2026-11-25T05:00:00Z", "2026-11-25T02:00:00Z"), music.sections[0].items.map { it.at })
        assertEquals(10 - 2, music.count)
        assertEquals("3 questions, 2 stopped runs, 1 to-do, 1 idea, 1 letter", music.summary)
        assertEquals("1 to-do, 1 letter", NeedsOrder.summary(needs, "garden"))
        assertEquals("", NeedsOrder.summary(needs, "nobody"))
    }

    @Test fun onlyRealLettersNeedTheOwner() {
        val real = letterNeed(Message("5", "garden", "me", "message", "A question", "Line one\nLine two\nLine three\nLine four"))
        assertEquals("garden: A question", real.title)
        assertEquals("Line one\nLine two\nLine three", real.text)
        val trouble = letterNeed(re("Couldn't do 'run': no plan"))
        assertEquals("Roundtable couldn't do it", trouble.title)
        assertEquals(NeedsOrder.Group.LETTER, NeedsOrder.groupOf(trouble))
    }
}
