package com.meztking.roundtable.notify

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label

/** Put on a project's screen: while it is in front, that project's news makes no notification. */
@Composable
fun QuietWhileOpen(project: String) {
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner, project) {
        val obs = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_RESUME -> OnScreen.project = project
                Lifecycle.Event.ON_PAUSE -> if (OnScreen.project == project) OnScreen.project = null
                else -> {}
            }
        }
        owner.lifecycle.addObserver(obs)
        if (owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) OnScreen.project = project
        onDispose {
            owner.lifecycle.removeObserver(obs)
            if (OnScreen.project == project) OnScreen.project = null
        }
    }
}

/** Settings → Notifications: a switch per kind of news (this phone's own), and Android's own page for sounds. */
@Composable
fun ColumnScope.NotifySettingsPanel() {
    val ctx = LocalContext.current
    val prefs = remember { NotifyPrefs(ctx) }
    val on = remember { mutableStateMapOf<String, Boolean>().apply { NewsKind.ALL.forEach { put(it, prefs.on(it)) } } }
    Text("NOTIFICATIONS", style = Label)
    Spacer(Modifier.height(8.dp))
    Text("Every 15 minutes or so the phone looks for news and tells you once about each. Answer short questions from the notification itself.",
        style = MaterialTheme.typography.bodySmall)
    Spacer(Modifier.height(6.dp))
    NewsKind.ALL.forEach { kind ->
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f)) {
                Text(NewsKind.name(kind), style = MaterialTheme.typography.bodyMedium)
                Text(NewsKind.hint(kind), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            }
            Switch(checked = on[kind] == true, onCheckedChange = { v -> prefs.set(kind, v); on[kind] = v },
                modifier = Modifier.semantics { contentDescription = "${NewsKind.name(kind)} notifications" })
        }
    }
    Spacer(Modifier.height(6.dp))
    OutlinedButton(onClick = {
        val i = if (Build.VERSION.SDK_INT >= 26) Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
        else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}"))
        ctx.startActivity(i)
    }) { Text("Sounds and more") }
}
