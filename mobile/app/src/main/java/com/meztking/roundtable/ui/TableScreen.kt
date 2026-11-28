package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PushPin
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
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.material.icons.filled.DragIndicator
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
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.layout.ContentScale
import com.meztking.roundtable.R
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.NeedsOrder
import com.meztking.roundtable.data.Letters
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

/**
 * Pinned and put-away projects on this phone (Comfort): pinned ones sit first, put-away ones wait behind
 * "Put away" (hidden, never deleted). [pin] and [putAway] change them.
 */
class TablePins(
    val pinned: Set<String> = emptySet(),
    val away: Set<String> = emptySet(),
    val pin: (String, Boolean) -> Unit = { _, _ -> },
    val putAway: (String, Boolean) -> Unit = { _, _ -> },
    /** The owner's own order (DS-19), and where a press, hold and drag saves it; null: no dragging. */
    val order: List<String> = emptyList(),
    val reorder: ((List<String>) -> Unit)? = null,
)

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
    onAutopilot: (on: Boolean, until: String, cap: Double?) -> Unit = { _, _, _ -> },
    onMarkAllRead: (List<NeedView>) -> Unit = {},
    onNotes: (() -> Unit)? = null,
    onSearch: (() -> Unit)? = null,
    onNewIdea: (() -> Unit)? = null,
    /** Everything finished, and what Roundtable can make (GalleryScreen). */
    onGallery: (() -> Unit)? = null,
    /** Pinned and put-away projects; null shows every project in the hub's order, with no menu. */
    pins: TablePins? = null,
    /** What waits for the owner is drawn beside the Table (two panes), so the peek at the bottom isn't needed. */
    needsBeside: Boolean = false,
) {
    val data = hall.data
    var showAutopilot by rememberSaveable { mutableStateOf(false) }
    var selected by rememberSaveable { mutableStateOf<String?>(null) }
    val all = data?.seats.orEmpty()
    val (seats, awaySeats) = remember(all, pins?.pinned, pins?.away, pins?.order) {
        com.meztking.roundtable.data.Comfort.arrange(all, { it.id }, pins?.pinned.orEmpty(), pins?.away.orEmpty(), pins?.order.orEmpty())
    }
    // Order by hand (DS-19): the list as it stands mid-drag, saved when the finger lifts.
    var arranging by rememberSaveable { mutableStateOf(false) }
    var live by remember(seats) { mutableStateOf(seats) }
    var dragged by remember { mutableStateOf<String?>(null) }
    var dragY by remember { mutableStateOf(0f) }
    val stepPx = with(androidx.compose.ui.platform.LocalDensity.current) { 78.dp.toPx() }
    val reorder = pins?.reorder
    fun handleFor(s: SeatView): Modifier = if (reorder == null) Modifier else Modifier.pointerInput(s.id) {
        detectDragGesturesAfterLongPress(
            onDragStart = { dragged = s.id; dragY = 0f },
            onDragEnd = { dragged = null; reorder(live.map { it.id } + awaySeats.map { it.id }) },
            onDragCancel = { dragged = null; live = seats },
            onDrag = { change, amount ->
                change.consume()
                dragY += amount.y
                val from = live.indexOfFirst { it.id == s.id }
                if (from >= 0 && kotlin.math.abs(dragY) >= stepPx) {
                    val to = from + if (dragY > 0) 1 else -1
                    live = com.meztking.roundtable.data.Comfort.moved(live, from, to)
                    dragY -= if (dragY > 0) stepPx else -stepPx
                }
            },
        )
    }
    val needs = data?.needs.orEmpty()
    // what waits on each seat, in words ("2 questions, 1 to-do"), for its badge and its card
    val waits = remember(needs) { NeedsOrder.organise(needs).associate { it.project to it.summary } }
    Column(Modifier.fillMaxSize()) {
        Header(whereLabel, mode, hall.loading, onRefresh, onNotes, onSearch, onNewIdea, onGallery)
        if (mode != null) AutopilotToggle(data?.autopilot, Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) { showAutopilot = true }
        UpdateBanner(Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        PullToRefreshBox(isRefreshing = hall.loading && data != null, onRefresh = onRefresh, modifier = Modifier.weight(1f)) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (hall.error != null) item { ErrorLine(hall.error, onRefresh) }
                when {
                    data == null && hall.loading -> item { Loading("Waking up…") }
                    data == null -> {}
                    all.isEmpty() -> item {
                        Panel(Modifier.fillMaxWidth()) {
                            Text("No projects yet", style = MaterialTheme.typography.titleMedium, color = Hall.goldBright)
                            Text("No projects in the hub yet. Add them under agents: in hub.yaml (or with darkness connect on your PC), then pull down to refresh.",
                                style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    seats.size > TABLE_MAX || arranging -> {
                        if (arranging && seats.size <= TABLE_MAX) item {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("Press, hold and drag a project to move it.", Modifier.weight(1f), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                                TextButton(onClick = { arranging = false }) { Text("Done") }
                            }
                        }
                        if (needs.isNotEmpty() && !arranging) item { CentreBanner(needs.size) { onShowNeeds(true) } }
                        items(live, key = { it.id }) {
                            SeatRow(it, waits[it.id], pins, lifted = dragged == it.id, handle = if (reorder != null) handleFor(it) else null) { onOpen(it) }
                        }
                    }
                    else -> {
                        item {
                            RoundTable(seats, needs.size, selected, Modifier.fillMaxWidth(), waits = waits,
                                onSeat = { s -> if (selected == s.id) onOpen(s) else selected = s.id },
                                onCentre = { onShowNeeds(true) })
                        }
                        item {
                            val s = seats.firstOrNull { it.id == selected }
                            if (s != null) SeatSummary(s, waits[s.id], pins) { onOpen(s) }
                            else Text("Tap a light to see where a project stands. Tap it again to open it.", color = Hall.muted,
                                style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                        }
                        if (reorder != null && seats.size > 1) item {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                                TextButton(onClick = { arranging = true }) { Text("Arrange the table", color = Hall.gold) }
                            }
                        }
                    }
                }
                if (awaySeats.isNotEmpty() && pins != null) item(key = "put-away") { PutAway(awaySeats, pins, onOpen) }
                item { Spacer(Modifier.height(56.dp)) }
            }
            if (data != null && !needsBeside) NeedsPeek(needs, Modifier.align(Alignment.BottomCenter)) { onShowNeeds(true) }
        }
    }
    if (showNeeds) {
        ModalBottomSheet(onDismissRequest = { onShowNeeds(false) }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false),
            containerColor = Hall.panel, contentColor = Hall.text) {
            NeedsList(needs, mode, busy, onAct, onOpenNeed, Modifier.padding(horizontal = 16.dp), onClose = { onShowNeeds(false) }, onAnswer = onAnswer,
                onMarkAllRead = onMarkAllRead)
        }
    }
    if (showAutopilot) {
        ModalBottomSheet(onDismissRequest = { showAutopilot = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = Hall.panel, contentColor = Hall.text) {
            AutopilotSheet(data?.autopilot, mode, Modifier.padding(horizontal = 16.dp)) { on, until, cap ->
                onAutopilot(on, until, cap); showAutopilot = false
            }
        }
    }
}

@Composable
private fun Header(where: String, mode: Mode?, loading: Boolean, onRefresh: () -> Unit, onNotes: (() -> Unit)? = null,
                   onSearch: (() -> Unit)? = null, onNewIdea: (() -> Unit)? = null, onGallery: (() -> Unit)? = null) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            TableMark(Modifier.size(34.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(Brand.NAME, fontFamily = Serif, fontWeight = FontWeight.Bold, fontSize = 21.sp, color = Hall.text, letterSpacing = (-0.4).sp,
                    maxLines = 1, softWrap = false, overflow = TextOverflow.Ellipsis)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(7.dp).background(if (mode == null) Hall.muted else Hall.good, CircleShape))
                    Spacer(Modifier.width(6.dp))
                    Text(where, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (onSearch != null) IconButton(onClick = onSearch) { Icon(Icons.Filled.Search, "Search everything", tint = Hall.gold) }
            IconButton(onClick = onRefresh, enabled = !loading) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
        }
        // The word buttons get a row of their own, so the title is never squeezed (owner's screenshot, 27 Nov).
        if (onNewIdea != null || onNotes != null || onGallery != null) Row(Modifier.fillMaxWidth().padding(start = 36.dp), verticalAlignment = Alignment.CenterVertically) {
            if (onNewIdea != null) TextButton(onClick = onNewIdea) { Text("+ New idea", color = Hall.gold, maxLines = 1) }
            if (onNotes != null) TextButton(onClick = onNotes) { Text("My notes", color = Hall.gold, maxLines = 1) }
            if (onGallery != null) TextButton(onClick = onGallery) { Text("Gallery", color = Hall.gold, maxLines = 1) }
        }
    }
}

/**
 * What a named failure's button does, for screens that can do more than retry (pair again, open Settings…).
 * Returns false when it can't, and the button retries instead. MainActivity provides it.
 */
val LocalFailureActions = androidx.compose.runtime.staticCompositionLocalOf<(com.meztking.roundtable.data.FailureAction) -> Boolean> { { false } }

@Composable
fun ErrorLine(text: String, onRetry: () -> Unit) {
    val failure = com.meztking.roundtable.data.Failure.ofSentence(text)
    val act = LocalFailureActions.current
    Row(Modifier.fillMaxWidth().background(Hall.bad.copy(alpha = 0.10f), RoundedCornerShape(6.dp))
        .border(1.dp, Hall.bad.copy(alpha = 0.5f), RoundedCornerShape(6.dp)).padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(text, Modifier.weight(1f).padding(vertical = 6.dp), color = Hall.bad, style = MaterialTheme.typography.bodyMedium)
        TextButton(onClick = { if (failure == null || failure.action == com.meztking.roundtable.data.FailureAction.TRY_AGAIN || !act(failure.action)) onRetry() }) {
            Text(failure?.button ?: "Try again")
        }
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

/**
 * The app's own mark: the launcher icon's art (made by an image model) on the Ring's dark disc, with a thin
 * corona drawn around it.
 */
@Composable
fun TableMark(modifier: Modifier = Modifier) {
    Box(modifier.clip(CircleShape).background(Hall.disc).border(1.dp, Hall.gold.copy(alpha = 0.7f), CircleShape), contentAlignment = Alignment.Center) {
        Image(painterResource(R.mipmap.ic_launcher_foreground), null, Modifier.fillMaxSize().graphicsLayer { scaleX = 1.45f; scaleY = 1.45f })
    }
}

/** The tall Eclipse backdrop (res/drawable-nodpi/eclipse_phone), once the art is in the app; 0 before. */
@Composable
fun eclipseBackdrop(): Int {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    return remember(ctx) {
        // looked up by name so the app builds before the art arrives; the name is a constant, so the resource
        // shrinker keeps it
        @Suppress("DiscouragedApi") ctx.resources.getIdentifier(ECLIPSE_ART, "drawable", ctx.packageName)
    }
}

private const val ECLIPSE_ART = "eclipse_phone"

/**
 * The Ring: a black disc with a thin corona of light, each project a light on it. The one that needs the owner
 * flares ember orange and sits at the top; the disc's middle counts what needs the owner (tap it for the list).
 * The corona breathes slowly; still when the phone asks for less motion.
 */
@Composable
fun RoundTable(
    seats: List<SeatView>, needCount: Int, selected: String?, modifier: Modifier = Modifier,
    onSeat: (SeatView) -> Unit, onCentre: () -> Unit, waits: Map<String, String> = emptyMap(),
) {
    // what needs the owner moves to the top of the ring, in the Table's order otherwise
    val ring = remember(seats) { seats.filter { it.status == "waiting" } + seats.filterNot { it.status == "waiting" } }
    val breath by com.meztking.roundtable.ui.theme.ringBreath()
    val corona = Hall.gold
    val flare = Hall.flare
    val art = eclipseBackdrop()
    BoxWithConstraints(modifier) {
        val w = maxWidth.coerceAtMost(440.dp)
        val h = w * 0.98f
        val cx = maxWidth / 2
        val cy = h / 2
        val r = w * 0.33f
        val light = if (ring.size > 6) 40.dp else 46.dp
        val label = (w * 0.32f).coerceIn(100.dp, 132.dp)
        val full = maxWidth
        Box(Modifier.fillMaxWidth().height(h)) {
            if (art != 0) Image(painterResource(art), null, Modifier.matchParentSize(), contentScale = ContentScale.Crop,
                alignment = Alignment.TopCenter, alpha = 0.6f)  // the art has a faint ring of its own: kept soft so only the drawn rim reads as the ring
            Canvas(Modifier.fillMaxSize()) {
                val c = Offset(cx.toPx(), cy.toPx())
                val rp = r.toPx()
                // the corona: a soft halo outside the rim, then the bright rim itself
                val glow = 0.30f + 0.20f * breath
                drawCircle(Brush.radialGradient(0.80f to Color.Transparent, 0.90f to corona.copy(alpha = glow), 1f to Color.Transparent,
                    center = c, radius = rp * 1.18f), rp * 1.18f, c)
                drawCircle(Hall.disc, rp, c)
                drawCircle(Brush.radialGradient(0.7f to Color.Transparent, 1f to corona.copy(alpha = 0.18f + 0.10f * breath), center = c, radius = rp),
                    rp, c)
                drawCircle(corona.copy(alpha = 0.85f), rp, c, style = Stroke(2.dp.toPx()))
                drawCircle(Color.White.copy(alpha = 0.35f + 0.25f * breath), rp, c, style = Stroke(0.8.dp.toPx()))
                // faint points round the inside
                val n = 48
                for (i in 0 until n) {
                    val a = Math.toRadians(360.0 * i / n)
                    drawCircle(Hall.onWood.copy(alpha = 0.16f), 1.2.dp.toPx(),
                        Offset(c.x + (rp - 12.dp.toPx()) * cos(a).toFloat(), c.y + (rp - 12.dp.toPx()) * sin(a).toFloat()))
                }
                // a wide, faint orbit beyond the ring
                drawCircle(Hall.line, rp * 1.42f, c, style = Stroke(1.dp.toPx()))
                if (ring.firstOrNull()?.status == "waiting") {
                    val top = Offset(c.x, c.y - rp)
                    drawCircle(Brush.radialGradient(listOf(flare.copy(alpha = 0.35f + 0.25f * breath), Color.Transparent), top, rp * 0.55f), rp * 0.55f, top)
                }
            }
            Column(
                Modifier.offset(cx - r * 0.62f, cy - r * 0.62f).size(r * 1.24f).clip(CircleShape).clickable(onClick = onCentre)
                    .semantics { contentDescription = if (needCount == 0) "Nothing needs you. Open the list." else "$needCount things need you. Open the list." },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
            ) {
                if (needCount > 0) {
                    Text("$needCount", fontFamily = Serif, fontWeight = FontWeight.Bold, fontSize = (r.value * 0.42f).sp, color = Hall.onWood,
                        letterSpacing = (-1).sp)
                    Text("need you", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = flareOnDisc(flare))
                } else {
                    Text("All quiet", fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.onWood)
                    Text("nothing needs you", fontSize = 12.sp, color = Hall.onWood.copy(alpha = 0.75f))
                }
            }
            ring.forEachIndexed { i, s ->
                val a = Math.toRadians(-90.0 + 360.0 * i / ring.size)
                val x = cx + r * cos(a).toFloat()
                val y = cy + r * sin(a).toFloat()
                // the name sits under the light, kept inside the screen
                val lx = (x - label / 2).coerceIn(0.dp, full - label)
                Box(Modifier.offset(x - light / 2, y - light / 2)
                    .clickable(remember { MutableInteractionSource() }, indication = null) { onSeat(s) }
                    .semantics { contentDescription = "${s.id}, ${s.statusText}" + (if (s.lives.isNotBlank()) ", ${s.lives}" else "") + (waits[s.id]?.let { ", waiting: $it" } ?: if (s.badge > 0) ", ${s.badge} waiting" else "") + if (s.autopilot) ", on autopilot" else "" }) {
                    SeatRing(s, s.id == selected, light, waits[s.id])
                    if (s.autopilot) AutopilotDot(Modifier.align(Alignment.TopStart))
                }
                Column(Modifier.offset(lx, y + light / 2 + 2.dp).width(label).clickable(remember { MutableInteractionSource() }, indication = null) { onSeat(s) },
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(s.id, Modifier.background(Hall.panel.copy(alpha = 0.92f), RoundedCornerShape(6.dp)).padding(horizontal = 6.dp, vertical = 1.dp),
                        fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, color = Hall.text,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
                }
            }
        }
    }
}

/** The flare as text on the dark disc: Ash's darker flare would not read there, so the disc keeps Eclipse's. */
private fun flareOnDisc(flare: Color): Color = if (flare.luminance() < 0.3f) com.meztking.roundtable.ui.theme.Eclipse.flare else flare

/**
 * A project's light: a small dark disc whose rim fills as tasks finish (in PC mode), with the initials and a badge.
 * The one that needs the owner flares ember orange (only that one); a word or a badge always says why too.
 */
@Composable
fun SeatRing(s: SeatView, selected: Boolean, size: Dp, badgeTip: String? = null) {
    val color = Hall.status(s.status)
    val waiting = s.status == "waiting"
    val lit = if (waiting) com.meztking.roundtable.ui.theme.flare().value else 0f
    val flare = Hall.flare
    val disc = Hall.disc
    val track = Hall.lineStrong.copy(alpha = 0.6f)
    Box(Modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = 3.dp.toPx()
            val r = this.size.minDimension / 2 - stroke
            if (waiting) drawCircle(Brush.radialGradient(listOf(flare.copy(alpha = 0.55f * lit), Color.Transparent), center, r * 1.9f), r * 1.9f)
            drawCircle(disc, r)
            drawCircle(track, r, style = Stroke(stroke))
            val p = s.progress
            val sweep = if (p != null && p.total > 0) 360f * p.done / p.total else 360f
            drawArc(color, -90f, sweep, false, Offset(center.x - r, center.y - r), Size(r * 2, r * 2), style = Stroke(stroke, cap = StrokeCap.Round))
            if (selected) drawCircle(Hall.onWood, r + stroke * 1.3f, style = Stroke(1.5.dp.toPx()))
        }
        Text(s.initials, fontFamily = Serif, fontWeight = FontWeight.Bold, fontSize = (size.value * 0.32f).sp, color = Hall.onWood)
        val count = badgeTip?.let { Regex("\\d+").findAll(it).sumOf { m -> m.value.toInt() } } ?: s.badge
        if (count > 0) {
            // long-press the badge: what waits, in words ("2 questions, 1 to-do")
            TooltipBox(TooltipDefaults.rememberPlainTooltipPositionProvider(), tooltip = { PlainTooltip { Text(badgeTip ?: "$count waiting") } },
                state = rememberTooltipState(), modifier = Modifier.align(Alignment.TopEnd)) {
                Box(Modifier.offset(16.dp, (-12).dp).size(22.dp).background(flareOnDisc(flare), CircleShape)
                    .border(1.5.dp, disc, CircleShape), contentAlignment = Alignment.Center) {
                    Text(if (count > 9) "9+" else "$count", fontSize = 10.sp, lineHeight = 10.sp, color = Color(0xFF0A0A0F), fontWeight = FontWeight.Bold,
                        maxLines = 1, softWrap = false)
                }
            }
        }
    }
}

/** The card under the table for the seat that is tapped. */
@Composable
fun SeatSummary(s: SeatView, waits: String? = null, pins: TablePins? = null, onOpen: () -> Unit) {
    Panel(Modifier.fillMaxWidth(), highlight = s.status == "waiting") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(9.dp).background(Hall.status(s.status), CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(s.id, style = MaterialTheme.typography.titleMedium, color = Hall.text, modifier = Modifier.weight(1f, fill = false),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.width(8.dp))
            Chip(s.status, Hall.status(s.status))
            if (s.autopilot) { Spacer(Modifier.width(6.dp)); AutopilotMark() }
            if (pins != null && s.id in pins.pinned) { Spacer(Modifier.width(6.dp)); PinMark() }
            Spacer(Modifier.weight(1f))
            if (s.lastActivity.isNotBlank()) Text(ago(s.lastActivity), style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            if (pins != null) SeatMenu(s, pins)
        }
        // short first: one line under the name (what waits for the owner, else where it stands); the rest is a tap away
        val line = when {
            !waits.isNullOrBlank() -> "Waits for you: $waits"
            s.building.isNotBlank() -> whereWords(s)
            s.leftOff.isNotBlank() -> s.leftOff
            else -> s.description
        }
        if (line.isNotBlank()) Text(line, Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis,
            color = if (!waits.isNullOrBlank()) Hall.candle else Hall.muted, fontWeight = if (!waits.isNullOrBlank()) FontWeight.SemiBold else null)
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(s.progress?.takeIf { it.total > 0 }?.let { "${it.done} of ${it.total} tasks" }.orEmpty(), style = MaterialTheme.typography.bodySmall,
                color = Hall.muted, modifier = Modifier.weight(1f))
            TextButton(onClick = onOpen) {
                Text("Open project")
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
            }
        }
    }
}

/** B's roll call: one row per project, for when there are too many seats for the table. */
@Composable
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
fun SeatRow(
    s: SeatView, waits: String? = null, pins: TablePins? = null, lifted: Boolean = false,
    /** The hold-and-drag handle's gesture (DS-19); null: no handle. */
    handle: Modifier? = null,
    onOpen: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    val buzz = com.meztking.roundtable.ui.theme.rememberHaptics()
    Box {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(if (lifted) Hall.line else Hall.panel)
        .border(if (s.status == "waiting" || lifted) 2.dp else 1.dp, if (lifted) Hall.gold else if (s.status == "waiting") Hall.candle else Hall.line, RoundedCornerShape(10.dp))
        .combinedClickable(onClick = onOpen, onLongClickLabel = if (pins != null) "Pin or put away" else null,
            onLongClick = if (pins != null) ({ buzz(); menu = true }) else null)
        .padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
        if (handle != null) Icon(Icons.Filled.DragIndicator, "Press, hold and drag to move ${s.id}", handle.size(28.dp), tint = Hall.muted)
        SeatRing(s, false, 46.dp, waits)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(s.id, Modifier.weight(1f, fill = false), style = MaterialTheme.typography.titleSmall, color = Hall.text, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
                if (pins != null && s.id in pins.pinned) { Spacer(Modifier.width(6.dp)); PinMark() }
            }
            if (!waits.isNullOrBlank()) Text("Waits for you: $waits", style = MaterialTheme.typography.bodySmall, color = Hall.candle, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            Text(listOf(s.statusText, if (s.building.isBlank()) s.lives else "").filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (s.high > 0) Chip("${s.high} high", Hall.bad)
                if (s.unread > 0) Chip("${s.unread} unread", Hall.amber)
                if (s.openTodos > 0) Chip("${s.openTodos} to-do", Hall.goldDim)
                if (s.autopilot) AutopilotMark()
            }
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Hall.goldDim)
    }
    if (pins != null) SeatMenuItems(s, pins, menu) { menu = false }
    }
}

/** A small pin by a pinned project's name. */
@Composable
fun PinMark() {
    Icon(Icons.Filled.PushPin, "Pinned to the top", Modifier.size(14.dp), tint = Hall.gold)
}

/** The ⋮ on a seat's card: pin it to the top, or put it away. */
@Composable
private fun SeatMenu(s: SeatView, pins: TablePins) {
    var menu by remember { mutableStateOf(false) }
    Box {
        TipIcon("Pin or put away", { menu = true }) { Icon(Icons.Filled.MoreVert, "Pin or put away", tint = Hall.gold) }
        SeatMenuItems(s, pins, menu) { menu = false }
    }
}

@Composable
private fun SeatMenuItems(s: SeatView, pins: TablePins, open: Boolean, close: () -> Unit) {
    val buzz = com.meztking.roundtable.ui.theme.rememberHaptics()
    androidx.compose.material3.DropdownMenu(open, close, containerColor = Hall.panel) {
        val pinned = s.id in pins.pinned
        androidx.compose.material3.DropdownMenuItem(text = { Text(if (pinned) "Unpin" else "Pin to the top") },
            onClick = { pins.pin(s.id, !pinned); buzz(); close() })
        androidx.compose.material3.DropdownMenuItem(
            text = {
                Column {
                    Text("Put away")
                    Text("Hidden from the Table on this phone. Nothing is deleted.", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
            },
            onClick = { pins.putAway(s.id, true); buzz(); close() })
    }
}

/** Put-away projects, folded at the bottom: each can be opened or brought back. */
@Composable
private fun PutAway(seats: List<SeatView>, pins: TablePins, onOpen: (SeatView) -> Unit) {
    Fold("Put away (${seats.size})") {
        Text("Hidden from the Table on this phone; nothing was deleted.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        seats.forEach { s ->
            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(s.id, Modifier.weight(1f).clickable { onOpen(s) }.padding(vertical = 8.dp), color = Hall.text,
                    style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                TextButton(onClick = { pins.putAway(s.id, false) }) { Text("Bring back") }
            }
        }
    }
}

@Composable
private fun CentreBanner(n: Int, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Hall.accentSoft)
        .border(1.dp, Hall.line, RoundedCornerShape(10.dp)).clickable(onClick = onClick).padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("$n", fontFamily = Serif, fontSize = 30.sp, color = Hall.text, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(12.dp))
        Text("NEED YOU", style = Label, modifier = Modifier.weight(1f))
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Hall.gold)
    }
}

/** The bar at the bottom of the table that opens the Needs you sheet. */
@Composable
private fun NeedsPeek(needs: List<NeedView>, modifier: Modifier, onOpen: () -> Unit) {
    Row(
        modifier.fillMaxWidth().padding(horizontal = 12.dp).clip(RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp))
            .background(Hall.panel)
            .border(1.dp, Hall.line, RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp))
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
    Box(Modifier.size(24.dp).background(Hall.gold, CircleShape), contentAlignment = Alignment.Center) {
        Text("$n", fontSize = 12.sp, color = Hall.onAccent, fontWeight = FontWeight.Bold)
    }
}

/**
 * The Needs you list, organised: a heading per project with its count, then its groups in order (decisions and
 * questions, money and stopped runs, to-dos, ideas, letters), newest first. Each group folds; it shows three and
 * "N more". Every card answers in place, so most things are one tap.
 */
@Composable
fun NeedsList(
    needs: List<NeedView>, mode: Mode?, busy: Set<String>, onAct: (NeedView, String) -> Unit, onOpen: (NeedView) -> Unit,
    modifier: Modifier = Modifier, onClose: (() -> Unit)? = null, onAnswer: (NeedView, AskReply) -> Unit = { _, _ -> },
    onMarkAllRead: (List<NeedView>) -> Unit = {},
    /** The machine (the PC or this phone) a need came through, for Answer these and a card's timer; null in Hub mode. */
    machineFor: (String) -> com.meztking.roundtable.net.Api? = rememberMachines(),
) {
    val projects = remember(needs) { NeedsOrder.organise(needs) }
    // Answer these: the cards that came from one machine (the one with the most), each with its folder and stamp
    val several = remember(needs) {
        needs.filter { it.ask != null }.groupBy { it.source }.maxByOrNull { it.value.size }?.let { (src, ns) ->
            src to ns.map { n -> n.ask!!.copy(project = n.project, path = n.ask.path ?: n.path) }
        }
    }
    val severalApi = several?.first?.let(machineFor)
    var folded by rememberSaveable { mutableStateOf(setOf<String>()) }
    var opened by rememberSaveable { mutableStateOf(setOf<String>()) }
    val letters = needs.filter { it.kind == "message" && it.message != null }
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("NEEDS YOU", style = Label)
                Spacer(Modifier.width(8.dp))
                CountBadge(needs.size)
                Spacer(Modifier.weight(1f))
                if (letters.isNotEmpty()) TextButton(onClick = { onMarkAllRead(letters) }) { Text("Mark all read") }
                if (onClose != null) TextButton(onClick = onClose) { Text("Handle later") }
            }
        }
        if (severalApi != null && several != null && com.meztking.roundtable.data.AnswerThese.shown(several.second)) item(key = "answer-these") {
            AnswerTheseBar(several.second, send = { severalApi.answerSeveral(it) },
                onAlone = { c -> needs.firstOrNull { it.ask?.id == c.id }?.let(onOpen) })
        }
        if (needs.isEmpty()) item {
            Text("Nothing waits for you. The Table will tell you when something does.", color = Hall.muted,
                modifier = Modifier.padding(vertical = 24.dp))
        }
        projects.forEach { p ->
            item(key = "p:${p.project}") {
                Column(Modifier.padding(top = 6.dp)) {
                    Text("${p.project} · ${p.count}", style = MaterialTheme.typography.titleMedium, color = Hall.goldBright)
                    Text(p.summary, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                }
            }
            p.sections.forEach { sec ->
                val gk = "${p.project}/${sec.group.name}"
                val shut = gk in folded
                item(key = "g:$gk") {
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .clickable { folded = if (shut) folded - gk else folded + gk }.padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text("${sec.group.label.uppercase()} (${sec.items.size})", style = Label.copy(fontSize = 11.sp), modifier = Modifier.weight(1f))
                        Text(if (shut) "Show" else "Hide", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                    }
                }
                if (!shut && sec.group == com.meztking.roundtable.data.NeedsOrder.Group.LETTER) {
                    // the chat replaced Letters (1.5.0): one row per project that wrote, opening its chat
                    item(key = "w:$gk") { WroteCard(p.project, sec.items, onOpen) }
                } else if (!shut) {
                    val all = gk in opened
                    val shown = if (all) sec.items else sec.items.take(3)
                    items(shown, key = { it.key }) { n ->
                        val ask = n.ask
                        if (ask != null) Column {
                            val help = remember(n.source) { machineFor(n.source)?.let { ApiCardHelp(it) } }
                            val placed = ask.copy(project = n.project, path = ask.path ?: n.path)
                            AskCard(placed, { onAnswer(n, it) }, busy = n.key in busy, showProject = false,
                                onTyping = rememberHold(help)?.let { h -> { h(placed) } })
                            if (n.asks > 1) TextButton({ onOpen(n) }) { Text("${n.asks - 1} more on the plan") }
                        } else NeedCard(n, mode, n.key in busy, onAct, onOpen)
                    }
                    if (sec.items.size > 3 && !all) item(key = "m:$gk") {
                        TextButton({ opened = opened + gk }) { Text("${sec.items.size - 3} more") }
                    }
                }
            }
        }
    }
}

/** "<project> wrote to you": what it said last, and Open the chat. */
@Composable
fun WroteCard(project: String, items: List<NeedView>, onOpen: (NeedView) -> Unit) {
    val last = items.first()
    Parchment(Modifier.fillMaxWidth(), seal = Hall.amber) {
        Text(com.meztking.roundtable.data.Words.t("{project} wrote to you", "project" to project), fontFamily = Serif,
            fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(2.dp))
        val sub = listOf(last.text.ifBlank { last.title }, if (items.size > 1) com.meztking.roundtable.data.Words.t("{n} new messages", "n" to items.size) else ago(last.at))
            .filter { it.isNotBlank() }.joinToString("\n")
        Text(sub, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft, maxLines = 4, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(8.dp))
        Button(onClick = { onOpen(last.copy(kind = "message")) }, colors = ParchmentButtons.main(), contentPadding = PaddingValues(horizontal = 14.dp)) {
            Text(com.meztking.roundtable.data.Words.t("Open the chat"))
        }
    }
}

@Composable
fun NeedCard(n: NeedView, mode: Mode?, busy: Boolean, onAct: (NeedView, String) -> Unit, onOpen: (NeedView) -> Unit) {
    val seal = when (n.kind) { "message" -> Hall.amber; "todo" -> Hall.good; else -> Hall.ember }
    val acts = actionsFor(n, mode)
    Parchment(Modifier.fillMaxWidth(), seal = seal) {
        Text(n.title, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink, maxLines = 3, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(2.dp))
        val sub = when (n.kind) {
            "message" -> listOf(n.text, ago(n.at)).filter { it.isNotBlank() }.joinToString("\n")
            else -> n.text.ifBlank { n.project }
        }
        Text(sub, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft, maxLines = 4, overflow = TextOverflow.Ellipsis)
        Text(needHint(n, acts), style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft, fontStyle = androidx.compose.ui.text.font.FontStyle.Italic)
        Spacer(Modifier.height(8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            acts.forEachIndexed { i, (action, label) ->
                val click = {
                    when (action) {
                        "open", "plan", "reply" -> onOpen(n)
                        "project" -> onOpen(n.copy(kind = "project"))
                        else -> onAct(n, action)
                    }
                }
                if (i == 0) Button(onClick = click, enabled = !busy, colors = ParchmentButtons.main(), contentPadding = PaddingValues(horizontal = 14.dp)) { Text(label) }
                else OutlinedButton(onClick = click, enabled = !busy, colors = ParchmentButtons.other(), border = ParchmentButtons.otherBorder,
                    contentPadding = PaddingValues(horizontal = 14.dp)) { Text(label) }
            }
        }
    }
}

/** One line under a card: what its buttons do. */
private fun needHint(n: NeedView, acts: List<Pair<String, String>>): String {
    val ids = acts.map { it.first }
    return when {
        n.kind == "message" && "reply" in ids -> "Read and reply opens the whole letter; Mark as read clears it from here."
        n.kind == "message" -> "Mark as read clears it from here; Open project shows what happened."
        n.kind == "todo" && "done" in ids -> "Done ticks it off in the project's journal; Open project shows where it stands."
        n.kind == "todo" -> "Open project shows where it stands and what to do."
        "plan" in ids -> "Opens the plan, where you approve it with one tap."
        else -> "Tap what should happen next."
    }
}

private fun actionsFor(n: NeedView, mode: Mode?): List<Pair<String, String>> = when (n.kind) {
    "message" -> when {
        n.message == null -> listOf("open" to "Read")
        // Roundtable's answer to the owner's own command (a refusal or a failure): nothing to reply to
        Letters.isReply(n.message.subject) -> listOf("read" to "Mark as read", "project" to "Open project")
        else -> listOf("reply" to "Read and reply", "read" to "Mark as read")
    }
    "todo" -> if (mode != null && n.id != null) listOf("done" to "Done", "open" to "Open project") else listOf("open" to "Open project")
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

/** "On your PC", "On this phone · also seen through the hub", "Building on your PC". */
fun whereWords(s: SeatView): String {
    val head = s.building.ifBlank { s.lives.replaceFirstChar { it.uppercase() } }
    val also = s.seenIn.mapNotNull { com.meztking.roundtable.data.Source.of(it)?.words }
    return head + if (also.isNotEmpty()) " · also seen through ${also.joinToString(" and ")}" else ""
}

/** The API of the machine a need came through (Source.key), from the app's connections; null for the hub or in tests. */
@Composable
fun rememberMachines(): (String) -> com.meztking.roundtable.net.Api? {
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as? com.meztking.roundtable.RoundtableApp
    return remember(app) {
        { key: String ->
            val src = com.meztking.roundtable.data.Source.of(key)
            if (app == null || src == null || src == com.meztking.roundtable.data.Source.HUB) null
            else runCatching { (app.backend()?.parts?.get(src) as? com.meztking.roundtable.data.PcBackend)?.api }.getOrNull()
        }
    }
}
