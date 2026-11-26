package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Parchment
import com.meztking.roundtable.ui.theme.ParchmentButtons
import com.meztking.roundtable.ui.theme.Serif

/**
 * A question to answer by tapping (Roundtable Hold's asks.py): the header chip, the question, one big
 * button per answer (the recommended one first and marked), ticks and Done when several fit, and
 * "Other…" for a typed answer. One tap answers; an answer that spends beyond the estimate shows an
 * "Are you sure?" card first. [sent] replaces the buttons once answered (what Roundtable said).
 */
@Composable
fun AskCard(ask: Ask, onAnswer: (AskReply) -> Unit, modifier: Modifier = Modifier, busy: Boolean = false, sent: String? = null) {
    var picked by rememberSaveable(ask.id, ask.stamp) { mutableStateOf(ask.answer?.chosen.orEmpty()) }
    var other by rememberSaveable(ask.id, ask.stamp) { mutableStateOf(ask.answer?.other.orEmpty()) }
    var otherOpen by rememberSaveable(ask.id, ask.stamp) { mutableStateOf(ask.options.isEmpty() || other.isNotBlank()) }
    var confirming by rememberSaveable(ask.id, ask.stamp) { mutableStateOf<String?>(null) }
    val send = { r: AskReply -> if (r.needsConfirm(ask) != null) confirming = r.chosen.joinToString(",") else onAnswer(r) }

    Parchment(modifier.fillMaxWidth(), seal = if (ask.kind == "money" || ask.kind == "failed") Hall.ember else Hall.amber) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Chip(ask.header.uppercase(), Hall.ink)
            if (ask.project.isNotBlank()) {
                Spacer(Modifier.width(8.dp))
                Text(ask.project, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
            }
        }
        Spacer(Modifier.height(4.dp))
        val confirm = confirming?.let { ids -> ask.options.firstOrNull { it.id in ids.split(",") && it.confirm != null } }
        if (confirm != null) {
            Text("Are you sure?", fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink)
            Text(confirm.confirm.orEmpty(), style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
            Spacer(Modifier.height(8.dp))
            OptionButton("Yes, go ahead", confirm.label, recommended = true, enabled = !busy) {
                onAnswer(AskReply(confirming!!.split(","), other, confirmed = true)); confirming = null
            }
            OptionButton("No, go back", "Nothing is changed.", enabled = !busy) { confirming = null }
            return@Parchment
        }
        Text(ask.question, fontFamily = Serif, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = Hall.ink)
        if (ask.detail.isNotBlank()) Text(ask.detail, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
        Spacer(Modifier.height(8.dp))
        if (sent != null) {
            Text(sent, color = Hall.ink, style = MaterialTheme.typography.bodyMedium)
            return@Parchment
        }
        ask.options.forEach { o ->
            val on = o.id in picked
            OptionButton(o.label, o.description, recommended = o.id == ask.recommended, selected = on, enabled = !busy,
                tick = if (ask.multi) on else null) {
                if (ask.multi) picked = if (on) picked - o.id else picked + o.id
                else send(AskReply(listOf(o.id), other))
            }
        }
        if (ask.allow_other && ask.options.isNotEmpty() && !otherOpen) {
            OptionButton("Other…", ask.other_hint, enabled = !busy) { otherOpen = true }
        }
        if (ask.allow_other && otherOpen) {
            OutlinedTextField(other, { other = it }, Modifier.fillMaxWidth().heightIn(min = 56.dp), placeholder = { Text(ask.other_hint) },
                colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Hall.ink, unfocusedTextColor = Hall.ink, focusedBorderColor = Hall.ink,
                    unfocusedBorderColor = Hall.inkSoft, cursorColor = Hall.ink, focusedPlaceholderColor = Hall.inkSoft,
                    unfocusedPlaceholderColor = Hall.inkSoft))
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (ask.multi) Button({ send(AskReply(picked, other)) }, enabled = !busy && (picked.isNotEmpty() || other.isNotBlank()),
                colors = ParchmentButtons.main()) { Text("Done") }
            else if (otherOpen) Button({ send(AskReply(emptyList(), other)) }, enabled = !busy && other.isNotBlank(),
                colors = ParchmentButtons.main()) { Text("Send") }
            if (otherOpen && ask.options.isNotEmpty()) TextButton({ otherOpen = false; other = "" }) { Text("Cancel", color = Hall.inkSoft) }
        }
    }
}

/** One big answer: its label (marked when recommended) and a line saying what it does. */
@Composable
private fun OptionButton(label: String, description: String, recommended: Boolean = false, selected: Boolean = false,
                         enabled: Boolean = true, tick: Boolean? = null, onClick: () -> Unit) {
    val shape = RoundedCornerShape(6.dp)
    Row(
        Modifier.fillMaxWidth().padding(vertical = 3.dp)
            .background(if (selected) Hall.gold.copy(alpha = 0.35f) else Hall.ink.copy(alpha = 0.05f), shape)
            .border(if (recommended || selected) 2.dp else 1.dp, if (selected) Hall.ink else if (recommended) Hall.inkSoft else Hall.inkSoft.copy(alpha = 0.4f), shape)
            .clickable(enabled = enabled, role = if (tick != null) Role.Checkbox else Role.Button, onClick = onClick)
            .heightIn(min = 48.dp).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (tick != null) {
            Checkbox(tick, null, colors = CheckboxDefaults.colors(checkedColor = Hall.ink, uncheckedColor = Hall.inkSoft, checkmarkColor = Hall.parchment))
            Spacer(Modifier.width(6.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(label + if (recommended) " (Recommended)" else "", fontWeight = FontWeight.SemiBold, color = Hall.ink)
            if (description.isNotBlank()) Text(description, style = MaterialTheme.typography.bodySmall, color = Hall.inkSoft)
        }
    }
}
