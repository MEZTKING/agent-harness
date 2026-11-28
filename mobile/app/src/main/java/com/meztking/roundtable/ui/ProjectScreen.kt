package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

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
import androidx.compose.material.icons.filled.Folder
import com.meztking.roundtable.data.ComposerSender
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.meztking.roundtable.ui.theme.LocalComfort
import com.meztking.roundtable.data.SentItem

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
    /** The project's files (the Files screen). */
    val files: (() -> Unit)? = null,
    /** The message box for "Tell the planner" (photos, files, Speak, @): with the machine that has the project.
     *  Null in Hub mode, where the note stays text only. */
    val composer: ComposerSender? = null,
    /** The project's folder on that machine, for the message box's @. */
    val path: String? = null,
    /** The machine that has the project (the PC, or this phone's Roundtable): Undo…, proof, kinds and pounds.
     *  Null in Hub mode, where those wait for the PC. */
    val machine: com.meztking.roundtable.net.Api? = null,
    /** A page in the app's own browser (the chat's key form and top-up links). */
    val page: (String) -> Unit = {},
    /** This phone's set-up (the chat's "Set up This phone first"). */
    val setupPhone: () -> Unit = {},
)

@Composable
fun ProjectScreen(ui: ProjectUi, a: ProjectActions, initialTab: Int = 0) {
    var tab by rememberSaveable { mutableIntStateOf(initialTab) }
    com.meztking.roundtable.notify.QuietWhileOpen(ui.id)  // no notification for this project while it's on screen
    val doc = ui.status.data
    // pounds beside the dollars, read through the PC (the phone asks no outside service)
    var rate by remember { mutableStateOf<com.meztking.roundtable.data.Rate?>(null) }
    LaunchedEffect(a.machine) {
        val m = a.machine
        rate = if (m == null) null else runCatching { com.meztking.roundtable.data.Pounds.parse(m.feature("GET", "/api/rates")) }.getOrNull()
    }
    var undo by remember { mutableStateOf<String?>(null) }  // the finished task whose Undo… sheet is open
    val undoTask = undo
    val machine = a.machine
    val folder = a.path
    if (undoTask != null && machine != null && folder != null) {
        RewindSheet(machine, folder, undoTask) { words -> undo = null; if (words.isNotBlank()) a.refresh() }
    }
    val canUndo = machine != null && folder != null && ui.seat?.status != "running"
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
            a.files?.let { open -> TipIcon("This project's files", open) { Icon(Icons.Filled.Folder, "This project's files", tint = Hall.gold) } }
            a.settings?.let { open -> TipIcon("This project's settings", open) { Icon(Icons.Filled.Settings, "This project's settings", tint = Hall.gold) } }
            IconButton(onClick = a.refresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
        }
        val desc = ui.seat?.description?.ifBlank { null } ?: doc?.description
        if (!desc.isNullOrBlank()) Text(desc, Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall, color = Hall.muted,
            maxLines = 3, overflow = TextOverflow.Ellipsis)
        if (machine != null && folder != null) ChecksChip(folder, { machine.feature("GET", com.meztking.roundtable.data.Team.ciUrl(folder)) },
            Modifier.padding(horizontal = 16.dp, vertical = 2.dp))
        Spacer(Modifier.height(6.dp))
        PrimaryTabRow(selectedTabIndex = tab, containerColor = Hall.bg) {
            // one line each, even on a narrow phone
            val one = @Composable { t: String -> Text(t, maxLines = 1, softWrap = false, overflow = TextOverflow.Clip) }
            Tab(tab == 0, { tab = 0 }, text = { one("Status") })
            Tab(tab == 1, { tab = 1 }, text = { one(if (ui.plan.data?.doc?.waitingForOwner == true || !ui.asks.data.isNullOrEmpty()) "Plan •" else "Plan") })
            Tab(tab == 2, { tab = 2 }, text = { one("Chat") })
            Tab(tab == 3, { tab = 3 }, text = { one("Live") })
        }
        Box(Modifier.weight(1f)) {
            when (tab) {
                0 -> StatusTab(ui.status, a.refresh)
                1 -> PlanTab(ui, a, rate, if (canUndo) ({ t: String -> undo = t }) else null)
                3 -> LiveTab(ui.live, ui.mode, a.refresh, finished = ui.seat?.status == "done" || ui.plan.data?.let { PlanTop.of(it, ui.id).finished } == true,
                    onTakePictures = { a.command("show_it", "show_it", emptyMap()) }, sent = ui.sent["show_it"],
                    proof = if (machine != null && folder != null) proofLoader(machine, folder) else null,
                    stream = if (machine != null && folder != null) ({ t, since ->
                        com.meztking.roundtable.data.Stream.parse(machine.feature("GET", com.meztking.roundtable.data.Stream.url(folder, t, since)))
                    }) else null)
                else -> Column(Modifier.fillMaxSize()) {
                    // what waits for the next task (the PC's queue), above the project's chat
                    if (machine != null && folder != null) WaitingQueue(remember(machine, folder) { ApiChat(machine, folder) })
                    Box(Modifier.weight(1f)) { ProjectChat(ui.seat, ui.id, onPage = a.page, onSetUpPhone = a.setupPhone) }
                }
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
private fun PlanTab(ui: ProjectUi, a: ProjectActions, rate: com.meztking.roundtable.data.Rate? = null,
                    onUndo: ((String) -> Unit)? = null) {
    val plan = ui.plan
    PullToRefreshBox(plan.loading && plan.data != null, a.refresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (plan.error != null) item { ErrorLine(plan.error, a.refresh) }
            val p = plan.data
            when {
                p == null && plan.loading -> item { Loading("Reading the plan…") }
                p == null -> {}
                p.doc == null && p.tasks.isEmpty() -> item {
                    Text("No plan yet. A plan appears here when ${Brand.NAME} plans a run for this project.", color = Hall.muted,
                        modifier = Modifier.padding(vertical = 24.dp))
                }
                else -> calmPlan(p, ui, a, rate, onUndo)
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

private fun androidx.compose.foundation.lazy.LazyListScope.calmPlan(p: PlanView, ui: ProjectUi, a: ProjectActions,
                                                                   rate: com.meztking.roundtable.data.Rate? = null,
                                                                   onUndo: ((String) -> Unit)? = null) {
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
            if (top.estimate.isNotBlank()) Text(top.estimate + com.meztking.roundtable.data.Pounds.besideText(top.estimate, rate),
                Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
    }
    // what kind of thing it is; the question itself comes as a card (kind "kind"), so here it only says what it is
    val kind = p.kind
    if (kind != null && cards.none { it.kind == "kind" }) item(key = "kind") { KindCard(kind, onChoose = null) }
    // what "finished" means: one line, each thing on opening (from the PC; nothing in Hub mode)
    val machine = a.machine
    val path = a.path
    if (machine != null && !path.isNullOrBlank()) item(key = "done") { DoneCard(machine, path) }
    // where rival planners disagreed: one line, the points on a tap (nothing for a plan by one planner)
    if (machine != null && !path.isNullOrBlank()) item(key = "council") {
        CouncilFold(path) { machine.feature("GET", com.meztking.roundtable.data.Council.url(path)) }
    }
    if (cards.isNotEmpty() && !top.finished) {
        val agreed = d?.let { !it.waitingForOwner && it.state.isNotBlank() } == true
        val placed = cards.map { it.copy(path = it.path ?: path) }
        // Answer these: three or more waiting, the recommended answer for the ticked ones in one go (the PC only)
        if (machine != null && com.meztking.roundtable.data.AnswerThese.shown(placed)) item(key = "answer-these") {
            AnswerTheseBar(placed, send = { machine.answerSeveral(it) }, onDone = a.refresh)
        }
        items(placed, key = { "ask:" + it.id }) { c ->
            val help = remember(machine) { machine?.let { ApiCardHelp(it) } }
            val looks = rememberLooks(help, path, placed)
            AskCard(c, { a.answer(c, it) }, sent = ui.sent["ask:${c.id}"], hint = Asks.hint(c, planAgreed = agreed && c.local), showProject = false,
                onTyping = rememberHold(help)?.let { h -> { h(c) } },
                pictures = if (c.kind == "look") com.meztking.roundtable.data.Looks.forCard(c, looks) else emptyList())
        }
    }
    if (hub && top.waiting) item(key = "actions") {
        val pending = p.words?.pendingChanges == true || ui.sent.keys.any { k -> listOf("note:", "choose:", "answer:", "idea:", "ask:").any { k.startsWith(it) } }
        PlanButtons(ui.id, ui.sent, a, pending = pending, canApprove = p.canApprove && cards.none { it.kind == "approve" })
    }
    // Lean, Balanced or Maximum, with prices, while the plan waits for approval (Maximum asks first)
    if (machine != null && !path.isNullOrBlank() && top.waiting && !top.finished) item(key = "checking") {
        CheckingChoice(machine, path, ui.sent) { lv -> a.command("checking:$lv", "checking", mapOf("name" to lv)) }
    }
    if (machine != null && !path.isNullOrBlank()) item(key = "stages") {
        StageStrip(path) { machine.feature("GET", com.meztking.roundtable.data.Stages.url(path)) }  // nothing without stages
    }
    if (machine != null && !path.isNullOrBlank() && top.tasks.isNotEmpty()) item(key = "board") {
        BoardFold(path) { machine.feature("GET", com.meztking.roundtable.data.Team.boardUrl(path)) }
    }
    // the sounds bought or made for it, Play and what they cost (nothing for a project without sounds)
    if (machine != null && !path.isNullOrBlank()) item(key = "sounds") { SoundsCard(machine, path) }
    if (top.tasks.isNotEmpty()) {
        item(key = "tasks-head") {
            SectionTitle("Tasks · ${top.tasks.count { it.status == "done" }} of ${top.tasks.size} done")
        }
        item(key = "tasks") { TaskLines(top.tasks, machine, path, onUndo) }
    }
    if (d != null) item(key = "more") { MoreAboutPlan(d, showSummary = top.summary.isBlank()) }
}

/** The task lines, each with who built it and who checked it under it once it has been built (the PC's
 * /api/tandem, loaded once; nothing in Hub mode or from an older PC). */
@Composable
private fun TaskLines(tasks: List<PlanDoc.PlanTask>, machine: com.meztking.roundtable.net.Api?, path: String?,
                      onUndo: ((String) -> Unit)?) {
    var tandem by remember(path) { mutableStateOf<com.meztking.roundtable.data.TandemView?>(null) }
    val built = tasks.count { it.status == "done" || it.status == "failed" }
    LaunchedEffect(path, built) {
        if (machine != null && !path.isNullOrBlank()) tandem = runCatching {
            com.meztking.roundtable.data.Tandem.parse(machine.feature("GET", com.meztking.roundtable.data.Tandem.url(path)))
        }.getOrNull()
    }
    var following by rememberSaveable(path) { mutableStateOf<String?>(null) }
    Column {
        tasks.forEach {
            val canFollow = machine != null && !path.isNullOrBlank() && (it.status == "done" || it.status == "failed")
            TaskLine(it, if (it.status == "done") onUndo else null, onFollow = if (canFollow) ({ id: String -> following = if (following == id) null else id }) else null)
            tandem?.tasks?.get(it.id)?.let { t -> Box(Modifier.padding(start = 22.dp)) { TandemLine(t) } }
            if (following == it.id && machine != null && path != null) {
                val src = remember(it.id) { ApiFollow(machine, path, it.id) }
                FollowBox(it.id, src) { following = null }
            }
        }
    }
}

/** "Checking": Lean, Balanced or Maximum with their prices. Maximum shows both figures and the planners' cost
 * before it is chosen, as on the PC. The choice goes to the PC as the plan's "checking" change. */
@Composable
private fun CheckingChoice(machine: com.meztking.roundtable.net.Api, path: String, sent: Map<String, *>,
                           choose: (String) -> Unit) {
    val T = com.meztking.roundtable.data.Tandem
    var v by remember(path) { mutableStateOf<com.meztking.roundtable.data.TandemView?>(null) }
    var confirm by remember { mutableStateOf(false) }
    LaunchedEffect(path, sent.keys.count { it.startsWith("checking:") }) {
        v = runCatching { T.parse(machine.feature("GET", T.url(path))) }.getOrNull()
    }
    val view = v ?: return
    if (view.estimates.isEmpty()) return  // a plan made before the dial, or an older PC
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text("Checking", color = Hall.text, style = MaterialTheme.typography.titleSmall)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            T.LEVELS.forEach { lv ->
                val on = lv == view.level
                val label = T.levelName(lv) + " · " + T.priceWords(view.estimates[lv])
                if (on) Button(onClick = {}) { Text(label, maxLines = 1) }
                else OutlinedButton(onClick = { if (lv == "maximum") confirm = true else choose(lv) },
                    enabled = sent.keys.none { it == "checking:$lv" }) { Text(label, maxLines = 1) }
            }
        }
    }
    if (confirm) {
        val now = view.estimates[view.level]
        val max = view.estimates["maximum"]
        val planning = max?.planning_usd ?: 0.0
        val words = "Maximum checking: ${T.priceWords(max)} instead of ${T.priceWords(now)} (${T.levelName(view.level)})." +
            (if (planning > 0) " Three planners and a chair cost about $" + String.format(java.util.Locale.UK, "%.2f", planning) +
                " of that, the next time it plans." else "")
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Use Maximum checking?") },
            text = { Text(words) },
            confirmButton = { TextButton(onClick = { confirm = false; choose("maximum") }) { Text("Use Maximum") } },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun TaskLine(t: PlanDoc.PlanTask, onUndo: ((String) -> Unit)? = null, onFollow: ((String) -> Unit)? = null) {
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
        // see which files would change back, then choose; it can be put back afterwards (the PC's rewind)
        // ask the model that built it, or change it with a new task (the price comes first)
        if (onFollow != null) TextButton(onClick = { onFollow(t.id) }) { Text("Ask…", color = Hall.gold, maxLines = 1) }
        if (onUndo != null) TextButton(onClick = { onUndo(t.id) }) { Text("Undo…", color = Hall.gold, maxLines = 1) }
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
private fun PlanButtons(project: String, sent: Map<String, String>, a: ProjectActions, pending: Boolean, canApprove: Boolean) {
    var writing by rememberSaveable { mutableStateOf(false) }
    var note by rememberSaveable { mutableStateOf("") }
    val comfort = LocalComfort.current
    Column(Modifier.fillMaxWidth()) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (pending) Button({ a.command("revise", "revise", emptyMap()) }, enabled = "revise" !in sent) { Text("Update plan") }
            if (canApprove && !pending) Button({ a.command("approve", "approve", emptyMap()) }, enabled = "approve" !in sent) { Text("Approve & start") }
            TextButton({ writing = !writing }) {
                Icon(Icons.Filled.Edit, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Tell the planner")
            }
        }
        val box = a.composer
        if (writing && box != null && a.path != null) {
            var problem by remember { mutableStateOf<String?>(null) }
            Composer(
                key = "note:${a.path}",
                onSend = { d, read ->
                    // the words wait in the plan for Update plan; pictures and files go to the planner with them
                    if (d.text.isBlank()) throw com.meztking.roundtable.data.ComposerProblem("Write what should change first.")
                    a.command("note:${d.text.hashCode()}", "note", mapOf("text" to d.text.trim()))
                    comfort?.remember(project, SentItem(SentItem.NOTE, d.text.trim()))
                    if (d.files.isNotEmpty()) box.send(d, a.path, "note", read) else "Noted."
                },
                onSent = { writing = false; problem = null; a.refresh() },
                onProblem = { problem = it },
                sender = box, project = a.path,
                placeholder = "What should change?", sendLabel = "Add this note",
            )
            problem?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodySmall) }
            Text("Your notes and answers wait until you press Update plan.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        } else if (writing) {
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth().heightIn(min = 80.dp), placeholder = { Text("What should change?") })
            Spacer(Modifier.height(6.dp))
            OutlinedButton({
                a.command("note:${note.hashCode()}", "note", mapOf("text" to note.trim()))
                comfort?.remember(project, SentItem(SentItem.NOTE, note.trim()))
                note = ""; writing = false
            },
                enabled = note.isNotBlank()) { Text("Add this note") }
            Text("Your notes and answers wait until you press Update plan.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        (sent["approve"] ?: sent["revise"])?.let { SentLine(it) }
    }
}

/** The messages waiting for the next task, when there are any: change, remove or send now (the PC's queue). */
@Composable
private fun WaitingQueue(source: ChatSource) {
    val scope = rememberCoroutineScope()
    var queue by remember { mutableStateOf(com.meztking.roundtable.data.QueueView()) }
    LaunchedEffect(source) {
        while (true) { queue = runCatching { source.queue() }.getOrDefault(queue); kotlinx.coroutines.delay(15_000) }
    }
    if (queue.items.isEmpty()) return
    Box(Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
        QueueCard(queue) { action, item, words -> scope.launch { runCatching { source.changeQueue(action, item.id, words) }.onSuccess { queue = it } } }
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

/** The PC's proof of one task, for the Live tab (null when it can't be read). */
private fun proofLoader(machine: com.meztking.roundtable.net.Api, folder: String): suspend (String) -> String? = { t ->
    runCatching { machine.feature("GET", com.meztking.roundtable.data.Proof.url(folder, t)) }.getOrNull()
}
