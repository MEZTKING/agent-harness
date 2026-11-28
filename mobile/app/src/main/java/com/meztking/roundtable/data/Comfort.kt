package com.meztking.roundtable.data

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * The accent colours the owner can pick: each has a light (Ash) and a dark (Eclipse, Pitch) shade that reads at
 * 4.5:1 or better on every floor. Violet, Eclipse's corona, is the usual one; the names are what is stored.
 */
enum class Accent(val words: String, val light: Long, val dark: Long) {
    VIOLET("Violet", 0xFF5B3FD6, 0xFFA78BFA),
    AMBER("Amber", 0xFF9A4A12, 0xFFE8A33D),
    MOSS("Moss", 0xFF3F5F1F, 0xFFA9C48F),
    SEA("Sea", 0xFF1D5670, 0xFF86C3DA),
    PLUM("Plum", 0xFF73345F, 0xFFDDA6D0);

    companion object { fun of(s: String?) = entries.firstOrNull { it.name == s } ?: VIOLET }
}

/**
 * The three looks (Settings → Comfort → Look): Eclipse, black with a ring of light, is the usual one; Pitch is
 * Eclipse on pure black (the old "true black" switch); Ash is light, for sunlight, and never the default.
 */
enum class Look(val words: String, val hint: String, val dark: Boolean) {
    ECLIPSE("Eclipse", "Black with a ring of violet light. The usual look.", true),
    PITCH("Pitch", "Pure black: easier on the battery on most phone screens.", true),
    ASH("Ash", "Light, for bright sunlight.", false);

    companion object { fun of(s: String?) = entries.firstOrNull { it.name == s } }
}

/** How strongly the phone buzzes on a press and hold or a sent answer. */
enum class Haptics(val words: String) {
    OFF("Off"), LIGHT("Light"), STRONG("Strong");
    companion object { fun of(s: String?) = entries.firstOrNull { it.name == s } ?: LIGHT }
}

/** How much the Live tab shows: Compact is one line per task, Detailed opens every step and number. */
enum class Detail(val words: String, val hint: String) {
    COMPACT("Compact", "One line per task. Steps and numbers stay folded."),
    STANDARD("Standard", "The latest steps, numbers under More."),
    DETAILED("Detailed", "Every step and number, already open.");
    companion object { fun of(s: String?) = entries.firstOrNull { it.name == s } ?: STANDARD }
}

/** One thing the owner sent from this phone (a note to the planner or a letter). Kept on the phone only. */
@Serializable
data class SentItem(val kind: String, val text: String, val subject: String = "", val at: String = "") {
    companion object {
        const val NOTE = "note"
        const val LETTER = "letter"
    }
}

/**
 * The phone's comfort settings: look (Eclipse, Pitch, Ash), accent, text size, haptics, how much detail, pinned and put-away
 * projects, and the history of what was sent. Its own plain preferences file ("roundtable.comfort"), which holds
 * nothing secret. Every value is Compose state, so a change redraws the screens straight away.
 */
class Comfort(private val prefs: SharedPreferences) {
    var accent by mutableStateOf(Accent.of(prefs.getString(K_ACCENT, null))); private set
    /** Which look: stored by name; a phone from before the looks keeps its true-black choice as Pitch. */
    var look by mutableStateOf(Look.of(prefs.getString(K_LOOK, null)) ?: if (prefs.getBoolean(K_BLACK, false)) Look.PITCH else Look.ECLIPSE)
        private set
    /** Pitch, in the old switch's words. */
    val trueBlack: Boolean get() = look == Look.PITCH
    var textScale by mutableStateOf(clampScale(prefs.getFloat(K_SCALE, 1f))); private set
    var haptics by mutableStateOf(Haptics.of(prefs.getString(K_HAPTICS, null))); private set
    var detail by mutableStateOf(Detail.of(prefs.getString(K_DETAIL, null))); private set
    var pinned by mutableStateOf(prefs.getStringSet(K_PINNED, null).orEmpty().toSet()); private set
    var putAway by mutableStateOf(prefs.getStringSet(K_AWAY, null).orEmpty().toSet()); private set
    /** The owner's own order of the Table's projects (DS-19), kept on the phone; projects not in it follow in the hub's order. */
    var order by mutableStateOf(prefs.getString(K_ORDER, null).orEmpty().split('\n').filter { it.isNotBlank() }); private set
    /** Bumps when the sent history changes, so screens that read it redraw. */
    var sentVersion by mutableStateOf(0); private set

    fun pickAccent(a: Accent) { accent = a; prefs.edit().putString(K_ACCENT, a.name).apply() }
    fun pickLook(l: Look) { look = l; prefs.edit().putString(K_LOOK, l.name).putBoolean(K_BLACK, l == Look.PITCH).apply() }
    /** The old switch: on is Pitch, off is Eclipse. */
    fun pickTrueBlack(on: Boolean) = pickLook(if (on) Look.PITCH else Look.ECLIPSE)
    fun pickTextScale(s: Float) { textScale = clampScale(s); prefs.edit().putFloat(K_SCALE, textScale).apply() }
    fun pickHaptics(h: Haptics) { haptics = h; prefs.edit().putString(K_HAPTICS, h.name).apply() }
    fun pickDetail(d: Detail) { detail = d; prefs.edit().putString(K_DETAIL, d.name).apply() }

    /** Pins a project to the top of the Table (and brings it back if it was put away). */
    fun pin(id: String, on: Boolean) {
        pinned = if (on) pinned + id else pinned - id
        if (on && id in putAway) putAway = putAway - id
        save()
    }

    /** Puts a project away (hidden from the Table, never deleted), or brings it back. */
    fun putAwayProject(id: String, on: Boolean) {
        putAway = if (on) putAway + id else putAway - id
        if (on && id in pinned) pinned = pinned - id
        save()
    }

    /** The Table's order after a press, hold and drag: [ids] as they now stand. */
    fun reorder(ids: List<String>) {
        order = ids.distinct().filter { it.isNotBlank() && '\n' !in it }.take(ORDER_MAX)
        prefs.edit().putString(K_ORDER, order.joinToString("\n")).apply()
    }

    private fun save() { prefs.edit().putStringSet(K_PINNED, pinned.toSet()).putStringSet(K_AWAY, putAway.toSet()).apply() }

    /** What was sent to [project], newest first (at most [SENT_MAX]). */
    fun sent(project: String): List<SentItem> {
        @Suppress("UNUSED_VARIABLE") val v = sentVersion // read, so a composable showing it redraws on a change
        val raw = prefs.getString(K_SENT + project, null) ?: return emptyList()
        return runCatching { json.decodeFromString(LIST, raw) }.getOrDefault(emptyList())
    }

    /** Remembers something sent to [project]; blank text is ignored, the same text again moves to the top. */
    fun remember(project: String, item: SentItem) {
        if (item.text.isBlank() || project.isBlank()) return
        val stamped = if (item.at.isBlank()) item.copy(at = java.time.Instant.now().toString()) else item
        val list = (listOf(stamped) + sent(project).filterNot { it.kind == item.kind && it.text == item.text && it.subject == item.subject })
            .take(SENT_MAX)
        prefs.edit().putString(K_SENT + project, json.encodeToString(LIST, list)).apply()
        sentVersion++
    }

    fun forgetSent(project: String) { prefs.edit().remove(K_SENT + project).apply(); sentVersion++ }

    companion object {
        const val FILE = "roundtable.comfort"
        const val SENT_MAX = 50
        const val SCALE_MIN = 0.9f
        const val SCALE_MAX = 1.3f
        private const val K_ACCENT = "accent"
        private const val K_BLACK = "true_black"
        private const val K_LOOK = "look"
        private const val K_SCALE = "text_scale"
        private const val K_HAPTICS = "haptics"
        private const val K_DETAIL = "detail"
        private const val K_PINNED = "pinned"
        private const val K_AWAY = "put_away"
        private const val K_ORDER = "table_order"
        const val ORDER_MAX = 500
        private const val K_SENT = "sent:"
        private val LIST = ListSerializer(SentItem.serializer())
        private val json = Json { ignoreUnknownKeys = true }

        fun clampScale(s: Float): Float = if (s.isNaN()) 1f else s.coerceIn(SCALE_MIN, SCALE_MAX)

        @Volatile private var shared: Pair<Context, Comfort>? = null

        /** The app's one Comfort (read from the phone's storage once per application). */
        fun get(ctx: Context): Comfort {
            val app = ctx.applicationContext ?: ctx
            shared?.takeIf { it.first === app }?.let { return it.second }
            return synchronized(this) {
                shared?.takeIf { it.first === app }?.second
                    ?: Comfort(app.getSharedPreferences(FILE, Context.MODE_PRIVATE)).also { shared = app to it }
            }
        }

        /** [list] with the item at [from] moved to [to] (both clamped): one step of a drag. */
        fun <T> moved(list: List<T>, from: Int, to: Int): List<T> {
            if (list.isEmpty() || from !in list.indices) return list
            val m = list.toMutableList()
            val item = m.removeAt(from)
            m.add(to.coerceIn(0, m.size), item)
            return m
        }

        /** Forgets the cached one (tests, to read the file again as after a restart). */
        fun reset() { shared = null }

        /**
         * Pinned first, then the rest, each in the owner's [order] (projects it doesn't name keep the hub's order,
         * after the ones it does); put-away projects apart. Never drops one.
         */
        fun <T> arrange(items: List<T>, id: (T) -> String, pinned: Set<String>, putAway: Set<String>, order: List<String> = emptyList()): Pair<List<T>, List<T>> {
            val rank = order.withIndex().associate { it.value to it.index }
            val sorted = if (rank.isEmpty()) items else items.withIndex().sortedWith(compareBy({ rank[id(it.value)] ?: Int.MAX_VALUE }, { it.index })).map { it.value }
            val away = sorted.filter { id(it) in putAway }
            val shown = sorted.filterNot { id(it) in putAway }
            return (shown.filter { id(it) in pinned } + shown.filterNot { id(it) in pinned }) to away
        }
    }
}

/** What the Live tab shows at a [Detail] level, worked out once (the tests read it too). */
data class LiveDetail(
    /** The steps drawn open (else folded under a title). */
    val stepsOpen: Boolean,
    /** The time bar and the context gauge. */
    val timeLine: Boolean,
    /** The "More" details already open. */
    val moreOpen: Boolean,
    /** The "More" fold at all. */
    val more: Boolean,
) {
    companion object {
        fun of(d: Detail, finished: Boolean, running: Boolean): LiveDetail {
            val done = finished && !running
            return when (d) {
                Detail.COMPACT -> LiveDetail(stepsOpen = false, timeLine = false, moreOpen = false, more = false)
                Detail.STANDARD -> LiveDetail(stepsOpen = !done, timeLine = true, moreOpen = false, more = true)
                Detail.DETAILED -> LiveDetail(stepsOpen = true, timeLine = true, moreOpen = true, more = true)
            }
        }
    }
}
