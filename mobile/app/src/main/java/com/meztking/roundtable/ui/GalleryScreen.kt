package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.GalleryEntry
import com.meztking.roundtable.data.GalleryList
import com.meztking.roundtable.data.GalleryTile
import com.meztking.roundtable.data.KindInfo
import com.meztking.roundtable.data.Kinds
import com.meztking.roundtable.data.KindsList
import com.meztking.roundtable.data.PcBackend
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.launch

/**
 * The Gallery: everything finished, and what Roundtable can make. It reads the PC (or this phone's
 * Roundtable). Hiding never deletes; there is no delete. [onOpenProject] gets a project's folder path;
 * [onStart] gets the kind's id and an example idea (empty for none) for a new project.
 */
@Composable
fun GalleryScreen(onBack: () -> Unit, onOpenProject: (String) -> Unit = {}, onStart: (String, String) -> Unit = { _, _ -> }) {
    val app = LocalContext.current.applicationContext as RoundtableApp
    val api: Api? = remember(app.backend()) {
        val parts = app.backend()?.parts.orEmpty()
        (parts[Source.PC] as? PcBackend)?.api ?: (parts[Source.PHONE] as? PcBackend)?.api
    }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var tick by remember { mutableIntStateOf(0) }
    var list by remember { mutableStateOf(Load<GalleryList>()) }
    var kinds by remember { mutableStateOf(Load<KindsList>()) }
    var open by remember { mutableStateOf<GalleryTile?>(null) }
    LaunchedEffect(tab, tick, api) {
        if (api == null) return@LaunchedEffect
        if (tab == 0) {
            list = list.copy(loading = true)
            list = runCatching { Kinds.parseGallery(api.feature("GET", Kinds.galleryPath())) }
                .fold({ Load(it) }, { Load(list.data, error = friendly(it)) })
        } else {
            kinds = kinds.copy(loading = true)
            kinds = runCatching { Kinds.parseList(api.feature("GET", "/api/kinds")) }
                .fold({ Load(it) }, { Load(kinds.data, error = friendly(it)) })
        }
    }
    val showing = open
    if (showing != null && api != null) {
        androidx.activity.compose.BackHandler { open = null }
        GalleryEntryScreen(api, showing, onBack = { open = null; tick++ }, onOpenProject = onOpenProject)
        return
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp)) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            Text("Gallery", Modifier.padding(top = 10.dp), style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        }
        TabRow(selectedTabIndex = tab) {
            Tab(tab == 0, { tab = 0 }, text = { Text("Finished") })
            Tab(tab == 1, { tab = 1 }, text = { Text("What it can make") })
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (api == null) {
                item { Text("The Gallery needs your PC, or Roundtable on this phone. Connect one in Settings.", color = Hall.muted) }
                return@LazyColumn
            }
            if (tab == 0) {
                list.error?.let { e -> item { ErrorLine(e) { tick++ } } }
                val d = list.data
                if (d == null && list.loading) item { Loading("Opening the Gallery…") }
                if (d != null) {
                    if (d.entries.isEmpty()) item { Text(d.words, color = Hall.muted) }
                    items(d.entries, key = { "${it.project}/${it.goal}" }) { t -> Tile(t) { open = t } }
                }
            } else {
                kinds.error?.let { e -> item { ErrorLine(e) { tick++ } } }
                val d = kinds.data
                if (d == null && kinds.loading) item { Loading("Reading the kinds…") }
                if (d != null) {
                    item { Text(d.words, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                    d.groups.forEach { g ->
                        item(key = "g-${g.group}") { Text(g.group, color = Hall.goldBright, style = MaterialTheme.typography.titleMedium) }
                        items(g.kinds, key = { "k-${it.id}" }) { k -> KindTile(k, onStart) }
                    }
                }
            }
        }
    }
}

@Composable
private fun DataImage(src: String, label: String, modifier: Modifier) {
    val bmp = remember(src) { Kinds.pictureBytes(src)?.let { runCatching { BitmapFactory.decodeByteArray(it, 0, it.size) }.getOrNull() } }
    if (bmp != null) Image(bmp.asImageBitmap(), label, modifier, contentScale = ContentScale.Crop)
    else Box(modifier) { Text("No picture", Modifier.padding(12.dp), color = Hall.muted) }
}

@Composable
private fun Tile(t: GalleryTile, onOpen: () -> Unit) {
    Panel(Modifier.fillMaxWidth().clickable(onClickLabel = "Open") { onOpen() }) {
        DataImage(t.cover, t.title, Modifier.fillMaxWidth().aspectRatio(16f / 10f))
        Spacer(Modifier.height(6.dp))
        Text((if (t.starred) "★ " else "") + t.title, color = Hall.text, style = MaterialTheme.typography.titleSmall,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(listOf(t.kindName, t.line).filter { it.isNotBlank() }.joinToString(" · "), color = Hall.muted,
            style = MaterialTheme.typography.bodySmall)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun KindTile(k: KindInfo, onStart: (String, String) -> Unit) {
    Panel(Modifier.fillMaxWidth()) {
        Row { Text(k.name, Modifier.weight(1f), color = Hall.text, style = MaterialTheme.typography.titleSmall); KindStatus(k.status, k.statusWords) }
        Text(k.blurb, color = Hall.text, style = MaterialTheme.typography.bodyMedium)
        if (k.typical.isNotBlank()) Text("Usually ${k.typical}", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        if (k.missing.isNotEmpty()) Text("Needs ${k.missing.joinToString(" and ")} on the PC: install it from the Tools page there.",
            color = Hall.warn, style = MaterialTheme.typography.bodySmall)
        if (k.usable) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                k.examples.forEach { ex -> TextButton(onClick = { onStart(k.id, ex) }) { Text(ex, style = MaterialTheme.typography.bodySmall) } }
            }
            Button(onClick = { onStart(k.id, "") }) { Text("Start one") }
        }
        Fold("More") {
            k.proof.forEach { p ->
                Text("• ${p.words}" + if (p.notYet) " (not checked yet)" else if (p.optional) " (when there are tests)" else "",
                    color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun GalleryEntryScreen(api: Api, tile: GalleryTile, onBack: () -> Unit, onOpenProject: (String) -> Unit) {
    var entry by remember { mutableStateOf(Load<GalleryEntry>(loading = true)) }
    var tick by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(tick) {
        entry = runCatching { Kinds.parseEntry(api.feature("GET", Kinds.entryPath(tile.project, tile.goal))) ?: error("That entry couldn't be read.") }
            .fold({ Load(it) }, { Load(error = friendly(it)) })
    }
    fun flag(key: String, value: Boolean) = scope.launch {
        runCatching { api.feature("POST", "/api/gallery/${if (key == "hidden") "hide" else "star"}", Kinds.flagBody(tile.project, tile.goal, key, value)) }
        if (key == "hidden" && value) onBack() else tick++
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp)) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the Gallery", tint = Hall.gold) }
            Text(tile.title, Modifier.padding(top = 10.dp), style = MaterialTheme.typography.titleLarge, color = Hall.goldBright,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            entry.error?.let { e -> item { ErrorLine(e) { tick++ } } }
            val e = entry.data
            if (e == null && entry.loading) item { Loading("Opening it…") }
            if (e != null) {
                item { Text(listOf(e.kindName, e.line).filter { it.isNotBlank() }.joinToString(" · "), color = Hall.muted) }
                if (e.summary.isNotBlank()) item { Text(e.summary, color = Hall.text) }
                items(e.pictures, key = { it.name }) { p -> DataImage(p.src, p.name, Modifier.fillMaxWidth().aspectRatio(16f / 10f)) }
                item { Text(e.proofWords.ifBlank { Kinds.proofWords(e.proof) }, color = Hall.text, style = MaterialTheme.typography.bodyMedium) }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { onOpenProject(e.path) }) { Text("Open the project") }
                        OutlinedButton(onClick = { flag("starred", !e.starred) }) { Text(if (e.starred) "Unstar" else "Star") }
                        OutlinedButton(onClick = { flag("hidden", !e.hidden) }) { Text(if (e.hidden) "Show again" else "Hide") }
                    }
                }
                item { Text("Hiding keeps it: nothing is ever deleted here.", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                item {
                    Fold("More") {
                        e.more.models.forEach { m -> Text("${m.task} ${m.role}: ${m.model}", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                        e.outputs.forEach { o -> Text("Made: ${o.path}", color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                        if (e.more.commit.isNotBlank()) Text("Version ${e.more.commit.take(10)}", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

