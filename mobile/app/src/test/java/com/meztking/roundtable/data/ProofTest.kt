package com.meztking.roundtable.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class ProofTest {
    private val before = "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(byteArrayOf(1, 2, 3))
    private val after = "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(byteArrayOf(4, 5, 6))

    private val json = """
        {"found": true, "task": "W2", "title": "dark mode", "at": "2026-11-27T10:00:00Z", "ok": true,
         "words": "A model that can see checked: the page is there. Tests: 41 pass, 3 new.",
         "before": {"task": "W1", "dir": "by-commit/abc123def456", "commit": "abc123def456", "pictures": {"desktop": "desktop.png"}, "reused": true},
         "after": {"task": "W2", "dir": "W2", "commit": "fed987", "pictures": {"desktop": "desktop.png", "dark": "dark.png"}, "errors": []},
         "pairs": [{"kind": "desktop", "before": "desktop.png", "after": "desktop.png", "change": 0.2, "measured": true, "words": "changed (about 20%)"},
                   {"kind": "dark", "before": null, "after": "dark.png", "change": null, "measured": false, "words": "new"}],
         "tests": {"command": "pytest", "before": {"ok": true, "passed": 38, "failed": 0, "tail": "38 passed"},
                   "after": {"ok": true, "passed": 41, "failed": 0, "tail": "41 passed"}, "verdict": "pass", "broke": [],
                   "words": "Tests: 41 pass, 3 new."},
         "judge": {"looked": true, "verdict": "shows_it", "what_changed": "the page is there", "problems": [],
                   "model": "a/reviewer", "cost_usd": 0.0012, "pictures": 3, "words": "A model that can see checked: the page is there"},
         "lines": [{"id": "starts", "passed": true, "words": "It opens with no errors", "optional": false, "checkable": true},
                   {"id": "plays", "passed": null, "words": "Played for a minute", "optional": false, "checkable": false}],
         "lines_text": "It opens with no errors ✓ · Played for a minute – not checked yet",
         "images": {"before": {"desktop": "$before"}, "after": {"desktop": "$after", "dark": "$after"}},
         "something_new": 1}
    """.trimIndent()

    @Test fun theProofFromThePc() {
        val p = Proof.parse(json)!!
        assertTrue(p.found)
        assertEquals("shows_it", p.verdict)
        assertEquals("✓", p.mark)
        assertEquals(41, p.tests!!.after!!.passed)
        assertNull(p.lines[1].passed)
        val pics = p.pictures()
        assertEquals(listOf("Computer", "Dark mode"), pics.map { it.label })
        assertArrayEquals(byteArrayOf(1, 2, 3), pics[0].before)
        assertArrayEquals(byteArrayOf(4, 5, 6), pics[0].after)
        assertNull(pics[1].before)  // a new picture has nothing before it
        assertEquals("new", pics[1].words)
    }

    @Test fun nobodyLookedAndNoProof() {
        val p = Proof.parse("""{"found": true, "task": "T1", "words": "Nobody looked at the pictures (none of the models can see).",
            "judge": {"looked": false, "words": "Nobody looked at the pictures"}}""")!!
        assertNull(p.verdict)
        assertEquals("–", p.mark)
        assertEquals("Nobody looked at the pictures.", Proof.markWords(p.verdict))
        assertTrue(p.pictures().isEmpty())
        assertFalse(Proof.parse("""{"found": false, "task": "T9", "words": "No proof for this task yet"}""")!!.found)
        assertNull(Proof.parse(null))
        assertNull(Proof.parse("not json"))
    }

    @Test fun moreAndTheAddress() {
        val p = Proof.parse(json)!!
        assertEquals(listOf("Looked at by a/reviewer · $0.0012", "Before: version abc123de (pictures kept from earlier)",
                            "After: version fed987"), Proof.moreLines(p))
        assertEquals("/api/proof?inline=1&path=C%3A%5CUsers%5Cme%5Cbakery&task=T+1", Proof.url("C:\\Users\\me\\bakery", "T 1"))
    }
}
