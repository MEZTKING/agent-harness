package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Council
import com.meztking.roundtable.data.CouncilView

/**
 * Where the planners disagreed, under the plan's summary: one line ("Three planners agreed on most of it; they
 * differed on 2 things"), the points on a tap, who planned behind More. Nothing for a plan made by one planner.
 */
@Composable
fun CouncilFold(path: String, load: suspend () -> String?) {
    var view by remember(path) { mutableStateOf<CouncilView?>(null) }
    LaunchedEffect(path) { view = runCatching { Council.parse(load()) }.getOrNull() }
    view?.let { CouncilFold(it) }
}

@Composable
fun CouncilFold(v: CouncilView) {
    val c = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Fold(Council.line(v)) {
            if (v.disagreements.isEmpty()) Text("They didn't differ on anything that mattered.", color = c.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall)
            v.disagreements.forEach { p ->
                Text(p.topic, Modifier.padding(top = 6.dp), color = c.onSurface, style = MaterialTheme.typography.bodyMedium)
                Council.pointLines(p).forEach {
                    Text(it, Modifier.padding(start = 8.dp), color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                }
            }
            val more = Council.moreLines(v)
            if (more.isNotEmpty()) Fold("More") {
                more.forEach { Text(it, color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
            }
        }
    }
}
