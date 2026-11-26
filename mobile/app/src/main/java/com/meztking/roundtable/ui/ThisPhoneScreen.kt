package com.meztking.roundtable.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.meztking.roundtable.runtime.RuntimeFailure
import com.meztking.roundtable.runtime.RuntimeState
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.hallBackground

const val DEEPSEEK_KEYS_URL = "https://platform.deepseek.com/api_keys"

/** The card on the connect screen. Shown only on 64-bit phones with Android 8 or later. */
@Composable
fun ThisPhoneCard(onSetUp: () -> Unit, modifier: Modifier = Modifier) {
    Panel(modifier.fillMaxWidth(), highlight = true) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.PhoneAndroid, null, tint = Hall.goldBright)
            Spacer(Modifier.width(8.dp))
            Text("THIS PHONE (BETA)", style = Label)
        }
        Spacer(Modifier.height(8.dp))
        Text("Roundtable runs on this phone: no computer and no GitHub needed. About 250 MB to download once.",
            style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(10.dp))
        Button(onClick = onSetUp, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text("Set up") }
    }
}

/** Where set-up is, as one of the four steps (4 = all done). */
fun setupStep(state: RuntimeState, last: Int): Int = when (state) {
    RuntimeState.NotInstalled, RuntimeState.Checking, is RuntimeState.Downloading -> 0
    RuntimeState.Verifying -> 1
    is RuntimeState.Unpacking -> 2
    is RuntimeState.Stopped, is RuntimeState.Starting, RuntimeState.Stopping -> 3
    is RuntimeState.Running -> 4
    is RuntimeState.Failed -> last
}

val SETUP_STEPS = listOf("Download", "Check", "Unpack", "Start")

/** The "This phone" set-up page: the four steps, the command question, then Add a key. */
@Composable
fun ThisPhoneSetupScreen(onDone: () -> Unit, onBack: () -> Unit, vm: RuntimeViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    val ui by vm.ui.collectAsState()
    var lastStep by remember { mutableIntStateOf(0) }
    val step = setupStep(state, lastStep)
    LaunchedEffect(step) { lastStep = step }
    LaunchedEffect(ui.done) { if (ui.done) { vm.doneShown(); onDone() } }
    // Starting set-up is the tap that opened this page: begin straight away (fewest taps).
    LaunchedEffect(Unit) { if (state is RuntimeState.NotInstalled || state is RuntimeState.Stopped) vm.setUp() }

    Column(
        Modifier.fillMaxSize().hallBackground().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
            Text("Set up this phone", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
            if (ui.test) { Spacer(Modifier.width(8.dp)); TestBadge() }
        }
        SetupSteps(state, step, ui.downloadBytes)
        (state as? RuntimeState.Failed)?.let { f ->
            Panel(Modifier.fillMaxWidth()) {
                Text(f.failure.plain(), color = Hall.bad)
                Spacer(Modifier.height(8.dp))
                Button(onClick = { if (f.record != null) vm.start() else vm.setUp() }) { Text("Try again") }
            }
        }
        if (ui.waitingForWifi) Panel(Modifier.fillMaxWidth()) {
            Text("Waiting for Wi-Fi. Connect to Wi-Fi, then press Set up.", color = Hall.muted)
            Spacer(Modifier.height(8.dp))
            Button(onClick = { vm.setUp() }) { Text("Set up") }
        }
        if (step < 4) CommandQuestion(vm)
        if (state is RuntimeState.Running) KeyForm(ui, onSave = vm::saveKey, onSkip = vm::skipKey)
        if (state is RuntimeState.Downloading || state is RuntimeState.Unpacking) {
            Text("You can leave this page or the app: it keeps going. A cut download carries on where it stopped.",
                color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = vm::cancel) { Text("Pause the download", color = Hall.muted) }
        }
    }

    if (ui.askMobileData) AlertDialog(
        onDismissRequest = vm::waitForWifi,
        title = { Text("Use mobile data?") },
        text = { Text("You're on mobile data. The download is about ${RuntimeFailure.mb(ui.downloadBytes ?: 0)}. Download now, or wait for Wi-Fi?") },
        confirmButton = { TextButton(onClick = { vm.setUp(mobileDataOk = true) }) { Text("Download now") } },
        dismissButton = { TextButton(onClick = vm::waitForWifi) { Text("Wait for Wi-Fi") } },
        containerColor = Hall.panelHi,
    )
}

@Composable
fun TestBadge() {
    TooltipBox(
        positionProvider = TooltipDefaults.rememberPlainTooltipPositionProvider(),
        tooltip = { PlainTooltip { Text("A test build of Roundtable for this phone, signed with a public test key. The official one comes later.") } },
        state = rememberTooltipState(),
    ) {
        Text("Test download", color = Hall.onAccent, style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.background(Hall.candle, RoundedCornerShape(8.dp)).padding(horizontal = 8.dp, vertical = 2.dp))
    }
}

@Composable
internal fun SetupSteps(state: RuntimeState, step: Int, bytes: Long?) {
    Panel(Modifier.fillMaxWidth()) {
        Text("STEPS", style = Label)
        Spacer(Modifier.height(8.dp))
        SETUP_STEPS.forEachIndexed { i, name ->
            Row(Modifier.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                when {
                    i < step -> Icon(Icons.Filled.CheckCircle, "Done", tint = Hall.good, modifier = Modifier.size(20.dp))
                    i == step && state.busy -> CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Hall.gold)
                    else -> Icon(Icons.Filled.RadioButtonUnchecked, null, tint = Hall.muted, modifier = Modifier.size(20.dp))
                }
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(name, color = if (i <= step) Hall.text else Hall.muted)
                    if (i == step) detail(state, bytes)?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                }
            }
            if (i == step) progress(state)?.let { LinearProgressIndicator(progress = { it }, modifier = Modifier.fillMaxWidth().padding(start = 30.dp), color = Hall.gold) }
        }
    }
}

private fun detail(state: RuntimeState, bytes: Long?): String? = when (state) {
    RuntimeState.Checking -> "Finding the download"
    is RuntimeState.Downloading -> "${RuntimeFailure.mb(state.done)} of ${RuntimeFailure.mb(state.total)}"
    RuntimeState.Verifying -> "Making sure the download is genuine"
    is RuntimeState.Unpacking -> if (state.totalEntries > 0) "${state.entries} of ${state.totalEntries} files" else "${state.entries} files"
    is RuntimeState.Starting -> "Starting Roundtable (the first start takes a minute or two)"
    RuntimeState.NotInstalled -> bytes?.let { "About ${RuntimeFailure.mb(it)}" }
    else -> null
}

private fun progress(state: RuntimeState): Float? = when (state) {
    is RuntimeState.Downloading -> if (state.total > 0) state.done.toFloat() / state.total else null
    is RuntimeState.Unpacking -> if (state.totalEntries > 0) state.entries.toFloat() / state.totalEntries else null
    else -> null
}

/** Asked once: what happens when Roundtable wants to run a command. */
@Composable
fun CommandQuestion(vm: RuntimeViewModel) {
    var choice by rememberSaveable { mutableStateOf(vm.commandChoice) }
    Panel(Modifier.fillMaxWidth(), highlight = choice.isBlank()) {
        Text("When Roundtable wants to run a command", style = MaterialTheme.typography.titleSmall, color = Hall.goldBright)
        Spacer(Modifier.height(4.dp))
        Text("Building means running commands (installing parts, running tests). A phone has no safe box for them: " +
            "they can't reach your photos or other apps, but they can change anything inside this app.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(8.dp))
        if (choice == "run") {
            Text("Run it: chosen. You can change it in Settings, Harness on this phone.", color = Hall.good)
        } else {
            Button(onClick = { vm.chooseCommands("run"); choice = "run" }, modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                Text("Run it (recommended for building)")
            }
            OutlinedButton(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth()) { Text("Ask me first (coming soon)") }
        }
    }
}

@Composable
internal fun KeyForm(ui: RuntimeViewModel.Ui, onSave: (String) -> Unit, onSkip: () -> Unit) {
    val ctx = LocalContext.current
    var key by rememberSaveable { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    Panel(Modifier.fillMaxWidth(), highlight = true) {
        Text("ADD A KEY", style = Label)
        Spacer(Modifier.height(8.dp))
        Text("Roundtable is running. To build, it needs your DeepSeek key. It goes straight to Roundtable on this phone; the app doesn't keep it.",
            style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(DEEPSEEK_KEYS_URL))) }) {
            Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Get a key from DeepSeek")
        }
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            key, { key = it }, Modifier.fillMaxWidth(), label = { Text("DeepSeek key") }, singleLine = true,
            placeholder = { Text("sk-…") },
            visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
            trailingIcon = {
                IconButton(onClick = { show = !show }) {
                    Icon(if (show) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, if (show) "Hide key" else "Show key")
                }
            },
        )
        ui.keyError?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp)) }
        Spacer(Modifier.height(8.dp))
        Button(onClick = { onSave(key) }, enabled = !ui.savingKey, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
            if (ui.savingKey) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Save and open the Table")
        }
        TextButton(onClick = onSkip) { Text("Later", color = Hall.muted) }
    }
}
