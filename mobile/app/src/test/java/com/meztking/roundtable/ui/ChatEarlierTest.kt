package com.meztking.roundtable.ui

import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.ChatRead
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Old letters (lines whose `earlier` is true) fold under "Earlier messages", never among the messages. */
class ChatEarlierTest {
    private val now = ChatLine(id = "n1", at = "2026-11-28T10:00:00.000Z", who = "owner", seat = "me", text = "where does it stand?")
    private val old = ChatLine(id = "earlier-a", at = "2026-11-01T10:00:00.000Z", who = "agent", seat = "", text = "hello\n\nthe whole note",
        from = "frontend", to = "shop", earlier = true)
    private val cmd = ChatLine(id = "earlier-b", at = "2026-11-02T10:00:00.000Z", who = "owner", seat = "", text = "You asked it to build · done", earlier = true)

    @Test fun theMachinesEarlierListIsFolded() {
        val ui = ChatThread.read(ChatUiState(), ChatRead(lines = listOf(now), earlier = listOf(cmd, old)))
        assertEquals(listOf("n1"), ui.lines.map { it.id })
        assertEquals(listOf("earlier-a", "earlier-b"), ui.earlier.map { it.id })  // oldest first
        assertEquals("agent", ui.earlier[0].kind)
        assertTrue(ui.earlier[0].text.contains("frontend") && ui.earlier[0].text.contains("hello"))
        assertEquals("the whole note", ui.earlier[0].more)
        assertEquals("command", ui.earlier[1].kind)
    }

    @Test fun anEarlierLineAmongTheLinesIsFoldedToo() {
        val ui = ChatThread.read(ChatUiState(), ChatRead(lines = listOf(old, now)))
        assertEquals(listOf("n1"), ui.lines.map { it.id })
        assertEquals(listOf("earlier-a"), ui.earlier.map { it.id })
    }

    @Test fun aLaterPageKeepsWhatWasFolded() {
        val first = ChatThread.read(ChatUiState(), ChatRead(lines = listOf(now), earlier = listOf(old)))
        val again = ChatThread.read(first, ChatRead(lines = listOf(now)))
        assertEquals(first.earlier, again.earlier)
    }
}
