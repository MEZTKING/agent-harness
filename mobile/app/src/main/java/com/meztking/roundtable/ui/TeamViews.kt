package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Agent
import com.meztking.roundtable.data.AgentsView
import com.meztking.roundtable.data.BoardView
import com.meztking.roundtable.data.CiView
import com.meztking.roundtable.data.Listening
import com.meztking.roundtable.data.Live
import com.meztking.roundtable.data.Recall
import com.meztking.roundtable.data.RecallAnswer
import com.meztking.roundtable.data.RecallFound
import com.meztking.roundtable.data.Team
import com.meztking.roundtable.data.UsageView
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** The checks on GitHub for one project, as a small chip ("Checks passing"); nothing for a project not on GitHub. */
@Composable
fun ChecksChip(path: String, load: suspend () -> String, modifier: Modifier = Modifier) {
    var v by remember(path) { mutableStateOf<CiView?>(null) }
    LaunchedEffect(path) { v = runCatching { Team.ci(load()) }.getOrNull() }
    v?.let { ChecksChipView(it, modifier) }
}

@Composable
fun ChecksChipView(v: CiView, modifier: Modifier = Modifier) {
    if (!v.shown) return
    val colour = when (v.state) { "passing" -> Hall.good; "failing" -> Hall.bad; "running" -> Hall.amber; else -> Hall.muted }
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).background(colour, CircleShape))
        Spacer(Modifier.width(6.dp))
        Text(v.words + v.failing.firstOrNull()?.let { ": ${it.name}" }.orEmpty(), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** The board, read only: one line of how the cards stand, the columns with their cards on a tap. Cards are moved on the PC. */
@Composable
fun BoardFold(path: String, load: suspend () -> String) {
    var v by remember(path) { mutableStateOf<BoardView?>(null) }
    LaunchedEffect(path) { v = runCatching { Team.board(load()) }.getOrNull() }
    v?.let { BoardFoldView(it) }
}

@Composable
fun BoardFoldView(v: BoardView) {
    if (v.shown.isEmpty()) return
    Fold("The board · ${v.summary}") {
        v.state?.line?.takeIf { it.isNotBlank() }?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        for (c in v.shown) {
            Text(c.title.uppercase() + " (${c.cards.size})", Modifier.padding(top = 8.dp), style = Label, color = Hall.muted)
            for (card in c.cards) Text("${card.number} · ${card.title}", color = Hall.text, style = MaterialTheme.typography.bodySmall,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text("Cards are moved on your PC.", Modifier.padding(top = 6.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

/** "Your PC last listened 2 minutes ago." in one line; a warning colour when it's been quiet a long time. */
@Composable
fun ListeningLine(v: Listening, modifier: Modifier = Modifier) {
    if (v.words.isBlank()) return
    Text(v.words, modifier, color = if (v.stale) Hall.warn else Hall.muted, style = MaterialTheme.typography.bodySmall)
}

/** What each service used this month, one line; each service on a tap. Limits are set on the PC. */
@Composable
fun UsageCard(v: UsageView) {
    Panel(Modifier.fillMaxWidth()) {
        Text("WHAT IT HAS USED", style = Label, color = Hall.muted)
        Text(Team.usageLine(v), Modifier.padding(top = 4.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        if (v.words.isNotBlank()) Text(v.words, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        if (v.services.isNotEmpty()) Fold("More") {
            for (s in v.services) {
                Text(s.words, color = if (s.reached.isNotBlank()) Hall.bad else Hall.text, style = MaterialTheme.typography.bodySmall)
                if (s.unpriced_words.isNotBlank()) Text(s.unpriced_words, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
            if (v.note.isNotBlank()) Text(v.note, Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            Text("Limits are set on your PC.", Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** The named agents, one per job: face, name and what they do. [onPick] (a job's agent chosen) only where the machine
 * lets the phone choose; otherwise "Changed on your PC". */
@Composable
fun AgentsCard(v: AgentsView, onPick: ((Agent) -> Unit)? = null) {
    Panel(Modifier.fillMaxWidth()) {
        Text("YOUR TEAM", style = Label, color = Hall.muted)
        if (v.words.isNotBlank()) Text(v.words, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        for (job in v.jobs) {
            val a = v.hiredFor(job.job)
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Face(a)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(a?.name ?: "Nobody yet", color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
                    Text(job.name + " · " + job.words, color = Hall.muted, style = MaterialTheme.typography.bodySmall, maxLines = 2,
                        overflow = TextOverflow.Ellipsis)
                }
                if (onPick != null && a != null) TextButton({ onPick(a) }) { Text("Pick") }
            }
        }
        val spare = v.agents.filter { !it.hired }
        if (spare.isNotEmpty()) Fold("Not doing a job (${spare.size})") {
            for (a in spare) Text("${a.name} · ${a.job_name}", color = Hall.text, style = MaterialTheme.typography.bodySmall)
        }
        if (onPick == null) Text("Who does which job is changed on your PC.", Modifier.padding(top = 6.dp), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Face(a: Agent?) {
    val img = remember(a?.face) { a?.face?.let { Live.dataUrl(it) }?.let { b -> runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull() } }
    val mod = Modifier.size(40.dp).clip(CircleShape).border(1.dp, Hall.line, CircleShape)
    if (img != null) Image(img, a?.name, mod, contentScale = ContentScale.Crop)
    else Box(mod.background(Hall.panelHi), contentAlignment = Alignment.Center) {
        Text(a?.initials ?: "?", color = Hall.gold, fontWeight = FontWeight.Bold)
    }
}

/** Find in your projects, documents and the journal by meaning; Ask a question about them (the price first). */
interface RecallSource {
    suspend fun find(words: String): RecallFound
    suspend fun ask(question: String, confirm: Boolean): RecallAnswer
}

class ApiRecall(private val api: Api) : RecallSource {
    override suspend fun find(words: String) = Recall.found(api.feature("GET", Recall.findUrl(words)))
    override suspend fun ask(question: String, confirm: Boolean) =
        Recall.answer(api.slowFeature("POST", Recall.ASK, Recall.askBody(question, confirm)))
}

@Composable
fun DocumentsCard(source: RecallSource) {
    val scope = rememberCoroutineScope()
    var words by remember { mutableStateOf("") }
    var found by remember { mutableStateOf<RecallFound?>(null) }
    var price by remember { mutableStateOf<RecallAnswer?>(null) }
    var answer by remember { mutableStateOf<RecallAnswer?>(null) }
    var said by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    fun act(block: suspend () -> Unit) = scope.launch {
        busy = true; said = null
        try { block() } catch (e: CancellationException) { throw e } catch (e: Exception) { said = friendly(e) } finally { busy = false }
    }
    DocumentsView(words, found, price, answer, busy, said, onWords = { words = it },
        onFind = { act { answer = null; price = null; found = source.find(words) } },
        onAsk = { act { found = null; answer = null; price = source.ask(words, confirm = false) } },
        onAskYes = { act { price = null; answer = source.ask(words, confirm = true) } },
        onAskNo = { price = null })
}

@Composable
fun DocumentsView(words: String, found: RecallFound?, price: RecallAnswer?, answer: RecallAnswer?, busy: Boolean, said: String?,
                  onWords: (String) -> Unit = {}, onFind: () -> Unit = {}, onAsk: () -> Unit = {}, onAskYes: () -> Unit = {},
                  onAskNo: () -> Unit = {}) {
    Panel(Modifier.fillMaxWidth()) {
        Text("YOUR DOCUMENTS AND PROJECTS", style = Label, color = Hall.muted)
        Text("Find by meaning, or Ask a question: the answer quotes where it came from.", color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(words, onWords, Modifier.fillMaxWidth().padding(top = 6.dp), enabled = !busy,
            placeholder = { Text("What are you looking for?") })
        Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onFind, enabled = !busy && words.isNotBlank()) { Text("Find") }
            TextButton(onAsk, enabled = !busy && words.isNotBlank()) { Text("Ask…") }
        }
        said?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodySmall) }
        if (price != null) {
            Text(Recall.priceLine(price), Modifier.padding(top = 6.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onAskYes, enabled = !busy) { Text("Ask it") }
                TextButton(onAskNo) { Text("Not now") }
            }
        }
        if (answer != null) {
            Text(answer.answer.ifBlank { answer.words }, Modifier.padding(top = 6.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            if (answer.quotes.isNotEmpty()) Fold("Where it came from (${answer.quotes.size})") {
                for (q in answer.quotes) Text("“${q.text}” · ${q.title}", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
        found?.let { f ->
            if (f.pieces.isEmpty()) Text("Nothing found. Try other words.", Modifier.padding(top = 6.dp), color = Hall.muted,
                style = MaterialTheme.typography.bodySmall)
            for (p in f.pieces.take(12)) Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Text(p.title, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
                Text(p.where, color = Hall.muted, style = MaterialTheme.typography.labelSmall)
                Text(Recall.snippet(p), color = Hall.text, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Your team, what it has used, who last listened, and your documents: read from the PC (or this phone). */
@Composable
fun TeamScreen(api: Api?, onBack: () -> Unit) {
    var agents by remember { mutableStateOf<AgentsView?>(null) }
    var usage by remember { mutableStateOf<UsageView?>(null) }
    var listening by remember { mutableStateOf<Listening?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(api) {
        if (api == null) return@LaunchedEffect
        try {
            agents = Team.agents(api.feature("GET", Team.AGENTS))
            usage = runCatching { Team.usage(api.feature("GET", Team.USAGE)) }.getOrNull()
            listening = runCatching { Team.listening(api.feature("GET", Team.LISTENING)) }.getOrNull()
        } catch (e: CancellationException) { throw e } catch (e: Exception) { problem = friendly(e) }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TextButton(onBack) { Text("← Back", color = Hall.muted) }
        Text("Your team", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        if (api == null) { Text("Connect your PC or start the harness on this phone to see your team.", color = Hall.warn); return@Column }
        listening?.let { ListeningLine(it) }
        problem?.let { ErrorLine(it) {} }
        agents?.let { AgentsCard(it) }
        usage?.let { UsageCard(it) }
        val recall = remember(api) { ApiRecall(api) }
        DocumentsCard(recall)
        Spacer(Modifier.height(24.dp))
    }
}
