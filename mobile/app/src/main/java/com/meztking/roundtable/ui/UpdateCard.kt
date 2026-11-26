package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.meztking.roundtable.update.AppUpdater
import com.meztking.roundtable.update.UpdateUi
import com.meztking.roundtable.update.UpdateWorker
import com.meztking.roundtable.update.notesPreview
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Panel

/** The updater, unless the screen is drawn in a preview or a screenshot test. */
@Composable
private fun rememberUpdater(): AppUpdater? {
    val ctx = LocalContext.current
    if (LocalInspectionMode.current) return null
    return remember { runCatching { AppUpdater.get(ctx) }.getOrNull() }
}

/** Settings → About: the version, whether it's up to date, and Download and install when a newer one is out. */
@Composable
fun UpdateAbout() {
    val ctx = LocalContext.current
    val updater = rememberUpdater() ?: return
    val s by updater.state.collectAsState()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { updater.onResumed() }
    val new = s.available
    Text(
        when {
            new != null -> "Roundtable Mobile ${s.current} · ${new.version} is out"
            s.latest != null -> "Roundtable Mobile ${s.current} · up to date"
            else -> "Roundtable Mobile ${s.current}"
        },
        style = MaterialTheme.typography.bodyLarge, color = if (new != null) Hall.goldBright else Hall.text,
    )
    if (new != null) {
        val notes = notesPreview(new.notes)
        if (notes.isNotBlank()) Text("What's new: $notes", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(8.dp))
        UpdateActions(updater, s)
    } else {
        Text(if (s.checking) "Checking…" else if (s.checkedAt > 0) "Checked ${checkedAgo(s.checkedAt)}." else "Not checked yet.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        s.error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Hall.bad) }
    }
    Spacer(Modifier.height(6.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("Check for updates", style = MaterialTheme.typography.bodyMedium)
            Text("When the app opens (at most every 4 hours) and once a day. It only asks GitHub.",
                style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        Switch(s.enabled, { on ->
            updater.enabled = on
            if (on) UpdateWorker.schedule(ctx) else UpdateWorker.cancel(ctx)
        })
    }
    if (new == null) TextButton(onClick = updater::checkNow, enabled = !s.checking) { Text("Check now") }
}

/** On the Table: a new version is out. Update works right here; the cross hides it until the next version. */
@Composable
fun UpdateBanner(modifier: Modifier = Modifier) {
    val updater = rememberUpdater() ?: return
    val s by updater.state.collectAsState()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { updater.onResumed() }
    val new = s.available ?: return
    if (!s.showBanner && s.phase == UpdateUi.Phase.IDLE && s.error == null) return
    Panel(modifier.fillMaxWidth(), highlight = true) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Roundtable Mobile ${new.version} is out", style = MaterialTheme.typography.titleSmall, color = Hall.goldBright)
                val notes = notesPreview(new.notes, lines = 1, maxChars = 90)
                if (notes.isNotBlank()) Text(notes, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
            }
            if (s.phase == UpdateUi.Phase.IDLE) {
                TooltipBox(TooltipDefaults.rememberPlainTooltipPositionProvider(),
                    tooltip = { PlainTooltip { Text("Hide this until the next version. You can still update in Settings.") } },
                    state = rememberTooltipState()) {
                    IconButton(onClick = updater::dismissBanner) { Icon(Icons.Filled.Close, "Hide until the next version", tint = Hall.muted) }
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        UpdateActions(updater, s, short = true)
    }
}

/** The button, the progress, Android's question and any error: the same in Settings and on the Table. */
@Composable
private fun UpdateActions(updater: AppUpdater, s: UpdateUi, short: Boolean = false) {
    val new = s.available ?: return
    val size = if (new.size > 0) AppUpdater.mb(new.size) else null
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        when (s.phase) {
            UpdateUi.Phase.DOWNLOADING -> {
                val total = if (s.total > 0) s.total else new.size
                if (total > 0) LinearProgressIndicator({ (s.done.toFloat() / total).coerceIn(0f, 1f) }, Modifier.fillMaxWidth(), color = Hall.gold)
                else LinearProgressIndicator(Modifier.fillMaxWidth(), color = Hall.gold)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (total > 0) "Downloading… ${AppUpdater.mb(s.done)} of ${AppUpdater.mb(total)}" else "Downloading… ${AppUpdater.mb(s.done)}",
                        Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                    TextButton(onClick = updater::cancelDownload) { Text("Stop") }
                }
            }
            UpdateUi.Phase.INSTALLING ->
                Text("Handing it to Android… tap Update (or Install) when it asks.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            UpdateUi.Phase.NEED_PERMISSION -> {
                Text("Android needs your OK once: turn on “Allow from this source” for Roundtable Mobile, then come back here.",
                    style = MaterialTheme.typography.bodySmall)
                Button(onClick = updater::openPermission, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                    Text("Open the setting")
                }
            }
            else -> {
                Button(onClick = { updater.downloadAndInstall() }, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                    Text(if (short) "Update" else "Download and install" + (size?.let { " ($it)" } ?: ""))
                }
                if (!s.explained && !short) {
                    Text("Android will ask once to allow installs from Roundtable Mobile: say yes, and updates install from here.",
                        style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
            }
        }
        s.error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Hall.bad) }
    }
    if (s.phase == UpdateUi.Phase.ASK_DATA) {
        AlertDialog(
            onDismissRequest = updater::cancelAsk,
            title = { Text("Use mobile data?") },
            text = { Text("You're not on Wi-Fi. The update is ${size ?: "a few MB"}. Download it now over mobile data?") },
            confirmButton = { TextButton(onClick = { updater.downloadAndInstall(overMobileData = true) }) { Text("Download") } },
            dismissButton = { TextButton(onClick = updater::cancelAsk) { Text("Wait for Wi-Fi") } },
            containerColor = Hall.panelHi,
        )
    }
}

private fun checkedAgo(at: Long): String {
    val mins = ((System.currentTimeMillis() - at) / 60000).coerceAtLeast(0)
    return when {
        mins < 1 -> "just now"
        mins < 60 -> "$mins min ago"
        mins < 48 * 60 -> "${mins / 60} h ago"
        else -> "${mins / 1440} days ago"
    }
}
