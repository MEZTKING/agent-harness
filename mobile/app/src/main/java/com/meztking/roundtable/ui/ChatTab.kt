package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Queue
import com.meztking.roundtable.data.QueueItem
import com.meztking.roundtable.data.QueueView
import com.meztking.roundtable.data.Slash
import com.meztking.roundtable.data.SlashCommand
import com.meztking.roundtable.data.SlashReply
import com.meztking.roundtable.data.Stream
import com.meztking.roundtable.data.StreamRead
import com.meztking.roundtable.data.Talk
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.ChatMessage
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Mono
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** What the chat with the planner reads and does (the PC or this phone); tests give made-up ones. */
interface ChatSource {
    suspend fun messages(): List<ChatMessage>
    suspend fun commands(): List<SlashCommand>
    suspend fun queue(): QueueView
    suspend fun changeQueue(action: String, id: String, text: String? = null): QueueView
    /** A question (or note) to the planner; the answer comes in the chat. */
    suspend fun ask(text: String): String
    suspend fun command(line: String, confirmed: Boolean): SlashReply
    suspend fun stream(task: String, since: Long): StreamRead
    /** Talk through the PC: what was heard; the answer is read aloud and may propose an action, which waits for a tap. */
    suspend fun talk(text: String): com.meztking.roundtable.data.TalkReply = com.meztking.roundtable.data.TalkReply(reply = ask(text))
}

class ApiChat(private val api: Api, private val path: String) : ChatSource {
    override suspend fun messages() = api.chat(path)
    override suspend fun commands() = Slash.parse(api.feature("GET", Slash.url(path)))
    override suspend fun queue() = Queue.parse(api.feature("GET", Queue.url(path)))
    override suspend fun changeQueue(action: String, id: String, text: String?) =
        Queue.parse(api.feature("POST", Queue.CHANGE, Queue.body(path, action, id, text)))
    override suspend fun ask(text: String) = api.ask(path, text, steer = false).reply
    override suspend fun command(line: String, confirmed: Boolean) =
        Slash.parseReply(api.slowFeature("POST", Slash.RUN, Slash.body(path, line, confirmed)))
    override suspend fun stream(task: String, since: Long) = Stream.parse(api.feature("GET", Stream.url(path, task, since)))
    override suspend fun talk(text: String) = Talk.parseReply(api.talk(path, text))
}

/**
 * The chat with the planner: what was said, the words of a running task as they are written, the messages waiting for
 * the next task (the queue), and the box. Typing "/" opens the commands; one that spends or can't be undone asks
 * "Are you sure?" first. Talk hears a question and reads the answer aloud.
 */
@Composable
fun ChatTab(source: ChatSource, running: String? = null) {
    val scope = rememberCoroutineScope()
    var messages by remember { mutableStateOf(Load<List<ChatMessage>>(loading = true)) }
    var commands by remember { mutableStateOf<List<SlashCommand>>(emptyList()) }
    var queue by remember { mutableStateOf(QueueView()) }
    var text by rememberSaveable { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<String?>(null) }
    var confirm by remember { mutableStateOf<SlashReply?>(null) }
    var spokenAsk by remember { mutableStateOf<String?>(null) }  // a command line waiting for a spoken yes
    var proposed by remember { mutableStateOf<com.meztking.roundtable.data.TalkAction?>(null) }  // from Talk: waits for a tap
    val voice = rememberVoice()

    suspend fun load() {
        messages = runCatching { Load(source.messages()) }.getOrElse { Load(messages.data, error = friendly(it)) }
        queue = runCatching { source.queue() }.getOrDefault(queue)
    }
    LaunchedEffect(source) {
        load()
        commands = runCatching { source.commands() }.getOrDefault(emptyList())
    }

    fun run(line: String, confirmed: Boolean, aloud: Boolean = false) = scope.launch {
        sending = true
        try {
            val r = source.command(line, confirmed)
            if (r.confirm.isNotBlank() && !confirmed) confirm = r.copy(command = r.command.ifBlank { line })
            else { notice = r.reply.ifBlank { "Done." }; text = ""; if (aloud) voice.say(Talk.forSpeaking(notice!!)) }
            load()
        } catch (e: CancellationException) { throw e } catch (e: Exception) { notice = friendly(e) } finally { sending = false }
    }

    fun send(words: String, aloud: Boolean = false) {
        val w = words.trim()
        if (w.isEmpty() || sending) return
        if (Slash.isCommand(w)) { run(w, confirmed = false, aloud = aloud); return }
        scope.launch {
            sending = true
            try {
                val reply = source.ask(w)
                text = ""; notice = null
                if (aloud) voice.say(Talk.forSpeaking(reply))
                load()
            } catch (e: CancellationException) { throw e } catch (e: Exception) { notice = friendly(e) } finally { sending = false }
        }
    }

    // Talk through the PC: the words go to /api/chat/talk, the answer is read aloud, and an action it proposes is shown
    // as a card that needs a tap (it is never done by speaking or by the PC on its own; "Are you sure?" still applies)
    fun talk(heard: String) {
        val w = heard.trim()
        if (w.isEmpty() || sending) return
        scope.launch {
            sending = true
            try {
                val r = source.talk(w)
                notice = null
                voice.say(Talk.forSpeaking(r.reply))
                proposed = r.action?.takeIf { it.line.startsWith("/") }
                load()
            } catch (e: CancellationException) { throw e } catch (e: Exception) { notice = friendly(e) } finally { sending = false }
        }
    }

    val listenYes = rememberListener("Say yes or no", onHeard = { heard ->
        val line = spokenAsk
        spokenAsk = null
        if (line != null && Talk.isYes(heard)) run(line, confirmed = false, aloud = true)
        else if (line != null) { notice = "Not done."; voice.say("Not done.") }
    }, onNone = { notice = NO_SPEECH })
    val listen = rememberListener("Ask the planner", onHeard = { heard ->
        val line = Talk.commandFrom(heard, commands)
        val c = line?.let { Talk.commandOf(it, commands) }
        when {
            line == null -> talk(heard)
            Talk.mayStartBySaying(c) -> { spokenAsk = line; voice.say(Talk.askAloud(c!!)) { listenYes() } }
            else -> { text = line; notice = "This one asks first: read it, then tap Send." }
        }
    }, onNone = { notice = NO_SPEECH })

    ChatView(
        ChatUi(messages, commands, queue, text, sending, notice, running),
        onText = { text = it; notice = null },
        onSend = { send(text) },
        onTalk = listen,
        onQueue = { action, item, words -> scope.launch {
            try { val v = source.changeQueue(action, item.id, words); queue = v; notice = v.reply.ifBlank { null } }
            catch (e: CancellationException) { throw e } catch (e: Exception) { notice = friendly(e) }
        } },
        onRefresh = { scope.launch { load() } },
        stream = { t, since -> source.stream(t, since) },
    )
    proposed?.let { p ->
        TalkActionCard(p, onDo = {
            proposed = null
            // a tap: the command runs as if typed, so one that spends or deletes still asks "Are you sure?" (below)
            run(p.line, confirmed = false)
        }, onNot = { proposed = null; notice = "Not done." })
    }
    confirm?.let { c ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Are you sure?") },
            text = { Text(c.confirm) },
            confirmButton = { TextButton(onClick = { confirm = null; run(c.command, confirmed = true) }) { Text("Do it") } },
            dismissButton = { TextButton(onClick = { confirm = null; notice = "Not done." }) { Text("Cancel") } },
        )
    }
}

private const val NO_SPEECH = "This phone has no speech service. Type instead, or add one from the Play Store (Speech Services by Google)."

/** Everything the chat draws, so tests can show it without a connection. */
data class ChatUi(
    val messages: Load<List<ChatMessage>> = Load(),
    val commands: List<SlashCommand> = emptyList(),
    val queue: QueueView = QueueView(),
    val text: String = "",
    val sending: Boolean = false,
    val notice: String? = null,
    /** The task being built now, whose words show as they are written. */
    val running: String? = null,
)

@Composable
fun ChatView(ui: ChatUi, onText: (String) -> Unit = {}, onSend: () -> Unit = {}, onTalk: () -> Unit = {},
             onQueue: (action: String, item: QueueItem, text: String?) -> Unit = { _, _, _ -> }, onRefresh: () -> Unit = {},
             stream: (suspend (String, Long) -> StreamRead)? = null) {
    val list = ui.messages.data.orEmpty()
    val keys = buildList<Any> {
        if (ui.messages.error != null) add("error")
        if (list.isEmpty()) add("empty")
        list.forEachIndexed { i, m -> add("m$i:${m.at}") }
        if (ui.running != null && stream != null) add("stream:${ui.running}")
        if (ui.queue.items.isNotEmpty()) add("queue")
    }
    Transcript(keys, composer = { ChatBox(ui, onText, onSend, onTalk) }) {
        ui.messages.error?.let { e -> item(key = "error") { ErrorLine(e, onRefresh) } }
        if (list.isEmpty()) item(key = "empty") {
            Text(if (ui.messages.loading) "Reading the chat…" else "Nothing said yet. Ask the planner anything about this project, or type / for the commands.",
                color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        }
        list.forEachIndexed { i, m -> item(key = "m$i:${m.at}") { Said(m) } }
        if (ui.running != null && stream != null) item(key = "stream:${ui.running}") { StreamWords(ui.running, { since -> stream(ui.running, since) }) }
        if (ui.queue.items.isNotEmpty()) item(key = "queue") { QueueCard(ui.queue, onQueue) }
    }
}

@Composable
private fun Said(m: ChatMessage) {
    val mine = m.who == "owner"
    Column(Modifier.fillMaxWidth(), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
        Text(if (mine) "You" + if (m.steer) " · to the task working now" else "" else "Planner", style = Label, color = Hall.muted)
        Box(Modifier.padding(top = 2.dp).background(if (mine) Hall.accentSoft else Hall.panel, RoundedCornerShape(12.dp))
            .border(1.dp, Hall.line, RoundedCornerShape(12.dp)).padding(10.dp)) {
            if (mine) Text(m.text, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            else MdBlocks(com.meztking.roundtable.data.Markdown.parse(m.text))
        }
    }
}

@Composable
private fun ChatBox(ui: ChatUi, onText: (String) -> Unit, onSend: () -> Unit, onTalk: () -> Unit) {
    val menu = Slash.menu(ui.text, ui.commands)
    Column(Modifier.fillMaxWidth().background(Hall.bg).padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (menu.isNotEmpty()) SlashMenu(menu) { onText(Slash.pick(it)) }
        ui.notice?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        OutlinedTextField(ui.text, onText, Modifier.fillMaxWidth().heightIn(min = 56.dp), enabled = !ui.sending,
            placeholder = { Text("Ask the planner, or type / for commands") })
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TipIcon("Talk: say a question and hear the answer. Say “slash” and a command's name to give a command.", onTalk) {
                Text("Talk", color = Hall.gold)
            }
            Box(Modifier.weight(1f))
            Button(onSend, enabled = !ui.sending && ui.text.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                Text(if (ui.sending) "Sending…" else if (Slash.isCommand(ui.text)) "Do it" else "Send")
            }
        }
    }
}

/** The commands matching what's typed after "/": each with what it does; a tap puts it in the box. */
@Composable
fun SlashMenu(items: List<SlashCommand>, onPick: (SlashCommand) -> Unit) {
    Column(Modifier.fillMaxWidth().heightIn(max = 260.dp).background(Hall.panel, RoundedCornerShape(10.dp))
        .border(1.dp, Hall.line, RoundedCornerShape(10.dp)).padding(4.dp)) {
        Text("COMMANDS", style = Label, modifier = Modifier.padding(6.dp))
        androidx.compose.foundation.lazy.LazyColumn {
            items(items, key = { it.name }) { c ->
                Row(Modifier.fillMaxWidth().clickable { onPick(c) }.padding(horizontal = 8.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("/${c.name}", color = Hall.gold, fontFamily = Mono, fontWeight = FontWeight.Bold, modifier = Modifier.padding(end = 8.dp))
                    Text(c.words + if (c.confirm) " · asks first" else "", Modifier.weight(1f), color = Hall.text,
                        style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

/** The messages waiting for the next task: change one, remove it, or send it to the task working now. */
@Composable
fun QueueCard(v: QueueView, onQueue: (action: String, item: QueueItem, text: String?) -> Unit) {
    var editing by remember { mutableStateOf<String?>(null) }
    var words by remember { mutableStateOf("") }
    Panel(Modifier.fillMaxWidth()) {
        Text("WAITING FOR THE NEXT TASK", style = Label, color = Hall.muted)
        Text(Queue.title(v), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        for (it in v.items) {
            Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                if (editing == it.id) {
                    OutlinedTextField(words, { w -> words = w }, Modifier.fillMaxWidth())
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton({ onQueue("change", it, words); editing = null }, enabled = words.isNotBlank()) { Text("Keep the new words") }
                        TextButton({ editing = null }) { Text("Cancel") }
                    }
                } else {
                    Text(it.text, color = Hall.text, style = MaterialTheme.typography.bodySmall, maxLines = 4, overflow = TextOverflow.Ellipsis)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TextButton({ editing = it.id; words = it.text }) { Text("Change") }
                        TextButton({ onQueue("remove", it, null) }) { Text("Remove") }
                        if (v.running) OutlinedButton({ onQueue("send_now", it, null) }) { Text("Send it now") }
                    }
                }
            }
        }
    }
}

/** What Talk proposes to do, as a card: what it does, and Do it or Not now. Nothing happens without a tap. */
@Composable
fun TalkActionCard(a: com.meztking.roundtable.data.TalkAction, onDo: () -> Unit, onNot: () -> Unit) {
    AlertDialog(
        onDismissRequest = onNot,
        title = { Text(com.meztking.roundtable.data.Words.t("The planner suggests")) },
        text = {
            Column {
                Text(Talk.actionLine(a))
                Text(a.line, Modifier.padding(top = 6.dp), fontFamily = Mono, color = Hall.muted)
            }
        },
        confirmButton = { TextButton(onClick = onDo) { Text(com.meztking.roundtable.data.Words.t("Do it")) } },
        dismissButton = { TextButton(onClick = onNot) { Text(com.meztking.roundtable.data.Words.t("Not now")) } },
    )
}
