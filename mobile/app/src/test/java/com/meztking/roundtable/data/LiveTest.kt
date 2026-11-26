package com.meztking.roundtable.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class LiveTest {
    @Test fun latestJsonFromTheHub() {
        val s = Live.parseShots("""
            {"task": "T2", "at": "2026-11-26T14:16:15Z", "title": "Harbour Tides",
             "pictures": {"desktop": "latest-desktop.jpg", "phone": "latest-phone.jpg", "dark": "latest-dark.jpg"},
             "errors": ["Uncaught TypeError: x is undefined"], "note": "",
             "history": [{"task": "T2", "at": "2026-11-26T14:16:15Z", "title": "Harbour Tides", "picture": "T2-desktop.jpg"}],
             "something_new": 1}
        """.trimIndent())!!
        assertEquals("T2", s.task)
        assertEquals("latest-phone.jpg", s.pictures["phone"])
        assertEquals(1, s.errors.size)
        assertEquals("T2-desktop.jpg", s.history.single().picture)
        assertNull(Live.parseShots(null))
        assertNull(Live.parseShots("not json"))
    }

    @Test fun sessionJsonFromTheHub() {
        val s = Live.parseSession("""
            {"project": "harbour-tides", "at": "2026-11-26T14:16:18Z",
             "task": {"id": "T2", "title": "Dark mode", "role": "coder", "status": "done", "cost": 0.0012, "summary": "done",
                      "steps": [{"kind": "tool", "line": "● Edit style.css · +3 −0", "error": false},
                                {"kind": "review", "line": "✓ Approved: fine", "error": false}]}}
        """.trimIndent())!!
        assertEquals("T2", s.task!!.id)
        assertEquals(2, s.task!!.steps.size)
        assertTrue(s.task!!.steps[0].line.startsWith("● Edit"))
        assertNull(Live.parseSession("{\"project\": \"x\", \"task\": null}")!!.task)
    }

    @Test fun thePcSendsPicturesAsDataAddresses() {
        val bytes = byteArrayOf(-1, -40, -1, 1, 2, 3)
        val json = """{"entry": "index.html", "latest": {"task": "T1", "pictures": {"desktop": "desktop.png"}},
            "images": {"desktop": "data:image/jpeg;base64,${Base64.getEncoder().encodeToString(bytes)}", "phone": "nonsense"}}"""
        val (shots, images) = Live.parsePc(json)
        assertEquals("T1", shots!!.task)
        assertArrayEquals(bytes, images["desktop"])
        assertEquals(setOf("desktop"), images.keys)
        assertEquals(listOf("desktop"), LiveView(shots, images).kinds)
        assertNull(Live.dataUrl("data:image/png,abc"))
    }
}
