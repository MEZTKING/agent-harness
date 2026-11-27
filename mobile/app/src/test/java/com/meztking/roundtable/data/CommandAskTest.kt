package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** A command waiting for "Ask me first", in the shape asks.py writes (made-up project). */
class CommandAskTest {
    private val json = """
        {"project": "lantern-app", "asks": [
          {"id": "command:20261127T100000-abc123", "kind": "command", "header": "Command",
           "question": "Task T3 “Add the timer” wants to run a command. Allow it?",
           "detail": "Why it asks: It sends your code to GitHub or another server.",
           "options": [
             {"id": "allow", "label": "Allow once", "description": "It runs this time. Next time it asks again."},
             {"id": "always", "label": "Always allow in this project", "description": "It runs now, and “git push” runs without asking."},
             {"id": "deny", "label": "Don't allow", "description": "It doesn't run."}],
           "recommended": null, "multi": false, "allow_other": true, "other_hint": "Don't allow, and tell it what to do instead",
           "stamp": "c0ffee1234", "answer": null, "source": {"command": "20261127T100000-abc123"},
           "command": "line 1\nline 2\nline 3", "preview": "line 1", "folded": true, "lines": 3, "size": 20,
           "reasons": ["it sends your code to GitHub or another server"], "task": {"id": "T3", "title": "Add the timer"},
           "remember": "“git push”", "asked_at": "2026-11-27T10:00:00Z", "expires_at": "2026-11-27T10:30:00Z",
           "project": "lantern-app", "path": "/home/x/lantern-app"}
        ]}
    """.trimIndent()

    @Test fun parsesACommandCard() {
        val a = Asks.parse(json).single()
        assertEquals("command", a.kind)
        assertEquals(listOf("allow", "always", "deny"), a.options.map { it.id })
        assertEquals(AskTask("T3", "Add the timer"), a.task)
        assertTrue(a.folded)
        assertEquals("line 1", a.commandShown(all = false))
        assertEquals("line 1\nline 2\nline 3", a.commandShown(all = true))
        assertEquals("If nobody answers in time, it doesn't run.", a.commandFoot)
        assertTrue(Asks.hint(a).startsWith("Read the command"))
        assertEquals(null, AskReply(listOf("allow")).needsConfirm(a))
    }

    @Test fun answersGoTheUsualWay() {
        val a = Asks.parse(json).single()
        val f = Asks.commandFields(a, AskReply(listOf("deny"), "use the test server"))
        assertEquals("command:20261127T100000-abc123", f["id"])
        assertEquals(listOf("deny"), f["chosen"])
        assertEquals("use the test server", f["other"])
        assertTrue(Asks.requestBody(a, AskReply(listOf("always"))).contains("\"always\""))
    }

    @Test fun oldCardsHaveNoCommand() {
        val a = Ask("money", "money")
        assertFalse(a.folded)
        assertEquals("", a.commandShown(true))
        assertEquals("", a.commandFoot)
    }
}
