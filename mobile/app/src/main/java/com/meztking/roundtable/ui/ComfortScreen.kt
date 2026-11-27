package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import com.meztking.roundtable.data.Accent
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.data.Detail
import com.meztking.roundtable.data.Haptics
import com.meztking.roundtable.data.Look
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.rememberHaptics
import kotlin.math.roundToInt

/**
 * Comfort (beta until tried on a real phone): how the app looks and feels on this phone. Short first: each choice
 * is one row with a one-line hint; nothing here leaves the phone.
 */
@Composable
fun ComfortScreen(comfort: Comfort, onBack: () -> Unit, dark: Boolean = comfort.look.dark) {
    val buzz = rememberHaptics()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            Text("Comfort", style = MaterialTheme.typography.headlineSmall, color = Hall.goldBright, modifier = Modifier.weight(1f))
            Chip("beta", Hall.muted)
        }
        Text("How ${Brand.NAME} looks and feels on this phone. These stay on this phone only.", color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)

        Panel(Modifier.fillMaxWidth()) {
            Text("LOOK", style = Label)
            Hint(comfort.look.hint)
            Spacer(Modifier.height(8.dp))
            Choices(Look.entries, comfort.look, { it.words }) { comfort.pickLook(it); buzz() }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("ACCENT COLOUR", style = Label)
            Hint("The colour of buttons and the selected tab. Each one is easy to read in every look.")
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Accent.entries.forEach { a ->
                    val c = Color(if (dark) a.dark else a.light)
                    val on = comfort.accent == a
                    Column(horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.clickable(role = Role.RadioButton, onClickLabel = "Use ${a.words}") { comfort.pickAccent(a); buzz() }
                            .semantics { contentDescription = a.words + if (on) ", chosen" else "" }) {
                        Box(Modifier.size(40.dp).background(c, CircleShape).border(if (on) 3.dp else 1.dp, if (on) Hall.text else Hall.line, CircleShape))
                        Text(a.words, style = MaterialTheme.typography.labelMedium, color = if (on) Hall.text else Hall.muted,
                            fontWeight = if (on) FontWeight.Bold else null, modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("TEXT SIZE", style = Label)
            Hint("On top of the phone's own text size.")
            val pct = (comfort.textScale * 100).roundToInt()
            Text("Aa · $pct%", color = Hall.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(top = 6.dp))
            Slider(comfort.textScale, { comfort.pickTextScale((it * 20).roundToInt() / 20f) },
                valueRange = Comfort.SCALE_MIN..Comfort.SCALE_MAX, steps = 7,
                colors = SliderDefaults.colors(thumbColor = Hall.gold, activeTrackColor = Hall.gold),
                modifier = Modifier.semantics { contentDescription = "Text size, $pct percent" })
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("BUZZ", style = Label)
            Hint("A small buzz when you press and hold, or pick something here.")
            Spacer(Modifier.height(8.dp))
            Choices(Haptics.entries, comfort.haptics, { it.words }) { comfort.pickHaptics(it); buzz() }
        }

        Panel(Modifier.fillMaxWidth()) {
            Text("HOW MUCH THE LIVE TAB SHOWS", style = Label)
            Hint(comfort.detail.hint)
            Spacer(Modifier.height(8.dp))
            Choices(Detail.entries, comfort.detail, { it.words }) { comfort.pickDetail(it); buzz() }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun Hint(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = Hall.muted, modifier = Modifier.padding(top = 2.dp))
}

@Composable
private fun <T> Choices(all: List<T>, chosen: T, words: (T) -> String, pick: (T) -> Unit) {
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        all.forEachIndexed { i, v ->
            SegmentedButton(chosen == v, { pick(v) }, SegmentedButtonDefaults.itemShape(i, all.size),
                colors = SegmentedButtonDefaults.colors(activeContainerColor = Hall.accentSoft, activeContentColor = Hall.text,
                    inactiveContainerColor = Hall.panel, inactiveContentColor = Hall.muted)) { Text(words(v)) }
        }
    }
}

/** One line of the battery checklist; [ok] null means the phone can't tell (check it by hand). */
data class BatteryCheck(val words: String, val ok: Boolean?)

/** What keeps Roundtable checking in the background, worked out from what the phone reports (tests call it). */
object BatteryChecklist {
    fun checks(unrestricted: Boolean, notifications: Boolean, dataSaverBlocks: Boolean): List<BatteryCheck> = listOf(
        BatteryCheck("Battery use for ${Brand.NAME}: Unrestricted", unrestricted),
        BatteryCheck("Notifications for ${Brand.NAME}: on", notifications),
        BatteryCheck("Data Saver lets ${Brand.NAME} use data in the background", !dataSaverBlocks),
        BatteryCheck("Your phone maker's own \"sleeping apps\" list doesn't include ${Brand.NAME}", null),
    )

    /** One plain sentence: all set, or how many things may stop it. */
    fun summary(checks: List<BatteryCheck>): String {
        val bad = checks.count { it.ok == false }
        return if (bad == 0) "All set: ${Brand.NAME} can keep checking while the phone sleeps."
        else "$bad thing${if (bad == 1) "" else "s"} may stop ${Brand.NAME} checking while the phone sleeps."
    }

    /** What this phone reports now. */
    fun read(ctx: Context): List<BatteryCheck> {
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        return checks(
            unrestricted = runCatching { pm?.isIgnoringBatteryOptimizations(ctx.packageName) == true }.getOrDefault(false),
            notifications = runCatching { NotificationManagerCompat.from(ctx).areNotificationsEnabled() }.getOrDefault(true),
            dataSaverBlocks = runCatching { cm?.restrictBackgroundStatus == ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED }.getOrDefault(false),
        )
    }

    /** Android's battery page (the list of apps and their battery use); this app's own page if that isn't there. */
    fun open(ctx: Context) {
        val tries = listOf(
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}")),
        )
        for (i in tries) {
            if (runCatching { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true }.getOrDefault(false)) return
        }
    }
}

/** The battery checklist panel for Settings: one sentence first, the list folded, one button to Android's page. */
@Composable
fun BatteryPanel(checks: List<BatteryCheck>, onOpen: () -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Text("WHILE THE PHONE SLEEPS", style = Label)
        Spacer(Modifier.height(6.dp))
        val bad = checks.any { it.ok == false }
        Text(BatteryChecklist.summary(checks), color = if (bad) Hall.candle else Hall.text, style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (bad) FontWeight.SemiBold else null)
        Fold("What to check (${checks.size})", startOpen = false) {
            checks.forEach { c ->
                Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(when (c.ok) { true -> "✓"; false -> "!"; null -> "?" }, Modifier.width(20.dp),
                        color = when (c.ok) { true -> Hall.good; false -> Hall.bad; null -> Hall.muted }, fontWeight = FontWeight.Bold)
                    Text(c.words, color = Hall.text, style = MaterialTheme.typography.bodySmall)
                }
            }
            Text("A question mark is something the phone can't tell ${Brand.NAME}: look for it in the phone's battery settings.",
                Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        }
        OutlinedButton(onClick = onOpen) { Text("Open battery settings") }
        Text("Choose ${Brand.NAME} there, then Unrestricted (or \"Don't optimise\"). This list checks again when you come back.",
            color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

/** The Comfort entry for Settings: what is chosen now, in one line, and Open. */
@Composable
fun ComfortEntry(comfort: Comfort, onOpen: () -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Text("COMFORT", style = Label)
        Spacer(Modifier.height(6.dp))
        Text(comfortLine(comfort.look, comfort.accent, comfort.textScale, comfort.detail), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(6.dp))
        OutlinedButton(onClick = onOpen) { Text("Open") }
    }
}

/** "Amber · true black · text 110% · Live: Compact". */
fun comfortLine(look: Look, accent: Accent, scale: Float, detail: Detail): String =
    listOf(look.words, accent.words, "text ${(scale * 100).roundToInt()}%", "Live: ${detail.words}")
        .joinToString(" · ")

/** The battery checklist, read again each time the app comes back to the front (after Android's battery page). */
@Composable
fun rememberBatteryChecks(): List<BatteryCheck> {
    val ctx = LocalContext.current
    var tick by remember { mutableIntStateOf(0) }
    androidx.lifecycle.compose.LifecycleResumeEffect(Unit) { tick++; onPauseOrDispose { } }
    return remember(tick) { BatteryChecklist.read(ctx) }
}
