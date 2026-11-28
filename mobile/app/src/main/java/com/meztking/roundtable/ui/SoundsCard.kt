package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.SoundItem
import com.meztking.roundtable.data.Sounds
import com.meztking.roundtable.data.SoundsView
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * A project's sounds (GET /api/sounds), read only: each with Play (the phone's own player, the file fetched from the
 * machine), who made it and what it cost, and "$0.42 of $2 used". Nothing shows for a project with no sounds, or a PC
 * too old to say. Make it again and the service are chosen on the PC.
 */
@Composable
fun SoundsCard(api: Api, path: String) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var v by remember(path) { mutableStateOf<SoundsView?>(null) }
    var said by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(path) { v = runCatching { Sounds.parse(api.feature("GET", Sounds.url(path))) }.getOrNull() }
    val files = remember(api, path) { ApiFiles(api, path) }
    v?.let { view ->
        SoundsCardView(view, said) { s ->
            scope.launch {
                said = try {
                    shareFile(ctx, files.copy(s.file), view = true)
                } catch (e: CancellationException) { throw e } catch (e: Exception) { friendly(e) }
            }
        }
    }
}

@Composable
fun SoundsCardView(v: SoundsView, said: String? = null, onPlay: (SoundItem) -> Unit = {}) {
    if (v.sounds.isEmpty()) return
    Panel(Modifier.fillMaxWidth()) {
        Text(Words.t("SOUNDS"), style = Label, color = Hall.muted)
        Text((if (v.sounds.size == 1) Words.t("1 sound") else Words.t("{n} sounds", "n" to v.sounds.size)) + " · " + Sounds.spendLine(v), color = Hall.text,
            style = MaterialTheme.typography.bodyMedium)
        for (s in v.sounds) Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(s.heading, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (s.line.isNotBlank()) Text(s.line, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
            if (Sounds.playable(s)) TextButton({ onPlay(s) }) { Text(Words.t("Play")) }
        }
        said?.let { Text(it, Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        Text(Words.t("New sounds and the service are chosen on your PC."), Modifier.padding(top = 6.dp), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
    }
}
