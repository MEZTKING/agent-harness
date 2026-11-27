package com.meztking.roundtable.ui

import org.junit.Assert.assertEquals
import org.junit.Test

/** DS-82: the reader's place survives a width change. */
class TranscriptPlaceTest {
    @Test
    fun `the same share of the same item stays at the top when heights change`() {
        // a third of the way into a 900 px message; the phone unfolds and it is now 450 px
        assertEquals(150, TranscriptPlace.offsetFor(1f / 3, 450))
        assertEquals(0, TranscriptPlace.offsetFor(-1f, 450))
        assertEquals(450, TranscriptPlace.offsetFor(2f, 450))
    }

    @Test
    fun `the item is found by its key even when new ones came in`() {
        assertEquals(3, TranscriptPlace.indexFor("m7", 1, listOf("m5", "m6", "x", "m7", "m8")))
        assertEquals(2, TranscriptPlace.indexFor("gone", 9, listOf("a", "b", "c")))
        assertEquals(0, TranscriptPlace.indexFor("gone", 4, emptyList()))
    }
}
