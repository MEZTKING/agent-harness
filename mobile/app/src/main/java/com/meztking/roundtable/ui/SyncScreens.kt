package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.ProjectSetting
import com.meztking.roundtable.data.ProjectSettings
import com.meztking.roundtable.data.ProjectSettingsView
import com.meztking.roundtable.data.RoleChoice
import com.meztking.roundtable.data.SharedSettings
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel

/** A button with a tooltip (long-press) saying what it does. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TipButton(text: String, tip: String, main: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    TooltipBox(TooltipDefaults.rememberPlainTooltipPositionProvider(), tooltip = { PlainTooltip { Text(tip) } }, state = rememberTooltipState()) {
        if (main) Button(onClick = onClick, enabled = enabled, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text(text) }
        else OutlinedButton(onClick = onClick, enabled = enabled) { Text(text) }
    }
}

@Composable
private fun TopBar(title: String, onBack: () -> Unit, onRefresh: (() -> Unit)? = null, busy: Boolean = false) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
        Text(title, style = MaterialTheme.typography.titleLarge, color = Hall.goldBright, modifier = Modifier.weight(1f))
        if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Hall.gold)
        if (onRefresh != null) IconButton(onClick = onRefresh, enabled = !busy) { Icon(Icons.Filled.Refresh, "Check again", tint = Hall.gold) }
    }
}

/**
 * Your computers: This phone, your PC and the hub, each with how it stands and what can be done in one tap.
 * [onAction]: phone.setup, phone.join, phone.open, pc.pair, pc.remove, hub.add, hub.remove, refresh.
 */
@Composable
fun ConnectionsContent(rows: List<ConnectionRow>, hubSet: Boolean, phoneJoined: Boolean, busy: String?, onBack: () -> Unit, onAction: (String) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TopBar("Your computers", onBack, onRefresh = { onAction("refresh") }, busy = busy == "refresh")
        Text("Everything set up here works at once. The Table shows each project once, read from the most direct place: this phone, then your PC, then the hub.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        for (r in rows) Panel(Modifier.fillMaxWidth(), highlight = r.set && r.ok == false) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(when (r.ok) { true -> Hall.good; false -> Hall.bad; null -> Hall.muted }, CircleShape))
                Spacer(Modifier.width(10.dp))
                Text(r.line, style = MaterialTheme.typography.titleMedium, color = Hall.text)
            }
            if (r.detail.isNotBlank()) Text(r.detail, style = MaterialTheme.typography.bodySmall, color = Hall.muted, modifier = Modifier.padding(top = 4.dp))
            Spacer(Modifier.height(10.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                when (r.source) {
                    Source.PHONE -> if (!r.set) TipButton("Set up on this phone", "Downloads ${Brand.NAME} to run on the phone itself.", main = true) { onAction("phone.setup") }
                    else {
                        if (hubSet && !phoneJoined) TipButton(if (busy == "join") "Joining…" else "Join my hub",
                            "Gives the harness on this phone your hub's address and GitHub token, so it syncs with your PC. Nothing to type.",
                            main = true, enabled = busy == null) { onAction("phone.join") }
                        TipButton("Harness on this phone", "Start, stop, its log and updates.") { onAction("phone.open") }
                    }
                    Source.PC -> if (!r.set) TipButton("Pair with your PC", "Opens the camera: point it at the code ${Brand.NAME} shows on your PC.", main = true) { onAction("pc.pair") }
                    else {
                        if (r.ok == false) TipButton(if (busy == "find") "Looking…" else "Look for it",
                            "Looks for your PC on this Wi-Fi, in case its address changed. Only your own PC's answer is used.",
                            main = true, enabled = busy == null) { onAction("pc.find") }
                        TipButton("Pair again", "Scan a new code, for example after reinstalling ${Brand.NAME}.") { onAction("pc.pair") }
                        TextButton(onClick = { onAction("pc.remove") }) { Text("Unpair", color = Hall.bad) }
                    }
                    Source.HUB -> if (!r.set) TipButton("Add the hub", "Paste a GitHub token that can read and write your hub repository.", main = true) { onAction("hub.add") }
                    else {
                        TipButton("Replace token", "Paste a new GitHub token, for example when the old one expires.") { onAction("hub.add") }
                        TextButton(onClick = { onAction("hub.remove") }) { Text("Remove", color = Hall.bad) }
                    }
                }
            }
        }
        Text("Commands go to the computer that has the project. When it's off they wait in the hub, and it picks them up when it's on.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(24.dp))
    }
}

/** A field that picks one of [choices], drawn as a button with a drop-down list. */
@Composable
fun Picker(value: String, choices: List<String>, empty: String = "Not set", onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { open = true }, enabled = choices.isNotEmpty()) {
            Text(value.ifBlank { empty }, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
            Icon(Icons.Filled.ArrowDropDown, null)
        }
        DropdownMenu(open, { open = false }) {
            choices.forEach { c -> DropdownMenuItem(text = { Text(c.ifBlank { empty }) }, onClick = { open = false; onPick(c) }) }
        }
    }
}

private fun num(v: Double?, whole: Boolean): String = when {
    v == null -> ""
    whole || v % 1.0 == 0.0 -> v.toLong().toString()
    else -> v.toString()
}

/** Shared settings: the same on every computer (limits, autopilot, the default set of models, who does which job). */
@Composable
fun SharedSettingsContent(load: Load<SharedSettings>, from: String, saving: Boolean, onBack: () -> Unit, onRefresh: () -> Unit, onSave: (SharedSettings) -> Unit) {
    val s = load.data
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        TopBar("Shared settings", onBack, onRefresh, busy = load.loading)
        Text("The same on every computer: your PC, this phone and any other that joins the hub.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        if (load.error != null) ErrorLine(load.error, onRefresh)
        if (s == null) { if (load.loading) Loading("Reading the settings…"); return@Column }
        val limits = remember(s) { mutableStateMapOf<String, String>().apply { SharedSettings.LIMITS.keys.forEach { k -> put(k, num(s.limits[k], SharedSettings.whole(k))) } } }
        var pilot by remember(s) { mutableStateOf(s.autopilot) }
        var cap by remember(s) { mutableStateOf(num(s.autopilotCap, false)) }
        var profile by remember(s) { mutableStateOf(s.defaultProfile) }
        val roles = remember(s) { mutableStateMapOf<String, String>().apply { s.roles.forEach { put(it.role, it.model) } } }

        Panel(Modifier.fillMaxWidth()) {
            Text("SPENDING LIMITS", style = Label)
            Spacer(Modifier.height(6.dp))
            SharedSettings.LIMITS.forEach { (k, words) ->
                OutlinedTextField(limits[k].orEmpty(), { limits[k] = it.filter { c -> c.isDigit() || c == '.' } }, Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text(words) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            }
        }
        Panel(Modifier.fillMaxWidth()) {
            Text("AUTOPILOT", style = Label)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Answer questions while I'm away")
                    Text("It picks the recommended answer; money pauses always wait for you.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
                Switch(pilot, { pilot = it })
            }
            OutlinedTextField(cap, { cap = it.filter { c -> c.isDigit() || c == '.' } }, Modifier.fillMaxWidth(), singleLine = true,
                label = { Text("Most it may spend while on (US \$)") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
        }
        Panel(Modifier.fillMaxWidth()) {
            Text("SET OF MODELS", style = Label)
            Text("Which set builds a project unless the project says otherwise.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Spacer(Modifier.height(6.dp))
            val opts = (s.profiles + profile).filter { it.isNotBlank() }.distinct()
            if (opts.isEmpty()) Text("No sets of models named yet.", color = Hall.muted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                opts.forEach { p -> FilterChip(profile == p, { profile = p }, label = { Text(p.replaceFirstChar { it.uppercase() }) }) }
            }
        }
        Panel(Modifier.fillMaxWidth()) {
            Text("WHO DOES WHICH JOB", style = Label)
            Text("Tap a model to choose another. If it fails, the job falls back to the next model it knows.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            if (s.roles.isEmpty()) Text("No jobs listed yet.", color = Hall.muted)
            s.roles.forEach { r: RoleChoice ->
                Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                    Text(r.label, style = MaterialTheme.typography.titleSmall, color = Hall.text)
                    Text(r.role, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                    Picker(roles[r.role].orEmpty(), r.choices) { roles[r.role] = it }
                }
            }
        }
        Button(onClick = {
            onSave(s.copy(
                limits = s.limits + limits.mapNotNull { (k, v) -> v.toDoubleOrNull()?.let { k to it } },
                autopilot = pilot, autopilotCap = cap.toDoubleOrNull(), defaultProfile = profile,
                roles = s.roles.map { it.copy(model = roles[it.role] ?: it.model) },
            ))
        }, enabled = !saving, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
            if (saving) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Save for every computer")
        }
        Text(listOf(from, if (s.updatedAt.isNotBlank()) "changed ${com.meztking.roundtable.data.ago(s.updatedAt)}" + (if (s.updatedBy.isNotBlank()) " by ${s.updatedBy}" else "") else "")
            .filter { it.isNotBlank() }.joinToString(" · ") + ". Changes go straight to your PC, or through the hub when it's off.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(24.dp))
    }
}

/** A project's own settings: each with what it does, edited in the way its type needs. */
@Composable
fun ProjectSettingsContent(id: String, load: Load<ProjectSettingsView>, saving: Boolean, onBack: () -> Unit, onRefresh: () -> Unit, onSave: (Map<String, String>) -> Unit) {
    val v = load.data
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TopBar("Settings: $id", onBack, onRefresh, busy = load.loading)
        Text("This project only. They win over the shared settings.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        if (load.error != null) ErrorLine(load.error, onRefresh)
        if (v == null) { if (load.loading) Loading("Reading the settings…"); return@Column }
        v.errors.forEach { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodySmall) }
        val drafts = remember(v) { mutableStateMapOf<String, String>().apply { v.items.forEach { put(it.key, ProjectSettings.draft(it)) } } }
        // the money and the checking first; the rest behind More (short first, details on request)
        val (first, rest) = remember(v) { ProjectSettings.split(v) }
        first.forEach { s -> SettingField(s, drafts[s.key].orEmpty()) { drafts[s.key] = it } }
        if (rest.isNotEmpty()) Fold(com.meztking.roundtable.data.Words.t("More ({n})", "n" to rest.size)) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                rest.forEach { s -> SettingField(s, drafts[s.key].orEmpty()) { drafts[s.key] = it } }
            }
        }
        Button(onClick = { onSave(drafts.toMap()) }, enabled = !saving, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
            if (saving) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Save")
        }
        v.warnings.forEach { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun SettingField(s: ProjectSetting, text: String, onChange: (String) -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Text(s.label, style = MaterialTheme.typography.titleSmall, color = Hall.text)
        Text(s.description, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(6.dp))
        when (s.type) {
            "choice" -> FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                s.choices.forEach { c -> FilterChip(text == c, { onChange(c) }, label = { Text(c.ifBlank { "The usual" }) }) }
            }
            "int" -> OutlinedTextField(text, { onChange(it.filter { c -> c.isDigit() }) }, Modifier.fillMaxWidth(), singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            "lines", "map", "number-map" -> OutlinedTextField(text, onChange, Modifier.fillMaxWidth(), minLines = 2,
                supportingText = { Text(when (s.type) { "lines" -> "One on each line"; "number-map" -> "One on each line, as name: number" + if (s.keys.isNotEmpty()) " (${s.keys.joinToString(", ")})" else ""; else -> "One on each line, as name: value" }) })
            else -> OutlinedTextField(text, onChange, Modifier.fillMaxWidth(), singleLine = s.key != "notes", minLines = if (s.key == "notes") 2 else 1)
        }
        Text(s.sourceWords, style = MaterialTheme.typography.labelSmall, color = Hall.muted, modifier = Modifier.padding(top = 2.dp))
    }
}

/** Your computers, wired: the one-tap pairing scan, Join my hub, and removing a connection (asked first). */
@Composable
fun ConnectionsScreen(
    onBack: () -> Unit, onPhoneSetup: () -> Unit, onHarness: () -> Unit, onHub: () -> Unit, onChanged: () -> Unit,
    vm: ConnectionsViewModel = androidx.lifecycle.viewmodel.compose.viewModel(),
    setup: SetupViewModel = androidx.lifecycle.viewmodel.compose.viewModel(),
) {
    val rows by vm.rows.collectAsState()
    val busy by vm.busy.collectAsState()
    val notice by vm.notice.collectAsState()
    val pairing by setup.state.collectAsState()
    var confirm by remember { mutableStateOf<String?>(null) }
    val snack = remember { androidx.compose.material3.SnackbarHostState() }
    androidx.compose.runtime.LaunchedEffect(Unit) { vm.refresh() }
    androidx.compose.runtime.LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); vm.noticeShown() } }
    androidx.compose.runtime.LaunchedEffect(pairing.done, pairing.error) {
        if (pairing.done) { setup.reset(); onChanged(); vm.refresh(); snack.showSnackbar("Paired with your PC") }
        pairing.error?.let { snack.showSnackbar(it); setup.clearError() }
    }
    val scan = androidx.activity.compose.rememberLauncherForActivityResult(com.journeyapps.barcodescanner.ScanContract()) { r ->
        val text = r.contents ?: return@rememberLauncherForActivityResult
        val offer = com.meztking.roundtable.net.Pairing.parse(text)
        if (offer == null) vm.notify("That QR code isn't a ${Brand.NAME} pairing code.") else setup.pair(offer, offer.code)
    }
    androidx.compose.material3.Scaffold(containerColor = androidx.compose.ui.graphics.Color.Transparent,
        snackbarHost = { androidx.compose.material3.SnackbarHost(snack) }) { pad ->
        Box(Modifier.padding(pad)) {
            ConnectionsContent(rows, vm.hubSet, vm.phoneJoined, if (pairing.busy) "pair" else busy, onBack) { a ->
                when (a) {
                    "refresh" -> vm.refresh()
                    "phone.setup" -> onPhoneSetup()
                    "phone.open" -> onHarness()
                    "phone.join" -> vm.joinHub()
                    "pc.pair" -> scan.launch(com.journeyapps.barcodescanner.ScanOptions().setPrompt("Point at the code on your PC").setBeepEnabled(false)
                        .setOrientationLocked(false).setDesiredBarcodeFormats(com.journeyapps.barcodescanner.ScanOptions.QR_CODE))
                    "pc.find" -> vm.findPc(onChanged)
                    "hub.add" -> onHub()
                    "pc.remove", "hub.remove" -> confirm = a
                }
            }
        }
    }
    confirm?.let { what ->
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (what == "pc.remove") "Unpair this phone?" else "Remove the GitHub token?") },
            text = {
                Text(if (what == "pc.remove") "The phone forgets your PC. To use it again, pair again from ${Brand.NAME}."
                else "The phone forgets the token. Delete it on GitHub too if you no longer need it.")
            },
            confirmButton = {
                TextButton(onClick = {
                    if (what == "pc.remove") vm.unpair() else vm.removeHub()
                    confirm = null
                    onChanged()
                }) { Text(if (what == "pc.remove") "Unpair" else "Remove", color = Hall.bad) }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Keep") } },
            containerColor = Hall.panelHi,
        )
    }
}

