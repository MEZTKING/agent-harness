package com.meztking.roundtable.data

import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

/** PC mode and This phone over a made-up machine's /api/chats routes; the fall to the phone when the PC is silent. */
class ApiBrainTest {
    private val calls = CopyOnWriteArrayList<String>()

    /** A made-up machine: the answer is written over three reads, then kept as a line. */
    private fun machine(): ChatCalls {
        var reads = 0
        return ChatCalls { method, path, body ->
            calls += "$method $path ${body.orEmpty()}"
            when {
                path == "/api/chats/say" -> """{"line": {"id": "o1", "at": "2026-11-28T10:00:00.000Z", "who": "owner", "seat": "pc", "text": "hi"}, "turn": "t1"}"""
                path.startsWith("/api/chats/read") -> when (++reads) {
                    1 -> """{"lines": [], "at": "", "answering": {"text": "Five", "thinking": "Look", "at": 1, "done": false}, "can": {"answer": true}}"""
                    2 -> """{"lines": [], "at": "", "answering": {"text": "Five ideas", "thinking": "Look at it", "at": 2, "done": false}, "can": {"answer": true}}"""
                    else -> """{"lines": [{"id": "a1", "at": "2026-11-28T10:00:02.000Z", "who": "chat", "seat": "pc", "device": "PC-Desk", "text": "Five ideas are ready.", "answers": "o1", "cost_usd": 0.0009}], "at": "x", "answering": null, "can": {"answer": true}}"""
                }
                path == "/api/chats/tap" -> """{"line": {"id": "a1", "at": "x", "who": "chat", "seat": "pc", "text": "Queued", "card": {"id": "c1", "title": "Build", "line": "", "command": "/build", "state": "queued", "buttons": []}}}"""
                path == "/api/chats" -> """{"chats": [{"id": "hall", "name": "Hall", "last": "hi", "unread": 1, "waiting": 0}]}"""
                else -> "{}"
            }
        }
    }

    @Test fun theAnswerIsReadAsItIsWrittenThenKept() = runBlocking {
        val pieces = ApiBrain(machine(), pollMs = 1).say("hall", "hi").toList()
        assertEquals("t1", (pieces.first() as Piece.Sent).turn)
        assertEquals(listOf("Five", " ideas"), pieces.filterIsInstance<Piece.Words>().map { it.text })
        assertEquals("Look at it", pieces.filterIsInstance<Piece.Thinking>().joinToString("") { it.text })
        assertEquals("Five ideas are ready.", (pieces.last() as Piece.Answer).line.text)
        assertTrue(calls.first().contains("\"chat\":\"hall\""))
    }

    @Test fun tapsChatsAndStopUseTheirRoutes() = runBlocking {
        val b = ApiBrain(machine(), pollMs = 1)
        assertEquals("queued", b.tap("hall", "c1", "do", confirmed = true).card!!.state)
        assertTrue(calls.last(), calls.last().contains("\"confirmed\":true") && calls.last().contains("\"button\":\"do\""))
        assertEquals("Hall", b.chats().single().name)
        b.stop("hall", "t1")
        assertTrue(calls.last().startsWith("POST /api/chats/stop"))
    }

    @Test fun aMachineThatCantAnswerSaysWhy() = runBlocking {
        val c = ChatCalls { _, path, _ ->
            if (path == "/api/chats/say") """{"line": {"id": "o1", "at": "a", "who": "owner", "seat": "pc", "text": "hi"}, "turn": "t1"}"""
            else """{"lines": [], "at": "", "answering": null, "can": {"answer": false, "why": "key_refused"}}"""
        }
        val last = ApiBrain(c, pollMs = 1).say("hall", "hi").toList().last() as Piece.Answer
        assertEquals(listOf("change_key"), last.line.card!!.buttons.map { it.id })
    }

    private class Fake(val words: String) : ChatBrain {
        override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> =
            flowOf(Piece.Sent(ChatLine(id = "p", who = "owner", text = text), "p"), Piece.Answer(ChatLine(id = "pa", who = "chat", text = words)))
        override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean) = ChatLine(text = "phone tap")
        override suspend fun read(chat: String, since: String) = ChatRead(listOf(ChatLine(text = words)))
    }

    private object Silent : ChatBrain {
        override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> = awaitCancellation()
        override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean): ChatLine = awaitCancellation()
        override suspend fun read(chat: String, since: String): ChatRead = awaitCancellation()
    }

    @Test fun aSilentPcFallsToThePhoneAndSaysSo() = runBlocking {
        val b = FallbackBrain(Silent, Fake("from the phone"), timeoutMs = 50)
        val pieces = b.say("hall", "hi").toList()
        assertEquals("Your PC stopped answering; I'm answering from this phone.", (pieces.first() as Piece.Answer).line.text)
        assertEquals("from the phone", (pieces.last() as Piece.Answer).line.text)
        assertTrue(b.fellBack)
        assertEquals("phone tap", b.tap("hall", "c", "do", false).text)
        assertEquals("from the phone", b.read("hall", "").lines.single().text)
    }

    @Test fun aPcThatStopsMidAnswerHandsOver() = runBlocking {
        val dying = object : ChatBrain {
            override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> = flow {
                emit(Piece.Sent(ChatLine(id = "o", who = "owner", text = text), "t")); emit(Piece.Words("Fi")); throw java.io.IOException("gone")
            }
            override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean) = ChatLine()
            override suspend fun read(chat: String, since: String) = ChatRead()
        }
        val pieces = FallbackBrain(dying, Fake("phone answer"), timeoutMs = 50).say("hall", "hi").toList()
        assertEquals(1, pieces.count { it is Piece.Sent }) // the owner's line isn't shown twice
        val answers = pieces.filterIsInstance<Piece.Answer>().map { it.line.text }
        assertEquals(listOf("Your PC stopped answering; I'm answering from this phone.", "phone answer"), answers)
    }

    @Test fun withNoHubASilentPcIsSaidPlainly() = runBlocking {
        val pieces = FallbackBrain(Silent, null, timeoutMs = 50).say("hall", "hi").toList()
        assertTrue((pieces.single() as Piece.Answer).line.text.startsWith("Your PC isn't answering"))
    }
}
