package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CouncilTest {
    private val council = """
        {"planners": [{"label": "A", "model": "a/planner", "maker": "a", "tasks": 2, "summary": "plan one", "votes": 2},
                      {"label": "B", "model": "b/critic", "maker": "b", "tasks": 3, "summary": "plan two", "votes": 1},
                      {"label": "C", "model": "c/planner3", "maker": "c", "tasks": 1}],
         "disagreements": [{"topic": "How to save", "options": [{"who": "A", "says": "files"}, {"who": "B", "says": "a database"}],
                            "chosen": "files", "why": "simpler"},
                           {"topic": "Tests first", "options": [{"who": "C", "says": "yes"}], "chosen": "yes"}],
         "chair": "a/planner", "merged": true, "best": "", "stopped": "", "cost_usd": 0.42, "at": "2026-11-27T10:00:00Z",
         "critiques": [{"by": "A", "best": "A", "points": []}]}
    """.trimIndent()

    @Test fun theCouncilApi() {
        val v = Council.parse("""{"found": true, "words": "Three planners agreed on most of it; they differed on 2 things", ${council.trim().removePrefix("{")}""")!!
        assertEquals(3, v.planners.size)
        assertEquals("Three planners agreed on most of it; they differed on 2 things", Council.line(v))
        assertEquals(listOf("Plan A: files", "Plan B: a database", "Chosen: files – simpler"), Council.pointLines(v.disagreements[0]))
        val more = Council.moreLines(v)
        assertTrue(more[0].startsWith("Plan A · a/planner · 2 tasks · liked best by 2"))
        assertTrue(more.contains("Merged by a/planner, your own planner"))
        assertEquals("The planners cost $0.42", more.last())
    }

    @Test fun fromThePlanDocumentOrThePlanApi() {
        val fromDoc = Council.parse("""{"title": "x", "council": $council}""")!!
        assertEquals("Three planners agreed on most of it; they differed on 2 things", Council.line(fromDoc))
        val fromPlan = Council.parse("""{"path": "/p", "doc": {"council": $council}}""")!!
        assertEquals(2, fromPlan.disagreements.size)
    }

    @Test fun theLineWhenNotMerged() {
        val v = Council.parse("""{"planners": [{"label": "A"}, {"label": "B"}], "merged": false, "best": "A", "stopped": "cap"}""")!!
        assertEquals("Two planners each made a plan; the one the others liked best (A) was used", Council.line(v))
        assertTrue(Council.moreLines(v).any { it.contains("spending cap") })
        val agreed = Council.parse("""{"planners": [{"label": "A"}, {"label": "B"}], "merged": true}""")!!
        assertEquals("Two planners agreed on the whole plan", Council.line(agreed))
    }

    @Test fun nothingForOnePlannerOrAnOlderPc() {
        assertNull(Council.parse(""))
        assertNull(Council.parse("not json"))
        assertNull(Council.parse("""{"found": false}"""))
        assertNull(Council.parse("""{"title": "x", "summary": "a plan with no council"}"""))
        assertNull(Council.parse("""{"doc": {"council": null}}"""))
    }
}
