package com.meztking.roundtable.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.BuildConfig
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.work.Watch

@Composable
fun SettingsScreen(onConnect: () -> Unit, onChanged: () -> Unit, onHarness: (() -> Unit)? = null, onComputers: () -> Unit = {}, onShared: () -> Unit = {}) {
    val ctx = LocalContext.current
    val app = ctx.applicationContext as RoundtableApp
    val store = app.store
    var version by remember { mutableIntStateOf(0) } // bumps to re-read the store after a change
    fun changed() { version++; onChanged() }
    val readAt = version // reading it here recomposes the screen when it changes
    val hasHub = store.githubToken != null
    val link = store.link
    var identity by rememberSaveable { mutableStateOf(store.identity) }
    var confirm by rememberSaveable { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall, color = Hall.goldBright)

        Panel(Modifier.fillMaxWidth()) {
            Text("YOUR COMPUTERS", style = Label)
            Spacer(Modifier.height(8.dp))
            val b = app.backend()
            val rows = connectionRows(ConnInputs(
                phoneSet = store.thisPhone, phoneState = phoneWords(app.runtime.state.value),
                phoneRunning = app.runtime.state.value is com.meztking.roundtable.runtime.RuntimeState.Running,
                pcSet = link != null, pc = b?.health(com.meztking.roundtable.data.Source.PC) ?: com.meztking.roundtable.data.ConnHealth(lastOk = store.lastOk(com.meztking.roundtable.data.Source.PC)),
                pcHost = (b?.parts?.get(com.meztking.roundtable.data.Source.PC) as? com.meztking.roundtable.data.PcBackend)?.api?.activeHost,
                hubSet = hasHub, hubRepo = store.hubRepo,
                hub = b?.health(com.meztking.roundtable.data.Source.HUB) ?: com.meztking.roundtable.data.ConnHealth(lastOk = store.lastOk(com.meztking.roundtable.data.Source.HUB)),
            ))
            rows.forEach { Text(it.line, color = if (it.ok == false) Hall.bad else if (it.set) Hall.text else Hall.muted, style = MaterialTheme.typography.bodyMedium) }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onComputers) { Text("Open") }
                OutlinedButton(onClick = onConnect) { Text(if (hasHub || link != null) "Add the hub or a PC" else "Set up") }
            }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("SHARED SETTINGS", style = Label)
            Spacer(Modifier.height(8.dp))
            Text("Spending limits, autopilot, the set of models and who does which job: the same on every computer.",
                style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Spacer(Modifier.height(6.dp))
            OutlinedButton(onClick = onShared, enabled = app.backend() != null) { Text("Open") }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("WHO YOU ARE IN THE HUB", style = Label)
            Spacer(Modifier.height(8.dp))
            Text("Letters you write are sent as this project, and letters to it are yours.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            OutlinedTextField(identity, { identity = it.trim() }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Identity") })
            Spacer(Modifier.height(6.dp))
            Button(onClick = { store.identity = identity.ifBlank { "me" }; identity = store.identity; changed() }, enabled = identity != store.identity) { Text("Save") }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("NOTIFICATIONS", style = Label)
            Spacer(Modifier.height(8.dp))
            Text("Every 15 minutes or so the phone checks for new letters for you and new high-priority to-dos, and tells you once about each.",
                style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(6.dp))
            OutlinedButton(onClick = {
                val i = if (Build.VERSION.SDK_INT >= 26) Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
                else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}"))
                ctx.startActivity(i)
            }) { Text("Notification settings") }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("ABOUT", style = Label)
            Spacer(Modifier.height(8.dp))
            UpdateAbout()
            Text("Released with Roundtable Hold of the same version.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        Spacer(Modifier.height(24.dp))
    }

    confirm?.let { what ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (what == "pc") "Unpair this phone?" else "Remove the GitHub token?") },
            text = {
                Text(if (what == "pc") "The phone forgets your PC. To use it again, pair again from Roundtable Hold. You can also remove this phone there."
                else "The phone forgets the token. Delete it on GitHub too if you no longer need it.")
            },
            confirmButton = {
                TextButton(onClick = {
                    if (what == "pc") store.link = null else store.githubToken = null
                    store.mode = ""
                    store.cachedHall = ""
                    if (!store.configured) Watch.cancel(ctx)
                    confirm = null
                    changed()
                }) { Text(if (what == "pc") "Unpair" else "Remove", color = Hall.bad) }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Keep") } },
            containerColor = Hall.panelHi,
        )
    }
}

@Composable
private fun Line(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, Modifier.width(110.dp), color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
