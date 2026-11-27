package com.meztking.roundtable.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.SentItem
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.rememberHaptics

/** How many sent things show before "Show all" (short first). */
const val SENT_SHOWN = 3

/**
 * What the owner sent to this project from this phone, newest first: the last [SENT_SHOWN], the rest folded.
 * Press and hold one to copy it, or to edit it and send it again ([onResend]; null where it can't be sent from here).
 */
@Composable
fun SentHistory(items: List<SentItem>, onResend: ((SentItem) -> Unit)?, modifier: Modifier = Modifier) {
    if (items.isEmpty()) return
    var editing by remember { mutableStateOf<SentItem?>(null) }
    Column(modifier.fillMaxWidth()) {
        Fold("What you sent from this phone (${items.size})") {
            Text("Press and hold one to copy it or send it again.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(6.dp))
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items.take(SENT_SHOWN).forEach { SentRow(it, onEdit = onResend?.let { { editing = it } }) }
            }
            if (items.size > SENT_SHOWN) Fold("Show all ${items.size}") {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items.drop(SENT_SHOWN).forEach { SentRow(it, onEdit = onResend?.let { { editing = it } }) }
                }
            }
        }
    }
    val send = onResend
    editing?.let { item ->
        if (send != null) EditAndSend(item, onDismiss = { editing = null }) { send(it); editing = null }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SentRow(item: SentItem, onEdit: ((SentItem) -> Unit)?) {
    var menu by remember { mutableStateOf(false) }
    val clip = LocalClipboardManager.current
    val buzz = rememberHaptics()
    Box {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Hall.bgDeep)
            .combinedClickable(onClickLabel = "Show what to do with it", onLongClickLabel = "Copy or send again",
                onClick = { menu = true }, onLongClick = { buzz(); menu = true })
            .padding(10.dp)) {
            val head = listOfNotNull(if (item.kind == SentItem.LETTER) "Letter" else "Note to the planner",
                item.at.ifBlank { null }?.let { ago(it) }).joinToString(" · ")
            Text(head, color = Hall.muted, style = MaterialTheme.typography.labelMedium)
            if (item.subject.isNotBlank()) Text(item.subject, color = Hall.text, style = MaterialTheme.typography.bodyMedium, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            Text(item.text, color = Hall.text, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        DropdownMenu(menu, { menu = false }, containerColor = Hall.panel) {
            DropdownMenuItem(text = { Text("Copy") }, onClick = {
                clip.setText(AnnotatedString(if (item.subject.isBlank()) item.text else item.subject + "\n\n" + item.text)); menu = false
            })
            if (onEdit != null) DropdownMenuItem(text = { Text("Edit and send again") }, onClick = { menu = false; onEdit(item) })
        }
    }
}

/** The sent thing in a box to change, then Send again (a letter keeps its subject). */
@Composable
fun EditAndSend(item: SentItem, onDismiss: () -> Unit, onSend: (SentItem) -> Unit) {
    var subject by rememberSaveable(item) { mutableStateOf(item.subject) }
    var text by rememberSaveable(item) { mutableStateOf(item.text) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (item.kind == SentItem.LETTER) "Send this letter again" else "Send this note again") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.kind == SentItem.LETTER) OutlinedTextField(subject, { subject = it }, Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text("Subject") })
                OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().heightIn(min = 100.dp), label = { Text("Message") })
                if (item.kind == SentItem.NOTE) Text("It waits in the plan until you press Update plan.", color = Hall.muted,
                    style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton(onClick = { onSend(item.copy(subject = subject.trim(), text = text.trim(), at = "")) },
                enabled = text.isNotBlank() && (item.kind != SentItem.LETTER || subject.isNotBlank())) { Text("Send again") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        containerColor = Hall.panelHi,
    )
}
