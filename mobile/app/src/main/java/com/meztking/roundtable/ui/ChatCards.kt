package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.ChatCard
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.ui.theme.Hall

/**
 * A chat card: what the chat offers to do, as the app built it (title, one sentence, the price) and its buttons. Only
 * a tap on one of them does anything; one that can't be undone asks "Are you sure?" first. Its states: open, queued
 * (for a machine, with "Run it on This phone instead"), running, done, cancelled. The rest is behind "More".
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatCardView(card: ChatCard, onTap: (button: String, confirmed: Boolean) -> Unit, busy: Boolean = false) {
    var asking by remember(card.id) { mutableStateOf<String?>(null) }
    var more by remember(card.id) { mutableStateOf(false) }
    val live = card.state == "open" || card.state == "queued"
    Column(
        Modifier.fillMaxWidth().background(if (live) Hall.panelHi else Hall.panel, RoundedCornerShape(12.dp))
            .border(1.dp, if (live) Hall.gold else Hall.line, RoundedCornerShape(12.dp)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (card.title.isNotBlank()) Text(card.title, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyLarge)
        if (card.line.isNotBlank() && card.line != card.title) Text(card.line, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        stateWords(card)?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        if (live && card.buttons.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            card.buttons.forEach { b ->
                val tap = { if (b.id == "do" && card.confirm != null) asking = b.id else if (b.id == "raise_today") asking = b.id else onTap(b.id, false) }
                if (b.primary) Button(tap, enabled = !busy, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text(b.words) }
                else OutlinedButton(tap, enabled = !busy) { Text(b.words) }
            }
        }
        if (!card.more.isNullOrBlank()) {
            Text(if (more) Words.t("Less") else Words.t("More"), color = Hall.gold, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.clickable { more = !more }.semantics { contentDescription = Words.t("More about this card") })
            if (more) Text(card.more, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    asking?.let { b ->
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(Words.t("Are you sure?")) },
            text = { Text(if (b == "raise_today") Words.t("Raise today's chat allowance? It goes back to the usual limit tomorrow.") else card.confirm.orEmpty()) },
            confirmButton = { TextButton({ asking = null; onTap(b, true) }) { Text(if (b == "raise_today") Words.t("Raise it for today") else Words.t("Do it")) } },
            dismissButton = { TextButton({ asking = null }) { Text(Words.t("Cancel")) } },
        )
    }
}

/** The small grey line under a card: where it waits, or how it ended. */
fun stateWords(card: ChatCard): String? = when (card.state) {
    "queued" -> card.queuedFor?.let { Words.t("Queued for {who}", "who" to it) } ?: Words.t("Queued")
    "running" -> Words.t("Running now")
    "done" -> Words.t("Done")
    "cancelled" -> Words.t("Not done")
    else -> null
}
