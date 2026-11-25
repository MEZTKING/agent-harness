package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlanDocTest {
    // the shape plandoc.render_markdown writes, with made-up content
    private val plan = """
        _Plan status: waiting for the owner · plan ready: 2 choices (about ${'$'}0.17, ~44 min) · updated 2026-11-25T22:41:05Z by Roundtable Hold_

        # Plan v2: Make a lantern timer, as a web app.

        Build a small timer page.

        Estimate: about ${'$'}0.17, about 44 minutes

        ## In scope
        - A start button

        ## Don't
        - Don't add a framework (One page does not need it.) {D1}

        ## Stack and files [S1]
        Static page, no build step.

        ## Decisions
        ### What happens when time is up? [C4]
        - Ring once (recommended): A single chime. [Low] {A}
        - Ring until stopped: Keeps going: needs a stop button. [Medium] {B}
        Why: Once is enough.

        ### Where do settings live? [C5]
        - Local storage (chosen): Kept in the browser. {a}
        - Nowhere {b}

        ## Questions for the owner
        - Which colour for the lantern? {Q1}
        - Should it work offline? {Q2}
          Answer: Yes, please

        ## Ideas
        - [open] Add a dark mode. (Night use.) {I1}
        - [accepted] Keyboard shortcuts {I2}

        ## Critique by a second model
        - [high] Something to fix

        ## Tasks
        - [T1] pending Scaffold the page (coder)
    """.trimIndent()

    @Test fun header() {
        val d = PlanDoc.parse(plan)
        assertEquals("waiting for the owner", d.state)
        assertTrue(d.waitingForOwner)
        assertFalse(d.approved)
        assertEquals("2026-11-25T22:41:05Z", d.updated)
        assertEquals("plan ready: 2 choices (about \$0.17, ~44 min)", d.summaryLine)
        assertEquals("Plan v2: Make a lantern timer, as a web app.", d.title)
        assertEquals(2, d.intro.size)
    }

    @Test fun decisions() {
        val d = PlanDoc.parse(plan).decisions
        assertEquals(2, d.size)
        assertEquals("C4", d[0].id)
        assertEquals("What happens when time is up?", d[0].question)
        assertEquals("Once is enough.", d[0].why)
        val (a, b) = d[0].options
        assertEquals(PlanDoc.Option("A", "Ring once", "A single chime.", "Low", recommended = true, chosen = false), a)
        assertEquals(PlanDoc.Option("B", "Ring until stopped", "Keeps going: needs a stop button.", "Medium", recommended = false, chosen = false), b)
        assertTrue(d[1].options[0].chosen)
        assertEquals("a", d[1].options[0].id)
        assertEquals(PlanDoc.Option("b", "Nowhere", "", "", recommended = false, chosen = false), d[1].options[1])
    }

    @Test fun questionsIdeasDonts() {
        val d = PlanDoc.parse(plan)
        assertEquals(listOf(PlanDoc.Question("Q1", "Which colour for the lantern?", ""), PlanDoc.Question("Q2", "Should it work offline?", "Yes, please")), d.questions)
        assertEquals(PlanDoc.Idea("I1", "open", "Add a dark mode.", "Night use."), d.ideas[0])
        assertEquals(PlanDoc.Idea("I2", "accepted", "Keyboard shortcuts", ""), d.ideas[1])
        assertEquals(listOf(PlanDoc.Dont("D1", "Don't add a framework (One page does not need it.)")), d.donts)
        assertEquals(2, d.openChoices) // C4 not chosen and Q1 unanswered; C5 chosen, Q2 answered
    }

    @Test fun otherSectionsStayMarkdown() {
        val d = PlanDoc.parse(plan)
        assertEquals(listOf("In scope", "Don't", "Stack and files", "Critique by a second model", "Tasks"), d.sections.map { it.title })
    }

    @Test fun approvedAndEmpty() {
        assertTrue(PlanDoc.parse("_Plan status: approved, building · 8 tasks · updated 2026-11-25T22:41:05Z by Roundtable Hold_\n\n# Plan v1: x").approved)
        assertEquals("", PlanDoc.parse("").title)
        // a plan without the status line still reads
        assertEquals("Plan v1: y", PlanDoc.parse("# Plan v1: y\n\n## Decisions\n### Q? [C1]\n- One {a}\n- Two {b}").title)
    }
}
