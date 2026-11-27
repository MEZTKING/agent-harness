package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Proof
import com.meztking.roundtable.data.ProofPicture
import com.meztking.roundtable.data.TaskProof
import com.meztking.roundtable.ui.theme.Hall

private fun proofBitmap(bytes: ByteArray): ImageBitmap? =
    runCatching { BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap() }.getOrNull()

/**
 * Proof under a finished task: one line (what a model that can see said, and the tests), opened with a tap to the
 * pictures before and after (a slider between them), what it noticed and the tests' last lines. [load] fetches the
 * PC's /api/proof (see [Proof.url]); nothing shows when there's no proof or the PC is older.
 */
@Composable
fun ProofCard(task: String, load: suspend () -> String?) {
    var proof by remember(task) { mutableStateOf<TaskProof?>(null) }
    var open by rememberSaveable(task) { mutableStateOf(false) }
    LaunchedEffect(task) { proof = runCatching { Proof.parse(load()) }.getOrNull()?.takeIf { it.found } }
    val p = proof ?: return
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(10.dp))
        .border(1.dp, Hall.line, RoundedCornerShape(10.dp)).background(Hall.bgDeep)) {
        Row(Modifier.fillMaxWidth().clickable(role = Role.Button, onClickLabel = if (open) "Close the proof" else "See the pictures before and after") { open = !open }
            .padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val tint = when (p.verdict) { "shows_it" -> Hall.good; "does_not" -> Hall.bad; "cant_tell" -> Hall.warn; else -> Hall.muted }
            Text(p.mark, Modifier.size(22.dp).clip(CircleShape).background(Hall.line).wrapContentSize(Alignment.Center)
                .semantics { contentDescription = Proof.markWords(p.verdict) }, color = tint,
                style = MaterialTheme.typography.labelMedium)
            Text(p.words, Modifier.weight(1f), color = Hall.text, style = MaterialTheme.typography.bodySmall,
                maxLines = if (open) 6 else 2)
        }
        if (open) Column(Modifier.fillMaxWidth().padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            val pics = remember(p) { p.pictures() }
            if (pics.isEmpty()) Text(p.after?.note?.takeIf { it.isNotBlank() } ?: "No pictures for this task: it has no screens to show.",
                color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            pics.forEach { BeforeAfter(it) }
            Text(Proof.markWords(p.verdict), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            p.judge?.takeIf { it.looked && it.problems.isNotEmpty() }?.let { j ->
                Fold("What it noticed (${j.problems.size})") { j.problems.forEach { Text("• $it", color = Hall.text, style = MaterialTheme.typography.bodySmall) } }
            }
            if (p.lines_text.isNotBlank()) Text(p.lines_text, color = Hall.text, style = MaterialTheme.typography.bodySmall)
            p.tests?.takeIf { it.words.isNotBlank() }?.let { t ->
                Text(t.words, color = Hall.text, style = MaterialTheme.typography.bodySmall)
                if (t.broke.isNotEmpty()) Text("Broke: " + t.broke.take(6).joinToString(", "), color = Hall.bad, style = MaterialTheme.typography.bodySmall)
                val tail = t.after?.tail.orEmpty()
                if (tail.isNotBlank()) Fold("The tests' last lines") { Text(tail, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
            }
            val more = Proof.moreLines(p)
            if (more.isNotEmpty()) Fold("More") { more.forEach { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) } }
        }
    }
}

/** One picture: before and after on top of each other; the slider wipes from one to the other. */
@Composable
private fun BeforeAfter(pic: ProofPicture) {
    val after = remember(pic) { proofBitmap(pic.after) } ?: return
    val before = remember(pic) { pic.before?.let { proofBitmap(it) } }
    var split by rememberSaveable(pic.kind) { mutableFloatStateOf(0.5f) }
    Column(Modifier.fillMaxWidth()) {
        Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).border(1.dp, Hall.line, RoundedCornerShape(8.dp))) {
            Image(after, "${pic.label}, after the task", Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
            if (before != null) {
                Image(before, "${pic.label}, before the task", Modifier.fillMaxWidth().drawWithContent {
                    clipRect(right = size.width * split) { this@drawWithContent.drawContent() }
                }, contentScale = ContentScale.FillWidth)
                Text("Before", Modifier.align(Alignment.TopStart).padding(6.dp).background(Hall.ink.copy(alpha = 0.7f), RoundedCornerShape(4.dp))
                    .padding(horizontal = 6.dp, vertical = 1.dp), color = Hall.parchment,
                    style = MaterialTheme.typography.labelSmall)
            }
            Text(if (before != null) "After" else "New", Modifier.align(Alignment.TopEnd).padding(6.dp)
                .background(Hall.ink.copy(alpha = 0.7f), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 1.dp),
                color = Hall.parchment,
                style = MaterialTheme.typography.labelSmall)
        }
        if (before != null) Slider(split, { split = it }, Modifier.fillMaxWidth()
            .semantics { contentDescription = "${pic.label}: slide between before and after" })
        Text("${pic.label} · ${pic.words}", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}
