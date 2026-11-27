package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.SessionSummary
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel

private fun bitmap(bytes: ByteArray): ImageBitmap? =
    runCatching { BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap() }.getOrNull()

/**
 * The Live tab: the newest pictures of the project's app, and the latest task's steps as lines. A finished
 * project shows its final pictures (or a button to take them) and folds its steps.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LiveTab(live: Load<LiveView>, mode: Mode?, onRefresh: () -> Unit, finished: Boolean = false,
            onTakePictures: (() -> Unit)? = null, sent: String? = null) {
    var big by remember { mutableStateOf<Pair<String, ImageBitmap>?>(null) }
    PullToRefreshBox(live.loading && live.data != null, onRefresh, Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (live.error != null) item { ErrorLine(live.error, onRefresh) }
            val v = live.data
            when {
                v == null && live.loading -> item { Loading("Fetching the pictures…") }
                v == null -> {}
                else -> {
                    item { Pictures(v, finished, onTakePictures, sent) { label, img -> big = label to img } }
                    item { Session(v, mode, finished) }
                }
            }
        }
    }
    big?.let { (label, img) -> FullScreen(label, img) { big = null } }
}

@Composable
private fun Pictures(v: LiveView, finished: Boolean, onTake: (() -> Unit)?, sent: String?, open: (String, ImageBitmap) -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        val s = v.shots
        val has = s != null && v.kinds.isNotEmpty()
        Text(if (finished && has) "FINAL PICTURES" + (s?.at?.ifBlank { null }?.let { " · ${day(it)}" } ?: "") else "PICTURES OF THE APP",
            style = Label, color = Hall.muted)
        if (!has) {
            if (finished) {
                Text("No pictures of this project yet.", color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
                if (onTake != null) {
                    Spacer(Modifier.height(8.dp))
                    if (sent != null) Text(sent, color = Hall.good, style = MaterialTheme.typography.bodySmall)
                    else androidx.compose.material3.Button(onClick = onTake) { Text("Take pictures now") }
                }
            } else Text(s?.failed?.ifBlank { null } ?: s?.note?.ifBlank { null }
                ?: "Roundtable takes pictures of the app after every finished task. None yet.",
                color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
            return@Panel
        }
        s!!
        if (!finished) Text(listOfNotNull(s.title.ifBlank { null }?.let { "After “$it”" }, s.at.ifBlank { null }?.let { ago(it) })
            .joinToString(" · "), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(10.dp))
        v.images["desktop"]?.let { Shot("Computer", it, Modifier.fillMaxWidth(), open) }
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            v.images["phone"]?.let { Shot("Phone", it, Modifier.weight(0.42f), open) }
            v.images["dark"]?.let { Shot("Dark mode", it, Modifier.weight(1f), open) } ?: Spacer(Modifier.weight(1f))
        }
        if (s.errors.isNotEmpty() && !finished) Text("The page reported ${s.errors.size} error${if (s.errors.size > 1) "s" else ""}: ${s.errors.first()}",
            Modifier.padding(top = 10.dp), color = Hall.bad, style = MaterialTheme.typography.bodySmall, maxLines = 3)
        if (s.note.isNotBlank() && !finished) Text(s.note, Modifier.padding(top = 6.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        Text("Tap a picture to see it full size.", Modifier.padding(top = 6.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Shot(label: String, bytes: ByteArray, modifier: Modifier, open: (String, ImageBitmap) -> Unit) {
    val img = remember(bytes) { bitmap(bytes) } ?: return
    Column(modifier) {
        Image(img, "$label: tap to see it full size", Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .border(1.dp, Hall.line, RoundedCornerShape(10.dp)).clickable { open(label, img) }, contentScale = ContentScale.FillWidth)
        Text(label, Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

/** The latest task's steps, like the lines of a terminal. */
@Composable
private fun Session(v: LiveView, mode: Mode?, finished: Boolean) {
    val s: SessionSummary? = v.session
    val t = s?.task
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (finished && !v.running) "WHAT IT DID LAST" else "WHAT IT'S DOING", style = Label, color = Hall.muted, modifier = Modifier.weight(1f))
            if (v.running) Text("● Live" + if (v.progress.isNotBlank()) " · ${v.progress}" else "", color = Hall.good, style = MaterialTheme.typography.labelMedium)
        }
        if (v.from.isNotBlank()) Text(v.from + (s?.at?.ifBlank { null }?.let { " · ${ago(it)}" } ?: "") + if (v.running) " · updates by itself" else "",
            color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        if (t == null) {
            Text(if (finished) "This project was built before Roundtable kept a step list." else "The steps show here once a task has run.",
                color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
            return@Panel
        }
        Text("[${t.id}] ${t.title}", color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
        Text(listOfNotNull(t.role.ifBlank { null }, t.status.ifBlank { null }, if (t.cost > 0) "$%.4f".format(t.cost) else null)
            .joinToString(" · "), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(8.dp))
        if (finished && !v.running) Fold("Its steps (${t.steps.size})") { Steps(t.steps) } else Steps(t.steps)
        if (mode == Mode.HUB && v.from.isBlank() && !finished) Text("Only the latest task's last steps come through the hub; the PC app shows every step and change.",
            Modifier.padding(top = 8.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

/** "26 Nov 2026" from an ISO time. */
private fun day(iso: String): String = runCatching {
    java.time.format.DateTimeFormatter.ofPattern("d MMM yyyy").withZone(java.time.ZoneId.systemDefault()).format(java.time.Instant.parse(iso))
}.getOrDefault(iso.take(10))

@Composable
private fun Steps(steps: List<com.meztking.roundtable.data.SessionStep>) {
        Column(Modifier.fillMaxWidth().background(TermBg, RoundedCornerShape(10.dp)).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            for (step in steps) {
                val colour = when {
                    step.error -> TermBad
                    step.kind == "review" && step.line.startsWith("✓") -> TermGood
                    step.kind == "review" -> TermBad
                    step.kind == "say" -> TermText
                    step.kind == "tool" -> TermText
                    else -> TermMuted
                }
                Text(step.line, color = colour, fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 16.sp)
            }
        }
}

// The session reads like a terminal in both looks: dark oak (the dark tokens).
private val TermBg = Color(0xFF1B1410)
private val TermText = Color(0xFFF4E8D4)
private val TermMuted = Color(0xFFB9A58C)
private val TermGood = Color(0xFFA9C48F)
private val TermBad = Color(0xFFF08A70)

/** A picture full screen: pinch to zoom, drag to look around, tap Close. */
@Composable
private fun FullScreen(label: String, img: ImageBitmap, close: () -> Unit) {
    Dialog(close, DialogProperties(usePlatformDefaultWidth = false)) {
        var scale by rememberSaveable { mutableFloatStateOf(1f) }
        var offset by remember { mutableStateOf(Offset.Zero) }
        Box(Modifier.fillMaxSize().background(Color(0xEE000000))) {
            Image(img, label, Modifier.fillMaxSize().pointerInput(Unit) {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(1f, 5f)
                    offset = if (scale == 1f) Offset.Zero else offset + pan
                }
            }.graphicsLayer(scaleX = scale, scaleY = scale, translationX = offset.x, translationY = offset.y),
                contentScale = ContentScale.Fit)
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.weight(1f).padding(start = 8.dp), color = TermText)
                TextButton(onClick = close) { Text("Close", color = TermText) }
            }
        }
    }
}
