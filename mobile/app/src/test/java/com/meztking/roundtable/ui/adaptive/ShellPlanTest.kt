package com.meztking.roundtable.ui.adaptive

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Where the main places go on a phone, a phone on its side, foldables and tablets. */
class ShellPlanTest {
    @Test fun phonesGetTheBottomBar() {
        for ((w, h) in listOf(360 to 780, 390 to 844, 412 to 915, 599 to 900)) {
            val p = ShellPlan.plan(w, h)
            assertEquals("$w x $h", ShellNav.BOTTOM_BAR, p.nav)
            assertEquals(1, p.panes)
        }
    }

    @Test fun aPhoneOnItsSideGetsARailAndOnePane() {
        val p = ShellPlan.plan(844, 390)
        assertEquals(ShellNav.RAIL, p.nav)
        assertFalse(p.twoPanes)
        assertTrue(p.maxPaneDp in 600..840)
    }

    @Test fun anOpenFoldableGetsARail() {
        // an open book-style foldable, about 673 x 841 dp, flat
        val p = ShellPlan.plan(673, 841)
        assertEquals(ShellNav.RAIL, p.nav)
        assertEquals(1, p.panes)
    }

    @Test fun aHalfOpenFoldableSplitsAtTheFold() {
        val p = ShellPlan.plan(673, 841, folded = true)
        assertEquals(ShellNav.RAIL, p.nav)
        assertTrue(p.twoPanes)
        assertEquals(0.5f, p.firstShare)
    }

    @Test fun aFoldedShutFoldableIsAPhone() {
        // the outer screen of a foldable is narrow: the hinge flag doesn't matter there
        assertEquals(ShellNav.BOTTOM_BAR, ShellPlan.plan(374, 832, folded = true).nav)
    }

    @Test fun tabletsGetTwoPanes() {
        for ((w, h) in listOf(840 to 1000, 1024 to 768, 1280 to 800)) {
            val p = ShellPlan.plan(w, h)
            assertEquals("$w x $h", ShellNav.RAIL, p.nav)
            assertTrue("$w x $h", p.twoPanes)
            assertTrue(p.firstShare in 0.5f..0.65f)
        }
        // the widest gives the Table a little more
        assertTrue(ShellPlan.plan(1280, 800).firstShare > ShellPlan.plan(900, 800).firstShare)
    }

    @Test fun aSmallTabletIsOnePaneWithARail() {
        val p = ShellPlan.plan(700, 1000)
        assertEquals(ShellNav.RAIL, p.nav)
        assertEquals(1, p.panes)
    }

    @Test fun oddSizesDontBreakIt() {
        assertEquals(ShellNav.BOTTOM_BAR, ShellPlan.plan(0, 0).nav)
        assertEquals(ShellNav.BOTTOM_BAR, ShellPlan.plan(-5, -5).nav)
        // wide but very short: no second pane
        assertFalse(ShellPlan.plan(1200, 400).twoPanes)
    }
}
