package com.meztking.roundtable.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class DoneListTest {
    private val json = """
        {"goal_index": 0, "items": [
           {"id": "D1", "text": "You can start a game, lose and start again", "how": "journey", "must": true, "by": "planner",
            "steps": [{"open": "/"}, {"click": "Start"}, {"wait": 2}], "state": "failed", "words": "Play again does nothing",
            "evidence": {"pictures": ["a.png"]}, "serves": ["T1"]},
           {"id": "D2", "text": "It opens with no errors", "how": "page_opens", "must": true, "by": "kind", "state": "passed",
            "words": "", "evidence": {}},
           {"id": "D3", "text": "My brother can win once", "how": "owner", "must": true, "by": "owner", "state": "open"},
           {"id": "D4", "text": "It feels fun", "how": "play", "must": false, "by": "planner", "state": "unchecked"}],
         "checked": 2, "passed": 1, "failed": 1, "unchecked": 2, "must_failed": ["D1"],
         "words": "Done when: 1 of 4 ✓ · 1 doesn’t work yet", "rounds": [{"at": "x", "item": "D1", "passed": false}],
         "finished": false, "marks": {"passed": "✓"}, "something_new": 1}
    """.trimIndent()

    @Test fun theDoneListFromThePc() {
        val d = DoneList.parse(json)!!
        assertEquals(4, d.items.size)
        assertEquals("Done when: 1 of 4 ✓ · 1 doesn’t work yet", DoneList.line(d))
        assertEquals("failed", d.items[0].state)
        assertEquals(listOf("for its kind"), DoneList.tags(d.items[1]))
        assertEquals(listOf("yours"), DoneList.tags(d.items[2]))
        assertEquals(listOf("nice to have"), DoneList.tags(d.items[3]))
        assertFalse(d.finished)
    }

    @Test fun onlyAPassedItemHasATick() {
        assertEquals("✓", DoneList.mark("passed"))
        listOf("failed", "unchecked", "open", "whatever").forEach { assertFalse(DoneList.mark(it) == "✓") }
        assertTrue(DoneList.markWords("unchecked").contains("no tick"))
    }

    @Test fun anOlderPcOrNothing() {
        assertNull(DoneList.parse(""))
        assertNull(DoneList.parse("not json"))
        val bare = DoneList.parse("""{"items": [{"id": "D1", "text": "x", "state": "passed"}, {"id": "D2", "text": "y"}], "passed": 1}""")!!
        assertEquals("Done when: 1 of 2 ✓", DoneList.line(bare))
        assertEquals("No done list yet.", DoneList.line(DoneSummary()))
    }

    @Test fun evidenceWithAPicture() {
        val png = "data:image/png;base64," + Base64.getEncoder().encodeToString(byteArrayOf(9, 8, 7))
        val e = DoneList.parseEvidence("""{"found": true, "item": "D1", "text": "t", "state": "failed", "words": "w",
            "texts": {"log": "ok"}, "pictures": [{"name": "a.png", "data": "$png"}]}""")!!
        assertTrue(e.found)
        assertEquals(mapOf("log" to "ok"), e.texts)
        assertArrayEquals(byteArrayOf(9, 8, 7), DoneList.pictureBytes(e).single().second)
        assertEquals("/api/done/evidence?path=%2Fa+b&item=D1", DoneList.evidenceUrl("/a b", "D1"))
        assertTrue(DoneList.url("/p").startsWith("/api/done?"))
    }
}
