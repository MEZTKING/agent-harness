package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.Files
import com.meztking.roundtable.data.FilePreview
import com.meztking.roundtable.data.FindInFile
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.NbCell
import com.meztking.roundtable.data.Preview
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Mono

/** A richer look at a file: a notebook, an archive's list, an office file's text, or Play for a video or a song. */
@Composable
fun PreviewBody(p: FilePreview, onPlay: () -> Unit) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (p.note.isNotBlank() && p.preview.isNotBlank()) Text(p.note, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        when (p.preview) {
            "video", "audio" -> {
                Text(if (p.preview == "video") "A video. It plays in the phone's own player." else "A sound. It plays in the phone's own player.",
                    color = Hall.text)
                Button(onPlay) { Text("Play") }
            }
            "notebook" -> NotebookView(p)
            "archive" -> ArchiveView(p)
            "office" -> OfficeView(p)
        }
    }
}

@Composable
private fun NotebookView(p: FilePreview) {
    Text("A notebook: ${p.cells.size} cell${if (p.cells.size == 1) "" else "s"}. It is never run here; outputs are what the file kept.",
        color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    for (c in p.cells) Cell(c, p.language)
    if (p.more > 0) Text("And ${p.more} more cells, not shown.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun Cell(c: NbCell, language: String) {
    when (c.type) {
        "markdown" -> MdBlocks(Markdown.parse(c.source))
        "code" -> {
            Row {
                Text(c.count?.let { "[$it]" } ?: "[ ]", Modifier.width(40.dp), color = Hall.muted, fontFamily = Mono, fontSize = 11.sp)
                Text(coloured(c.source, language), Modifier.fillMaxWidth().background(Hall.code, RoundedCornerShape(6.dp))
                    .border(1.dp, Hall.line, RoundedCornerShape(6.dp)).horizontalScroll(rememberScrollState()).padding(8.dp),
                    color = Hall.text, fontFamily = Mono, fontSize = 12.sp)
            }
            for (o in c.outputs) when (o.kind) {
                "image" -> {
                    val img = remember(o.data) { runCatching { java.util.Base64.getDecoder().decode(o.data) }.getOrNull()
                        ?.let { b -> runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull() } }
                    if (img != null) Image(img, "A picture the cell made", Modifier.fillMaxWidth().padding(start = 40.dp).clip(RoundedCornerShape(6.dp)),
                        contentScale = ContentScale.FillWidth)
                }
                else -> Text(o.text, Modifier.padding(start = 40.dp), color = if (o.kind == "error") Hall.bad else Hall.muted,
                    fontFamily = Mono, fontSize = 12.sp, maxLines = 40, overflow = TextOverflow.Ellipsis)
            }
        }
        else -> Text(c.source, color = Hall.muted, fontFamily = Mono, fontSize = 12.sp)
    }
}

@Composable
private fun ArchiveView(p: FilePreview) {
    Text(Preview.archiveLine(p), color = if (p.unsafe > 0) Hall.warn else Hall.text, style = MaterialTheme.typography.bodyMedium)
    for (e in p.entries.take(400)) Row(Modifier.fillMaxWidth()) {
        Text((if (e.folder) "📁 " else "") + e.name + if (e.unsafe) "  (outside the folder)" else "", Modifier.weight(1f),
            color = if (e.unsafe) Hall.bad else Hall.text, fontFamily = Mono, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (!e.folder) Text(Files.size(e.size), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
    val left = maxOf(p.count, p.entries.size) - minOf(p.entries.size, 400)
    if (left > 0) Text("And $left more, not shown.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    Text("Nothing is unpacked: this is only the list.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun OfficeView(p: FilePreview) {
    for (b in p.blocks) when (b.type) {
        "heading" -> Text(b.plain, color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
        "list" -> for (item in b.items) Text("• " + item.joinToString("") { it.text }, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        "table" -> SmallTable(b.rows)
        else -> Text(b.plain, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
    }
    for (s in p.sheets) { Text(s.name.uppercase(), style = Label, color = Hall.muted); SmallTable(s.rows) }
    for (s in p.slides) {
        Text("Slide ${s.n}: ${s.title}", color = Hall.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
        for (l in s.lines) Text(l, color = Hall.text, style = MaterialTheme.typography.bodySmall)
    }
    Text("A simple view: the PC shows it exactly, as a PDF.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun SmallTable(rows: List<List<String>>) {
    Column(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
        for (r in rows.take(100)) Row {
            for (c in r.take(12)) Text(c, Modifier.width(110.dp).padding(2.dp), color = Hall.text, style = MaterialTheme.typography.bodySmall,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Find in this file: a box, how many lines hold the words, and those lines with their numbers (the words marked). */
@Composable
fun FindInFileBar(text: String, words: String, onWords: (String) -> Unit) {
    val hits = remember(text, words) { FindInFile.hits(text, words) }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        OutlinedTextField(words, onWords, Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text("Find in this file") })
        val line = FindInFile.countLine(hits, words)
        if (line.isNotBlank()) Text(line, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        for (h in hits.take(200)) Row {
            Text("${h.number}", Modifier.width(44.dp), color = Hall.muted, fontFamily = Mono, fontSize = 11.sp)
            Text(buildAnnotatedString {
                append(h.line)
                addStyle(SpanStyle(background = Hall.gold.copy(alpha = 0.35f), fontWeight = FontWeight.Bold), h.start, h.end)
            }, color = Hall.text, fontFamily = Mono, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}
