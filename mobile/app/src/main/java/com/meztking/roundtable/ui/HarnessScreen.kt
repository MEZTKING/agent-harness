package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.meztking.roundtable.runtime.RuntimeFailure
import com.meztking.roundtable.runtime.RuntimeState
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.hallBackground

/** Plain words for where Roundtable on this phone stands. */
fun runtimeStatus(state: RuntimeState): String = when (state) {
    RuntimeState.NotInstalled -> "Not set up"
    RuntimeState.Checking -> "Looking for the download"
    is RuntimeState.Downloading, RuntimeState.Verifying, is RuntimeState.Unpacking -> "Setting up"
    is RuntimeState.Stopped -> "Stopped"
    is RuntimeState.Starting -> "Starting"
    is RuntimeState.Running -> "Running"
    RuntimeState.Stopping -> "Stopping"
    is RuntimeState.Failed -> "Stopped: something went wrong"
}

/** Phone makers known to stop apps in the background harder than Android itself. */
fun strictMaker(manufacturer: String): Boolean = manufacturer.lowercase() in setOf("oppo", "realme", "oneplus", "xiaomi", "redmi", "poco", "vivo", "huawei", "honor")

/** Settings, Harness on this phone. */
@Composable
fun HarnessScreen(onBack: () -> Unit, onSetUp: () -> Unit, vm: RuntimeViewModel = viewModel()) {
    val ctx = LocalContext.current
    val state by vm.state.collectAsState()
    val ui by vm.ui.collectAsState()
    var confirm by rememberSaveable { mutableStateOf<String?>(null) }
    var tick by rememberSaveable { mutableStateOf(0) }
    LaunchedEffect(state is RuntimeState.Running, tick) { vm.refreshStorage() }

    Column(
        Modifier.fillMaxSize().hallBackground().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
            Text("Harness on this phone", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("ROUNDTABLE ON THIS PHONE", style = Label)
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(runtimeStatus(state), style = MaterialTheme.typography.titleMedium,
                    color = if (state is RuntimeState.Running) Hall.good else if (state is RuntimeState.Failed) Hall.bad else Hall.text)
                val record = when (state) {
                    is RuntimeState.Running -> (state as RuntimeState.Running).record
                    is RuntimeState.Stopped -> (state as RuntimeState.Stopped).record
                    else -> null
                }
                if (record?.isTest == true) { Spacer(Modifier.width(8.dp)); TestBadge() }
            }
            (state as? RuntimeState.Failed)?.let { Text(it.failure.plain(), color = Hall.bad, style = MaterialTheme.typography.bodySmall) }
            Spacer(Modifier.height(8.dp))
            if (state is RuntimeState.NotInstalled) {
                Button(onClick = onSetUp, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text("Set up") }
            } else FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = vm::start, enabled = !state.busy && state !is RuntimeState.Running) { Text("Start") }
                OutlinedButton(onClick = vm::stop, enabled = state is RuntimeState.Running || state is RuntimeState.Starting) { Text("Stop") }
                OutlinedButton(onClick = vm::restart, enabled = !state.busy && state !is RuntimeState.NotInstalled) { Text("Restart") }
                TextButton(onClick = { vm.showLog(true) }) { Text("Show log") }
            }
        }

        if (state !is RuntimeState.NotInstalled) CommandQuestion(vm)
        if (state !is RuntimeState.NotInstalled) {
            val check by vm.check.collectAsState()
            val notice by vm.updateNotice.collectAsState()
            RuntimeUpdate(check, busy = state.busy, onCheck = vm::checkForNewer, onUpdate = vm::updateRuntime,
                notice = notice?.plain(), onTryAgain = vm::tryNewAgain)
        }

        if (state !is RuntimeState.NotInstalled) PhoneProjectsCard(vm.phoneProjects, vm::projectNames, running = state is RuntimeState.Running)

        Panel(Modifier.fillMaxWidth()) {
            Text("STORAGE", style = Label)
            Spacer(Modifier.height(8.dp))
            Text("Used on this phone: " + (ui.storage?.let { RuntimeFailure.mb(it) } ?: "…"))
            Text("Of that, your projects: " + (ui.projects?.let { RuntimeFailure.mb(it) } ?: "…"), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { confirm = "remove" }, enabled = !state.busy) { Text("Remove (keeps projects)") }
                TextButton(onClick = { confirm = "delete" }, enabled = !state.busy) { Text("Delete everything", color = Hall.bad) }
            }
        }

        KeepRunning(onChanged = { tick++ })
        Spacer(Modifier.height(24.dp))
    }

    ui.log?.let { text ->
        AlertDialog(
            onDismissRequest = { vm.showLog(false) },
            title = { Text("Log") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text("The secret ${Brand.NAME} uses is hidden.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                    Text(text, fontFamily = com.meztking.roundtable.ui.theme.Mono, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = { vm.showLog(false) }) { Text("Close") } },
            containerColor = Hall.panelHi,
        )
    }

    confirm?.let { what ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (what == "remove") "Remove ${Brand.NAME} from this phone?" else "Delete everything?") },
            text = {
                Text(if (what == "remove") "The download goes (it can be set up again). Your projects and its settings stay."
                else "${Brand.NAME}, your projects on this phone and its settings, keys included, are deleted. This can't be undone.")
            },
            confirmButton = {
                TextButton(onClick = { vm.remove(keepProjects = what == "remove"); confirm = null }) {
                    Text(if (what == "remove") "Remove" else "Delete everything", color = Hall.bad)
                }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Keep") } },
            containerColor = Hall.panelHi,
        )
    }
}

/** The "Keep it running" checklist: notifications, battery Unrestricted, and the phone maker's own setting. */
@Composable
private fun KeepRunning(onChanged: () -> Unit) {
    val ctx = LocalContext.current
    val notifications = NotificationManagerCompat.from(ctx).areNotificationsEnabled()
    val battery = runCatching { ctx.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(ctx.packageName) == true }.getOrDefault(false)
    val maker = Build.MANUFACTURER.orEmpty()
    Panel(Modifier.fillMaxWidth()) {
        Text("KEEP IT RUNNING", style = Label)
        Spacer(Modifier.height(6.dp))
        Text("Android stops apps in the background. These keep ${Brand.NAME} building while the phone is locked.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(8.dp))
        Check(notifications, "Notifications on", "So Android lets ${Brand.NAME} keep its \"running\" notice.", "Turn on") {
            ctx.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName))
            onChanged()
        }
        Check(battery, "Battery: Unrestricted", "In the app's settings: Battery, then Unrestricted.", "Open") {
            ctx.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}")))
            onChanged()
        }
        Spacer(Modifier.height(6.dp))
        if (strictMaker(maker)) {
            Text(if (maker.equals("oppo", true) || maker.equals("realme", true) || maker.equals("oneplus", true))
                "On OPPO phones (ColorOS) also: in the app's settings, Battery, turn on Allow background activity; and in Recent apps, " +
                    "pull ${Brand.NAME} down to lock it. Step by step:"
            else "Your phone's maker adds its own battery saver. Step by step:", style = MaterialTheme.typography.bodySmall)
        } else Text("Some phones add their own battery saver. Step by step:", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        TextButton(onClick = {
            val page = if (strictMaker(maker)) "https://dontkillmyapp.com/${maker.lowercase()}" else "https://dontkillmyapp.com"
            ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(page)))
        }) { Text("Open dontkillmyapp.com") }
    }
}

@Composable
private fun Check(ok: Boolean, title: String, help: String, action: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.ErrorOutline, if (ok) "Done" else "Not yet",
            tint = if (ok) Hall.good else Hall.warn, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title)
            Text(help, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
        if (!ok) TextButton(onClick = onClick) { Text(action) }
    }
}

/** Check for a newer Roundtable on this phone, and fetch it in one more tap. */
@Composable
fun RuntimeUpdate(
    check: RuntimeCheck?, busy: Boolean, onCheck: () -> Unit, onUpdate: () -> Unit,
    notice: String? = null, onTryAgain: () -> Unit = {},
) {
    Panel(Modifier.fillMaxWidth()) {
        Text("UPDATES", style = Label)
        Spacer(Modifier.height(8.dp))
        if (notice != null) {
            Text(notice, color = Hall.ember, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(8.dp))
        }
        when (check) {
            null -> Text("The harness on this phone is updated separately from the app.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            RuntimeCheck.Checking -> Text("Checking…", color = Hall.muted)
            is RuntimeCheck.UpToDate -> Text("You have the newest one" + (if (check.version.isNotBlank()) " (${check.version})." else "."), color = Hall.good)
            is RuntimeCheck.Newer -> {
                Text("A newer one is ready" + (if (check.version.isNotBlank()) ": ${check.version}" else "") + ", ${RuntimeFailure.mb(check.bytes)} to download.")
                Text("${Brand.NAME} stops for a moment while it swaps over, then starts again. Your projects and keys stay.",
                    style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            }
            is RuntimeCheck.Problem -> Text(check.text, color = Hall.bad, style = MaterialTheme.typography.bodySmall)
            is RuntimeCheck.HeldBack -> Text("The newest one" + (if (check.version.isNotBlank()) " (${check.version})" else "") +
                " didn't start on this phone before, so it isn't tried again by itself.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        Spacer(Modifier.height(8.dp))
        if (notice != null || check is RuntimeCheck.HeldBack) OutlinedButton(onClick = onTryAgain, enabled = !busy) { Text("Try the new one again") }
        else if (check is RuntimeCheck.Newer) Button(onClick = onUpdate, enabled = !busy,
            colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text("Update now") }
        else OutlinedButton(onClick = onCheck, enabled = !busy && check != RuntimeCheck.Checking) { Text("Check for a newer runtime") }
    }
}
