package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.Autopilot
import com.meztking.roundtable.data.AutopilotState
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.ago
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.ParchmentButtons
import com.meztking.roundtable.ui.theme.Serif

/** The Autopilot switch on the Table: outlined when off, lit amber when on ("until 8am · $0.40 of $2.00"). */
@Composable
fun AutopilotToggle(state: AutopilotState?, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val on = state?.on == true
    val shape = RoundedCornerShape(50)
    Row(
        modifier.clip(shape).background(if (on) Hall.candle else Hall.panel)
            .border(1.dp, if (on) Hall.candle else Hall.line, shape)
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp)
            .semantics { contentDescription = if (on) "Autopilot on, ${state?.label}. Open to see what it did or turn it off." else "Autopilot off. Open to turn it on." },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val ink = if (on) Hall.onAccent else Hall.muted
        Box(Modifier.size(9.dp).clip(CircleShape).background(if (on) Hall.onAccent else Hall.panel).border(2.dp, ink, CircleShape))
        Spacer(Modifier.width(8.dp))
        Text("Autopilot", fontWeight = FontWeight.Bold, color = if (on) Hall.onAccent else Hall.text, fontSize = 15.sp)
        if (on) {
            Spacer(Modifier.width(8.dp))
            Text(state?.label.orEmpty(), color = Hall.onAccent, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** A small mark on a seat that autopilot is looking after. */
@Composable
fun AutopilotMark() {
    Text("AUTOPILOT", Modifier.clip(RoundedCornerShape(50)).background(Hall.warn.copy(alpha = 0.16f)).padding(horizontal = 6.dp, vertical = 1.dp),
        color = Hall.warn, fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp)
}

/** On the round table: a small lit "A" on the seat's ring (the seat's description says "on autopilot"). */
@Composable
fun AutopilotDot(modifier: Modifier = Modifier) {
    Box(modifier.size(18.dp).clip(CircleShape).background(Hall.candle).border(2.dp, Hall.panel, CircleShape), contentAlignment = Alignment.Center) {
        Text("A", color = Hall.onAccent, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}

/** Turn autopilot on (until when, how much it may spend) or off, and read what it did. */
@Composable
fun AutopilotSheet(state: AutopilotState?, mode: Mode?, modifier: Modifier = Modifier, onSet: (Boolean, String, Double?) -> Unit) {
    var until by rememberSaveable { mutableStateOf("") }
    var cap by rememberSaveable { mutableStateOf("%.2f".format(state?.spend_cap_usd ?: 2.0)) }
    val on = state?.on == true
    Column(modifier.fillMaxWidth().heightIn(max = 640.dp).verticalScroll(rememberScrollState()).padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Autopilot", fontFamily = Serif, fontWeight = FontWeight.Bold, fontSize = 24.sp, color = Hall.text)
        if (on) {
            Text("On · ${state?.label}", color = Hall.candle, fontWeight = FontWeight.Bold)
            Text("It answers with the recommended answer, tries a failed task once more and starts a plan when its cost fits the limit. Money pauses and anything that asks “Are you sure?” wait for you.",
                style = MaterialTheme.typography.bodyMedium, color = Hall.muted)
            Button({ onSet(false, "", null) }, colors = ParchmentButtons.main()) { Text("Turn off") }
        } else {
            Text("While you're away, ${Brand.NAME} answers what waits for you with the recommended answer and writes down every choice. It never raises a limit, never picks anything that asks “Are you sure?”, and never deletes, publishes or releases anything.",
                style = MaterialTheme.typography.bodyMedium, color = Hall.muted)
            if (state == null) Text(if (mode == Mode.HUB) "Your PC hasn't said how autopilot stands yet. It still listens for this." else "Couldn't read autopilot from your PC.",
                style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Text("UNTIL", style = Label)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Autopilot.UNTIL.forEach { (value, label, meaning) ->
                    val picked = until == value
                    Text(label, Modifier.clip(RoundedCornerShape(50)).background(if (picked) Hall.gold else Hall.panel)
                        .border(1.dp, if (picked) Hall.gold else Hall.line, RoundedCornerShape(50))
                        .clickable(role = Role.RadioButton) { until = value }.padding(horizontal = 14.dp, vertical = 8.dp)
                        .semantics { contentDescription = "$label: $meaning" },
                        color = if (picked) Hall.onAccent else Hall.text, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                }
            }
            Text(Autopilot.UNTIL.first { it.first == until }.third, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            Text("SPEND LIMIT", style = Label)
            OutlinedTextField(cap, { cap = it.filter { c -> c.isDigit() || c == '.' }.take(7) }, singleLine = true,
                prefix = { Text("$") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                supportingText = { Text("The most it may spend while it's on, on every project together. Then it stops.") })
            Button({ onSet(true, until, cap.toDoubleOrNull()) }, colors = ParchmentButtons.main()) { Text("Turn on") }
        }
        Spacer(Modifier.height(4.dp))
        Text("WHAT AUTOPILOT DID", style = Label)
        val log = state?.log.orEmpty()
        if (log.isEmpty()) Text("Nothing yet. Its choices show up here, newest first.", color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        log.forEach { e ->
            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(ago(e.at), color = Hall.muted, fontSize = 12.sp)
                    if (!e.project.isNullOrBlank()) Text(e.project, color = Hall.gold, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
                Text(e.text, color = if (e.kind == "left") Hall.muted else Hall.text, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
