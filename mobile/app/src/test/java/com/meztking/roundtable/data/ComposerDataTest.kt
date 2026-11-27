package com.meztking.roundtable.data

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.Base64

class ComposerDataTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun aDraftSurvivesClosingTheApp() {
        val dir = tmp.newFolder("drafts")
        DraftStore(dir).setText("new-idea", "a bakery site", Delivery.STEER)
        DraftStore(dir).addFile("new-idea", "shop.jpg", "image/jpeg", byteArrayOf(1, 2, 3))
        val again = DraftStore(dir).load("new-idea") // a new store, as after the app was closed
        assertEquals("a bakery site", again.text)
        assertEquals(Delivery.STEER, Delivery.of(again.mode))
        assertEquals(listOf("shop.jpg"), again.files.map { it.name })
        assertEquals(3, DraftStore(dir).read("new-idea", again.files[0]).size)
        assertTrue(DraftStore(dir).load("other").empty)
        DraftStore(dir).clear("new-idea")
        assertTrue(DraftStore(dir).load("new-idea").empty)
    }

    @Test fun capsSayWhatToDo() {
        val s = DraftStore(tmp.newFolder("d"), Caps(maxBytes = 10, maxTotal = 15, maxFiles = 2))
        val tooBig = runCatching { s.addFile("k", "big.txt", "text/plain", ByteArray(11)) }.exceptionOrNull()
        assertTrue(tooBig is ComposerProblem && tooBig.message!!.contains("too big"))
        s.addFile("k", "a.txt", "text/plain", ByteArray(8))
        assertTrue(runCatching { s.addFile("k", "b.txt", "text/plain", ByteArray(8)) }.exceptionOrNull()!!.message!!.contains("Together"))
        s.addFile("k", "b.txt", "text/plain", ByteArray(2))
        assertTrue(runCatching { s.addFile("k", "c.txt", "text/plain", ByteArray(1)) }.exceptionOrNull()!!.message!!.contains("most files"))
        assertEquals("x.png", ComposerText.safeName("../../evil\\x.png"))
    }

    @Test fun atWordAndPick() {
        assertEquals(AtWord(7, "src/ma"), ComposerText.atWord("change @src/ma", 14))
        assertNull(ComposerText.atWord("mail me@example.com", 19))
        val (t, caret) = ComposerText.pick("change @src/ma please", AtWord(7, "src/ma"), 14, "src/main.py")
        assertEquals("change @src/main.py  please", t)
        assertEquals(20, caret)
    }

    @Test fun picturesAreMadeSmaller() {
        assertEquals(1568 to 784, ComposerText.scaled(4000, 2000))
        assertEquals(800 to 600, ComposerText.scaled(800, 600))
        assertEquals(2, ComposerText.sampleSize(4000, 3000))
        assertEquals(1, ComposerText.sampleSize(1000, 800))
    }

    @Test fun aDraftGoesInPartsThenStartsTheIdea() = runTest {
        val calls = mutableListOf<Pair<String, JsonObject?>>()
        val sender = ComposerSender { m, p, b ->
            calls += p to b?.let { Json.parseToJsonElement(it).jsonObject }
            when {
                p == "/api/attach/upload" && calls.count { it.first == p } == 1 -> """{"upload_id":"u1"}"""
                p == "/api/attach/start" -> """{"reply":"Started bakery-site with 1 attached"}"""
                else -> "{}"
            }
        }
        val bytes = ByteArray(1_000_000) { (it % 251).toByte() } // more than one part
        val draft = ComposerDraft("new-idea", "a bakery site", files = listOf(DraftFile("f1", "shop.jpg", "image/jpeg", bytes.size.toLong(), "x")))
        assertEquals("Started bakery-site with 1 attached", sender.startIdea(draft) { bytes })
        val ups = calls.filter { it.first == "/api/attach/upload" }.map { it.second!! }
        assertTrue(ups.size >= 2)
        assertEquals("u1", ups[1]["upload_id"]!!.jsonPrimitive.content)
        assertEquals("true", ups.last()["last"]!!.jsonPrimitive.content)
        val joined = Base64.getDecoder().decode(ups.joinToString("") { it["data"]!!.jsonPrimitive.content })
        assertTrue(joined.contentEquals(bytes))
        assertEquals("phone:new-idea", calls.last().second!!["key"]!!.jsonPrimitive.content)
        assertEquals(listOf("/api/attach/clear", "/api/attach/upload"), calls.take(2).map { it.first })
        assertFalse(runCatching { sender.startIdea(ComposerDraft("k")) { ByteArray(0) } }.isSuccess) // no idea, nothing sent
    }
}
