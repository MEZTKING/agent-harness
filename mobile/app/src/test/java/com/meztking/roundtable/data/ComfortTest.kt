package com.meztking.roundtable.data

import android.content.Context
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import com.meztking.roundtable.ui.BatteryChecklist
import com.meztking.roundtable.ui.comfortLine
import com.meztking.roundtable.ui.theme.Ash
import com.meztking.roundtable.ui.theme.Eclipse
import com.meztking.roundtable.ui.theme.Pitch
import com.meztking.roundtable.ui.theme.paletteFor
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** The phone's comfort settings: stored, restored after a restart, and safe to read in every look. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class ComfortTest {
    private val ctx: Context get() = RuntimeEnvironment.getApplication()

    @Before @After fun clean() {
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().clear().commit()
        Comfort.reset()
    }

    @Test fun theTablesOrderByHandSurvivesARestart() {
        val c = Comfort.get(ctx)
        val hub = listOf("alpha", "beta", "gamma", "delta")
        // a drag: delta to the top, beta to the end
        val dragged = Comfort.moved(Comfort.moved(hub, 3, 0), 2, 3)
        assertEquals(listOf("delta", "alpha", "gamma", "beta"), dragged)
        c.reorder(dragged)
        Comfort.reset()
        val again = Comfort.get(ctx)
        assertEquals(dragged, again.order)
        // a new project from the hub follows the ones the owner placed; pinned still come first; nothing is dropped
        val (shown, away) = Comfort.arrange(hub + "epsilon", { it }, setOf("gamma"), setOf("alpha"), again.order)
        assertEquals(listOf("gamma", "delta", "beta", "epsilon"), shown)
        assertEquals(listOf("alpha"), away)
        assertEquals(hub, Comfort.moved(hub, 9, 0)) // a drag of a row that has gone changes nothing
    }

    @Test fun defaultsAreTheUsualLook() {
        val c = Comfort.get(ctx)
        assertEquals(Accent.VIOLET, c.accent)
        assertEquals(Look.ECLIPSE, c.look)
        assertFalse(c.trueBlack)
        assertEquals(1f, c.textScale)
        assertEquals(Haptics.LIGHT, c.haptics)
        assertEquals(Detail.STANDARD, c.detail)
        assertTrue(c.pinned.isEmpty() && c.putAway.isEmpty())
        // violet on Eclipse is the palette itself: what anyone who never opens Comfort sees
        assertSame(Eclipse, paletteFor())
        assertSame(Eclipse, paletteFor(dark = true))
        assertSame(Ash, paletteFor(Look.ASH))
        assertSame(Pitch, paletteFor(Look.PITCH))
    }

    @Test fun everyChoiceSurvivesARestart() {
        val c = Comfort.get(ctx)
        c.pickAccent(Accent.SEA); c.pickTrueBlack(true); c.pickTextScale(1.2f); c.pickHaptics(Haptics.OFF); c.pickDetail(Detail.COMPACT)
        c.pin("lantern-app", true); c.putAwayProject("old-sketch", true)
        c.remember("lantern-app", SentItem(SentItem.NOTE, "Make the glow warmer"))
        Comfort.reset() // as if the app closed and opened again
        val d = Comfort.get(ctx)
        assertEquals(Accent.SEA, d.accent)
        assertTrue(d.trueBlack)
        assertEquals(1.2f, d.textScale, 0.001f)
        assertEquals(Haptics.OFF, d.haptics)
        assertEquals(Detail.COMPACT, d.detail)
        assertEquals(setOf("lantern-app"), d.pinned)
        assertEquals(setOf("old-sketch"), d.putAway)
        assertEquals("Make the glow warmer", d.sent("lantern-app").single().text)
    }

    @Test fun aPhoneFromBeforeTheLooksKeepsItsChoices() {
        // 0.12's true-black switch becomes Pitch, and its amber stays amber
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().putBoolean("true_black", true).putString("accent", "AMBER").commit()
        Comfort.reset()
        val c = Comfort.get(ctx)
        assertEquals(Look.PITCH, c.look)
        assertEquals(Accent.AMBER, c.accent)
        // and the looks survive a restart; Ash turns the old switch off
        c.pickLook(Look.ASH); Comfort.reset()
        assertEquals(Look.ASH, Comfort.get(ctx).look)
        assertFalse(Comfort.get(ctx).trueBlack)
        Comfort.get(ctx).pickTrueBlack(false); Comfort.reset()
        assertEquals(Look.ECLIPSE, Comfort.get(ctx).look)
    }

    @Test fun textSizeStaysInRange() {
        val c = Comfort.get(ctx)
        c.pickTextScale(3f); assertEquals(Comfort.SCALE_MAX, c.textScale)
        c.pickTextScale(0.2f); assertEquals(Comfort.SCALE_MIN, c.textScale)
        c.pickTextScale(Float.NaN); assertEquals(1f, c.textScale)
        // a bad stored value is clamped when read
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().putFloat("text_scale", 9f).commit()
        Comfort.reset()
        assertEquals(Comfort.SCALE_MAX, Comfort.get(ctx).textScale)
    }

    @Test fun unknownStoredWordsFallBackToTheDefaults() {
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().putString("accent", "NEON").putString("detail", "HUGE").commit()
        Comfort.reset()
        assertEquals(Accent.VIOLET, Comfort.get(ctx).accent)
        assertEquals(Detail.STANDARD, Comfort.get(ctx).detail)
        assertEquals(Look.ECLIPSE, Comfort.get(ctx).look)
    }

    @Test fun pinningAndPuttingAwayNeverLoseAProject() {
        val c = Comfort.get(ctx)
        c.pin("b", true)
        c.putAwayProject("b", true) // putting away unpins
        assertFalse("b" in c.pinned); assertTrue("b" in c.putAway)
        c.pin("b", true) // pinning brings it back
        assertTrue("b" in c.pinned); assertFalse("b" in c.putAway)
        c.putAwayProject("c", true)
        val (shown, away) = Comfort.arrange(listOf("a", "b", "c", "d"), { it }, c.pinned, c.putAway)
        assertEquals(listOf("b", "a", "d"), shown)
        assertEquals(listOf("c"), away)
        assertEquals(4, shown.size + away.size)
        c.putAwayProject("c", false)
        assertTrue(c.putAway.isEmpty())
    }

    @Test fun sentHistoryIsNewestFirstPerProjectAndCapped() {
        val c = Comfort.get(ctx)
        for (i in 1..60) c.remember("quill-notes", SentItem(SentItem.NOTE, "note $i"))
        c.remember("tide-clock", SentItem(SentItem.LETTER, "Hello", "A question"))
        val q = c.sent("quill-notes")
        assertEquals(Comfort.SENT_MAX, q.size)
        assertEquals("note 60", q.first().text)
        assertEquals("note 11", q.last().text)
        assertTrue(q.all { it.at.isNotBlank() })
        assertEquals("A question", c.sent("tide-clock").single().subject)
        // the same note again moves to the top instead of showing twice
        c.remember("quill-notes", SentItem(SentItem.NOTE, "note 30"))
        assertEquals("note 30", c.sent("quill-notes").first().text)
        assertEquals(1, c.sent("quill-notes").count { it.text == "note 30" })
        // blank text is ignored
        c.remember("tide-clock", SentItem(SentItem.LETTER, "   "))
        assertEquals(1, c.sent("tide-clock").size)
        c.forgetSent("tide-clock")
        assertTrue(c.sent("tide-clock").isEmpty())
    }

    @Test fun aDamagedHistoryReadsAsEmpty() {
        ctx.getSharedPreferences(Comfort.FILE, Context.MODE_PRIVATE).edit().putString("sent:x", "{not json").commit()
        assertTrue(Comfort.get(ctx).sent("x").isEmpty())
    }

    private fun contrast(a: Color, b: Color): Double {
        val la = a.luminance() + 0.05; val lb = b.luminance() + 0.05
        return maxOf(la, lb) / minOf(la, lb)
    }

    @Test fun everyAccentReadsOnEveryFloor() {
        for (a in Accent.entries) for (look in Look.entries) {
            val p = paletteFor(look, a)
            val where = "${a.words} on ${look.words}"
            // the accent as text on the page and on a card, and text on a filled accent button
            assertTrue("$where on the page", contrast(p.accent, p.background) >= 4.5)
            assertTrue("$where on a card", contrast(p.accent, p.surface) >= 4.5)
            assertTrue("$where button text", contrast(p.accentText, p.accent) >= 4.5)
        }
        // true black only changes the dark look
        assertSame(Ash, paletteFor(dark = false, trueBlack = true))
        assertSame(Pitch, paletteFor(dark = true, trueBlack = true))
        assertEquals(Color.Black, Pitch.background)
    }

    @Test fun everyTextColourReadsInEveryLook() {
        // the design brief's tokens: text, muted and the states at 4.5:1 on the page and on a card; control borders at 3:1
        for (look in Look.entries) {
            val p = paletteFor(look)
            for ((name, c) in listOf("text" to p.text, "muted" to p.muted, "accent" to p.accent, "flare" to p.flare,
                "good" to p.good, "bad" to p.bad, "warn" to p.warn)) {
                assertTrue("$name on ${look.words} page", contrast(c, p.background) >= 4.5)
                assertTrue("$name on ${look.words} card", contrast(c, p.surface) >= 4.5)
            }
            assertTrue("control borders on ${look.words}", contrast(p.lineStrong, p.surface) >= 3.0)
            assertTrue("control borders on ${look.words} page", contrast(p.lineStrong, p.background) >= 3.0)
        }
        assertEquals(Color(0xFF0A0A0F), Eclipse.background)
        assertEquals(Color(0xFFA78BFA), Eclipse.accent)
        assertEquals(Color(0xFFFF9D4D), Eclipse.flare)
    }

    @Test fun liveDetailLevels() {
        val c = LiveDetail.of(Detail.COMPACT, finished = false, running = true)
        assertFalse(c.stepsOpen); assertFalse(c.timeLine); assertFalse(c.more)
        val s = LiveDetail.of(Detail.STANDARD, finished = false, running = true)
        assertTrue(s.stepsOpen); assertTrue(s.timeLine); assertTrue(s.more); assertFalse(s.moreOpen)
        // Standard folds a finished project's steps, as before
        assertFalse(LiveDetail.of(Detail.STANDARD, finished = true, running = false).stepsOpen)
        val d = LiveDetail.of(Detail.DETAILED, finished = true, running = false)
        assertTrue(d.stepsOpen); assertTrue(d.moreOpen)
    }

    @Test fun batteryChecklistInWords() {
        val good = BatteryChecklist.checks(unrestricted = true, notifications = true, dataSaverBlocks = false)
        assertTrue(BatteryChecklist.summary(good).startsWith("All set"))
        val bad = BatteryChecklist.checks(unrestricted = false, notifications = true, dataSaverBlocks = true)
        assertEquals("2 things may stop Darkness Harness checking while the phone sleeps.", BatteryChecklist.summary(bad))
        assertEquals("1 thing may stop Darkness Harness checking while the phone sleeps.",
            BatteryChecklist.summary(BatteryChecklist.checks(false, true, false)))
        // what the phone can't tell is a question, never counted as a problem
        assertTrue(good.any { it.ok == null })
        // and reading this (test) phone doesn't throw
        assertEquals(4, BatteryChecklist.read(ctx).size)
    }

    @Test fun theSettingsLine() {
        assertEquals("Eclipse · Violet · text 100% · Live: Standard", comfortLine(Look.ECLIPSE, Accent.VIOLET, 1f, Detail.STANDARD))
        assertEquals("Pitch · Plum · text 130% · Live: Compact", comfortLine(Look.PITCH, Accent.PLUM, 1.3f, Detail.COMPACT))
    }
}
