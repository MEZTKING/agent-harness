package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LearnedTest {
    private val json = """
        {"lines": [
           {"id": "P1", "when": "2026-11-27T10:00:00Z", "words": "Coder now starts with Coder2: it passed 9 of 10 against 6 of 10.",
            "what": "Coder now starts with Coder2", "why": "it passed 9 of 10 against 6 of 10", "state": "watching",
            "by": "by itself", "can_undo": true, "can_put_back": false, "kind": "routing", "role": "coder",
            "numbers": {"test": {"n": 10}}, "before_after": {"before": ["Coder"], "after": ["Coder2"]}},
           {"id": "P2", "words": "", "what": "Coder now thinks high", "why": "", "state": "undone", "by": "your phone",
            "can_undo": false, "can_put_back": true}],
         "waiting": [{"id": "P3", "words": "Reviewer has new instructions.", "why": "Only with your yes.", "from": "", "can_apply": true}],
         "not_here": [], "never": ["Your money limits"],
         "wallet": {"on": true, "allowance": 2, "left": 1.25, "words": "Learning by itself: ${'$'}1.25 of ${'$'}2.00 left this week."},
         "counts": {"on": 1}, "share": true, "something_new": 1}
    """.trimIndent()

    @Test fun readsTheLinesFromThePc() {
        val v = Learned.parse(json)!!
        assertEquals(2, v.lines.size)
        assertEquals("Coder now starts with Coder2: it passed 9 of 10 against 6 of 10.", Learned.line(v.lines[0]))
        assertTrue(v.lines[0].can_undo)
        assertEquals("by itself · Being watched", Learned.byWords(v.lines[0]))
        assertEquals("Coder now thinks high.", Learned.line(v.lines[1]))
        assertEquals("your phone · Undone", Learned.byWords(v.lines[1]))
        assertEquals("1 change learned is in use. 1 waits for you on the PC.", Learned.summary(v))
        assertEquals(listOf("Your money limits"), v.never)
        assertEquals("Learning by itself: $1.25 of $2.00 left this week.", v.wallet.words)
    }

    @Test fun anUndoSendsOnlyTheId() {
        assertEquals("""{"id":"P1"}""", Learned.undoBody("P1"))
        assertTrue(Learned.UNDO_URL.startsWith(Learned.URL))
    }

    @Test fun nothingOrBrokenGivesNothing() {
        assertNull(Learned.parse(""))
        assertNull(Learned.parse("not json"))
        assertEquals("Nothing learned in use yet.", Learned.summary(LearnedView()))
        assertEquals("Put back", Learned.stateWords("put_back"))
    }
}
