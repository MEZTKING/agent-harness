package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.WizardFlow
import com.meztking.roundtable.ui.theme.Hall

/**
 * A new project, card by card as on the PC (asks.py wizard_asks): what to make, "Make it like this" (links or names,
 * one per line), the set of models and the look, then the idea itself in the message box with photos and files.
 * Nothing is built until the plan is approved. An older PC without the cards gets the idea box alone.
 */
@Composable
fun WizardScreen(onBack: () -> Unit, onStarted: (String) -> Unit) {
    val app = LocalContext.current.applicationContext as RoundtableApp
    val api = remember { composerApi(app) }
    val sender = remember(api) { api?.let { composerSender(it) } }
    var flow by remember { mutableStateOf<WizardFlow?>(null) }
    var tried by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(api) {
        flow = api?.let { a -> runCatching { WizardFlow.of(a.wizardAsks()) }.getOrNull()?.takeIf { it.asks.isNotEmpty() } }
            ?.let { ordered(it) }
        tried = true
    }
    val f = flow
    if (!tried) { Loading("Getting the questions…"); return }
    if (f == null || sender == null) { NewIdeaScreen(onBack, onStarted); return }
    WizardContent(f, notice, onBack = { if (f.at > 0) flow = f.back() else onBack() }, onAnswer = { a, r -> flow = f.answer(a.id, r) }) {
        Composer(
            key = "new-idea",
            onSend = { d, read -> sender.startWizard(d, f, read) },
            onSent = onStarted,
            onProblem = { notice = it },
            placeholder = "What should be built? Who is it for, what must it do? Add a sketch or a photo if you like.",
            sendLabel = "Make the plan",
        )
    }
}

/** The idea last: the box with its photos ends the cards. */
private fun ordered(f: WizardFlow) = f.copy(asks = f.asks.filter { !f.isIdea(it) } + f.asks.filter { f.isIdea(it) })

@Composable
fun WizardContent(f: WizardFlow, notice: String?, onBack: () -> Unit, onAnswer: (Ask, AskReply) -> Unit, box: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TextButton(onBack) { Text("← Back", color = Hall.muted) }
        Text("New project", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        Text("Step ${f.step}. Nothing is built until you approve the plan; making the plan costs a little, usually a few cents.",
            color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        val said = f.asks.take(f.at).mapNotNull { a -> f.said(a.id).takeIf { it.isNotBlank() }?.let { "${a.header}: $it" } }
        if (said.isNotEmpty()) Text(said.joinToString(" · "), color = Hall.text, style = MaterialTheme.typography.bodySmall)
        val a = f.current
        when {
            a == null -> {}
            f.isIdea(a) -> {
                Text(a.question, style = MaterialTheme.typography.titleMedium, color = Hall.text)
                if (a.detail.isNotBlank()) Text(a.detail, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                box()
            }
            else -> AskCard(a.copy(options = a.options.filter { o -> o.id !in disabled(a) }), { r -> onAnswer(a, r) },
                showProject = false, pictures = com.meztking.roundtable.data.Looks.forCard(a, emptyMap()),
                hint = if (a.id == WizardFlow.LIKE) "Paste links or names, one per line. It makes something similar, never a copy." else "")
        }
        if (notice != null) Text(notice, color = Hall.bad)
    }
}

/** Kinds marked "Coming" on the PC can't be picked yet: they stay off the card. */
private fun disabled(a: Ask): Set<String> = a.options.filter { it.disabled }.map { it.id }.toSet()
