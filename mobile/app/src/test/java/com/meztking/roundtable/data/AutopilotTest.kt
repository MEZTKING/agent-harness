package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AutopilotTest {
    // the shape the PC's /api/autopilot and the hub's plans/autopilot.json have (made-up projects)
    private val json = """
        {"on": true, "until": "2026-11-27T08:00:00Z", "until_label": "8am", "spend_cap_usd": 2.0, "spent_usd": 0.4,
         "started_at": "2026-11-26T22:00:00Z", "never": ["stone-bridge"], "label": "until 8am · ${'$'}0.40 of ${'$'}2.00",
         "stopped": "", "inbox": "harness", "log": [
           {"at": "2026-11-26T22:05:00Z", "kind": "chose", "project": "quill-notes", "path": "/x/quill-notes", "ask": "choose:C1",
            "chosen": ["a"], "text": "Autopilot chose “Pixel art” for “Which logo style?” because it's the recommended answer."}]}
    """.trimIndent()

    @Test fun readsTheState() {
        val s = Autopilot.parse(json)!!
        assertTrue(s.on)
        assertEquals("until 8am · \$0.40 of \$2.00", s.label)
        assertEquals(listOf("stone-bridge"), s.never)
        assertEquals("quill-notes", s.log.single().project)
        assertNull(Autopilot.parse("not json"))
        assertNull(Autopilot.parse(null))
        assertFalse(Autopilot.parse("{}")!!.on)
    }

    @Test fun theHubCommand() {
        assertEquals(mapOf("state" to "on", "until" to "tonight", "cap" to 3.0), Autopilot.commandFields(true, "tonight", 3.0))
        assertEquals(mapOf("state" to "off"), Autopilot.commandFields(false))
        val seats = listOf(SeatView("me"), SeatView("quill-notes", hasPlan = true))
        assertEquals("harness", Autopilot.commandTarget(Autopilot.parse(json), seats))
        assertEquals("quill-notes", Autopilot.commandTarget(null, seats))
        assertNull(Autopilot.commandTarget(null, listOf(SeatView("me"))))
    }
}
