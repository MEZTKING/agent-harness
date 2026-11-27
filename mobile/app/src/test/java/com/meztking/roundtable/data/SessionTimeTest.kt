package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Where each task's time went, its context, and several tasks at once. Every log here is made up. */
class SessionTimeTest {
    @Test fun thePcSendsEveryRunningTask() {
        val s = Live.parseSession("""
            {"project": "made-up", "at": "2026-11-27T10:00:00Z",
             "task": {"id": "T2", "title": "Sounds", "status": "running", "steps": []},
             "tasks": [
               {"id": "T1", "title": "Menu", "status": "running", "now": "Edit menu.js · +3 −0",
                "time": {"parts": [{"key": "first", "label": "Waiting for the first word", "ms": 1200},
                                   {"key": "you", "label": "Waiting for you", "ms": 60000}], "total_ms": 61200, "unrecorded": 0},
                "context": {"used": 4100, "window": 128000, "share": 0.032, "model": "x/y", "cache_hit": 0.71},
                "changes": [{"path": "menu.js", "added": 3, "removed": 0, "new": true}], "steps": []},
               {"id": "T2", "title": "Sounds", "status": "running", "time": null, "context": null, "steps": []}]}
        """.trimIndent())!!
        assertEquals(listOf("T1", "T2"), s.shown.map { it.id })
        val t1 = s.tasks[0]
        assertEquals(61200L, t1.time!!.total)
        assertEquals(0.71, t1.context!!.cache_hit!!, 1e-9)
        assertEquals("menu.js", t1.changes.single().path)
        assertNull(s.tasks[1].time)
    }

    @Test fun anOlderPcSendsOneTask() {
        val s = Live.parseSession("""{"project": "x", "task": {"id": "T1", "title": "A", "status": "done", "steps": []}}""")!!
        assertEquals(listOf("T1"), s.shown.map { it.id })
        assertNull(s.task!!.time)  // no times: no bar, never a bar of zeros
    }

    @Test fun hubLinesGroupByTask() {
        val jsonl = """
            {"at": "2026-11-27T10:00:00Z", "kind": "task_started", "task": "T1", "title": "Menu", "index": 1, "total": 3}
            {"at": "2026-11-27T10:00:01Z", "kind": "task_started", "task": "T2", "title": "Sounds", "index": 2, "total": 3}
            {"at": "2026-11-27T10:00:02Z", "kind": "turn", "task": "T1", "line": "Making the menu", "ms": 3000, "first_ms": 1000}
            {"at": "2026-11-27T10:00:03Z", "kind": "turn", "task": "T2", "line": "Adding sounds", "ms": 2000}
            {"at": "2026-11-27T10:00:04Z", "kind": "tool", "task": "T1", "line": "● Run `npm test` · passed", "ms": 50000, "waited_ms": 45000}
            {"at": "2026-11-27T10:00:05Z", "kind": "task_done", "task": "T1", "status": "done", "summary": "menu works"}
            {"at": "2026-11-27T10:00:06Z", "kind": "tool", "task": "T2", "line": "● Write sfx.js · +2 −0"}
        """.trimIndent()
        val r = SessionLog.parse(jsonl, "made-up")!!
        assertTrue(r.running)
        assertEquals(listOf("T2"), r.summary.tasks.map { it.id })  // T1 finished
        val t2 = r.summary.tasks.single()
        assertEquals(listOf("Adding sounds", "● Write sfx.js · +2 −0"), t2.steps.map { it.line })
        assertEquals(listOf("model" to 2000L), t2.time!!.parts.map { it.key to it.ms })  // the untimed tool line is left out
        assertEquals("Write sfx.js · +2 −0", t2.now)
        assertEquals("T2", r.summary.task!!.id)
    }

    @Test fun twoTasksRunningBothShow() {
        val jsonl = """
            {"kind": "task_started", "task": "T1", "title": "Menu"}
            {"kind": "task_started", "task": "T2", "title": "Sounds"}
            {"kind": "turn", "task": "T1", "line": "menu", "ms": 3000, "first_ms": 1000}
            {"kind": "tool", "task": "T1", "line": "● Run `npm test` · passed", "ms": 50000, "waited_ms": 45000}
        """.trimIndent()
        val r = SessionLog.parse(jsonl)!!
        assertEquals(listOf("T1", "T2"), r.summary.tasks.map { it.id })
        val parts = r.summary.tasks[0].time!!.parts.associate { it.key to it.ms }
        assertEquals(mapOf("first" to 1000L, "writing" to 2000L, "tools" to 5000L, "you" to 45000L), parts)
        assertNull(r.summary.tasks[1].time)
    }

    @Test fun oldLinesWithoutTaskIdsStillWork() {
        val jsonl = """
            {"kind": "task_started", "task": "T1", "title": "Old"}
            {"kind": "turn", "line": "hello"}
            {"kind": "cost", "usd": 0.01}
        """.trimIndent()
        val r = SessionLog.parse(jsonl)!!
        assertEquals(listOf("hello"), r.summary.task!!.steps.map { it.line })
        assertEquals(0.01, r.summary.task!!.cost, 1e-9)
        assertNull(r.summary.task!!.time)
    }

    @Test fun durationsInWords() {
        assertEquals("under a second", com.meztking.roundtable.ui.duration(400))
        assertEquals("42s", com.meztking.roundtable.ui.duration(42_000))
        assertEquals("2m", com.meztking.roundtable.ui.duration(120_300))
        assertEquals("3m 10s", com.meztking.roundtable.ui.duration(190_000))
        assertEquals("1h 5m", com.meztking.roundtable.ui.duration(3_900_000))
    }
}
