package com.meztking.roundtable.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.meztking.roundtable.data.CodeColours
import com.meztking.roundtable.data.CommandLog
import com.meztking.roundtable.data.CommandRun
import com.meztking.roundtable.data.FileItem
import com.meztking.roundtable.data.Files
import com.meztking.roundtable.data.FilesSource
import com.meztking.roundtable.data.FolderView
import com.meztking.roundtable.data.JsonNode
import com.meztking.roundtable.data.JsonTree
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.OpenedFile
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/*
 * The Files screen: a project's folder, any file opened (code lightly coloured, markdown drawn, CSV as a table, JSON
 * folded, pictures, PDFs opened with the phone's own viewer), Save a copy through the share sheet, and the commands
 * its tasks ran with "Run the tests" – the phone's answer to a terminal (no free shell). Reads the PC (PC mode) or
 * Roundtable on this phone; in Hub mode it says where the files are.
 */

/** Everything the Files screen draws, so it can be shown in tests without a connection. */
data class FilesUi(
    val title: String,
    val tab: Int = 0,
    val folder: Load<FolderView> = Load(),
    val opened: Load<OpenedFile>? = null,
    val log: Load<CommandLog> = Load(),
    val testsRunning: Boolean = false,
    /** A line to show after something was done ("The tests passed."). */
    val said: String? = null,
    /** When there's no connection to the machine with the files: where they are, in words. */
    val elsewhere: String? = null,
)

class FilesActions(
    val back: () -> Unit = {},
    val refresh: () -> Unit = {},
    val tab: (Int) -> Unit = {},
    val openDir: (String) -> Unit = {},
    val openFile: (FileItem) -> Unit = {},
    val closeFile: () -> Unit = {},
    val saveCopy: (OpenedFile) -> Unit = {},
    val openOutside: (OpenedFile) -> Unit = {},
    val runTests: () -> Unit = {},
)

/** The screen with its state: give it the machine's [source] (null in Hub mode, with [elsewhere] saying where). */
@Composable
fun FilesScreen(title: String, source: FilesSource?, elsewhere: String, onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var dir by rememberSaveable { mutableStateOf("") }
    var ui by remember { mutableStateOf(FilesUi(title, elsewhere = if (source == null) elsewhere else null)) }
    fun loadDir(d: String) {
        if (source == null) return
        dir = d
        ui = ui.copy(folder = ui.folder.copy(loading = true, error = null))
        scope.launch {
            ui = runCatching { source.list(d) }.fold({ v ->
                if (!v.here) ui.copy(folder = Load(), elsewhere = v.words) else ui.copy(folder = Load(v)) },
                { ui.copy(folder = ui.folder.copy(loading = false, error = it.message ?: "The files can't be read just now.")) })
        }
    }
    fun loadLog() {
        if (source == null) return
        ui = ui.copy(log = ui.log.copy(loading = true, error = null))
        scope.launch {
            ui = runCatching { source.log() }.fold({ ui.copy(log = Load(it)) },
                { ui.copy(log = ui.log.copy(loading = false, error = it.message ?: "The command log can't be read just now.")) })
        }
    }
    LaunchedEffect(source) { loadDir(dir); loadLog() }
    val a = FilesActions(
        back = onBack,
        refresh = { loadDir(dir); loadLog() },
        tab = { ui = ui.copy(tab = it, said = null) },
        openDir = { loadDir(it) },
        openFile = { item ->
            if (source != null) {
                ui = ui.copy(opened = Load(loading = true))
                scope.launch {
                    ui = ui.copy(opened = runCatching { Load(source.open(item.path)) }
                        .getOrElse { Load(error = it.message ?: "That file can't be opened just now.") })
                }
            }
        },
        closeFile = { ui = ui.copy(opened = null) },
        saveCopy = { f ->
            if (source != null) scope.launch {
                val copy = if (f.data != null && f.kind in setOf("image", "pdf")) f else runCatching { source.copy(f.file) }.getOrElse {
                    ui = ui.copy(said = it.message ?: "That file can't be copied just now."); return@launch
                }
                ui = ui.copy(said = shareFile(ctx, copy, view = false))
            }
        },
        openOutside = { f -> ui = ui.copy(said = shareFile(ctx, f, view = true)) },
        runTests = {
            if (source != null && !ui.testsRunning) scope.launch {
                ui = ui.copy(testsRunning = true, said = null)
                val id = runCatching { source.runTests() }.getOrElse {
                    ui = ui.copy(testsRunning = false, said = it.message ?: "The tests can't be started just now."); return@launch
                }
                var words = "Finished."
                for (i in 0 until 1200) { // at most half an hour of looking
                    delay(1500)
                    val (running, w, _) = runCatching { source.job(id) }.getOrElse { Triple(false, it.message ?: "Lost touch with the tests.", false) }
                    if (!running) { words = w; break }
                }
                ui = ui.copy(testsRunning = false, said = words)
                loadLog()
            }
        },
    )
    BackHandler(ui.opened != null) { a.closeFile() }
    FilesBody(ui, a)
}

@Composable
fun FilesBody(ui: FilesUi, a: FilesActions) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = if (ui.opened != null) a.closeFile else a.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            Column(Modifier.weight(1f)) {
                Text(ui.opened?.data?.name?.ifBlank { null } ?: "Files", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(ui.title, style = MaterialTheme.typography.bodySmall, color = Hall.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (ui.elsewhere == null && ui.opened == null) IconButton(onClick = a.refresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
        }
        when {
            ui.elsewhere != null -> Panel(Modifier.fillMaxWidth().padding(16.dp)) {
                Text("WHERE THE FILES ARE", style = Label, color = Hall.muted)
                Spacer(Modifier.height(6.dp))
                Text(ui.elsewhere, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            }
            ui.opened != null -> Viewer(ui.opened, ui.said, a)
            else -> {
                PrimaryTabRow(selectedTabIndex = ui.tab, containerColor = Color.Transparent, contentColor = Hall.gold) {
                    Tab(ui.tab == 0, { a.tab(0) }, text = { Text("Files") })
                    Tab(ui.tab == 1, { a.tab(1) }, text = { Text("Commands") })
                }
                if (ui.tab == 0) Folder(ui.folder, a) else Commands(ui, a)
            }
        }
    }
}

// -- the folder ---------------------------------------------------------------------------------------
private val ICONS = mapOf("folder" to "📁", "image" to "🖼", "pdf" to "📄", "markdown" to "📝", "csv" to "▦", "json" to "{ }",
    "code" to "</>", "text" to "≡")

@Composable
private fun Folder(folder: Load<FolderView>, a: FilesActions) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        folder.error?.let { e -> item { ErrorLine(e, a.refresh) } }
        val v = folder.data
        if (v == null) { if (folder.loading) item { Loading("Fetching the files…") }; return@LazyColumn }
        item {
            FlowRow(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalArrangement = Arrangement.Center) {
                v.crumbs.forEachIndexed { i, c ->
                    if (i > 0) Text(" / ", color = Hall.muted)
                    val last = i == v.crumbs.lastIndex
                    Text(c.name, color = if (last) Hall.text else Hall.gold, fontWeight = if (last) FontWeight.Bold else null,
                        modifier = if (last) Modifier else Modifier.clickable { a.openDir(c.dir) })
                }
            }
        }
        if (v.items.isEmpty()) item { Text("This folder is empty.", color = Hall.muted, modifier = Modifier.padding(vertical = 16.dp)) }
        items(v.items, key = { it.path }) { it ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { if (it.folder) a.openDir(it.path) else a.openFile(it) }
                .padding(horizontal = 6.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(ICONS[it.kind] ?: "•", Modifier.width(34.dp), color = Hall.muted, fontFamily = FontFamily.Monospace, fontSize = 13.sp)
                Text(it.name, Modifier.weight(1f), color = Hall.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (!it.folder) Text(Files.size(it.size), color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
        if (v.more > 0) item { Text("And ${v.more} more, not shown.", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
        item { Text("Hidden files, keys and Roundtable's own records are never shown.", Modifier.padding(top = 12.dp), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall) }
    }
}

// -- one file -----------------------------------------------------------------------------------------
private const val PHONE_TEXT_MAX = 150_000
private const val PHONE_CSV_ROWS = 200
private const val PHONE_CSV_COLS = 12

@Composable
private fun Viewer(opened: Load<OpenedFile>, said: String?, a: FilesActions) {
    val f = opened.data
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        opened.error?.let { e -> item { ErrorLine(e, a.closeFile) } }
        if (f == null) { if (opened.loading) item { Loading("Opening it…") }; return@LazyColumn }
        item {
            Text(listOf(Files.KIND_WORDS[f.kind] ?: "File", Files.size(f.size), f.file).joinToString(" · "), color = Hall.muted,
                style = MaterialTheme.typography.bodySmall)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (f.kind == "pdf" && f.data != null) Button(onClick = { a.openOutside(f) }) { Text("Open") }
                OutlinedButton(onClick = { a.saveCopy(f) }) { Text("Save a copy") }
            }
            said?.let { Text(it, Modifier.padding(top = 4.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
            if (f.words.isNotBlank()) Text(f.words, Modifier.padding(top = 6.dp), color = Hall.muted, style = MaterialTheme.typography.bodyMedium)
        }
        if (f.too_big) return@LazyColumn
        when (f.kind) {
            "image" -> item { Picture(f) }
            "pdf" -> item { Text("Tap Open to read it with the phone's own PDF viewer.", color = Hall.text) }
            "markdown" -> item { MdBlocks(Markdown.parse(cut(f.text.orEmpty()))) }
            "csv" -> item { Table(f.rows) }
            "json" -> item { JsonView(f.text.orEmpty()) }
            "code", "text" -> {
                val text = cut(f.text.orEmpty())
                val lines = coloured(text, if (f.kind == "code") f.lang else "").lines()
                item { CodeBox(lines) }
                if (text.length < (f.text?.length ?: 0)) item {
                    Text("Only the start is shown here: Save a copy for the rest.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

private fun cut(s: String) = if (s.length > PHONE_TEXT_MAX) s.take(PHONE_TEXT_MAX) else s

@Composable
private fun Picture(f: OpenedFile) {
    val img = remember(f.data) { f.bytes()?.let { b -> runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull() } }
    if (img == null) Text("This picture can't be drawn on the phone (an SVG, or a kind Android doesn't know). Save a copy to open it with another app.",
        color = Hall.muted)
    else Image(img, f.name, Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).border(1.dp, Hall.line, RoundedCornerShape(10.dp)),
        contentScale = ContentScale.FillWidth)
}

@Composable
private fun Table(rows: List<List<String>>) {
    if (rows.isEmpty()) { Text("This table is empty.", color = Hall.muted); return }
    Column(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
        rows.take(PHONE_CSV_ROWS).forEachIndexed { i, row ->
            Row(Modifier.padding(vertical = 3.dp)) {
                row.take(PHONE_CSV_COLS).forEach { cell ->
                    Text(cell, Modifier.width(120.dp).padding(end = 8.dp), style = MaterialTheme.typography.bodySmall, maxLines = 3,
                        overflow = TextOverflow.Ellipsis, fontWeight = if (i == 0) FontWeight.SemiBold else null, color = if (i == 0) Hall.gold else Hall.text)
                }
            }
            if (i == 0) HorizontalDivider(color = Hall.line)
        }
    }
    if (rows.size > PHONE_CSV_ROWS || rows.any { it.size > PHONE_CSV_COLS })
        Text("The phone shows the first $PHONE_CSV_ROWS rows and $PHONE_CSV_COLS columns.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun JsonView(text: String) {
    val root = remember(text) { JsonTree.parse(text) }
    if (root == null) { CodeBox(coloured(cut(text), "json").lines()); return }
    Column(Modifier.fillMaxWidth().background(Hall.code, RoundedCornerShape(10.dp)).padding(10.dp)) { JsonRow(root, 0) }
}

@Composable
private fun JsonRow(n: JsonNode, depth: Int) {
    var open by rememberSaveable { mutableStateOf(depth == 0) }
    val keyPart = n.key?.let { "\"$it\": " }.orEmpty()
    if (n.leaf != null) {
        Text(buildAnnotatedString {
            withStyle(SpanStyle(color = Hall.gold)) { append(keyPart) }
            withStyle(SpanStyle(color = if (n.kind == "string") Hall.good else Hall.warn)) { append(n.leaf) }
        }, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
        return
    }
    Text((if (open) "▾ " else "▸ ") + keyPart + n.summary, Modifier.fillMaxWidth().clickable { open = !open }.padding(vertical = 2.dp),
        color = Hall.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
    if (open) Column(Modifier.padding(start = 14.dp)) { n.kids.forEach { JsonRow(it, depth + 1) } }
}

private fun AnnotatedString.Builder.withStyle(style: SpanStyle, block: AnnotatedString.Builder.() -> Unit) {
    val i = pushStyle(style); block(); pop(i)
}

private fun coloured(text: String, lang: String): AnnotatedString = buildAnnotatedString {
    append(text)
    for (s in CodeColours.spans(text, lang)) addStyle(when (s.part) {
        CodeColours.Part.COMMENT -> SpanStyle(color = Hall.muted, fontStyle = FontStyle.Italic)
        CodeColours.Part.STRING -> SpanStyle(color = Hall.good)
        CodeColours.Part.NUMBER -> SpanStyle(color = Hall.warn)
        CodeColours.Part.KEYWORD -> SpanStyle(color = Hall.gold, fontWeight = FontWeight.Bold)
    }, s.start, s.end)
}

/** An AnnotatedString split into its lines (each keeps its colours). */
private fun AnnotatedString.lines(): List<AnnotatedString> {
    val out = mutableListOf<AnnotatedString>()
    var start = 0
    while (true) {
        val nl = text.indexOf('\n', start)
        if (nl < 0) { out += subSequence(start, text.length); break }
        out += subSequence(start, nl)
        start = nl + 1
    }
    return out
}

@Composable
private fun CodeBox(lines: List<AnnotatedString>) {
    Column(Modifier.fillMaxWidth().background(Hall.code, RoundedCornerShape(10.dp)).border(1.dp, Hall.line, RoundedCornerShape(10.dp)).padding(10.dp)) {
        lines.forEachIndexed { i, line ->
            Row {
                Text("${i + 1}", Modifier.width(34.dp), color = Hall.muted, fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 16.sp)
                Text(line, color = Hall.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 16.sp)
            }
        }
    }
}

// -- the commands -------------------------------------------------------------------------------------
@Composable
private fun Commands(ui: FilesUi, a: FilesActions) {
    val log = ui.log
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        log.error?.let { e -> item { ErrorLine(e, a.refresh) } }
        val v = log.data
        if (v == null) { if (log.loading) item { Loading("Fetching the commands…") }; return@LazyColumn }
        item {
            Panel(Modifier.fillMaxWidth()) {
                Text("COMMANDS IT RAN", style = Label, color = Hall.muted)
                Spacer(Modifier.height(4.dp))
                Text(Files.summary(v) + if (v.commands.isNotEmpty()) " Tap one to see its output." else "", color = Hall.text,
                    style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(10.dp))
                if (v.test_command.isNotBlank()) {
                    Button(onClick = a.runTests, enabled = v.can_run && !ui.testsRunning) {
                        Text(if (ui.testsRunning) "Running the tests…" else "Run the tests")
                    }
                    Text(if (!v.can_run) v.why_not else "Runs the project's own test command: ${v.test_command}", Modifier.padding(top = 4.dp),
                        color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                } else Text(v.why_not, color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                ui.said?.let { Text(it, Modifier.padding(top = 6.dp), color = Hall.text, style = MaterialTheme.typography.bodyMedium) }
            }
        }
        itemsIndexed(v.commands, key = { i, c -> "$i:${c.at}:${c.command}" }) { _, c -> CommandRow(c) }
    }
}

@Composable
private fun CommandRow(c: CommandRun, startOpen: Boolean = false) {
    var open by rememberSaveable(c.at, c.command) { mutableStateOf(startOpen) }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable(onClickLabel = if (open) "Hide the output" else "Show the output") { open = !open }
        .padding(horizontal = 4.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(Files.mark(c), Modifier.width(24.dp), fontWeight = FontWeight.Bold,
                color = when (c.passed) { true -> Hall.good; false -> Hall.bad; null -> Hall.muted })
            Text(c.command.ifBlank { "(no command)" }, Modifier.weight(1f), color = Hall.text, fontFamily = FontFamily.Monospace, fontSize = 13.sp,
                maxLines = if (open) 6 else 1, overflow = TextOverflow.Ellipsis)
            Text(if (open) "▾" else "▸", color = Hall.gold)
        }
        Text(Files.detail(c), Modifier.padding(start = 24.dp), color = Hall.muted, style = MaterialTheme.typography.bodySmall,
            maxLines = if (open) 4 else 1, overflow = TextOverflow.Ellipsis)
        if (open) {
            Spacer(Modifier.height(6.dp))
            if (c.output.isBlank()) Text("No output was kept.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            else Text(c.output.takeLast(PHONE_TEXT_MAX / 10), Modifier.fillMaxWidth().background(TermBg, RoundedCornerShape(10.dp)).padding(10.dp),
                color = TermText, fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 15.sp)
        }
    }
}

private val TermBg = Color(0xFF1B1410)
private val TermText = Color(0xFFF4E8D4)

// -- Save a copy and Open: through the phone's share sheet and its own viewers ---------------------------
/** Shares (or, with [view], opens) a file the screen fetched; returns the words to show. */
fun shareFile(ctx: Context, f: OpenedFile, view: Boolean): String {
    val bytes = f.bytes() ?: return "That file didn't come through. Try again."
    return try {
        val dir = java.io.File(ctx.cacheDir, "shared").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() } // only the newest copy is kept
        val out = java.io.File(dir, Files.safeName(f.name))
        out.writeBytes(bytes)
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", out)
        val mime = Files.mimeOf(f)
        val intent = if (view) Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
        else Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri).putExtra(Intent.EXTRA_TITLE, f.name)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        ctx.startActivity(Intent.createChooser(intent, if (view) "Open ${f.name}" else "Save a copy of ${f.name}")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        ""
    } catch (e: ActivityNotFoundException) {
        "No app on this phone opens this kind of file. Save a copy instead."
    } catch (e: Exception) {
        "That file couldn't be handed over (${e.message ?: "unknown reason"}). Try again."
    }
}

/** The Files screen's source on the PC (PC mode) or Roundtable on this phone: the same API calls. */
class ApiFiles(private val api: Api, private val path: String) : FilesSource {
    override suspend fun list(dir: String) = Files.folder(api.files(path, dir))
    override suspend fun open(file: String) = Files.opened(api.fileOpen(path, file))
    override suspend fun copy(file: String) = Files.opened(api.fileOpen(path, file, copy = true))
    override suspend fun log() = Files.log(api.commandLog(path))
    override suspend fun runTests(): String = Files.jobId(api.runTests(path))
    override suspend fun job(id: String) = Files.job(api.job(id))
}

/** One command row, opened (for pictures in tests). */
@Composable
internal fun CommandRowForTest(c: CommandRun) {
    CommandRow(c, startOpen = true)
}
