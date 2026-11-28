package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/** One read of GET /api/stream: what was written since the last read (harness/streamlog.py). */
@Serializable
data class StreamRead(val text: String = "", val thinking: String = "", val at: Long = 0, val done: Boolean = true,
                      val skipped: Long = 0)

/**
 * A task's reply as it is written: the words so far and the thinking (folded on screen). Each read adds what is new;
 * a read from a newer model conversation of the task (the builder, then its checker) starts the words again.
 */
data class StreamText(val text: String = "", val thinking: String = "", val at: Long = 0, val done: Boolean = false,
                      /** Some of the start was let go (only the newest part is kept). */
                      val cut: Boolean = false) {
    val empty: Boolean get() = text.isBlank() && thinking.isBlank()

    /** The words with [r] added (or started again when [r] belongs to a newer conversation). */
    fun plus(r: StreamRead): StreamText {
        val fresh = r.at / GEN != at / GEN && at != 0L
        val base = if (fresh) StreamText() else this
        return StreamText(keep(base.text + r.text), keep(base.thinking + r.thinking), maxOf(r.at, if (fresh) 0 else at), r.done,
            base.cut || r.skipped > 0)
    }

    companion object {
        const val GEN = 1_000_000_000_000L // streamlog.GEN: at = gen * GEN + position
        /** The phone keeps the newest 16,000 characters of each. */
        const val KEEP = 16_000

        private fun keep(s: String) = if (s.length > KEEP) s.takeLast(KEEP) else s
    }
}

object Stream {
    fun url(path: String, task: String, since: Long): String =
        "/api/stream?path=${e(path)}&task=${e(task)}&since=$since"

    fun parse(json: String): StreamRead = ApiJson.decodeFromString(StreamRead.serializer(), json)

    /** How long to wait before the next read: soon while words come, slower while it's quiet. */
    fun pauseMs(last: StreamRead, quietReads: Int): Long = when {
        last.done -> 0
        last.text.isNotEmpty() || last.thinking.isNotEmpty() -> 1_200
        else -> minOf(1_200L + quietReads * 800L, 6_000L)
    }

    private fun e(s: String) = URLEncoder.encode(s, "UTF-8")
}
