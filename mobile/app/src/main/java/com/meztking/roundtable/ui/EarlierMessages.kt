package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Letters
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.ui.theme.Hall

// The Letters screen became the chat in 1.5.0 (ChatScreen.kt); the old letters stay readable, folded at the top of
// each chat under "Earlier messages" (this file).

/**
 * One old letter as the chat shows it under "Earlier messages" (1.5.0: Letters became the chat; nothing in the hub
 * was deleted). [kind]: "letter" (between the owner and a project), "command" (a `roundtable:` command, one plain
 * line), "agent" (agents speaking to each other: grey, folded, can't be answered).
 */
data class EarlierLine(val id: String, val at: String, val kind: String, val text: String, val more: String = "")

object Earlier {
    private val COMMAND_WORDS = mapOf(
        "run" to "build", "carry_on" to "carry on", "approve" to "approve the plan and build", "choose" to "choose an option",
        "answer" to "answer a question", "note" to "tell the planner something", "revise" to "change the plan", "looks" to "make new looks",
        "show_it" to "show pictures", "retry" to "try a task again", "skip" to "leave a task out", "accept" to "accept a task",
        "autopilot" to "switch autopilot", "profile" to "change the models", "todo_done" to "mark a to-do done", "ask" to "answer a question",
        "steer" to "steer the task working now", "shared_settings" to "change shared settings",
    )

    /** The letters of one chat, oldest first: [mine] is the owner's own name in the hub. */
    fun lines(messages: List<Message>, mine: String): List<EarlierLine> = messages.sortedBy { it.created_at }.map { m ->
        val toMe = m.recipient == mine
        val fromMe = m.sender == mine
        when {
            m.kind == "request" && m.subject.startsWith("roundtable:") -> {
                val action = m.subject.removePrefix("roundtable:").trim()
                EarlierLine(m.id, m.created_at, "command",
                    com.meztking.roundtable.data.Words.t("You asked it to {what}.", "what" to (COMMAND_WORDS[action] ?: action.replace('_', ' '))))
            }
            fromMe -> EarlierLine(m.id, m.created_at, "letter", com.meztking.roundtable.data.Words.t("You: {words}", "words" to m.subject.ifBlank { m.body.take(80) }), m.body)
            toMe -> EarlierLine(m.id, m.created_at, "letter", "${m.sender}: " + Letters.plain(m).let { it.title.ifBlank { m.subject } }, m.body)
            else -> EarlierLine(m.id, m.created_at, "agent", com.meztking.roundtable.data.Words.t("{from} told {to}: {what}",
                "from" to m.sender, "to" to m.recipient, "what" to m.subject.ifBlank { m.body.take(60) }), m.body)
        }
    }
}

/** "Earlier messages", folded at the top of a chat: the old letters, read only. */
@Composable
fun EarlierMessages(lines: List<EarlierLine>) {
    if (lines.isEmpty()) return
    var open by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth()) {
        Text(if (open) com.meztking.roundtable.data.Words.t("Hide earlier messages")
            else com.meztking.roundtable.data.Words.t("Earlier messages ({n})", "n" to lines.size),
            color = Hall.gold, style = MaterialTheme.typography.bodySmall, modifier = Modifier.clickable { open = !open }.padding(vertical = 6.dp))
        if (open) lines.forEach { l -> EarlierRow(l) }
    }
}

@Composable
private fun EarlierRow(l: EarlierLine) {
    var more by rememberSaveable(l.id) { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 3.dp).clickable(enabled = l.more.isNotBlank()) { more = !more }) {
        Text(l.text, color = if (l.kind == "letter") Hall.text else Hall.muted, style = MaterialTheme.typography.bodySmall,
            maxLines = if (more) Int.MAX_VALUE else 2, overflow = TextOverflow.Ellipsis)
        Text(ago(l.at) + if (l.more.isNotBlank() && !more) " · " + com.meztking.roundtable.data.Words.t("More") else "",
            color = Hall.muted, style = MaterialTheme.typography.labelSmall)
        if (more) Text(l.more, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}
