package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Undo a task from the phone: the PC's answers read, and the words the sheet shows (made-up projects). */
class RewindTest {
    @Test fun readsAPreview() {
        val p = Rewind.preview("""{"mode": "undo_task", "task": "T2", "title": "Logo", "words": "Undo \u201cLogo\u201d: 1 file changes back.",
            "files": [{"path": "assets/logo.png", "change": "removed", "words": "goes"}], "back_to_todo": ["T2"],
            "hand_edits": [{"path": "notes.txt", "change": "added"}], "hand_edits_kept": true, "blocked": "", "offer": "", "stamp": "abc123",
            "conflicts": []}""")
        assertEquals("T2", p.task)
        assertEquals("assets/logo.png – goes", Rewind.fileLine(p.files.single()))
        assertEquals(listOf("T2"), p.back_to_todo)
        assertTrue(Rewind.canApply(p))
        assertEquals("Your own edits to 1 file stay as they are.", Rewind.handEdits(p))
    }

    @Test fun aBlockedPreviewCantBeApplied() {
        val p = Rewind.preview("""{"mode": "back_to_before", "task": "T2", "blocked": "Some of this work has already been sent to GitHub.",
            "offer": "undo_task", "stamp": "abc"}""")
        assertFalse(Rewind.canApply(p))
        assertFalse(Rewind.canApply(null))
        assertEquals("undo_task", p.offer)
        assertNull(Rewind.handEdits(p))
        assertEquals("Your own edits to 2 files are kept safe and come back with Put it back.",
            Rewind.handEdits(RewindPreview(hand_edits = listOf(RewindFile("a"), RewindFile("b")), hand_edits_kept = false)))
    }

    @Test fun readsTheHistoryAndTheLastRewind() {
        val h = Rewind.history("""{"rows": [{"id": "T1", "title": "Hello module", "status": "done", "words": "Changed 1 file.",
            "files": [{"path": "hello.py", "change": "added"}], "pushed": false, "undone": false, "can_undo": true, "can_go_back": true,
            "commit": "0123456789abcdef"}], "last": {"id": "x", "words": "Undid \u201cLogo\u201d.", "can_put_back": true, "why_not": ""},
            "can_change": true, "why_not": ""}""")
        assertEquals("Hello module", h.rows.single().title)
        assertTrue(h.rows.single().can_undo)
        assertTrue(h.last!!.can_put_back)
        assertNull(Rewind.history("""{"rows": [], "last": null, "can_change": false, "why_not": "busy"}""").last)
    }

    @Test fun foldsLongFileListsAndNamesTheCopy() {
        val files = (1..9).map { RewindFile("f$it.txt") }
        val (first, folded) = Rewind.firstFiles(files)
        assertEquals(6, first.size)
        assertEquals(3, folded)
        assertEquals(0, Rewind.firstFiles(files.take(2)).second)
        assertEquals("bakery", Rewind.folderName("C:\\lab\\bakery"))
        assertEquals("bakery", Rewind.folderName("/home/me/lab/bakery/"))
        assertEquals("bakery-another-way", Rewind.copyName("bakery"))
        assertEquals("Made \u201ctry-2\u201d.", Rewind.done("""{"ok": true, "words": "Made \u201ctry-2\u201d.", "path": "/x/try-2", "name": "try-2"}""").words)
        assertEquals(2, Rewind.MODES.size)
    }
}
