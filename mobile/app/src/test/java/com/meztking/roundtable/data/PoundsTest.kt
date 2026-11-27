package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PoundsTest {
    @Test fun roundsLikeTheDesktop() {
        assertEquals("≈ £0.95", Pounds.text(1.1875, 0.8))
        assertEquals("≈ £1.01", Pounds.text(1.00625, 1.0))
        assertEquals("≈ £1.01", Pounds.text(1.005, 1.0))
        assertEquals("≈ £0.01", Pounds.text(0.005, 1.0))
        assertEquals("≈ under £0.01", Pounds.text(0.004, 1.0))
        assertEquals("≈ £0.00", Pounds.text(0.0, 0.8))
        assertEquals("≈ £1,235", Pounds.text(1234.5, 1.0))
        assertEquals("≈ £99.99", Pounds.text(99.994, 1.0))
        assertEquals("", Pounds.text(3.45, null))
        assertEquals("", Pounds.text(null, 0.8))
        assertEquals("", Pounds.text(-2.0, 0.8))
    }

    @Test fun readsThePcsRate() {
        val r = Pounds.parse("""{"currency": "GBP", "per_usd": 0.8, "at": "2026-11-26", "source": "ecb",
            "stale": false, "show": "usd+gbp", "setting": "auto", "words": "$1 = £0.8000"}""")
        assertEquals(0.8, r.per_usd!!, 1e-9)
        assertEquals("≈ £0.95", Pounds.beside(1.1875, r))
        assertEquals("", Pounds.beside(1.1875, r.copy(show = "usd")))
        assertEquals("", Pounds.beside(1.1875, null))
        assertTrue(Pounds.parse("not json").per_usd == null)
        assertEquals("", Pounds.beside(2.0, Pounds.parse("""{"per_usd": null, "source": "none"}""")))
    }
}
