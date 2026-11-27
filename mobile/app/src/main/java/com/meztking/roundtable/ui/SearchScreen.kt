package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.FilePeek
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.PcBackend
import com.meztking.roundtable.data.Search
import com.meztking.roundtable.data.SearchHit
import com.meztking.roundtable.data.SearchResult
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.delay

/** What a tapped hit shows on the phone itself: the file around the words, a memory, or a saved note. */
sealed interface Opened {
    data class File(val peek: FilePeek) : Opened
    data class Text(val title: String, val markdown: String, val words: String = "") : Opened
}

/**
 * Search everything on your PC (or on this phone's Roundtable): plans, tasks, the journal, letters, memory, notes
 * and project files. [onOpen] takes a hit that belongs on another screen (a project's plan or journal, Letters) and
 * returns true when it opened it; anything else (files, memory, notes, or when it returns false) opens here.
 */
@Composable
fun SearchScreen(onBack: () -> Unit, onOpen: (SearchHit) -> Boolean = { false }) {
    val app = LocalContext.current.applicationContext as RoundtableApp
    val api: Api? = remember(app.backend()) {
        val parts = app.backend()?.parts.orEmpty()
        (parts[Source.PC] as? PcBackend)?.api ?: (parts[Source.PHONE] as? PcBackend)?.api
    }
    var query by rememberSaveable { mutableStateOf("") }
    var place by rememberSaveable { mutableIntStateOf(0) }
    var tick by remember { mutableIntStateOf(0) }
    var result by remember { mutableStateOf(Load<SearchResult>()) }
    var openHit by remember { mutableStateOf<SearchHit?>(null) }
    var opened by remember { mutableStateOf(Load<Opened>()) }
    LaunchedEffect(query, place, tick) {
        if (api == null || query.isBlank()) { result = Load(); return@LaunchedEffect }
        delay(350) // wait for a pause in typing
        result = result.copy(loading = true)
        result = runCatching { Search.parse(api.search(query.trim(), Search.places[place].second)) }
            .fold({ Load(it) }, { Load(result.data, error = friendly(it)) })
    }
    LaunchedEffect(openHit) {
        val hit = openHit ?: return@LaunchedEffect
        val o = hit.open
        opened = Load(loading = true)
        opened = runCatching<Opened> {
            when (o.room) {
                "file" -> Opened.File(Search.parsePeek(api!!.peek(o.path, o.file, o.line)))
                "memory" -> Search.parseMemory(api!!.memory(o.path, o.machine, o.archive)).let {
                    Opened.Text("${it.where.ifBlank { hit.where }}: memory", it.markdown, it.words)
                }
                "note" -> Opened.Text(hit.title, app.backend()?.note(o.name) ?: "That note isn't in the hub any more.")
                else -> Opened.Text(hit.title, hit.snippet, hit.where)
            }
        }.fold({ Load(it) }, { Load(error = friendly(it)) })
    }
    val showing = openHit
    if (showing != null) {
        androidx.activity.compose.BackHandler { openHit = null }
        SearchOpened(showing, opened, onBack = { openHit = null })
        return
    }
    SearchView(query, { query = it }, place, { place = it }, result, available = api != null, onBack = onBack,
        onRetry = { tick++ }, onHit = { hit -> if (!onOpen(hit)) openHit = hit })
}

@Composable
fun SearchView(
    query: String, onQuery: (String) -> Unit, place: Int, onPlace: (Int) -> Unit, result: Load<SearchResult>,
    available: Boolean, onBack: () -> Unit, onRetry: () -> Unit, onHit: (SearchHit) -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
            Spacer(Modifier.width(4.dp))
            Text("Search", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        }
        OutlinedTextField(query, onQuery, Modifier.fillMaxWidth().padding(horizontal = 16.dp), singleLine = true,
            enabled = available, placeholder = { Text("What are you looking for?") },
            leadingIcon = { Icon(Icons.Filled.Search, null, tint = Hall.muted) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { onRetry() }))
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Search.places.forEachIndexed { i, (label, _, _) -> FilterChip(place == i, { onPlace(i) }, label = { Text(label) }) }
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (!available) {
                item { Text("Search needs your PC, or the harness on this phone. Connect one in Settings.", color = Hall.muted,
                    modifier = Modifier.padding(vertical = 24.dp)) }
                return@LazyColumn
            }
            if (result.error != null) item { ErrorLine(result.error, onRetry) }
            val r = result.data
            when {
                query.isBlank() -> item { Text("Type a word or two. \"Quoted words\" must be together.", color = Hall.muted,
                    modifier = Modifier.padding(vertical = 12.dp)) }
                r == null && result.loading -> item { Loading("Looking…") }
                r != null -> {
                    item { Text(r.words, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
                    items(r.hits, key = { "${it.kind}|${it.where}|${it.title}|${it.open.id}|${it.open.file}|${it.open.task}" }) { hit ->
                        HitCard(hit, query, onHit)
                    }
                }
            }
        }
    }
}

@Composable
private fun HitCard(hit: SearchHit, query: String, onHit: (SearchHit) -> Unit) {
    Panel(Modifier.fillMaxWidth().clickable { onHit(hit) }) {
        Text(marked(hit.title, query), color = Hall.text, style = MaterialTheme.typography.titleSmall, maxLines = 2,
            overflow = TextOverflow.Ellipsis)
        Text(hit.where, color = Hall.muted, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (hit.snippet.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(marked(hit.snippet, query), color = Hall.text, style = MaterialTheme.typography.bodyMedium, maxLines = 4,
                overflow = TextOverflow.Ellipsis)
        }
    }
}

/** The text with the searched words marked. */
@Composable
fun marked(text: String, query: String): AnnotatedString {
    val style = SpanStyle(background = Hall.gold.copy(alpha = 0.30f), fontWeight = FontWeight.SemiBold)
    return buildAnnotatedString {
        var i = 0
        for ((s, e) in Search.marks(text, query)) {
            append(text.substring(i, s))
            pushStyle(style); append(text.substring(s, e)); pop()
            i = e
        }
        append(text.substring(i))
    }
}

@Composable
fun SearchOpened(hit: SearchHit, opened: Load<Opened>, onBack: () -> Unit) {
    val o = opened.data
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to the results", tint = Hall.gold) }
            Spacer(Modifier.width(4.dp))
            Text(if (o is Opened.Text) o.title else hit.title, Modifier.weight(1f), style = MaterialTheme.typography.titleLarge,
                color = Hall.goldBright, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { Text(hit.where, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
            if (opened.error != null) item { ErrorLine(opened.error) { onBack() } }
            if (o == null && opened.loading) item { Loading("Opening it…") }
            when (o) {
                is Opened.File -> {
                    if (o.peek.words.isNotBlank()) item { Text(o.peek.words, color = Hall.muted) }
                    items(o.peek.lines.size) { i ->
                        val n = o.peek.from + i
                        Text("${n.toString().padStart(4)}  ${o.peek.lines[i]}", fontFamily = com.meztking.roundtable.ui.theme.Mono, fontSize = 12.sp,
                            color = if (n == o.peek.line) Hall.goldBright else Hall.text,
                            fontWeight = if (n == o.peek.line) FontWeight.Bold else FontWeight.Normal)
                    }
                }
                is Opened.Text -> {
                    if (o.words.isNotBlank() && o.words != hit.where) item { Text(o.words, color = Hall.muted) }
                    item { MdBlocks(Markdown.parse(o.markdown)) }
                }
                null -> {}
            }
            item { TextButton(onClick = onBack) { Text("Back to the results", color = Hall.gold) } }
        }
    }
}
