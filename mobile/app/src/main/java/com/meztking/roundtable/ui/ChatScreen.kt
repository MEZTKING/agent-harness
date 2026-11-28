package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.CanAnswer
import com.meztking.roundtable.data.ChatBrain
import com.meztking.roundtable.data.ChatHome
import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.ChatRead
import com.meztking.roundtable.data.ChatSafety
import com.meztking.roundtable.data.ChatSummary
import com.meztking.roundtable.data.HubChat
import com.meztking.roundtable.data.MultiBackend
import com.meztking.roundtable.data.Piece
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.Talk
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.net.DeepSeekChat
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The chat (1.5.0, instead of Letters): one chat per project and one for everything, Hall. Type, and the answer is
 * written as it comes; the thinking is folded behind "More"; under each answer which device answered and what it
 * cost. It acts only through cards, on a tap. Old letters are under "Earlier messages".
 */

/** Everything one chat draws (tests and screenshots build it by hand). */
data class ChatUiState(
    val lines: List<ChatLine> = emptyList(),
    /** The answer being written now, and its thinking. */
    val writing: String? = null,
    val thinking: String = "",
    val turn: String? = null,
    val notice: String? = null,
    val can: CanAnswer = CanAnswer(true),
    val earlier: List<EarlierLine> = emptyList(),
    val loading: Boolean = false,
    val busyCard: String? = null,
    /** This phone's seat: whose owner lines are "You". */
    val seat: String = "",
)

/** The chat's state as pieces and reads come in (no Android: unit tests drive it). */
object ChatThread {
    fun key(l: ChatLine) = l.seat + "|" + l.id

    /** [incoming] merged into [lines]: a line seen again replaces the old one; the order is the hub's. */
    fun merge(lines: List<ChatLine>, incoming: List<ChatLine>): List<ChatLine> {
        val byKey = LinkedHashMap<String, ChatLine>()
        lines.forEach { byKey[key(it)] = it }
        incoming.forEach { byKey[key(it)] = it }
        // a line kept on the PC comes back with the PC's seat; drop the phone's provisional copy of the same id
        val ids = incoming.map { it.id }.toSet()
        return byKey.values.filter { it.id !in ids || it in incoming }.sortedWith(com.meztking.roundtable.data.ChatLayout.order)
    }

    /** A read merged in. Lines whose `earlier` is true (old letters) are folded under "Earlier messages", never shown
     *  as messages; the machine's own list of them, when it sends one, stands for the phone's. */
    fun read(s: ChatUiState, r: ChatRead): ChatUiState {
        val (old, now) = r.lines.partition { it.earlier }
        val folded = (r.earlier + old).distinctBy { it.id }
        val earlier = if (folded.isEmpty()) s.earlier else folded.sortedWith(com.meztking.roundtable.data.ChatLayout.order).map(::earlierLine)
        return s.copy(lines = merge(s.lines.filterNot { it.earlier }, now), can = r.can, loading = false, earlier = earlier)
    }

    /** An old letter as the Earlier fold shows it: its first line, the rest behind More. */
    fun earlierLine(l: ChatLine): EarlierLine {
        val first = l.text.lineSequence().firstOrNull { it.isNotBlank() }.orEmpty().take(120)
        val rest = l.text.trim().removePrefix(first).trim()
        return when {
            l.who == "agent" -> EarlierLine(l.id, l.at, "agent",
                Words.t("{from} told {to}: {what}", "from" to l.from.orEmpty(), "to" to l.to.orEmpty(), "what" to first), rest)
            l.who == "owner" && l.text.startsWith("You asked it to") -> EarlierLine(l.id, l.at, "command", l.text)
            l.who == "owner" -> EarlierLine(l.id, l.at, "letter", Words.t("You: {words}", "words" to first), rest)
            else -> EarlierLine(l.id, l.at, "letter", "${l.from.orEmpty().ifBlank { l.device.orEmpty() }}: $first", rest)
        }
    }

    fun piece(s: ChatUiState, p: Piece): ChatUiState = when (p) {
        is Piece.Sent -> s.copy(lines = merge(s.lines, listOf(p.line)), turn = p.turn, writing = "", thinking = "", notice = null)
        is Piece.Words -> s.copy(writing = (s.writing ?: "") + p.text)
        is Piece.Thinking -> s.copy(thinking = s.thinking + p.text)
        is Piece.Answer -> {
            val done = p.line.who != "app"
            s.copy(lines = merge(s.lines, listOf(p.line)), writing = if (done) null else s.writing,
                thinking = if (done) "" else s.thinking, turn = if (done) null else s.turn)
        }
    }

    /** The answer has ended (the pieces stopped): nothing is being written any more. */
    fun finish(s: ChatUiState): ChatUiState = s.copy(turn = null, writing = null, thinking = "")

    /** The small grey foot under an answer: the device and what it cost ("This phone · 0.1¢"). */
    fun foot(l: ChatLine): String = listOfNotNull(l.device?.takeIf { it.isNotBlank() }, l.costUsd?.let { cost(it) }).joinToString(" · ")

    fun cost(usd: Double): String {
        val cents = usd * 100
        return when {
            cents < 0.05 -> Words.t("under 0.1¢")
            cents < 1 -> "%.1f¢".format(cents)
            usd < 1 -> "%.0f¢".format(cents)
            else -> "$" + "%.2f".format(usd)
        }
    }

    /** What the answer being written shows: model words as plain text, never a link or a picture. */
    fun shown(text: String): String = ChatSafety.plainFromModel(text)
}

/** One chat: the lines, the answer as it comes, cards, Earlier messages and the box. */
@Composable
fun ChatContent(
    ui: ChatUiState,
    onTap: (line: ChatLine, button: String, confirmed: Boolean) -> Unit = { _, _, _ -> },
    onStop: () -> Unit = {},
    onRead: (String) -> Unit = {},
    box: @Composable () -> Unit = {},
) {
    val keys = buildList<Any> {
        add("earlier")
        ui.lines.forEach { add(ChatThread.key(it)) }
        if (ui.writing != null) add("writing")
        if (ui.lines.isEmpty() && ui.writing == null) add("empty")
    }
    Transcript(keys, composer = {
        Column(Modifier.fillMaxWidth().background(Hall.bg).padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            ui.notice?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
            if (ui.turn != null) TextButton(onStop) { Text(Words.t("Stop")) }
            box()
        }
    }) {
        item(key = "earlier") { EarlierMessages(ui.earlier) }
        if (ui.lines.isEmpty() && ui.writing == null) item(key = "empty") {
            Text(if (ui.loading) Words.t("Reading the chat…") else Words.t("Nothing said yet. Ask anything: where it stands, what it costs, what to do next."),
                color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        }
        ui.lines.forEach { l -> item(key = ChatThread.key(l)) { ChatLineView(l, ui, onTap, onRead) } }
        if (ui.writing != null) item(key = "writing") { Writing(ui) }
    }
}

@Composable
private fun Writing(ui: ChatUiState) {
    Column(Modifier.fillMaxWidth()) {
        Text(Words.t("Writing…"), style = Label, color = Hall.muted)
        Box(Modifier.padding(top = 2.dp).background(Hall.panel, RoundedCornerShape(12.dp)).border(1.dp, Hall.line, RoundedCornerShape(12.dp)).padding(10.dp)) {
            Text(ChatThread.shown(ui.writing.orEmpty()).ifBlank { "…" }, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        }
        if (ui.thinking.isNotBlank()) Folded(Words.t("More: its thinking"), ui.thinking)
    }
}

@Composable
private fun Folded(title: String, body: String) {
    var open by remember { mutableStateOf(false) }
    Text(if (open) Words.t("Less") else title, color = Hall.gold, style = MaterialTheme.typography.labelSmall,
        modifier = Modifier.clickable { open = !open }.padding(top = 4.dp))
    if (open) Text(body, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun ChatLineView(l: ChatLine, ui: ChatUiState, onTap: (ChatLine, String, Boolean) -> Unit, onRead: (String) -> Unit) {
    when (l.who) {
        "owner" -> {
            val mine = l.seat == ui.seat || ui.seat.isBlank()
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
                Text(if (mine) Words.t("You") else Words.t("You, on {device}", "device" to (l.device ?: Words.t("another device"))), style = Label, color = Hall.muted)
                Bubble(l.text, mine = true)
                l.files.forEach { f -> Text("${if (f.kind == "picture") Words.t("Picture") else Words.t("File")}: ${f.name}" +
                    (f.on?.let { " · " + Words.t("kept on the device it was added on") } ?: ""), color = Hall.muted, style = MaterialTheme.typography.labelSmall) }
                if (l.state == "waiting") Text(Words.t("Waiting for your PC"), color = Hall.warn, style = MaterialTheme.typography.labelSmall)
            }
        }
        "agent" -> Column(Modifier.fillMaxWidth()) {
            Folded("${l.from ?: Words.t("An agent")} → ${l.to ?: Words.t("another agent")}: " + l.text.take(60).replace('\n', ' '), ChatThread.shown(l.text))
        }
        "app" -> Column(Modifier.fillMaxWidth().background(Hall.bgDeep, RoundedCornerShape(10.dp)).padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (l.card == null || l.card.line != l.text) Text(l.text, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            l.card?.let { c -> ChatCardView(c, { b, ok -> onTap(l, b, ok) }, busy = ui.busyCard == c.id) }
        }
        else -> Column(Modifier.fillMaxWidth()) {
            Text(if (l.who == "project") (l.from ?: Words.t("The project")) else Words.t("Chat"), style = Label, color = Hall.muted)
            Bubble(ChatThread.shown(l.text), mine = false)
            l.card?.let { c -> Box(Modifier.padding(top = 6.dp)) { ChatCardView(c, { b, ok -> onTap(l, b, ok) }, busy = ui.busyCard == c.id) } }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(ChatThread.foot(l), color = Hall.muted, style = MaterialTheme.typography.labelSmall, modifier = Modifier.weight(1f))
                TextButton({ onRead(l.text) }) { Text(Words.t("Read aloud"), style = MaterialTheme.typography.labelSmall) }
            }
            val more = listOfNotNull(l.model?.let { Words.t("Model: {m}", "m" to it) }, l.thinking?.takeIf { it.isNotBlank() }).joinToString("\n\n")
            if (more.isNotBlank()) Folded(Words.t("More"), more)
        }
    }
}

@Composable
private fun Bubble(text: String, mine: Boolean) {
    Box(Modifier.padding(top = 2.dp).background(if (mine) Hall.accentSoft else Hall.panel, RoundedCornerShape(12.dp))
        .border(1.dp, Hall.line, RoundedCornerShape(12.dp)).padding(10.dp)) {
        Text(text, color = Hall.text, style = MaterialTheme.typography.bodyMedium) // plain text: nothing in it opens or loads
    }
}

/** The list of chats: Hall first, then the projects, newest spoken-in next. */
@Composable
fun ChatListContent(rows: List<ChatSummary>, onOpen: (ChatSummary) -> Unit, onKey: (() -> Unit)? = null, keyEnd: String? = null) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item(key = "head") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Words.t("Chat"), color = Hall.text, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
                if (onKey != null) TipIcon(Words.t("The DeepSeek key this phone answers with when your PC is off."), onKey) {
                    Text(if (keyEnd != null) Words.t("Key …{end}", "end" to keyEnd) else Words.t("Add a key"), color = Hall.gold)
                }
            }
        }
        items(rows, key = { it.id }) { r ->
            Column(Modifier.fillMaxWidth().background(Hall.panel, RoundedCornerShape(12.dp)).border(1.dp, Hall.line, RoundedCornerShape(12.dp))
                .clickable { onOpen(r) }.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(r.name, color = Hall.text, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    if (r.waiting > 0) Text(Words.t("{n} waiting", "n" to r.waiting), color = Hall.warn, style = MaterialTheme.typography.labelSmall)
                    else if (r.unread > 0) Text(Words.t("{n} new", "n" to r.unread), color = Hall.gold, style = MaterialTheme.typography.labelSmall)
                }
                Text(r.last.ifBlank { Words.t("Nothing said yet") }, color = Hall.muted, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/**
 * One chat, live: reads it (every few seconds), sends what is typed through [brain] and shows the answer as it is
 * written; a tap on a card goes back through [brain]. [onAddKey] opens the key form, [onPage] a page in the app's
 * own browser, [onSetUpPhone] This phone's set-up.
 */
@Composable
fun ChatView(
    chat: String,
    brain: ChatBrain,
    seat: String,
    earlier: suspend () -> List<EarlierLine> = { emptyList() },
    onAddKey: () -> Unit = {},
    onPage: (String) -> Unit = {},
    onSetUpPhone: () -> Unit = {},
    pollMs: Long = 10_000,
) {
    val scope = rememberCoroutineScope()
    var ui by remember(chat) { mutableStateOf(ChatUiState(loading = true, seat = seat)) }
    var job by remember { mutableStateOf<Job?>(null) }
    val voice = rememberVoice()

    LaunchedEffect(chat) {
        ui = ui.copy(earlier = runCatching { earlier() }.getOrDefault(emptyList()))
        while (true) {
            if (ui.turn == null) ui = runCatching { ChatThread.read(ui, brain.read(chat, "")) }.getOrElse { ui.copy(loading = false, notice = friendly(it)) }
            delay(pollMs)
        }
    }

    fun tap(l: ChatLine, button: String, confirmed: Boolean) {
        val c = l.card ?: return
        when (button) {
            "add_key", "change_key" -> { onAddKey(); return }
            "top_up" -> { onPage(DEEPSEEK_TOP_UP_PAGE); return }
            "setup_phone" -> { onSetUpPhone(); return }
        }
        scope.launch {
            ui = ui.copy(busyCard = c.id)
            ui = try {
                val line = brain.tap(chat, c.id, button, confirmed)
                ui.copy(lines = ChatThread.merge(ui.lines, listOf(line)), busyCard = null)
            } catch (e: CancellationException) { throw e } catch (e: Exception) { ui.copy(busyCard = null, notice = friendly(e)) }
        }
    }

    ChatContent(ui, ::tap, onStop = {
        job?.cancel()
        val t = ui.turn
        ui = ui.copy(turn = null, writing = null, thinking = "", notice = Words.t("Stopped."))
        if (t != null) scope.launch { runCatching { brain.stop(chat, t) } }
    }, onRead = { voice.say(Talk.forSpeaking(it)) }) {
        Composer(
            key = "chat:$chat",
            onSend = { draft, _ ->
                val flow = brain.say(chat, draft.text, if (draft.files.isEmpty()) null else draft.key) // reads the files before returning
                job = scope.launch {
                    try { flow.collect { p -> ui = ChatThread.piece(ui, p) }; ui = ChatThread.finish(ui) }
                    catch (e: CancellationException) { throw e }
                    catch (e: Exception) { ui = ui.copy(turn = null, writing = null, notice = friendly(e)) }
                }
                ""
            },
            onSent = {},
            onProblem = { ui = ui.copy(notice = it) },
            placeholder = Words.t("Message"),
        )
    }
}

/**
 * The Chat tab: the list of chats and, once one is opened, that chat. [backend] is every connection at once;
 * [seats] the projects on the Table. Keeps the key form for Hub mode's own answers.
 */
@Composable
fun ChatsScreen(
    backend: MultiBackend?,
    seats: List<SeatView>,
    open: String? = null,
    onPage: (String) -> Unit = {},
    onSetUpPhone: () -> Unit = {},
) {
    val context = LocalContext.current
    val app = context.applicationContext as? RoundtableApp
    remember(context) { ChatHome.ensure(context.filesDir) { runCatching { context.assets.open("chat-opening.json").bufferedReader().readText() }.getOrNull() } }
    val store = app?.store
    var current by rememberSaveable { mutableStateOf(open) }
    var keying by remember { mutableStateOf(false) }
    var keyEnd by remember { mutableStateOf(store?.chatKeyEnd) }
    var rows by remember { mutableStateOf(listOf(ChatSummary(com.meztking.roundtable.data.ChatLayout.HALL, Words.t("Hall")))) }

    LaunchedEffect(backend, seats) {
        val base = listOf(ChatSummary(com.meztking.roundtable.data.ChatLayout.HALL, Words.t("Hall"))) +
            seats.map { ChatSummary(HubChat.chatOf(it), it.id) }
        val known = runCatching { backend?.chatBrain(null)?.chats() }.getOrNull().orEmpty().associateBy { it.id }
        rows = base.distinctBy { it.id }.map { r -> known[r.id]?.copy(name = r.name) ?: r }
    }

    Column(Modifier.fillMaxSize()) {
        if (keying && store != null) Box(Modifier.padding(12.dp)) {
            ChatKeyCard(keyEnd, onSave = { store.chatKey = it; keyEnd = store.chatKeyEnd }, onRemove = { store.chatKey = null; keyEnd = null },
                check = { DeepSeekChat.create(it).check() }, onOpenPage = onPage,
                onToThisPhone = if (store.thisPhone) ({ store.chatKey?.let { app.thisPhoneApi().saveKey("deepseek", it) } }) else null,
                onClose = { keying = false })
        }
        val id = current
        if (id == null) {
            ChatListContent(rows, onOpen = { current = it.id }, onKey = if (store?.githubToken != null) ({ keying = true }) else null, keyEnd = keyEnd)
        } else {
            val seat = seats.firstOrNull { HubChat.chatOf(it) == id }
            val brain = remember(backend, id, keyEnd) { backend?.chatBrain(seat) ?: com.meztking.roundtable.data.NoChatBrain }
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 8.dp)) {
                TextButton({ current = null }) { Text(Words.t("← Chats")) }
                Text(rows.firstOrNull { it.id == id }?.name ?: id, color = Hall.text, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            ChatView(id, brain, store?.chatSeat.orEmpty(),
                earlier = { earlierFor(backend, seat, store?.identity ?: "me") },
                onAddKey = { keying = true }, onPage = onPage, onSetUpPhone = onSetUpPhone)
        }
    }
}

/**
 * A project's own chat (the project page's Chat tab): the same chat as in the Chat tab's list, its id by the one rule
 * everywhere ([HubChat.chatOf]: chatstore.chat_id of the hub name), answered by whichever machine or this phone can.
 * [seat] null: a project the Table doesn't show now, found by [project].
 */
@Composable
fun ProjectChat(seat: SeatView?, project: String, onPage: (String) -> Unit = {}, onSetUpPhone: () -> Unit = {}) {
    val context = LocalContext.current
    val app = context.applicationContext as? RoundtableApp
    remember(context) { ChatHome.ensure(context.filesDir) { runCatching { context.assets.open("chat-opening.json").bufferedReader().readText() }.getOrNull() } }
    val store = app?.store
    val backend = remember(app) { app?.backend() }
    val id = remember(seat, project) { if (seat != null) HubChat.chatOf(seat) else HubChat.chatOf(project) }
    var keying by remember { mutableStateOf(false) }
    var keyEnd by remember { mutableStateOf(store?.chatKeyEnd) }
    val brain = remember(backend, seat, keyEnd) { backend?.chatBrain(seat) ?: com.meztking.roundtable.data.NoChatBrain }
    Column(Modifier.fillMaxSize()) {
        if (keying && store != null) Box(Modifier.padding(12.dp)) {
            ChatKeyCard(keyEnd, onSave = { store.chatKey = it; keyEnd = store.chatKeyEnd }, onRemove = { store.chatKey = null; keyEnd = null },
                check = { DeepSeekChat.create(it).check() }, onOpenPage = onPage,
                onToThisPhone = if (store.thisPhone) ({ store.chatKey?.let { app.thisPhoneApi().saveKey("deepseek", it) } }) else null,
                onClose = { keying = false })
        }
        ChatView(id, brain, store?.chatSeat.orEmpty(),
            earlier = { earlierFor(backend, seat, store?.identity ?: "me") },
            onAddKey = { keying = true }, onPage = onPage, onSetUpPhone = onSetUpPhone)
    }
}

/** The old letters of a chat: a project's own inbox and its letters to the owner; Hall gets the rest. */
private suspend fun earlierFor(backend: MultiBackend?, seat: SeatView?, me: String): List<EarlierLine> {
    val b = backend ?: return emptyList()
    val mine = runCatching { b.letters() }.getOrDefault(emptyList())
    val list: List<Message> = if (seat == null) {
        mine.filter { m -> m.sender == me || b.seats.none { it.id == m.sender || it.hubName == m.sender } }
    } else {
        val name = seat.hubName.ifBlank { seat.id }
        runCatching { b.inbox(name) }.getOrDefault(emptyList()) +
            mine.filter { it.sender == name || it.sender == seat.id }
    }
    return Earlier.lines(list.distinctBy { it.id }, me)
}
