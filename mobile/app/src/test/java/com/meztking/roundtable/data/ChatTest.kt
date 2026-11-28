package com.meztking.roundtable.data

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The chat's shapes, frozen in Step 0: the same line and card as the PC's tests/test_chat_seam.py. */
class ChatTest {
    private val sample = """{"id": "20261128T101500123-3fa9c1d2", "at": "2026-11-28T10:15:00.123Z", "who": "chat",
 "seat": "pc-desk-1a2b", "device": "PC-Desk", "text": "Five ideas are accepted and ready to build.",
 "thinking": "The board shows five accepted.", "cost_usd": 0.0009, "model": "deepseek/deepseek-v4-flash",
 "answers": "20261128T101458001-0c0ffee0",
 "files": [{"name": "sketch.png", "sha": "ab12", "ext": "png", "size": 120000, "kind": "picture"}],
 "card": {"id": "c1", "title": "Build the 5 accepted ideas", "line": "About ${"$"}1.40, stops at ${"$"}2.00.",
          "price_usd": 1.4, "cap_usd": 2.0, "command": "/build accepted at most ${"$"}2", "state": "open",
          "buttons": [{"id": "do", "words": "Build", "primary": true}, {"id": "not_now", "words": "Not now"}]}}"""

    @Test fun theSampleLineReadsAsThePcWritesIt() {
        val l = ChatLayout.parseLine(sample)
        assertEquals("chat", l.who)
        assertEquals("pc-desk-1a2b", l.seat)
        assertEquals(0.0009, l.costUsd!!, 1e-12)
        assertEquals("picture", l.files.single().kind)
        val c = l.card!!
        assertEquals("/build accepted at most $2", c.command)
        assertEquals(2.0, c.capUsd!!, 1e-12)
        assertEquals(listOf("do", "not_now"), c.buttons.map { it.id })
        assertTrue(c.buttons.first().primary)
        assertEquals("open", c.state)
        assertEquals(l, ChatLayout.parseLine(ChatLayout.lineJson(l)))
    }

    @Test fun theHubLayoutIsThePcs() {
        assertEquals("chats/hall/2026-11-28.phone-1a2b3c4d.jsonl", ChatLayout.dayPath("hall", "2026-11-28", "phone-1a2b3c4d"))
        assertEquals("chats/hall/files/ab12.png", ChatLayout.filePath("hall", "ab12", "png"))
        assertEquals("chats/hall/claims/t1.json", ChatLayout.claimPath("hall", "t1"))
        assertFalse(ChatLayout.isChat("../inbox"))
        assertTrue(runCatching { ChatLayout.dayPath("../inbox", "d", "s") }.isFailure)
    }

    @Test fun linesMergeByTimeThenSeatThenId() {
        val a = ChatLine(id = "2", at = "2026-11-28T10:15:00.123Z", seat = "b")
        val b = ChatLine(id = "9", at = "2026-11-28T10:15:00.123Z", seat = "a")
        val c = ChatLine(id = "1", at = "2026-11-28T10:14:00.000Z", seat = "z")
        assertEquals(listOf(c, b, a), listOf(a, b, c).sortedWith(ChatLayout.order))
    }

    @Test fun neverV4Pro() {
        assertTrue(ChatLayout.never("deepseek/DeepSeek-V4-Pro"))
        assertFalse(ChatLayout.never(ChatLayout.MODEL))
    }

    @Test fun theStubBrainSendsNothingAndSaysSo() = runBlocking {
        val pieces = NoChatBrain.say("hall", "hello").toList()
        val answer = pieces.single() as Piece.Answer
        assertEquals("app", answer.line.who)
        assertFalse(NoChatBrain.read("hall").can.answer)
        assertEquals("off", NoChatBrain.read("hall").can.why)
    }
}
