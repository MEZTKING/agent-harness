package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Stream
import com.meztking.roundtable.data.StreamRead
import com.meztking.roundtable.data.StreamText
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/**
 * A task's reply as it is being written (GET /api/stream), read again every second or so while words come and less
 * often while it's quiet; it stops once the reply is finished. The thinking is folded under its own line.
 */
@Composable
fun StreamWords(task: String, read: suspend (since: Long) -> StreamRead, modifier: Modifier = Modifier) {
    var s by remember(task) { mutableStateOf(StreamText()) }
    LaunchedEffect(task) {
        var quiet = 0
        while (true) {
            val r = try { read(s.at) } catch (e: CancellationException) { throw e } catch (_: Exception) { null }
            if (r == null) { delay(6_000); continue }  // a missed read: the words wait, nothing is shown as an error
            s = s.plus(r)
            if (r.done) break
            quiet = if (r.text.isEmpty() && r.thinking.isEmpty()) quiet + 1 else 0
            delay(Stream.pauseMs(r, quiet))
        }
    }
    StreamWordsView(s, modifier)
}

/** The words drawn from [s] (tests and pictures use this with made-up words). Nothing at all while there are none. */
@Composable
fun StreamWordsView(s: StreamText, modifier: Modifier = Modifier) {
    if (s.empty) return
    Panel(modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (s.done) "WHAT IT WROTE" else "WORDS AS THEY ARE WRITTEN", Modifier.weight(1f), style = Label, color = Hall.muted)
            if (!s.done) Text("● Writing", color = Hall.good, style = MaterialTheme.typography.labelMedium)
        }
        if (s.cut) Text("Only the newest part is kept here.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        if (s.text.isNotBlank()) Text(s.text.trim(), Modifier.padding(top = 6.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        else if (!s.done) Text("Thinking first…", Modifier.padding(top = 6.dp), color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        if (s.thinking.isNotBlank()) {
            val n = s.thinking.trim().split(Regex("\\s+")).size
            Fold("Its thinking ($n word${if (n == 1) "" else "s"})") {
                Text(s.thinking.trim(), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
