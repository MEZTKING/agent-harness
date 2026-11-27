package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.Asks
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.PlanDoc
import com.meztking.roundtable.data.PlanView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.Task
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.Parchment
import com.meztking.roundtable.ui.theme.ParchmentButtons
import com.meztking.roundtable.ui.theme.Serif

/** Everything the project screen draws, so it can be shown in previews and tests without a ViewModel. */
data class ProjectUi(
    val id: String,
    val seat: SeatView?,
    val mode: Mode?,
    val identity: String,
    val status: Load<StatusDoc>,
    val plan: Load<PlanView>,
    val inbox: Load<List<Message>>,
    val sent: Map<String, String> = emptyMap(),
    /** The questions waiting on this project, as cards to tap (asks.py). */
    val asks: Load<List<Ask>> = Load(),
    /** The newest pictures of the app and the latest task's steps (the Live tab). */
    val live: Load<com.meztking.roundtable.data.LiveView> = Load(),
)

class ProjectActions(
    val back: () -> Unit = {},
    val refresh: () -> Unit = {},
    val command: (key: String, action: String, fields: Map<String, Any?>) -> Unit = { _, _, _ -> },
    val act: (String) -> Unit = {},
    val opened: (Message) -> Unit = {},
    val reply: (Message, String, Done) -> Unit = { _, _, _ -> },
    val send: (String, String, Done) -> Unit = { _, _, _ -> },
    val answer: (Ask, AskReply) -> Unit = { _, _ -> },
    /** This project's own settings; null when no connected machine has it. */
    val settings: (() -> Unit)? = null,
)

@Composable
fun ProjectScreen(ui: ProjectUi, a: ProjectActions, initialTab: Int = 0) {
    var tab by rememberSaveable { mutableIntStateOf(initialTab) }
    com.meztking.roundtable.notify.QuietWhileOpen(ui.id)  // no notification for this project while it's on screen
    val doc = ui.status.data
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = a.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            if (ui.seat != null) SeatRing(ui.seat, false, 40.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(ui.id, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val updated = doc?.updated?.ifBlank { null } ?: ui.seat?.lastActivity?.ifBlank { null }
                Text(listOfNotNull(ui.seat?.building?.ifBlank { null } ?: ui.seat?.status, ui.seat?.lives?.ifBlank { null }?.takeIf { ui.seat?.building.isNullOrBlank() },
                    updated?.let { "updated ${ago(it)}" }).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            a.settings?.let { open -> TipIcon("This project's settings", open) { Icon(Icons.Filled.Settings, "This project's settings", tint = Hall.gold) } }
            IconButton(onClick = a.refresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
        }
        val desc = ui.seat?.description?.ifBlank { null } ?: doc?.description
        if (!desc.isNullOrBlank()) Text(desc, Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall, color = Hall.muted,
            maxLines = 3, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(6.dp))
        val unread = ui.inbox.data?.count { !it.read } ?: 0
        PrimaryTabRow(selectedTabIndex = tab, containerColor = Hall.bg) {
            // one line each, even on a narrow phone ("Letters", as in the bottom bar)
            val one = @Composable { t: String -> Text(t, maxLines = 1, softWrap = false, overflow = TextOverflow.Clip) }
            Tab(tab == 0, { tab = 0 }, text = { one("Status") })
            Tab(tab == 1, { tab = 1 }, text = { one(if (ui.plan.data?.doc?.waitingForOwner == true || !ui.asks.data.isNullOrEmpty()) "Plan •" else "Plan") })
            Tab(tab == 2, { tab = 2 }, text = { one(if (unread > 0) "Letters •" else "Letters") })
            Tab(tab == 3, { tab = 3 }, text = { one("Live") })
        }
        Box(Modifier.weight(1f)) {
            when (tab) {
                0 -> StatusTab(ui.status, a.refresh)
                1 -> PlanTab(ui, a)
                3 -> LiveTab(ui.live, ui.mode, a.refresh, finished = ui.seat?.status == "done" || ui.plan.data?.let { PlanTop.of(it, ui.id).finished } == true,
                    onTakePictures = { a.command("show_it", "show_it", emptyMap()) }, sent = ui.sent["show_it"])
                else -> MessagesTab(ui, a)
            }
        }
    }
}

/** Status, short first: the first part (where it left off) open, every other part folded under its title. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun StatusTab(status: Load<StatusDoc>, onRefresh: () -> Unit) {
    PullToRefreshBox(status.loading && status.data != null, onRefresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp)) {
            if (status.error != null) item { ErrorLine(status.error, onRefresh) }
            val doc = status.data
            when {
                doc == null && status.loading -> item { Loading("Reading the status page…") }
                doc == null -> {}
                doc.isEmpty -> item {
                    Text("No status page yet. It appears once a session writes to this project's journal.", color = Hall.muted,
                        modifier = Modifier.padding(vertical = 24.dp))
                }
                else -> {
                    val first = doc.sections.first()
                    item(key = "first") {
                        SectionTitle(first.title)
                        Spacer(Modifier.height(6.dp))
                        MdBlocks(first.blocks)
                        Spacer(Modifier.height(10.dp))
                    }
                    items(doc.sections.drop(1), key = { it.title }) { s ->
                        val n = s.blocks.count { it is com.meztking.roundtable.data.Md.Item }
                        Fold(if (n > 0) "${s.title} ($n)" else s.title) { MdBlocks(s.blocks) }
                    }
                }
            }
        }
    }
}

/**
 * The Plan tab, short first: the title, one sentence of where it stands, what waits for the owner, the tasks one
 * line each; everything else (the builders' brief, scope, spec, choices, the second opinion, prices) folded
 * under "More about this plan".
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlanTab(ui: ProjectUi, a: ProjectActions) {
    val plan = ui.plan
    PullToRefreshBox(plan.loading && plan.data != null, a.refresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (plan.error != null) item { ErrorLine(plan.error, a.refresh) }
            val p = plan.data
            when {
                p == null && plan.loading -> item { Loading("Reading the plan…") }
                p == null -> {}
                p.doc == null && p.tasks.isEmpty() -> item {
                    Text("No plan yet. A plan appears here when Roundtable Hold plans a run for this project.", color = Hall.muted,
                        modifier = Modifier.padding(vertical = 24.dp))
                }
                else -> calmPlan(p, ui, a)
            }
        }
    }
}

/** What the plan view shows at the top, worked out once (tests read it too). */
data class PlanTop(val title: String, val state: String, val summary: String, val estimate: String,
                   val waiting: Boolean, val finished: Boolean, val tasks: List<PlanDoc.PlanTask>) {
    companion object {
        fun of(p: PlanView, fallback: String): PlanTop {
            val d = p.doc
            val w = p.words
            val tasks = d?.tasks?.takeIf { it.isNotEmpty() } ?: p.tasks.map { PlanDoc.PlanTask(it.id, it.status, it.title, it.role) }
            val finished = d?.finished ?: (p.runStatus == "done")
            val waiting = !finished && (d?.waitingForOwner ?: p.canApprove)
            val state = w?.state?.ifBlank { null } ?: d?.stateSentence() ?: when {
                finished -> "Finished – ${tasks.size} task${if (tasks.size == 1) "" else "s"}"
                waiting -> "Waiting for you to approve it"
                else -> p.runStatus.replace('_', ' ').replaceFirstChar { it.uppercase() }
            }
            val est = (w?.estimate?.ifBlank { null } ?: d?.estimate.orEmpty()).replace(", about ", " and ")
            return PlanTop(w?.title?.ifBlank { null } ?: d?.shortTitle ?: fallback, state,
                w?.summary.orEmpty(), if (waiting && est.isNotBlank()) est.replaceFirstChar { it.uppercase() } else "", waiting, finished, tasks)
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.calmPlan(p: PlanView, ui: ProjectUi, a: ProjectActions) {
    val top = PlanTop.of(p, ui.id)
    val d = p.doc
    val cards = ui.asks.data.orEmpty()
    val hub = ui.mode == Mode.HUB
    item(key = "top") {
        Column {
            Text(top.title, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).background(if (top.finished) Hall.good else if (top.waiting) Hall.ember else Hall.amber, RoundedCornerShape(5.dp)))
                Spacer(Modifier.width(8.dp))
                Text(top.state, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            }
            if (top.summary.isNotBlank()) Text(top.summary, Modifier.padding(top = 6.dp), color = Hall.muted,
                style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
            if (top.estimate.isNotBlank()) Text(top.estimate, Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    if (cards.isNotEmpty() && !top.finished) {
        val agreed = d?.let { !it.waitingForOwner && it.state.isNotBlank() } == true
        items(cards, key = { "ask:" + it.id }) { c ->
            AskCard(c, { a.answer(c, it) }, sent = ui.sent["ask:${c.id}"], hint = Asks.hint(c, planAgreed = agreed && c.local), showProject = false)
        }
    }
    if (hub && top.waiting) item(key = "actions") {
        val pending = p.words?.pendingChanges == true || ui.sent.keys.any { k -> listOf("note:", "choose:", "answer:", "idea:", "ask:").any { k.startsWith(it) } }
        PlanButtons(ui.sent, a, pending = pending, canApprove = p.canApprove && cards.none { it.kind == "approve" })
    }
    if (top.tasks.isNotEmpty()) {
        item(key = "tasks-head") {
            SectionTitle("Tasks · ${top.tasks.count { it.status == "done" }} of ${top.tasks.size} done")
        }
        item(key = "tasks") { Column { top.tasks.forEach { TaskLine(it) } } }
    }
    if (d != null) item(key = "more") { MoreAboutPlan(d, showSummary = top.summary.isBlank()) }
}

@Composable
private fun TaskLine(t: PlanDoc.PlanTask) {
    val (mark, color) = when (t.status) {
        "done" -> "✓" to Hall.good
        "running" -> "●" to Hall.amber
        "failed" -> "!" to Hall.bad
        "skipped" -> "–" to Hall.muted
        else -> "○" to Hall.muted
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(mark, Modifier.width(22.dp), color = color, fontWeight = FontWeight.Bold)
        Text(Markdown.plain(t.title), Modifier.weight(1f), color = if (t.status == "done") Hall.text else Hall.muted, maxLines = 1,
            overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
    }
}

/** Everything but the top, collapsed: each part its own fold. */
@Composable
private fun MoreAboutPlan(d: PlanDoc, showSummary: Boolean) {
    var open by rememberSaveable { mutableStateOf(false) }
    Panel(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (open) "▾" else "▸", color = Hall.gold, modifier = Modifier.width(20.dp))
            Text("More about this plan", Modifier.weight(1f), color = Hall.text, style = MaterialTheme.typography.titleSmall)
        }
        if (!open) return@Panel
        if (showSummary && d.intro.isNotEmpty()) Fold("What it will be") { MdBlocks(d.intro) }
        if (d.decisions.isNotEmpty()) Fold("Choices (${d.decisions.size})") {
            d.decisions.forEach { dec ->
                val pick = dec.options.firstOrNull { it.chosen } ?: dec.options.firstOrNull { it.recommended }
                Text(styled("**${Markdown.plain(dec.question)}** ${pick?.label.orEmpty()}" +
                    if (dec.options.any { it.chosen }) " (your choice)" else " (recommended)"), style = MaterialTheme.typography.bodySmall)
            }
        }
        if (d.questions.isNotEmpty()) Fold("Questions (${d.questions.size})") {
            d.questions.forEach { q ->
                Text(styled("**${Markdown.plain(q.text)}** ${q.answer.ifBlank { "not answered yet" }}"), style = MaterialTheme.typography.bodySmall)
            }
        }
        if (d.ideas.isNotEmpty()) Fold("Ideas (${d.ideas.size})") {
            d.ideas.forEach { i ->
                val word = when (i.state) { "accepted" -> "yes"; "rejected" -> "no thanks"; else -> "not decided" }
                Text(styled("${Markdown.plain(i.text)} · $word"), style = MaterialTheme.typography.bodySmall)
            }
        }
        d.sections.forEach { s -> Fold(s.title) { MdBlocks(s.blocks) } }
    }
}

@Composable
private fun SentLine(text: String) {
    Text(text, color = Hall.good, fontStyle = FontStyle.Italic, style = MaterialTheme.typography.bodySmall)
}

/** "Tell the planner" is a small button that opens the box; Update plan shows only when changes wait. */
@Composable
private fun PlanButtons(sent: Map<String, String>, a: ProjectActions, pending: Boolean, canApprove: Boolean) {
    var writing by rememberSaveable { mutableStateOf(false) }
    var note by rememberSaveable { mutableStateOf("") }
    Column(Modifier.fillMaxWidth()) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (pending) Button({ a.command("revise", "revise", emptyMap()) }, enabled = "revise" !in sent) { Text("Update plan") }
            if (canApprove && !pending) Button({ a.command("approve", "approve", emptyMap()) }, enabled = "approve" !in sent) { Text("Approve & start") }
            TextButton({ writing = !writing }) {
                Icon(Icons.Filled.Edit, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Tell the planner")
            }
        }
        if (writing) {
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth().heightIn(min = 80.dp), placeholder = { Text("What should change?") })
            Spacer(Modifier.height(6.dp))
            OutlinedButton({ a.command("note:${note.hashCode()}", "note", mapOf("text" to note.trim())); note = ""; writing = false },
                enabled = note.isNotBlank()) { Text("Add this note") }
            Text("Your notes and answers wait until you press Update plan.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        (sent["approve"] ?: sent["revise"])?.let { SentLine(it) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MessagesTab(ui: ProjectUi, a: ProjectActions) {
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var writing by rememberSaveable { mutableStateOf(false) }
    val inbox = ui.inbox
    val unread = inbox.data?.count { !it.read } ?: 0
    PullToRefreshBox(inbox.loading && inbox.data != null, a.refresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${ui.id}'s inbox" + if (unread > 0) " · $unread new" else "", style = MaterialTheme.typography.bodySmall, color = Hall.muted, modifier = Modifier.weight(1f))
                    TextButton(onClick = { writing = true }) { Text("Write to ${ui.id}") }
                }
            }
            if (inbox.error != null) item { ErrorLine(inbox.error, a.refresh) }
            if (inbox.data == null && inbox.loading) item { Loading("Fetching the inbox…") }
            if (inbox.data?.isEmpty() == true) item { Text("No messages.", color = Hall.muted, modifier = Modifier.padding(vertical = 24.dp)) }
            items(inbox.data.orEmpty(), key = { it.id }) { m -> LetterRow(m, showTo = false, plan = ui.plan.data?.doc) { open = m.id; a.opened(m) } }
        }
    }
    inbox.data?.firstOrNull { it.id == open }?.let { m ->
        MessageSheet(m, ui.identity, plan = ui.plan.data?.doc, onDismiss = { open = null }, onReply = { body, done -> a.reply(m, body) { ok -> done(ok); if (ok) open = null } })
    }
    if (writing) ComposeSheet(listOf(ui.id), ui.identity, ui.id, onDismiss = { writing = false }) { _, s, b, done ->
        a.send(s, b) { ok -> done(ok); if (ok) writing = false }
    }
}

/** An icon button with a tooltip saying what it does (long-press). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TipIcon(tip: String, onClick: () -> Unit, icon: @Composable () -> Unit) {
    androidx.compose.material3.TooltipBox(androidx.compose.material3.TooltipDefaults.rememberPlainTooltipPositionProvider(),
        tooltip = { PlainTooltip { Text(tip) } }, state = androidx.compose.material3.rememberTooltipState()) {
        IconButton(onClick = onClick) { icon() }
    }
}
