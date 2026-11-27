package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.DoneEvidence
import com.meztking.roundtable.data.DoneItem
import com.meztking.roundtable.data.DoneList
import com.meztking.roundtable.data.DoneSummary
import com.meztking.roundtable.net.Api

/**
 * The done list under the plan's summary: one line first ("Done when: 5 of 7 ✓"), the items on a tap, each item's
 * evidence behind More. Nothing shows when the PC has no done list for this project, or is older.
 */
@Composable
fun DoneCard(api: Api?, path: String) {
    var done by remember(path) { mutableStateOf<DoneSummary?>(null) }
    var open by rememberSaveable(path) { mutableStateOf(false) }
    LaunchedEffect(api, path) {
        done = api?.let { a -> runCatching { DoneList.parse(a.feature("GET", DoneList.url(path))) }.getOrNull() }
            ?.takeIf { it.items.isNotEmpty() }
    }
    val d = done ?: return
    val c = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(10.dp))
        .border(1.dp, c.outlineVariant, RoundedCornerShape(10.dp)).background(c.surfaceVariant)) {
        Text(DoneList.line(d), Modifier.fillMaxWidth()
            .clickable(role = Role.Button, onClickLabel = if (open) "Close the done list" else "See what finished means") { open = !open }
            .padding(10.dp), color = if (d.failed > 0) c.error else c.onSurface, style = MaterialTheme.typography.bodyMedium)
        if (open) Column(Modifier.fillMaxWidth().padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            d.items.forEach { DoneRow(api, path, it) }
            if (d.unchecked > 0) Text("${d.unchecked} couldn't be checked yet or here: they show no tick.",
                color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun DoneRow(api: Api?, path: String, i: DoneItem) {
    val c = MaterialTheme.colorScheme
    val tint = when (i.state) { "passed" -> c.primary; "failed" -> c.error; "unchecked" -> c.tertiary; else -> c.onSurfaceVariant }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        Text(DoneList.mark(i.state), Modifier.size(22.dp).clip(CircleShape).background(c.outlineVariant)
            .wrapContentSize(Alignment.Center).semantics { contentDescription = DoneList.markWords(i.state) },
            color = tint, style = MaterialTheme.typography.labelMedium)
        Column(Modifier.weight(1f)) {
            val tags = DoneList.tags(i)
            Text(i.text + if (tags.isEmpty()) "" else "  · " + tags.joinToString(" · "), color = c.onSurface,
                style = MaterialTheme.typography.bodySmall)
            if (i.words.isNotBlank()) Text(i.words, color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            if (i.state != "open") Fold("More") { Evidence(api, path, i.id) }
        }
    }
}

/** The check's pictures and notes, fetched when More is opened. */
@Composable
private fun Evidence(api: Api?, path: String, item: String) {
    var ev by remember(path, item) { mutableStateOf<DoneEvidence?>(null) }
    var tried by remember(path, item) { mutableStateOf(false) }
    LaunchedEffect(api, path, item) {
        ev = api?.let { a -> runCatching { DoneList.parseEvidence(a.feature("GET", DoneList.evidenceUrl(path, item))) }.getOrNull() }
        tried = true
    }
    val c = MaterialTheme.colorScheme
    val e = ev
    if (e == null || !e.found) {
        if (tried) Text("The check left nothing more to show.", color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        return
    }
    val pics = remember(e) { DoneList.pictureBytes(e).mapNotNull { (name, b) ->
        runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull()?.let { name to it } } }
    pics.forEach { (name, bmp) ->
        Image(bmp, "${e.text}: $name", Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)), contentScale = ContentScale.FillWidth)
    }
    e.texts.forEach { (k, v) -> Text("$k: $v", color = c.onSurfaceVariant, style = MaterialTheme.typography.bodySmall, maxLines = 12) }
    if (pics.isEmpty() && e.texts.isEmpty()) Text("The check left nothing more to show.", color = c.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall)
}
