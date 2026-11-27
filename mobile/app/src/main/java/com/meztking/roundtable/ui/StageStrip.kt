package com.meztking.roundtable.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.StageRow
import com.meztking.roundtable.data.Stages
import com.meztking.roundtable.data.StagesView

/**
 * The plan's stages over the task list: one plain sentence and a chip per stage; the parts and the warnings fold
 * under "More". [load] fetches the PC's /api/stages (see [Stages.url]); nothing shows for a plan without stages
 * or an older PC.
 */
@Composable
fun StageStrip(path: String, load: suspend () -> String?) {
    var view by remember(path) { mutableStateOf<StagesView?>(null) }
    LaunchedEffect(path) { view = runCatching { Stages.parse(load()) }.getOrNull()?.takeIf { it.stages.isNotEmpty() } }
    val v = view ?: return
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (v.words.isNotBlank()) Text(v.words, color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            v.stages.forEachIndexed { i, s -> StageChip(i, s) }
        }
        val more = Stages.moreLines(v)
        if (more.isNotEmpty()) Fold("More") {
            more.forEach { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun StageChip(index: Int, s: StageRow) {
    val c = MaterialTheme.colorScheme
    val edge = when (s.state) { "now" -> c.primary; "stuck" -> c.error; else -> c.outlineVariant }
    Row(Modifier.border(1.dp, edge, RoundedCornerShape(10.dp)).padding(horizontal = 10.dp, vertical = 6.dp)
        .semantics { contentDescription = Stages.chipWords(index, s) }, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("${index + 1}", color = if (s.state == "done") c.primary else c.onSurfaceVariant, style = MaterialTheme.typography.labelMedium)
        Text(s.title, color = c.onSurface, style = MaterialTheme.typography.labelMedium)
        Text("${s.done}/${s.total}", color = c.onSurfaceVariant, style = MaterialTheme.typography.labelSmall)
    }
}
