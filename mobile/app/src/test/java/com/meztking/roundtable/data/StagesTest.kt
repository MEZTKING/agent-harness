package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StagesTest {
    private val json = """
        {"stages": [{"id": "M1", "title": "A first slice", "shows": "a page that opens", "done": 1, "total": 1,
                     "state": "done", "tasks": ["A1"], "ready_at": "2026-11-27T10:00:00Z"},
                    {"id": "M2", "title": "The middle", "shows": "", "done": 0, "total": 2, "state": "stuck",
                     "tasks": ["B1", "B2"], "ready_at": ""}],
         "parts": [{"id": "game", "name": "Game", "folder": "game"}],
         "words": "Stage 2 of 2: The middle. Something in it didn't pass.",
         "warnings": [{"id": "overlap:B1:B2", "by": "stages", "kind": "overlap", "tasks": ["B1", "B2"],
                       "files": ["game.js"], "text": "B1 and B2 both change game.js: they'll run one after the other"}],
         "strayed": [{"task": "A1", "files": ["notes.md"]}], "files": {"A1": ["a1.txt"]}, "something_new": 1}
    """.trimIndent()

    @Test fun theStagesFromThePc() {
        val v = Stages.parse(json)!!
        assertEquals(listOf("M1", "M2"), v.stages.map { it.id })
        assertEquals("M2", v.current!!.id)
        assertEquals("Something didn't pass", Stages.stateWords(v.current!!.state))
        assertEquals("Stage 1, A first slice: Built, 1 of 1 done. At the end you can try a page that opens",
            Stages.chipWords(0, v.stages[0]))
        val more = Stages.moreLines(v)
        assertEquals("Parts: Game (in game/)", more[0])
        assertTrue(more.contains("A1 also changed notes.md"))
    }

    @Test fun groupsTasksByStage() {
        val v = Stages.parse(json)!!
        assertEquals(listOf("M1" to listOf("A1"), "M2" to listOf("B1", "B2"), "" to listOf("Z")),
            Stages.group(v, listOf("B1", "A1", "Z", "B2")))
    }

    @Test fun nothingOrRubbish() {
        assertNull(Stages.parse(""))
        assertNull(Stages.parse("not json"))
        assertNull(Stages.parse("{}")!!.current)
        assertEquals("/api/stages?path=C%3A%5Cmy+game", Stages.url("C:\\my game"))
    }
}
