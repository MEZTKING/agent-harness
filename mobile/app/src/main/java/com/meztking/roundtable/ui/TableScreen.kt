package com.meztking.roundtable.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.Parchment
import com.meztking.roundtable.ui.theme.ParchmentButtons
import com.meztking.roundtable.ui.theme.Serif
import kotlin.math.cos
import kotlin.math.sin

/** Above this many seats the table becomes a list (the round table fits about eight). */
const val TABLE_MAX = 8

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TableScreen(
    hall: Load<HallState>,
    mode: Mode?,
    whereLabel: String,
    busy: Set<String>,
    onRefresh: () -> Unit,
    onOpen: (SeatView) -> Unit,
    onAct: (NeedView, String) -> Unit,
    onOpenNeed: (NeedView) -> Unit,
    showNeeds: Boolean,
    onShowNeeds: (Boolean) -> Unit,
    onAnswer: (NeedView, AskReply) -> Unit = { _, _ -> },
) {
    val data = hall.data
    var selected by rememberSaveable { mutableStateOf<String?>(null) }
    val seats = data?.seats.orEmpty()
    val needs = data?.needs.orEmpty()
    Column(Modifier.fillMaxSize()) {
        Header(whereLabel, mode, hall.loading, onRefresh)
        PullToRefreshBox(isRefreshing = hall.loading && data != null, onRefresh = onRefresh, modifier = Modifier.weight(1f)) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (hall.error != null) item { ErrorLine(hall.error, onRefresh) }
                when {
                    data == null && hall.loading -> item { Loading("Gathering the table…") }
                    data == null -> {}
                    seats.isEmpty() -> item {
                        Panel(Modifier.fillMaxWidth()) {
                            Text("The table is empty", style = MaterialTheme.typography.titleMedium, color = Hall.goldBright)
                            Text("No projects in the hub yet. Add them under agents: in hub.yaml (or with roundtable connect on your PC), then pull down to refresh.",
                                style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    seats.size > TABLE_MAX -> {
                        item { CentreBanner(needs.size) { onShowNeeds(true) } }
                        items(seats, key = { it.id }) { SeatRow(it) { onOpen(it) } }
                    }
                    else -> {
                        item {
                            RoundTable(seats, needs.size, selected, Modifier.fillMaxWidth(),
                                onSeat = { s -> if (selected == s.id) onOpen(s) else selected = s.id },
                                onCentre = { onShowNeeds(true) })
                        }
                        item {
                            val s = seats.firstOrNull { it.id == selected }
                            if (s != null) SeatSummary(s) { onOpen(s) }
                            else Text("Tap a seat to see where it stands. Tap it again to open it.", color = Hall.muted,
                                style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                        }
                    }
                }
                item { Spacer(Modifier.height(56.dp)) }
            }
            if (data != null) NeedsPeek(needs, Modifier.align(Alignment.BottomCenter)) { onShowNeeds(true) }
        }
    }
    if (showNeeds) {
        ModalBottomSheet(onDismissRequest = { onShowNeeds(false) }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false),
            containerColor = Hall.panel, contentColor = Hall.text) {
            NeedsList(needs, mode, busy, onAct, onOpenNeed, Modifier.padding(horizontal = 16.dp), onClose = { onShowNeeds(false) }, onAnswer = onAnswer)
        }
    }
}

@Composable
private fun Header(where: String, mode: Mode?, loading: Boolean, onRefresh: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        TableMark(Modifier.size(34.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text("ROUNDTABLE", fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, letterSpacing = 2.8.sp, color = Hall.goldBright)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).background(if (mode == null) Hall.muted else Hall.good, CircleShape))
                Spacer(Modifier.width(6.dp))
                Text(where, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        IconButton(onClick = onRefresh, enabled = !loading) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
    }
}

@Composable
fun ErrorLine(text: String, onRetry: () -> Unit) {
    Row(Modifier.fillMaxWidth().background(Hall.bad.copy(alpha = 0.10f), RoundedCornerShape(6.dp))
        .border(1.dp, Hall.bad.copy(alpha = 0.5f), RoundedCornerShape(6.dp)).padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(text, Modifier.weight(1f).padding(vertical = 6.dp), color = Hall.bad, style = MaterialTheme.typography.bodyMedium)
        TextButton(onClick = onRetry) { Text("Try again") }
    }
}

@Composable
fun Loading(text: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        androidx.compose.material3.CircularProgressIndicator(color = Hall.gold)
        Spacer(Modifier.height(12.dp))
        Text(text, color = Hall.muted)
    }
}

/** The app's own mark: a ring with a candle flame (drawn, no image). */
@Composable
fun TableMark(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val r = size.minDimension / 2
        drawCircle(Hall.gold, r * 0.86f, style = Stroke(r * 0.1f))
        for (i in 0 until 6) {
            val a = Math.toRadians(i * 60.0 - 90)
            drawCircle(Hall.gold, r * 0.09f, Offset(center.x + cos(a).toFloat() * r * 0.86f, center.y + sin(a).toFloat() * r * 0.86f))
        }
        flame(center.copy(y = center.y - r * 0.05f), r * 0.5f)
    }
}

private fun DrawScope.flame(c: Offset, h: Float) {
    val w = h * 0.42f
    val p = Path().apply {
        moveTo(c.x, c.y - h / 2)
        cubicTo(c.x + w * 0.9f, c.y - h * 0.05f, c.x + w, c.y + h * 0.3f, c.x, c.y + h / 2)
        cubicTo(c.x - w, c.y + h * 0.3f, c.x - w * 0.9f, c.y - h * 0.05f, c.x, c.y - h / 2)
        close()
    }
    drawPath(p, Brush.verticalGradient(listOf(Color(0xFFFFF1C4), Hall.amber, Color(0xFFB0611F)), startY = c.y - h / 2, endY = c.y + h / 2))
}

/** The round table: seats around a central circle that counts what needs the owner. */
@Composable
fun RoundTable(
    seats: List<SeatView>, needCount: Int, selected: String?, modifier: Modifier = Modifier,
    onSeat: (SeatView) -> Unit, onCentre: () -> Unit,
) {
    BoxWithConstraints(modifier) {
        val w = maxWidth.coerceAtMost(460.dp)
        val h = w * 1.22f
        val ring = if (seats.size > 6) 50.dp else 58.dp
        val label = 100.dp
        val cx = maxWidth / 2
        val cy = h * 0.46f
        val rx = w * 0.37f
        val ry = h * 0.36f
        val centreR = w * 0.17f
        Box(Modifier.fillMaxWidth().height(h)) {
            // the table top and its glow
            Canvas(Modifier.fillMaxSize()) {
                val c = Offset(cx.toPx(), cy.toPx())
                val r = centreR.toPx()
                drawCircle(Brush.radialGradient(listOf(Hall.amber.copy(alpha = 0.22f), Color.Transparent), c, r * 2.2f), r * 2.2f, c)
                drawCircle(Brush.radialGradient(listOf(Color(0xFF4A3820), Color(0xFF2A2117), Color(0xFF1A1510)), c, r), r, c)
                drawCircle(Hall.gold, r, c, style = Stroke(2.dp.toPx()))
                drawCircle(Hall.goldDim, r * 0.86f, c, style = Stroke(1.dp.toPx()))
                // the seats' places, faintly
                drawOval(Hall.lineGold.copy(alpha = 0.5f), Offset(c.x - rx.toPx(), c.y - ry.toPx()), Size(rx.toPx() * 2, ry.toPx() * 2),
                    style = Stroke(1.dp.toPx(), pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(4f, 10f))))
                for (i in -1..1) flame(Offset(c.x + i * r * 0.22f, c.y - r * 0.42f), r * 0.2f)
            }
            Column(
                Modifier.offset(cx - centreR, cy - centreR).size(centreR * 2).clip(CircleShape).clickable(onClick = onCentre)
                    .semantics { contentDescription = "$needCount things need you. Open the list." },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
            ) {
                Spacer(Modifier.height(centreR * 0.3f))
                Text("$needCount", fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = (centreR.value * 0.55f).sp, color = Hall.goldBright)
                Text("NEED YOU", fontFamily = Serif, fontSize = 10.sp, letterSpacing = 2.4.sp, color = Hall.gold)
            }
            seats.forEachIndexed { i, s ->
                val a = Math.toRadians(-90.0 + 360.0 * i / seats.size)
                val x = cx + rx * cos(a).toFloat()
                val y = cy + ry * sin(a).toFloat()
                Column(
                    Modifier.offset(x - label / 2, y - ring / 2).width(label)
                        .clickable(remember { MutableInteractionSource() }, indication = null) { onSeat(s) }
                        .semantics { contentDescription = "${s.id}, ${s.statusText}" + if (s.badge > 0) ", ${s.badge} waiting" else "" },
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    SeatRing(s, s.id == selected, ring)
                    Spacer(Modifier.height(3.dp))
                    Text(s.id, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = Hall.text,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
                    Text(s.statusText, fontSize = 11.sp, color = Hall.status(s.status).let { if (s.status == "idle") Hall.muted else it },
                        maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
                }
            }
        }
    }
}

/** A seat: a ring (filled as tasks finish, in PC mode) with the initials and a badge. */
@Composable
fun SeatRing(s: SeatView, selected: Boolean, size: Dp) {
    val color = Hall.status(s.status)
    Box(Modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = 3.5.dp.toPx()
            val r = this.size.minDimension / 2 - stroke
            if (selected) drawCircle(Brush.radialGradient(listOf(Hall.amber.copy(alpha = 0.45f), Color.Transparent), center, r * 1.5f), r * 1.5f)
            drawCircle(Brush.radialGradient(listOf(Color(0xFF332A1F), Hall.panel), center, r), r)
            drawCircle(Hall.line, r, style = Stroke(stroke))
            val p = s.progress
            val sweep = if (p != null && p.total > 0) 360f * p.done / p.total else 360f
            drawArc(color, -90f, sweep, false, Offset(center.x - r, center.y - r), Size(r * 2, r * 2), style = Stroke(stroke, cap = StrokeCap.Round))
            if (selected) drawCircle(Hall.goldBright, r + stroke * 1.2f, style = Stroke(1.dp.toPx()))
        }
        Text(s.initials, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.32f).sp, color = Hall.goldBright)
        if (s.badge > 0) {
            Box(Modifier.align(Alignment.TopEnd).offset(4.dp, (-2).dp).size(20.dp).background(Hall.ember, CircleShape)
                .border(1.5.dp, Hall.bg, CircleShape), contentAlignment = Alignment.Center) {
                Text(if (s.badge > 9) "9+" else "${s.badge}", fontSize = 10.sp, color = Color.White, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** The card under the table for the seat that is tapped. */
@Composable
fun SeatSummary(s: SeatView, onOpen: () -> Unit) {
    Panel(Modifier.fillMaxWidth(), highlight = true) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(9.dp).background(Hall.status(s.status), RoundedCornerShape(2.dp)))
            Spacer(Modifier.width(8.dp))
            Text(s.id, style = MaterialTheme.typography.titleMedium, color = Hall.goldBright, modifier = Modifier.weight(1f, fill = false),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.width(8.dp))
            Chip(s.status, Hall.status(s.status))
            Spacer(Modifier.weight(1f))
            if (s.lastActivity.isNotBlank()) Text(ago(s.lastActivity), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        if (s.description.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(s.description, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        if (s.leftOff.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text("WHERE WE LEFT OFF", style = Label.copy(fontSize = 10.sp))
            Text(s.leftOff, style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis)
            s.nextSteps.take(2).forEach { Text("· $it", style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) }
        }
        s.progress?.takeIf { it.total > 0 }?.let { p ->
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth().height(4.dp).background(Hall.line, RoundedCornerShape(2.dp))) {
                Box(Modifier.fillMaxWidth(p.done.toFloat() / p.total).height(4.dp).background(Hall.amber, RoundedCornerShape(2.dp)))
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            val bits = buildList {
                s.progress?.takeIf { it.total > 0 }?.let { add("${it.done} of ${it.total} tasks") }
                add(if (s.openTodos == 1) "1 to-do" else "${s.openTodos} to-dos")
                if (s.high > 0) add("${s.high} high")
                if (s.unread > 0) add("${s.unread} unread")
                if (s.hasPlan) add("plan")
            }
            Text(bits.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = Hall.muted, modifier = Modifier.weight(1f))
            TextButton(onClick = onOpen) {
                Text("Open seat")
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
            }
        }
    }
}

/** B's roll call: one row per project, for when there are too many seats for the table. */
@Composable
fun SeatRow(s: SeatView, onOpen: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Hall.panel).border(1.dp, Hall.line, RoundedCornerShape(8.dp))
        .clickable(onClick = onOpen).padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
        SeatRing(s, false, 46.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(s.id, style = MaterialTheme.typography.titleSmall, color = Hall.goldBright, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(s.statusText, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (s.high > 0) Chip("${s.high} high", Hall.bad)
                if (s.unread > 0) Chip("${s.unread} unread", Hall.amber)
                if (s.openTodos > 0) Chip("${s.openTodos} to-do", Hall.goldDim)
            }
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Hall.goldDim)
    }
}

@Composable
private fun CentreBanner(n: Int, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Brush.horizontalGradient(listOf(Color(0xFF33290F), Color(0xFF281F0C))))
        .border(1.dp, Hall.goldDim, RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("$n", fontFamily = Serif, fontSize = 30.sp, color = Hall.goldBright, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.width(12.dp))
        Text("NEED YOU", style = Label, modifier = Modifier.weight(1f))
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Hall.gold)
    }
}

/** The bar at the bottom of the table that opens the Needs you sheet. */
@Composable
private fun NeedsPeek(needs: List<NeedView>, modifier: Modifier, onOpen: () -> Unit) {
    Row(
        modifier.fillMaxWidth().padding(horizontal = 12.dp).clip(RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
            .background(Brush.verticalGradient(listOf(Hall.panelHi, Hall.panel)))
            .border(1.dp, Hall.lineGold, RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))
            .clickable(onClick = onOpen).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("NEEDS YOU", style = Label)
        Spacer(Modifier.width(8.dp))
        CountBadge(needs.size)
        Spacer(Modifier.width(12.dp))
        Text(if (needs.isEmpty()) "Nothing waits for you" else needs.joinToString(" · ") { it.title }, style = MaterialTheme.typography.bodySmall,
            color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
    }
}

@Composable
fun CountBadge(n: Int) {
    Box(Modifier.size(24.dp).background(Hall.accentSoft, CircleShape).border(1.dp, Hall.gold, CircleShape), contentAlignment = Alignment.Center) {
        Text("$n", fontSize = 12.sp, color = Hall.goldBright, fontFamily = Serif, fontWeight = FontWeight.SemiBold)
    }
}

/** The Needs you list: one parchment card per thing, each with its one-tap answers. */
@Composable
fun NeedsList(
    needs: List<NeedView>, mode: Mode?, busy: Set<String>, onAct: (NeedView, String) -> Unit, onOpen: (NeedView) -> Unit,
    modifier: Modifier = Modifier, onClose: (() -> Unit)? = null, onAnswer: (NeedView, AskReply) -> Unit = { _, _ -> },
) {
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("NEEDS YOU", style = Label)
                Spacer(Modifier.width(8.dp))
                CountBadge(needs.size)
                Spacer(Modifier.weight(1f))
                if (onClose != null) TextButton(onClick = onClose) { Text("Handle later") }
            }
        }
        if (needs.isEmpty()) item {
            Text("Nothing waits for you. The table will tell you when something does.", color = Hall.muted,
                modifier = Modifier.padding(vertical = 24.dp))
        }
        items(needs, key = { it.key }) { n ->
            val ask = n.ask
            if (ask != null) Column {
                AskCard(ask.copy(project = n.project), { onAnswer(n, it) }, busy = n.key in busy)
                if (n.asks > 1) TextButton({ onOpen(n) }) { Text("${n.asks - 1} more on the plan") }
            } else NeedCard(n, mode, n.key in busy, onAct, onOpen)
        }
    }
}

@Composable
fun NeedCard(n: NeedView, mode: Mode?, busy: Boolean, onAct: (NeedView, String) -> Unit, onOpen: (NeedView) -> Unit) {
    val seal = when (n.kind) { "message" -> Hall.amber; "todo" -> Hall.good; else -> Hall.ember }
    Parchment(Modifier.fillMaxWidth(), seal = seal) {
        Text(n.title, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink, maxLines = 3, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(2.dp))
        val sub = when (n.kind) {
            "message" -> "from ${n.project}" + (if (n.at.isNotBlank()) " · ${ago(n.at)}" else "") + " · \"${n.text}\""
            else -> n.text.ifBlank { n.project }
        }
        Text(sub, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft, maxLines = 3, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            val acts = actionsFor(n, mode)
            acts.forEachIndexed { i, (action, label) ->
                val click = { if (action == "open" || action == "plan" || action == "reply") onOpen(n) else onAct(n, action) }
                if (i == 0) Button(onClick = click, enabled = !busy, colors = ParchmentButtons.main(), contentPadding = PaddingValues(horizontal = 14.dp)) { Text(label) }
                else OutlinedButton(onClick = click, enabled = !busy, colors = ParchmentButtons.other(), border = ParchmentButtons.otherBorder,
                    contentPadding = PaddingValues(horizontal = 14.dp)) { Text(label) }
            }
        }
    }
}

private fun actionsFor(n: NeedView, mode: Mode?): List<Pair<String, String>> = when (n.kind) {
    "message" -> if (n.message != null) listOf("reply" to "Read and reply", "read" to "Mark as read") else listOf("open" to "Read")
    "todo" -> if (mode == Mode.PC && n.id != null) listOf("done" to "Mark done", "open" to "Open project") else listOf("open" to "Open project")
    else -> n.actions.mapNotNull {
        when (it) {
            "approve" -> "plan" to "Read and approve the plan"
            "retry" -> "retry" to "Retry"
            "skip" -> "skip" to "Skip"
            "budget" -> "budget" to "Raise the budget"
            "resume" -> "resume" to "Resume"
            "done" -> "done" to "Mark done"
            "read" -> "open" to "Read"
            else -> null
        }
    }.ifEmpty { listOf("open" to "Open project") }
}
