package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.meztking.roundtable.data.Follow
import com.meztking.roundtable.data.FollowItem
import com.meztking.roundtable.data.FollowReply
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Follow-ups to one finished task: what was asked before, and the box. */
interface FollowSource {
    suspend fun earlier(): List<FollowItem>
    suspend fun send(text: String, mode: String, confirmed: Boolean): FollowReply
}

class ApiFollow(private val api: Api, private val path: String, private val task: String) : FollowSource {
    override suspend fun earlier() = Follow.parse(api.feature("GET", Follow.url(path, task)))
    override suspend fun send(text: String, mode: String, confirmed: Boolean) =
        Follow.parseReply(api.slowFeature("POST", Follow.POST, Follow.body(path, task, text, mode, confirmed)))
}

/**
 * A follow-up to a finished task: Ask (the model that built it answers; the price shows first and nothing is spent
 * until you say yes) or Change it (a new task that builds on it). The answers show under the task.
 */
@Composable
fun FollowBox(task: String, source: FollowSource, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var items by remember(task) { mutableStateOf<List<FollowItem>>(emptyList()) }
    var text by remember(task) { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var said by remember { mutableStateOf<String?>(null) }
    var price by remember { mutableStateOf<Pair<String, FollowReply>?>(null) }
    LaunchedEffect(task) { items = runCatching { source.earlier() }.getOrDefault(emptyList()) }

    fun go(mode: String, confirmed: Boolean) = scope.launch {
        busy = true
        try {
            val r = source.send(text, mode, confirmed)
            when {
                r.confirm.isNotBlank() && !confirmed -> price = mode to r
                else -> { said = r.reply.ifBlank { "Sent." }; text = ""; items = runCatching { source.earlier() }.getOrDefault(items) }
            }
        } catch (e: CancellationException) { throw e } catch (e: Exception) { said = friendly(e) } finally { busy = false }
    }

    FollowView(task, items, text, busy, said, onText = { text = it; said = null }, onAsk = { go("ask", false) },
        onChange = { go("change", false) }, onClose = onClose)
    price?.let { (mode, p) ->
        AlertDialog(
            onDismissRequest = { price = null },
            title = { Text(if (mode == "ask") "Ask it?" else "Are you sure?") },
            text = { Text(p.confirm) },
            confirmButton = { TextButton(onClick = { price = null; go(mode, true) }) { Text(if (mode == "ask") "Ask" else "Do it") } },
            dismissButton = { TextButton(onClick = { price = null }) { Text("Not now") } },
        )
    }
}

@Composable
fun FollowView(task: String, items: List<FollowItem>, text: String, busy: Boolean, said: String?,
               onText: (String) -> Unit = {}, onAsk: () -> Unit = {}, onChange: () -> Unit = {}, onClose: () -> Unit = {}) {
    Column(Modifier.fillMaxWidth().padding(start = 22.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (i in items.takeLast(5)) {
            Text(i.question.ifBlank { i.change }, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodySmall)
            if (i.answer.isNotBlank()) Text(i.answer, color = Hall.text, style = MaterialTheme.typography.bodySmall)
            else if (i.change.isNotBlank()) Text("Made into a new task.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
        OutlinedTextField(text, onText, Modifier.fillMaxWidth().heightIn(min = 56.dp), enabled = !busy,
            placeholder = { Text("Ask about $task, or say what to change") })
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onAsk, enabled = !busy && text.isNotBlank()) { Text("Ask") }
            OutlinedButton(onChange, enabled = !busy && text.isNotBlank()) { Text("Change it") }
            TextButton(onClose) { Text("Close") }
        }
        Text("Ask shows the price first. Change it adds a new task that builds on this one.", color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
        said?.let { Text(it, color = Hall.good, style = MaterialTheme.typography.bodySmall) }
    }
}
