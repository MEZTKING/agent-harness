package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
)

@Composable
fun ProjectScreen(ui: ProjectUi, a: ProjectActions, initialTab: Int = 0) {
    var tab by rememberSaveable { mutableIntStateOf(initialTab) }
    val doc = ui.status.data
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = a.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            if (ui.seat != null) SeatRing(ui.seat, false, 40.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(ui.id, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val updated = doc?.updated?.ifBlank { null } ?: ui.seat?.lastActivity?.ifBlank { null }
                Text(listOfNotNull(ui.seat?.status, updated?.let { "updated ${ago(it)}" }).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            }
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
                3 -> LiveTab(ui.live, ui.mode, a.refresh)
                else -> MessagesTab(ui, a)
            }
        }
    }
}

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
                else -> items(doc.sections, key = { it.title }) { s ->
                    SectionTitle(s.title)
                    Spacer(Modifier.height(6.dp))
                    MdBlocks(s.blocks)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlanTab(ui: ProjectUi, a: ProjectActions) {
    val plan = ui.plan
    PullToRefreshBox(plan.loading && plan.data != null, a.refresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (plan.error != null) item { ErrorLine(plan.error, a.refresh) }
            val cards = ui.asks.data.orEmpty()
            val agreed = plan.data?.doc?.let { !it.waitingForOwner && it.state.isNotBlank() } == true
            if (cards.isNotEmpty()) {
                item { SectionTitle("Your answers") }
                item {
                    Text("Tap an answer: the recommended one is first. Or choose Other… to type your own.",
                        style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
                items(cards, key = { "ask:" + it.id }) { c ->
                    AskCard(c, { a.answer(c, it) }, sent = ui.sent["ask:${c.id}"], hint = Asks.hint(c, planAgreed = agreed && c.local), showProject = false)
                }
            }
            val p = plan.data
            when {
                p == null && plan.loading -> item { Loading("Reading the plan…") }
                p == null -> {}
                p.doc != null -> planDoc(p.doc, ui, a, cards.map { it.id }.toSet())
                p.tasks.isNotEmpty() -> {
                    item { Text("Run: ${p.runStatus.replace('_', ' ')}", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                    if (p.canApprove && cards.none { it.kind == "approve" }) item {
                        Button(onClick = { a.act("approve") }, modifier = Modifier.fillMaxWidth()) { Text("Approve & start") }
                    }
                    items(p.tasks, key = { it.id }) { TaskRow(it) }
                }
                else -> item {
                    Text("No plan yet. A plan appears here when Roundtable Hold plans a run for this project.", color = Hall.muted,
                        modifier = Modifier.padding(vertical = 24.dp))
                }
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.planDoc(d: PlanDoc, ui: ProjectUi, a: ProjectActions, carded: Set<String> = emptySet()) {
    val hub = ui.mode == Mode.HUB
    // what is a card above (to tap) isn't repeated here; the rest is shown to read (what was chosen or answered)
    val canAnswer = false
    val decisions = d.decisions.filter { "choose:${it.id}" !in carded }
    val questions = d.questions.filter { "answer:${it.id}" !in carded }
    val ideas = d.ideas.filter { "idea:${it.id}" !in carded }
    item {
        Column {
            if (d.state.isNotBlank()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Chip(d.state, if (d.waitingForOwner) Hall.bad else if (d.approved) Hall.good else Hall.goldDim)
                    Spacer(Modifier.width(8.dp))
                    if (d.updated.isNotBlank()) Text("updated ${ago(d.updated)}", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
                if (d.summaryLine.isNotBlank()) Text(d.summaryLine, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                Spacer(Modifier.height(8.dp))
            }
            Text(d.title, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
            Spacer(Modifier.height(6.dp))
            MdBlocks(d.intro)
        }
    }
    if (decisions.isNotEmpty()) item { SectionTitle("Choices") }
    items(decisions, key = { "C" + (it.id ?: it.question) }) { dec -> DecisionCard(dec, canAnswer, ui.sent, a) }
    if (questions.isNotEmpty()) item { SectionTitle("Questions for you") }
    items(questions, key = { "Q" + (it.id ?: it.text) }) { q -> QuestionCard(q, canAnswer, ui.sent, a) }
    if (ideas.isNotEmpty()) item { SectionTitle("Ideas") }
    items(ideas, key = { "I" + (it.id ?: it.text) }) { i -> IdeaCard(i, canAnswer, ui.sent, a) }
    if (hub && (d.waitingForOwner || carded.isNotEmpty())) item { PlannerBox(ui.sent, a, canApprove = d.waitingForOwner) }
    else if (hub && !d.waitingForOwner && d.state.isNotBlank()) item {
        Text("This plan is agreed and nothing in it waits for you.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    } else if (!hub) item {
        Text("Plan choices can be answered from the phone in Hub mode (Settings).", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
    items(d.sections, key = { "S" + it.title }) { s ->
        Column {
            SectionTitle(s.title)
            Spacer(Modifier.height(6.dp))
            MdBlocks(s.blocks)
        }
    }
}

@Composable
private fun SentLine(text: String) {
    Text(text, color = Hall.ink, fontStyle = FontStyle.Italic, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun DecisionCard(d: PlanDoc.Decision, canAnswer: Boolean, sent: Map<String, String>, a: ProjectActions) {
    val key = "choose:${d.id}"
    Parchment(Modifier.fillMaxWidth(), seal = if (d.options.any { it.chosen }) Hall.good else Hall.ember) {
        Text(d.question, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink)
        if (d.why.isNotBlank()) Text("Why: ${d.why}", style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
        Spacer(Modifier.height(8.dp))
        d.options.forEach { o ->
            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)
                .background(if (o.chosen) Hall.accentSoft else Hall.parchment, RoundedCornerShape(14.dp))
                .border(if (o.chosen || o.recommended) 2.dp else 1.dp, if (o.chosen) Hall.ink else if (o.recommended) Hall.gold else Hall.line,
                    RoundedCornerShape(14.dp)).padding(12.dp)) {
                FlowRow(verticalArrangement = Arrangement.Center, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(styled(o.label, codeBg = Hall.parchmentLo, codeFg = Hall.ink), fontWeight = FontWeight.SemiBold, color = Hall.ink)
                    if (o.recommended) Chip("recommended", Hall.ink)
                    if (o.chosen) Chip("chosen", Hall.ink, filled = true)
                    if (o.cost.isNotBlank()) Chip(o.cost, Hall.inkSoft)
                }
                if (o.detail.isNotBlank()) Text(styled(o.detail, codeBg = Hall.parchmentLo, codeFg = Hall.ink), style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
                if (canAnswer && !o.chosen && d.id != null && o.id != null && key !in sent) {
                    Spacer(Modifier.height(6.dp))
                    if (o.recommended) Button({ a.command(key, "choose", mapOf("decision" to d.id, "option" to o.id)) }, colors = ParchmentButtons.main()) { Text("Choose this") }
                    else OutlinedButton({ a.command(key, "choose", mapOf("decision" to d.id, "option" to o.id)) }, colors = ParchmentButtons.other(),
                        border = ParchmentButtons.otherBorder) { Text("Choose this") }
                }
            }
        }
        sent[key]?.let { SentLine(it) }
    }
}

@Composable
private fun QuestionCard(q: PlanDoc.Question, canAnswer: Boolean, sent: Map<String, String>, a: ProjectActions) {
    val key = "answer:${q.id}"
    var text by rememberSaveable(q.id) { mutableStateOf("") }
    Parchment(Modifier.fillMaxWidth(), seal = if (q.answer.isNotBlank()) Hall.good else Hall.ember) {
        Text(styled(q.text, codeBg = Hall.parchmentLo, codeFg = Hall.ink), fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = Hall.ink)
        if (q.answer.isNotBlank()) Text("Your answer: ${q.answer}", style = MaterialTheme.typography.bodyMedium, color = Hall.inkSoft)
        if (canAnswer && q.id != null && key !in sent) {
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth(), placeholder = { Text(if (q.answer.isBlank()) "Your answer" else "A new answer") },
                colors = parchmentFieldColors())
            Spacer(Modifier.height(6.dp))
            Button({ a.command(key, "answer", mapOf("question" to q.id, "text" to text.trim())) }, enabled = text.isNotBlank(),
                colors = ParchmentButtons.main()) { Text("Send answer") }
        }
        sent[key]?.let { SentLine(it) }
    }
}

@Composable
private fun IdeaCard(i: PlanDoc.Idea, canAnswer: Boolean, sent: Map<String, String>, a: ProjectActions) {
    val key = "idea:${i.id}"
    Parchment(Modifier.fillMaxWidth(), seal = when (i.state) { "accepted" -> Hall.good; "rejected" -> Hall.inkSoft; else -> Hall.amber }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Chip(i.state, Hall.ink)
        }
        Text(styled(i.text, codeBg = Hall.parchmentLo, codeFg = Hall.ink), color = Hall.ink, fontWeight = FontWeight.SemiBold)
        if (i.why.isNotBlank()) Text(i.why, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
        if (canAnswer && i.id != null && key !in sent) {
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (i.state != "accepted") Button({ a.command(key, "idea", mapOf("id" to i.id, "accept" to true)) }, colors = ParchmentButtons.main()) { Text("Yes") }
                if (i.state != "rejected") OutlinedButton({ a.command(key, "idea", mapOf("id" to i.id, "accept" to false)) }, colors = ParchmentButtons.other(),
                    border = ParchmentButtons.otherBorder) { Text("No thanks") }
            }
        }
        sent[key]?.let { SentLine(it) }
    }
}

@Composable
private fun PlannerBox(sent: Map<String, String>, a: ProjectActions, canApprove: Boolean = true) {
    var note by rememberSaveable { mutableStateOf("") }
    Panel(Modifier.fillMaxWidth(), highlight = true) {
        Text("TELL THE PLANNER", style = Label)
        Spacer(Modifier.height(6.dp))
        OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth().heightIn(min = 90.dp), placeholder = { Text("Tell the planner…") })
        Spacer(Modifier.height(6.dp))
        OutlinedButton({ a.command("note:${note.hashCode()}", "note", mapOf("text" to note.trim())); note = "" }, enabled = note.isNotBlank()) {
            Icon(Icons.Filled.Edit, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Add this note")
        }
        Spacer(Modifier.height(12.dp))
        Text("Your choices, answers and notes wait until you press Update plan; the planner then rewrites the plan once.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton({ a.command("revise", "revise", emptyMap()) }, enabled = "revise" !in sent, modifier = Modifier.weight(1f)) { Text("Update plan") }
            if (canApprove) Button({ a.command("approve", "approve", emptyMap()) }, enabled = "approve" !in sent, modifier = Modifier.weight(1f)) { Text("Approve & start") }
        }
        (sent["approve"] ?: sent["revise"])?.let { Text(it, color = Hall.good, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
    }
}

@Composable
private fun parchmentFieldColors() = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
    focusedTextColor = Hall.ink, unfocusedTextColor = Hall.ink, focusedBorderColor = Hall.ink, unfocusedBorderColor = Hall.inkSoft,
    cursorColor = Hall.ink, focusedPlaceholderColor = Hall.inkSoft, unfocusedPlaceholderColor = Hall.inkSoft,
)

@Composable
private fun TaskRow(t: Task) {
    val color = when (t.status) { "done" -> Hall.good; "running" -> Hall.amber; "failed" -> Hall.bad; else -> Hall.muted }
    Panel(Modifier.fillMaxWidth(), highlight = t.status == "running") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(9.dp).background(color, RoundedCornerShape(5.dp)))
            Spacer(Modifier.width(8.dp))
            Text("${t.id} ", fontWeight = FontWeight.Bold, color = Hall.goldBright)
            Text(t.title, Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        val meta = listOfNotNull(t.role.ifBlank { null }, t.status, t.attempts.lastOrNull()?.model,
            if (t.depends_on.isNotEmpty()) "after ${t.depends_on.joinToString(", ")}" else null)
        Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        if (t.summary.isNotBlank()) Text(t.summary, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
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
