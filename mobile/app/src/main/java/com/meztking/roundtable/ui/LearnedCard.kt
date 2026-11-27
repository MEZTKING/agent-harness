package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Learned
import com.meztking.roundtable.data.LearnedLine
import com.meztking.roundtable.data.LearnedView
import com.meztking.roundtable.net.Api
import kotlinx.coroutines.launch

/**
 * What the harness learned, with an Undo on each line. Only with a PC or this phone's own harness ([api] null:
 * nothing shows, as Hub mode has no lab). Using or turning down a waiting change stays on the PC.
 */
@Composable
fun LearnedCard(api: Api?) {
    if (api == null) return
    var view by remember(api) { mutableStateOf<LearnedView?>(null) }
    var note by remember(api) { mutableStateOf("") }
    var asking by remember(api) { mutableStateOf<LearnedLine?>(null) }
    var busy by remember(api) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(api) { view = runCatching { Learned.parse(api.feature("GET", Learned.URL)) }.getOrNull() }
    val v = view ?: return
    val c = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(10.dp))
        .border(1.dp, c.outlineVariant, RoundedCornerShape(10.dp)).background(c.surfaceVariant).padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("What it learned", color = c.onSurface, style = MaterialTheme.typography.titleSmall)
        Text(Learned.summary(v), color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        if (v.wallet.words.isNotBlank()) Text(v.wallet.words, color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        if (note.isNotBlank()) Text(note, color = c.error, style = MaterialTheme.typography.bodySmall)
        v.lines.take(20).forEach { l ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(Learned.line(l), color = if (l.state == "undone") c.onSurfaceVariant else c.onSurface,
                        style = MaterialTheme.typography.bodySmall)
                    Text(Learned.byWords(l), color = c.onSurfaceVariant, style = MaterialTheme.typography.labelSmall)
                }
                if (l.can_undo) TextButton({ asking = l }, enabled = !busy) { Text("Undo", color = c.error) }
            }
        }
        if (v.never.isNotEmpty()) Fold("What it can never change") {
            v.never.forEach { Text("· $it", color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
        }
    }
    asking?.let { l ->
        AlertDialog(onDismissRequest = { asking = null },
            title = { Text("Undo this change?") },
            text = { Text("Only this change is taken out; everything else stays. It can be put back on the PC.") },
            confirmButton = {
                TextButton({
                    asking = null; busy = true
                    scope.launch {
                        val r = runCatching { api.feature("POST", Learned.UNDO_URL, Learned.undoBody(l.id)) }
                        note = if (r.isSuccess) "" else "Couldn't undo it: check the PC is on, then try again."
                        Learned.parse(r.getOrNull())?.let { view = it }
                        busy = false
                    }
                }) { Text("Undo", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton({ asking = null }) { Text("Keep it") } })
    }
}
