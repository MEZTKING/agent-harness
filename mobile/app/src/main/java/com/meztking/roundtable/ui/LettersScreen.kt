package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Serif

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LettersScreen(
    letters: Load<List<Message>>, identity: String, projects: List<String>,
    onRefresh: () -> Unit, onOpened: (Message) -> Unit,
    onSend: (String, String, String, Done) -> Unit, onReply: (Message, String, Done) -> Unit,
) {
    var mineOnly by rememberSaveable { mutableStateOf(true) }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var writing by rememberSaveable { mutableStateOf(false) }
    val all = letters.data.orEmpty()
    val mine = all.filter { it.recipient == identity }
    val shown = if (mineOnly) mine else all
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Text("Letters", style = MaterialTheme.typography.headlineSmall, color = Hall.goldBright, modifier = Modifier.padding(start = 16.dp, top = 12.dp))
            Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(mineOnly, { mineOnly = true }, label = { Text("For me (${mine.count { !it.read }} new)") })
                FilterChip(!mineOnly, { mineOnly = false }, label = { Text("All inboxes") })
            }
            PullToRefreshBox(letters.loading && letters.data != null, onRefresh, Modifier.weight(1f)) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (letters.error != null) item { ErrorLine(letters.error, onRefresh) }
                    if (letters.data == null && letters.loading) item { Loading("Fetching the letters…") }
                    if (letters.data != null && shown.isEmpty()) item {
                        Text(if (mineOnly) "No letters for you ($identity). Letters your projects send you arrive here." else "No letters in any inbox.",
                            color = Hall.muted, modifier = Modifier.padding(vertical = 24.dp))
                    }
                    items(shown, key = { it.recipient + "/" + it.id }) { m ->
                        LetterRow(m, showTo = !mineOnly) { open = m.recipient + "/" + m.id; onOpened(m) }
                    }
                }
            }
        }
        ExtendedFloatingActionButton(
            onClick = { writing = true }, icon = { Icon(Icons.Filled.Edit, null) }, text = { Text("Write") },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp), containerColor = Hall.gold, contentColor = Hall.ink,
        )
    }
    all.firstOrNull { it.recipient + "/" + it.id == open }?.let { m ->
        MessageSheet(m, identity, onDismiss = { open = null }, onReply = { body, done -> onReply(m, body) { ok -> done(ok); if (ok) open = null } })
    }
    if (writing) ComposeSheet(projects, identity, null, onDismiss = { writing = false }) { to, s, b, done -> onSend(to, s, b) { ok -> done(ok); if (ok) writing = false } }
}

@Composable
fun LetterRow(m: Message, showTo: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(if (m.read) Hall.panel else Hall.panelHi)
        .border(1.dp, if (m.read) Hall.line else Hall.lineGold, RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(12.dp)) {
        Box(Modifier.padding(top = 6.dp).size(8.dp).background(if (m.read) Hall.line else Hall.amber, CircleShape))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (showTo) "${m.sender} → ${m.recipient}" else m.sender, style = MaterialTheme.typography.bodySmall, color = Hall.gold,
                    modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(ago(m.created_at), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            }
            Text(m.subject.ifBlank { "(no subject)" }, fontFamily = Serif, fontWeight = if (m.read) FontWeight.Normal else FontWeight.SemiBold,
                fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(com.meztking.roundtable.data.Markdown.plain(m.body).replace("\n", " "), style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** One letter, read in full, with a reply box under it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessageSheet(m: Message, identity: String, onDismiss: () -> Unit, onReply: (String, Done) -> Unit) {
    var reply by rememberSaveable(m.id) { mutableStateOf("") }
    var sending by rememberSaveable(m.id) { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = Hall.panel, contentColor = Hall.text) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).navigationBarsPadding().imePadding().verticalScroll(rememberScrollState())) {
            Text("${m.sender} → ${m.recipient} · ${m.kind}", style = MaterialTheme.typography.bodySmall, color = Hall.gold)
            Text(m.subject.ifBlank { "(no subject)" }, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
            Text(m.created_at.replace('T', ' ').removeSuffix("Z") + " UTC · " + ago(m.created_at), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Spacer(Modifier.height(12.dp))
            SelectionContainer {
                MdBlocks(com.meztking.roundtable.data.Markdown.parse(m.body))
            }
            Spacer(Modifier.height(16.dp))
            val to = if (m.sender == identity) m.recipient else m.sender
            Text("REPLY TO ${to.uppercase()}", style = Label)
            OutlinedTextField(reply, { reply = it }, Modifier.fillMaxWidth().heightIn(min = 100.dp), placeholder = { Text("Write your answer…") })
            Spacer(Modifier.height(8.dp))
            Button(onClick = { sending = true; onReply(reply.trim()) { ok -> sending = false; if (ok) reply = "" } },
                enabled = reply.isNotBlank() && !sending, modifier = Modifier.align(Alignment.End)) {
                Icon(Icons.AutoMirrored.Filled.Send, null, Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text(if (sending) "Sending…" else "Send reply")
            }
            Spacer(Modifier.height(20.dp))
        }
    }
}

/** Write a new letter from the owner to a project. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ComposeSheet(projects: List<String>, identity: String, fixedTo: String?, onDismiss: () -> Unit, onSend: (String, String, String, Done) -> Unit) {
    var to by rememberSaveable { mutableStateOf(fixedTo ?: projects.firstOrNull { it != identity }.orEmpty()) }
    var subject by rememberSaveable { mutableStateOf("") }
    var body by rememberSaveable { mutableStateOf("") }
    var menu by rememberSaveable { mutableStateOf(false) }
    var sending by rememberSaveable { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = Hall.panel, contentColor = Hall.text) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).navigationBarsPadding().imePadding().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("A NEW LETTER", style = Label)
            Text("From $identity", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            if (fixedTo != null) Text("To $fixedTo", style = MaterialTheme.typography.titleMedium, color = Hall.goldBright)
            else ExposedDropdownMenuBox(menu, { menu = it }) {
                OutlinedTextField(to, {}, readOnly = true, label = { Text("To") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(menu) },
                    modifier = Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryNotEditable))
                ExposedDropdownMenu(menu, { menu = false }) {
                    projects.forEach { p -> DropdownMenuItem(text = { Text(p) }, onClick = { to = p; menu = false }) }
                }
            }
            OutlinedTextField(subject, { subject = it }, Modifier.fillMaxWidth(), label = { Text("Subject") }, singleLine = true)
            OutlinedTextField(body, { body = it }, Modifier.fillMaxWidth().heightIn(min = 140.dp), label = { Text("Letter") })
            Text("It arrives in the project's inbox; its next session reads it.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Button(onClick = { sending = true; onSend(to, subject.trim(), body.trim()) { sending = false } },
                enabled = to.isNotBlank() && subject.isNotBlank() && body.isNotBlank() && !sending, modifier = Modifier.align(Alignment.End)) {
                Icon(Icons.AutoMirrored.Filled.Send, null, Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text(if (sending) "Sending…" else "Send")
            }
            Spacer(Modifier.height(20.dp))
        }
    }
}
