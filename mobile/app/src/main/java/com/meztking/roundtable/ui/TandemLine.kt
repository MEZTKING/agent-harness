package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Tandem
import com.meztking.roundtable.data.TandemTask
import com.meztking.roundtable.ui.theme.Hall

/**
 * Who built a task and who checked it, in one line under the task ("Built by Claude Opus · checked by GPT and
 * Gemini · they disagreed"); each try, why a rival won and what each checker said fold under "More". Nothing shows
 * for a task nobody has built yet. [task] is one entry of the PC's /api/tandem (see [Tandem.url]), loaded once per
 * project by the screen that lists the tasks.
 */
@Composable
fun TandemLine(task: TandemTask?) {
    val t = task ?: return
    val line = Tandem.line(t)
    if (line.isBlank()) return
    Column(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(line, Modifier.semantics { contentDescription = line }, color = if (t.disagreed) Hall.warn else Hall.muted,
            style = MaterialTheme.typography.bodySmall)
        val more = Tandem.foldLines(t)
        if (more.isNotEmpty()) Fold("More") {
            more.forEach { Text(it, color = Hall.text, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 2.dp)) }
        }
    }
}
