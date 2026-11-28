package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.AnswerSeveralResult
import com.meztking.roundtable.data.AnswerThese
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * Answer these, on the Table and a project's plan: with three or more cards waiting, a bar; open, a tick beside each
 * card that may take its recommended answer, and the others greyed with "Answer this one by itself". [send] posts the
 * ticked ones (POST /api/board/answer-several); what was left and why is listed after. Nothing shows for fewer cards.
 */
@Composable
fun AnswerTheseBar(cards: List<Ask>, send: suspend (List<Triple<String, String, String>>) -> String, onAlone: (Ask) -> Unit = {},
                   onDone: () -> Unit = {}) {
    if (!AnswerThese.shown(cards)) return
    val scope = rememberCoroutineScope()
    var open by remember { mutableStateOf(false) }
    var ticked by remember(cards) { mutableStateOf(AnswerThese.ticked(cards)) }
    var busy by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<AnswerSeveralResult?>(null) }
    var said by remember { mutableStateOf<String?>(null) }
    AnswerTheseView(cards, open, ticked, busy, result, said,
        onOpen = { open = !open; said = null },
        onTick = { id -> ticked = if (id in ticked) ticked - id else ticked + id },
        onAlone = onAlone,
        onSend = {
            val items = AnswerThese.items(cards, ticked)
            if (items.isNotEmpty() && !busy) scope.launch {
                busy = true; said = null
                try { result = AnswerThese.parse(send(items)); onDone() }
                catch (e: CancellationException) { throw e } catch (e: Exception) { said = friendly(e) }
                finally { busy = false }
            }
        })
}

@Composable
fun AnswerTheseView(cards: List<Ask>, open: Boolean, ticked: Set<String>, busy: Boolean, result: AnswerSeveralResult?, said: String?,
                    onOpen: () -> Unit = {}, onTick: (String) -> Unit = {}, onAlone: (Ask) -> Unit = {}, onSend: () -> Unit = {}) {
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(Words.t("ANSWER THESE"), style = Label, color = Hall.muted)
                Text(AnswerThese.barLine(cards), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            }
            TextButton(onOpen) { Text(if (open) Words.t("Close") else Words.t("Answer these")) }
        }
        if (result != null) {
            Text(result.reply, Modifier.padding(top = 6.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            val left = AnswerThese.leftLines(result, cards)
            if (left.isNotEmpty()) {
                Text(Words.t("LEFT FOR YOU, AND WHY"), Modifier.padding(top = 6.dp), style = Label, color = Hall.muted)
                left.forEach { Text("• $it", color = Hall.text, style = MaterialTheme.typography.bodySmall) }
            }
        }
        said?.let { Text(it, Modifier.padding(top = 4.dp), color = Hall.bad, style = MaterialTheme.typography.bodySmall) }
        if (!open) return@Panel
        cards.forEach { c ->
            val why = AnswerThese.alone(c)
            val rec = c.options.firstOrNull { it.id == c.recommended }?.label.orEmpty()
            Row(Modifier.fillMaxWidth().padding(top = 6.dp).alpha(if (why.isEmpty()) 1f else 0.55f)
                .clickable(enabled = why.isEmpty() && !busy, role = Role.Checkbox) { onTick(c.id) },
                verticalAlignment = Alignment.CenterVertically) {
                Checkbox(why.isEmpty() && c.id in ticked, null, enabled = why.isEmpty() && !busy)
                Spacer(Modifier.width(6.dp))
                Column(Modifier.weight(1f)) {
                    Text(c.question, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(if (why.isEmpty()) Words.t("Recommended: {answer}", "answer" to rec) else why, color = Hall.muted,
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            if (why.isNotEmpty()) TextButton({ onAlone(c) }, Modifier.padding(start = 40.dp)) { Text(Words.t("Answer this one by itself")) }
        }
        val n = AnswerThese.items(cards, ticked).size
        Button(onSend, Modifier.fillMaxWidth().padding(top = 8.dp), enabled = n > 0 && !busy,
            colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
            Text(Words.t("Use the recommended answer for the ticked ones") + " ($n)")
        }
    }
}
