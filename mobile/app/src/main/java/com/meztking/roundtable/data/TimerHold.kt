package com.meztking.roundtable.data

/**
 * Timers on question cards (asktimer.py), the phone's half: the countdown on the card, and the hold sent while the
 * owner types an answer. The phone only ever asks the PC to stop the clock for a while (`{path, id, hold: true}`);
 * setting a timer or clearing one stays on the PC (phone.PHONE_NARROW refuses it).
 */
object TimerHold {
    /** At most one hold every 20 seconds for a card: the PC keeps the clock stopped longer than that each time. */
    const val EVERY_MS = 20_000L

    /** "4 min left", "1 min 05 s left", "40 s left"; "" when the card has no running timer (none, held, run out, a command). */
    fun countdown(ask: Ask, nowMs: Long = System.currentTimeMillis()): String {
        if (ask.kind == "command" || ask.held || ask.timed_out != null || ask.expires_at.isBlank() || ask.on_expire.isBlank()) return ""
        val end = runCatching { java.time.Instant.parse(ask.expires_at).toEpochMilli() }.getOrNull() ?: return ""
        val left = (end - nowMs) / 1000
        return when {
            left <= 0 -> "Time is up: waiting for the PC."
            left < 60 -> Words.t("{n} s left", "n" to left)
            left < 600 -> Words.t("{m} min {s} s left", "m" to left / 60, "s" to String.format(java.util.Locale.UK, "%02d", left % 60))
            else -> Words.t("{m} min left", "m" to left / 60)
        }
    }

    /** Whether the card has a timer worth holding while the owner types. */
    fun holdable(ask: Ask): Boolean =
        ask.kind != "command" && ask.timed_out == null && ask.expires_at.isNotBlank() && ask.on_expire.isNotBlank() && !ask.path.isNullOrBlank()
}

/** Sends a hold at most once every [everyMs] for each card, however fast the owner types. */
class HoldThrottle(private val everyMs: Long = TimerHold.EVERY_MS, private val now: () -> Long = System::currentTimeMillis) {
    private val last = mutableMapOf<String, Long>()

    /** True when a hold for [key] should go now (and remembers that it went). */
    @Synchronized
    fun shouldSend(key: String): Boolean {
        val t = now()
        val before = last[key]
        if (before != null && t - before < everyMs) return false
        last[key] = t
        return true
    }
}
