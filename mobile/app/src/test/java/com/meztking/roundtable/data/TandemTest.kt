package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TandemTest {
    private val json = """
        {"level": "balanced", "label": "Checking: Balanced", "words": "Checking: Balanced (about ${'$'}0.40 of this)",
         "allowance": {"usd": 0.5, "spent": 0.12, "used_up": false},
         "estimates": {"lean": {"cost_usd": 1.0, "minutes": 10, "extra_usd": 0, "planning_usd": 0, "unpriced": false},
                       "balanced": {"cost_usd": 1.4, "minutes": 13, "extra_usd": 0.4, "planning_usd": 0, "unpriced": false},
                       "maximum": {"cost_usd": 3.1, "minutes": 20, "extra_usd": 1.8, "planning_usd": 0.3, "unpriced": false}},
         "tasks": {"T1": {"built_by": "anthropic/claude-opus-5-5", "built_by_label": "Claude Opus 5.5", "agent": "ada",
                          "rivals": [{"id": "r1", "model": "anthropic/claude-opus-5-5", "picked": true, "why": "smaller"},
                                     {"id": "r2", "model": "b/coder2", "picked": false}],
                          "reviews": [{"model": "openai/gpt-6", "approved": true},
                                      {"model": "google/gemini-3-pro", "approved": false, "breaks": "the score must show"}],
                          "disagreed": true, "same_maker": false,
                          "line": "Built by Claude Opus 5.5 (ada) · best of 2 · checked by GPT 6 and Gemini 3 Pro · they disagreed",
                          "fold": ["Try 1 (rival r2): Coder2 – built (a rival)"], "routed": {"from": "x", "why": "y"}}},
         "something_new": 1}
    """.trimIndent()

    @Test fun theDialAndWhoDidWhatFromThePc() {
        val v = Tandem.parse(json)!!
        assertEquals("Checking: Balanced", Tandem.label(v))
        assertEquals(0.5, v.allowance.usd!!, 1e-9)
        assertEquals("about $3.10", Tandem.priceWords(v.estimates["maximum"]))
        val t = v.tasks["T1"]!!
        assertEquals("Built by Claude Opus 5.5 (ada) · best of 2 · checked by GPT 6 and Gemini 3 Pro · they disagreed",
            Tandem.line(t))
        assertEquals(listOf("Try 1 (rival r2): Coder2 – built (a rival)"), Tandem.foldLines(t))
    }

    @Test fun makesTheLineWhenAnOlderPcLeftItOut() {
        val t = TandemTask(built_by = "deepseek/deepseek-v4", reviews = listOf(TandemReview(model = "b/reviewer-two"),
            TandemReview(model = "c/checker", breaks = "must save")), same_maker = true)
        assertEquals("Built by Deepseek V4 · checked by Reviewer Two and Checker · one checker is from the same company",
            Tandem.line(t))
        assertTrue(Tandem.foldLines(t).last().endsWith("“must save”"))
    }

    @Test fun nothingOrRubbish() {
        assertNull(Tandem.parse(""))
        assertNull(Tandem.parse("not json"))
        val v = Tandem.parse("{}")!!
        assertEquals("Checking: Lean", Tandem.label(v))
        assertEquals("price not known", Tandem.priceWords(null))
    }
}
