package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.ApiRewind
import com.meztking.roundtable.data.Rewind
import com.meztking.roundtable.data.RewindPreview
import com.meztking.roundtable.data.RewindSource
import com.meztking.roundtable.data.UNDO_TASK
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import kotlinx.coroutines.launch

/**
 * Undo a finished task from the phone (the PC's /api/rewind): the two ways back, the files that change, then
 * Undo it. [onDone] gets the words to show ("" when the sheet was closed without changing anything).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RewindSheet(api: Api, path: String, task: String, onDone: (String) -> Unit) {
    val source = remember(api, path) { ApiRewind(api, path) }
    ModalBottomSheet(onDismissRequest = { onDone("") }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = Hall.panel, contentColor = Hall.text) {
        RewindPanel(source, task, onDone, Modifier.padding(horizontal = 16.dp), project = Rewind.folderName(path))
    }
}

/** The sheet's insides, over any [RewindSource] (a stand-in in tests). */
@Composable
fun RewindPanel(source: RewindSource, task: String, onDone: (String) -> Unit, modifier: Modifier = Modifier, project: String = "") {
    var mode by remember { mutableStateOf(UNDO_TASK) }
    var preview by remember { mutableStateOf<RewindPreview?>(null) }
    var error by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(task, mode) {
        preview = null; error = ""
        runCatching { source.preview(task, mode) }.onSuccess { preview = it }.onFailure { error = it.message ?: "Couldn't reach the PC." }
    }
    RewindBody(preview, mode, error, busy, modifier,
        onMode = { mode = it },
        onApply = {
            val p = preview ?: return@RewindBody
            busy = true
            scope.launch {
                runCatching { source.apply(task, p.mode, p.stamp) }
                    .onSuccess { busy = false; onDone(it.words) }
                    .onFailure { busy = false; error = it.message ?: "That didn't work. Try again." }
            }
        },
        onTryAnother = {
            busy = true
            scope.launch {
                runCatching { source.fork(task, Rewind.copyName(project)) }
                    .onSuccess { busy = false; onDone(it.words) }
                    .onFailure { busy = false; error = it.message ?: "Couldn't make the copy." }
            }
        },
        onCancel = { onDone("") })
}

/** Stateless, so it can be drawn in tests: the choice of way back, the one sentence, the files (more folded). */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun RewindBody(preview: RewindPreview?, mode: String, error: String, busy: Boolean, modifier: Modifier = Modifier,
               onMode: (String) -> Unit = {}, onApply: () -> Unit = {}, onTryAnother: () -> Unit = {}, onCancel: () -> Unit = {}) {
    var more by remember { mutableStateOf(false) }
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(preview?.title?.let { "Undo “$it”?" } ?: "Undo this task?", style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold, color = Hall.text)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Rewind.MODES.forEach { (m, label, _) ->
                if (m == mode) Button(onClick = {}, enabled = !busy) { Text(label) }
                else OutlinedButton(onClick = { onMode(m) }, enabled = !busy) { Text(label) }
            }
        }
        Text(Rewind.MODES.first { it.first == mode }.third, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        when {
            error.isNotBlank() -> Text(error, color = Hall.bad)
            preview == null -> Row { CircularProgressIndicator(color = Hall.gold) }
            else -> {
                Text(preview.words, color = if (preview.blocked.isBlank()) Hall.text else Hall.bad)
                if (preview.blocked.isBlank()) {
                    val (first, folded) = Rewind.firstFiles(preview.files)
                    (if (more) preview.files else first).forEach { Text(Rewind.fileLine(it), style = MaterialTheme.typography.bodySmall, color = Hall.text) }
                    if (folded > 0 && !more) TextButton(onClick = { more = true }) { Text("More ($folded)", color = Hall.gold) }
                    Rewind.handEdits(preview)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Hall.muted) }
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = onCancel, enabled = !busy) { Text("Cancel", color = Hall.muted) }
            Spacer(Modifier.weight(1f))
            Button(onClick = onApply, enabled = !busy && Rewind.canApply(preview),
                colors = ButtonDefaults.buttonColors(containerColor = Hall.bad, contentColor = Hall.text)) { Text("Undo it") }
        }
        TextButton(onClick = onTryAnother, enabled = !busy && preview != null) {
            Text("Or try another way: a separate copy from here (costs nothing until you run it)", color = Hall.gold)
        }
        Text("Nothing is lost: Put it back undoes this, from the project's history on the PC.", style = MaterialTheme.typography.bodySmall,
            color = Hall.muted)
    }
}
