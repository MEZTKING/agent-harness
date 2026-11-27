package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SearchTest {
    private val json = """
        {"query": "croissant", "total": 2, "words": "2 found.", "extra": 1, "hits": [
          {"kind": "file", "kind_words": "File", "title": "src/menu.js", "where": "Bakery site · Files",
           "snippet": "const items = ['croissant'];", "score": 3.0, "at": "",
           "open": {"room": "file", "path": "/made/up/bakery", "file": "src/menu.js", "line": 1}},
          {"kind": "memory", "title": "The owner likes the croissant photo", "where": "Bakery site · Memory",
           "snippet": "", "open": {"room": "memory", "path": "/made/up/bakery", "archive": true}}
        ]}""".trimIndent()

    @Test fun readsThePcsAnswer() {
        val r = Search.parse(json)
        assertEquals(2, r.hits.size)
        assertEquals("2 found.", r.words)
        assertEquals("src/menu.js", r.hits[0].open.file)
        assertEquals(1, r.hits[0].open.line)
        assertTrue(r.hits[1].open.archive)
        assertEquals("Shows the older memory", Search.openWords(r.hits[1]))
        assertEquals(SearchResult(), Search.parse("not json"))
    }

    @Test fun readsPeeksAndMemory() {
        val p = Search.parsePeek("""{"file": "a.txt", "from": 3, "line": 4, "lines": ["x", "y"], "words": ""}""")
        assertEquals(listOf("x", "y"), p.lines)
        assertEquals(3, p.from)
        val m = Search.parseMemory("""{"markdown": "# Memory", "where": "This computer", "words": "1 rule", "counts": {"rules": 1}}""")
        assertEquals("This computer", m.where)
    }

    @Test fun wordsAndMarks() {
        assertEquals(listOf("opening hours", "menu", "js"), Search.terms("Menu \"opening hours\" js"))
        val text = "The Menu has croissants; menu again"
        assertEquals(listOf(4 to 8, 25 to 29), Search.marks(text, "menu"))
        assertEquals(listOf(4 to 8, 13 to 22, 25 to 29), Search.marks(text, "croissant menu"))
        assertTrue(Search.marks(text, "").isEmpty())
    }
}
