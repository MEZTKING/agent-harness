package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.Md
import com.meztking.roundtable.data.Note
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Panel

/** My notes: the owner's saved documents in the hub, by title; one opens as readable markdown. */
@Composable
fun NotesScreen(onBack: () -> Unit) {
    val app = LocalContext.current.applicationContext as RoundtableApp
    var tick by remember { mutableIntStateOf(0) }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var list by remember { mutableStateOf(Load<List<Note>>(loading = true)) }
    var text by remember { mutableStateOf(Load<String>()) }
    LaunchedEffect(tick) {
        list = list.copy(loading = true)
        list = runCatching { app.backend()?.notes().orEmpty() }.fold({ Load(it) }, { Load(list.data, error = friendly(it)) })
    }
    LaunchedEffect(open, tick) {
        val name = open ?: return@LaunchedEffect
        text = Load(loading = true)
        text = runCatching { app.backend()?.note(name) }.fold({ if (it == null) Load(error = "That document isn't in the hub any more.") else Load(it) },
            { Load(error = friendly(it)) })
    }
    val note = list.data?.firstOrNull { it.name == open }
    if (open != null) {
        androidx.activity.compose.BackHandler { open = null }
        NoteReader(note?.title ?: open!!, text, onBack = { open = null }, onRefresh = { tick++ })
    } else NotesList(list, onBack = onBack, onRefresh = { tick++ }, onOpen = { open = it.name })
}

@Composable
fun NotesList(notes: Load<List<Note>>, onBack: () -> Unit, onRefresh: () -> Unit, onOpen: (Note) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        TopRow("My notes", onBack, onRefresh)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (notes.error != null) item { ErrorLine(notes.error, onRefresh) }
            val list = notes.data
            when {
                list == null && notes.loading -> item { Loading("Reading your documents…") }
                list.isNullOrEmpty() -> if (notes.error == null) item {
                    Text("No saved documents yet. Documents saved in the hub's notes folder show here.", color = Hall.muted,
                        modifier = Modifier.padding(vertical = 24.dp))
                }
                else -> items(list, key = { it.name }) { n ->
                    Panel(Modifier.fillMaxWidth().clickable { onOpen(n) }) {
                        Text(n.title, color = Hall.text, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

/** One document, as readable markdown: tables and links drawn; a link opens in the browser. */
@Composable
fun NoteReader(title: String, text: Load<String>, onBack: () -> Unit, onRefresh: () -> Unit) {
    val blocks = remember(text.data) { text.data?.let { Markdown.parse(it) }.orEmpty() }
    // the first heading is the title above: don't show it twice
    val body = if ((blocks.firstOrNull() as? Md.Heading)?.text == title) blocks.drop(1) else blocks
    Column(Modifier.fillMaxSize()) {
        TopRow(title, onBack, onRefresh)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp)) {
            if (text.error != null) item { ErrorLine(text.error, onRefresh) }
            if (text.data == null && text.loading) item { Loading("Opening it…") }
            if (body.isNotEmpty()) item { MdBlocks(body) }
        }
    }
}

@Composable
private fun TopRow(title: String, onBack: () -> Unit, onRefresh: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Hall.gold) }
        Spacer(Modifier.width(4.dp))
        Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, color = Hall.goldBright, maxLines = 1, overflow = TextOverflow.Ellipsis)
        IconButton(onClick = onRefresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = Hall.gold) }
    }
}
