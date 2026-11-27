package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.ui.theme.Hall

/** A part shown by its title only, opened with a tap (short first, details on request). */
@Composable
fun Fold(title: String, startOpen: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    var open by rememberSaveable(title) { mutableStateOf(startOpen) }
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = if (open) "Close" else "Open") { open = !open }
            .padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (open) "▾" else "▸", Modifier.width(20.dp), color = Hall.gold)
            Text(title, Modifier.weight(1f), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        }
        if (open) Column(Modifier.fillMaxWidth().padding(start = 20.dp, bottom = 8.dp)) { content() }
    }
}
