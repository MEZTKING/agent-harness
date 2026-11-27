package com.meztking.roundtable.data

import com.meztking.roundtable.ui.PlanTop
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Short first: a plan's top is a short title and one sentence; the builders' brief is folded away. */
class PlanCalmTest {
    private val old = """
        _Plan status: done · plan ready · updated 2026-11-26T10:00:00Z by Roundtable Hold_

        # Plan v2: Also ship the player as an Android app (APK) and a Windows app (EXE). One code base: both wrap index.html, css and js.

        The player gains two wrappers.

        Estimate: about ${'$'}3.45, about 45 minutes

        Settings: budget about ${'$'}3.45; quality about ${'$'}31.33

        ## In scope
        - scripts/sync-web.js — the copy step

        ## Tasks
        - [T1] done Copy the player (coder)
        - [T2] done The Android app (coder)
    """.trimIndent()

    @Test fun anOldPlanGetsAShortTitleAndItsBriefMovesIntoMore() {
        val d = PlanDoc.parse(old)
        assertEquals("Also ship the player as an Android app and a Windows app", d.shortTitle)
        assertEquals(listOf("T1", "T2"), d.tasks.map { it.id })
        assertEquals("Copy the player", d.tasks[0].title)
        assertEquals("The builders' brief", d.sections.first().title)
        assertTrue(d.sections.any { it.title == "Sets of models" })
        assertTrue(d.sections.none { it.title == "Tasks" })
        assertEquals("about \$3.45, about 45 minutes", d.estimate)
        val top = PlanTop.of(PlanView(d), "music-box")
        assertTrue(top.finished)
        assertEquals("Finished – 2 tasks", top.state)
        assertEquals("", top.estimate)  // a finished plan shows no estimate
    }

    @Test fun theWordsFileWinsAndTheEstimateShowsOnlyWhileItWaits() {
        val d = PlanDoc.parse("_Plan status: waiting for the owner · x · updated 2026-11-26T10:00:00Z by Roundtable Hold_\n\n# Kite shop\n\nEstimate: about \$0.42 and 18 minutes\n")
        val w = PlanWords.parse("""{"asks": [], "title": "Kite shop for phone", "state": "Waiting for you: 2 questions", "waiting": ["2 questions"], "estimate": "about ${'$'}0.42 and 18 minutes"}""")!!
        val top = PlanTop.of(PlanView(d, canApprove = true, words = w), "kite-shop")
        assertEquals("Kite shop for phone", top.title)
        assertEquals("Waiting for you: 2 questions", top.state)
        assertEquals("About \$0.42 and 18 minutes", top.estimate)
        assertEquals(false, w.pendingChanges)
        assertEquals(null, PlanWords.parse("""{"asks": []}"""))
    }

    @Test fun shortTitles() {
        assertEquals("Build a lantern timer web app", PlanWords.shortTitle("Build a lantern timer web app with index.html and app.js"))
        assertEquals("Shop for kites", PlanWords.shortTitle("a shop for kites"))
        assertTrue(PlanWords.shortTitle("word ".repeat(40)).length <= 60)
        assertEquals("The plan", PlanWords.shortTitle(""))
    }

    @Test fun savedDocumentsAreNamedByTheirHeading() {
        assertEquals("Kite links", Note.title("Some intro\n\n# Kite links\n\n| a | b |", "kites.md"))
        assertEquals("Kite links", Note.title("no heading", "kite-links.md"))
        assertTrue(Note.safe("links.md"))
        assertTrue(!Note.safe("../hub.yaml") && !Note.safe(".hidden.md"))
    }
}
