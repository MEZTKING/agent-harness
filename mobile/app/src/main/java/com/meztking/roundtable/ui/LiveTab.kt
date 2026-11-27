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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Detail
import com.meztking.roundtable.data.LiveDetail
import com.meztking.roundtable.ui.theme.LocalComfort
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.SessionSummary
import com.meztking.roundtable.data.SessionTask
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlin.math.roundToInt

private fun bitmap(bytes: ByteArray): ImageBitmap? =
    runCatching { BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap() }.getOrNull()

/**
 * The Live tab: the newest pictures of the project's app, and the latest task's steps as lines (several tasks at
 * once: a short row each, with where its time went and how full its context is). A finished
 * project shows its final pictures (or a button to take them) and folds its steps.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LiveTab(live: Load<LiveView>, mode: Mode?, onRefresh: () -> Unit, finished: Boolean = false,
            onTakePictures: (() -> Unit)? = null, sent: String? = null, detail: Detail? = null) {
    // how much it shows: the owner's choice in Comfort (Standard when nothing is chosen)
    val level = detail ?: LocalComfort.current?.detail ?: Detail.STANDARD
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
                    item { Session(v, mode, finished, LiveDetail.of(level, finished, v.running)) }
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

/** The latest task's steps, like the lines of a terminal. Several tasks at once: one short row each, side by side
 * in a list (title, state, what it's doing, the time bar and the context gauge), their steps folded. */
@Composable
private fun Session(v: LiveView, mode: Mode?, finished: Boolean, d: LiveDetail) {
    val s: SessionSummary? = v.session
    val shown = s?.shown.orEmpty()
    val t = shown.lastOrNull()
    Panel(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (finished && !v.running) "WHAT IT DID LAST" else if (shown.size > 1) "WORKING ON ${shown.size} TASKS AT ONCE" else "WHAT IT'S DOING",
                style = Label, color = Hall.muted, modifier = Modifier.weight(1f))
            if (v.running) Text("● Live" + if (v.progress.isNotBlank() && shown.size < 2) " · ${v.progress}" else "", color = Hall.good, style = MaterialTheme.typography.labelMedium)
        }
        if (v.from.isNotBlank()) Text(v.from + (s?.at?.ifBlank { null }?.let { " · ${ago(it)}" } ?: "") + if (v.running) " · updates by itself" else "",
            color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        if (t == null) {
            Text(if (finished) "This project was built before Roundtable kept a step list." else "The steps show here once a task has run.",
                color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
            return@Panel
        }
        if (shown.size > 1) {
            Spacer(Modifier.height(8.dp))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { for (task in shown) TaskRow(task, d) }
            for (task in shown) Fold("Steps: ${task.title.ifBlank { task.id }} (${task.steps.size})", startOpen = d.stepsOpen && d.moreOpen) { Steps(task.steps) }
        } else {
            Text("[${t.id}] ${t.title}", color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
            if (d.more) Text(listOfNotNull(t.role.ifBlank { null }, t.status.ifBlank { null }, if (t.cost > 0) "$%.4f".format(t.cost) else null)
                .joinToString(" · "), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            if (!d.stepsOpen && t.now.isNotBlank()) Text(t.now, color = Hall.muted, style = MaterialTheme.typography.bodySmall, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            if (d.timeLine) TimeLine(t, Modifier.padding(top = 6.dp))
            Spacer(Modifier.height(8.dp))
            if (d.stepsOpen) Steps(t.steps) else Fold("Its steps (${t.steps.size})") { Steps(t.steps) }
            if (d.more) More(t, d.moreOpen)
        }
        if (mode == Mode.HUB && v.from.isBlank() && !finished) Text("Only the latest task's last steps come through the hub; the PC app shows every step and change.",
            Modifier.padding(top = 8.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

private val STATE_WORDS = mapOf("running" to "Being built", "done" to "Done", "failed" to "Didn't work", "paused" to "Paused")

/** One running task as a short row: title, state, what it's doing now, the time bar and the gauge. */
@Composable
private fun TaskRow(t: SessionTask, d: LiveDetail) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).border(1.dp, Hall.line, RoundedCornerShape(10.dp)).padding(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t.title.ifBlank { t.id }, Modifier.weight(1f), color = Hall.text, fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(STATE_WORDS[t.status] ?: t.status, color = if (t.status == "failed") Hall.bad else Hall.good, style = MaterialTheme.typography.labelMedium)
        }
        Text(t.now.ifBlank { "Starting" }, color = Hall.muted, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (d.timeLine) TimeLine(t, Modifier.padding(top = 6.dp))
        if (d.more) More(t, d.moreOpen)
    }
}

/** The bar of where the time went and the context gauge, on one line; nothing when neither was recorded. */
@Composable
private fun TimeLine(t: SessionTask, modifier: Modifier = Modifier) {
    val time = t.time?.takeIf { it.parts.isNotEmpty() }
    val ctx = t.context
    if (time == null && ctx == null) return
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (time != null) {
            val total = time.total.coerceAtLeast(1)
            Row(Modifier.width(120.dp).height(8.dp).clip(RoundedCornerShape(4.dp)).background(Hall.line)
                .semantics { contentDescription = "Where the time went: " + time.parts.joinToString(", ") { "${it.label} ${duration(it.ms)}" } }) {
                for (p in time.parts) Box(Modifier.weight(maxOf(p.ms.toFloat(), total / 100f)).fillMaxHeight().background(PART_COLOURS[p.key] ?: Hall.muted))
            }
            Text(duration(time.total), color = Hall.text, style = MaterialTheme.typography.bodySmall)
        }
        if (ctx != null) {
            val share = ctx.share
            if (share != null) {
                Box(Modifier.width(44.dp).height(6.dp).clip(RoundedCornerShape(3.dp)).background(Hall.line)) {
                    Box(Modifier.fillMaxWidth(share.toFloat().coerceIn(0.03f, 1f)).fillMaxHeight()
                        .background(if (share >= 0.85) PART_COLOURS.getValue("you") else if (share >= 0.6) PART_COLOURS.getValue("model") else PART_COLOURS.getValue("tools")))
                }
                Text("${(share * 100).roundToInt()}% full", color = Hall.text, style = MaterialTheme.typography.bodySmall)
            } else Text("${tokens(ctx.used)} tokens", color = Hall.text, style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** The details, folded under one "More": the time in words, the context, the cache and the files changed. */
@Composable
private fun More(t: SessionTask, open: Boolean = false) {
    val time = t.time?.takeIf { it.parts.isNotEmpty() }
    if (time == null && t.context == null && t.changes.isEmpty()) return
    val n = t.changes.size
    Fold(if (n > 0) "More · changed $n file${if (n > 1) "s" else ""}" else "More", startOpen = open) {
        time?.parts?.forEach { p ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.width(10.dp).height(10.dp).clip(RoundedCornerShape(2.dp)).background(PART_COLOURS[p.key] ?: Hall.muted))
                Text("  ${p.label}: ${duration(p.ms)}", color = Hall.text, style = MaterialTheme.typography.bodySmall)
            }
        }
        t.context?.let { c ->
            Text("Context: ${"%,d".format(c.used)} tokens" + (c.window?.let { " of ${"%,d".format(it)}" } ?: " (how much this model holds isn't known)"),
                Modifier.padding(top = 4.dp), color = Hall.text, style = MaterialTheme.typography.bodySmall)
            c.cache_hit?.let { Text("From the cache: ${(it * 100).roundToInt()}% of what the models read (cheaper)", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        }
        if (n > 0) {
            Text("Changed $n file${if (n > 1) "s" else ""} · +${t.changes.sumOf { it.added }} −${t.changes.sumOf { it.removed }}",
                Modifier.padding(top = 4.dp), color = Hall.text, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold)
            for (c in t.changes) Text("${c.path}  ${if (c.new) "new · " else ""}+${c.added} −${c.removed}", color = Hall.text,
                fontFamily = FontFamily.Monospace, fontSize = 12.sp)
        }
    }
}

/** "under a second", "42s", "3m 10s", "1h 5m". */
internal fun duration(ms: Long): String {
    if (ms < 1000) return "under a second"
    val sec = (ms + 500) / 1000
    if (sec < 60) return "${sec}s"
    val m = sec / 60
    return if (m >= 60) "${m / 60}h ${m % 60}m" else if (sec % 60 == 0L) "${m}m" else "${m}m ${sec % 60}s"
}

private fun tokens(n: Long): String = if (n >= 10_000) "${(n + 500) / 1000}k" else "%,d".format(n)

// the same colours as the desktop's bar (watch.js)
private val PART_COLOURS = mapOf("first" to Color(0xFF9C8B74), "writing" to Color(0xFFE8A33D), "model" to Color(0xFFE8A33D),
    "tools" to Color(0xFF7FA35C), "you" to Color(0xFFD0643F), "other" to Color(0xFF6F5A46))

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
