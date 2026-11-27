package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Kinds
import com.meztking.roundtable.data.PlanKind
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Panel

/** The kind's words on a small label: "Proven (3 built)", "On trial", "Not yet". */
@Composable
fun KindStatus(status: String, words: String) {
    val colour = when (status) { "proven" -> Hall.good; "not_yet" -> Hall.muted; else -> Hall.gold }
    Text(words, color = colour, style = MaterialTheme.typography.labelMedium)
}

/**
 * The first card on a plan: "This looks like a website, because you said “site”. Right?" with the top
 * choices and Something else. [onChoose] posts /api/kinds/set; null hides the buttons (Hub mode: read only).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun KindCard(kind: PlanKind, onChoose: ((String) -> Unit)?, busy: Boolean = false) {
    Panel(Modifier.fillMaxWidth(), highlight = !kind.confirmed && !kind.fixed) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("KIND", color = Hall.gold, style = MaterialTheme.typography.labelSmall)
            Spacer(Modifier.width(8.dp))
            KindStatus(kind.status, kind.statusWords)
        }
        Spacer(Modifier.height(4.dp))
        Text(kind.question, color = Hall.text, style = MaterialTheme.typography.titleSmall)
        if (kind.fixed) {
            Text("Fixed for this plan. To make it as something else, use Try another way or start a new goal.",
                color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            return@Panel
        }
        if (onChoose != null) {
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                kind.choices.forEach { c ->
                    if (c.recommended) Button(onClick = { onChoose(c.id) }, enabled = !busy) { Text(Kinds.choiceLabel(kind, c)) }
                    else OutlinedButton(onClick = { onChoose(c.id) }, enabled = !busy) { Text(Kinds.choiceLabel(kind, c)) }
                }
            }
        }
        if (kind.changeWords.isNotBlank()) Text(kind.changeWords, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}
