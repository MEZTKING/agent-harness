package com.meztking.roundtable.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import com.meztking.roundtable.data.FolderSource
import com.meztking.roundtable.data.PhoneProjects
import com.meztking.roundtable.data.ProjectTooBig
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Harness on this phone, Projects (DS-55): get a repository by its address, bring in a zip or a folder from the
 * phone's Files, and share a project as a zip. Only while the harness on this phone runs.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PhoneProjectsCard(projects: PhoneProjects, names: () -> List<String>, running: Boolean) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by rememberSaveable { mutableStateOf("") }
    var private by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var line by remember { mutableStateOf<String?>(null) }
    var list by remember { mutableStateOf(names()) }

    fun work(start: String, block: suspend () -> String) {
        busy = true; line = start
        scope.launch {
            line = try { block() } catch (e: CancellationException) { throw e } catch (e: ProjectTooBig) { e.message } catch (e: Exception) { friendly(e) }
            busy = false
            list = names()
        }
    }

    val pickZip = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) work("Bringing it in…") {
            val name = PhoneProjects.nameFrom(displayName(ctx, uri) ?: "project")
            val input = withContext(Dispatchers.IO) { ctx.contentResolver.openInputStream(uri) } ?: return@work "That file couldn't be opened. Pick it again."
            val done = withContext(Dispatchers.IO) { projects.import(name, input) }
            "${done.name} is on this phone (${done.files} files)."
        }
    }
    val pickFolder = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
        if (uri != null) work("Bringing the folder in…") {
            val source = TreeSource(ctx, uri)
            val zip = File(ctx.cacheDir, "import-folder.zip")
            withContext(Dispatchers.IO) { zip.outputStream().use { PhoneProjects.zipFolder(source, it) } }
            try {
                val done = withContext(Dispatchers.IO) { projects.import(PhoneProjects.nameFrom(source.root.name), zip.inputStream()) }
                "${done.name} is on this phone (${done.files} files)."
            } finally { zip.delete() }
        }
    }

    Panel(Modifier.fillMaxWidth()) {
        Text("PROJECTS", style = Label)
        Spacer(Modifier.height(8.dp))
        if (!running) {
            Text("Start the harness on this phone to add or share projects.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            return@Panel
        }
        OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), label = { Text("Repository address (https://…)") }, singleLine = true)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(private, { private = it })
            Spacer(Modifier.height(0.dp))
            Text("  Private: use my project key", style = MaterialTheme.typography.bodySmall)
        }
        Text("A private repository uses the project key saved in Keys, never the hub's.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(6.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { work("Getting it…") { val d = projects.clone(url, useKey = private); url = ""; "${d.name} is on this phone." } },
                enabled = !busy && url.startsWith("https://"),
                colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) { Text("Get it") }
            OutlinedButton(onClick = { pickZip.launch(arrayOf("application/zip", "application/x-zip-compressed", "application/octet-stream")) }, enabled = !busy) { Text("Import a zip") }
            OutlinedButton(onClick = { pickFolder.launch(null) }, enabled = !busy) { Text("Import a folder") }
        }
        line?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Hall.muted) }
        if (list.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text("Share a project as a zip (without the harness's own files or anything that looks like a key):", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (n in list) TextButton(onClick = { work("Packing $n…") { shareProject(ctx, projects, n) } }, enabled = !busy) { Text(n) }
            }
        }
    }
}

private suspend fun shareProject(ctx: Context, projects: PhoneProjects, name: String): String {
    val dir = File(ctx.cacheDir, "shared").apply { mkdirs() }
    dir.listFiles()?.forEach { it.delete() }
    val out = File(dir, PhoneProjects.nameFrom(name).ifBlank { "project" } + ".zip")
    withContext(Dispatchers.IO) { projects.share(name, out.outputStream()) }
    val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", out)
    val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    ctx.startActivity(Intent.createChooser(send, "Share $name").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    return ""
}

private fun displayName(ctx: Context, uri: Uri): String? = runCatching {
    ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
}.getOrNull()

/** A folder picked with the phone's Files (the Storage Access Framework), walked with DocumentsContract. */
private class TreeSource(private val ctx: Context, private val tree: Uri) : FolderSource {
    override val root: FolderSource.Node = run {
        val id = DocumentsContract.getTreeDocumentId(tree)
        val name = runCatching {
            ctx.contentResolver.query(DocumentsContract.buildDocumentUriUsingTree(tree, id), arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null }
        }.getOrNull() ?: "project"
        FolderSource.Node(id, name, true)
    }

    override fun children(node: FolderSource.Node): List<FolderSource.Node> {
        val uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, node.id)
        val cols = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE)
        return ctx.contentResolver.query(uri, cols, null, null, null)?.use { c ->
            buildList { while (c.moveToNext()) add(FolderSource.Node(c.getString(0), c.getString(1) ?: "", c.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR)) }
        }.orEmpty()
    }

    override fun open(node: FolderSource.Node) =
        ctx.contentResolver.openInputStream(DocumentsContract.buildDocumentUriUsingTree(tree, node.id)) ?: throw java.io.IOException("That file couldn't be opened.")
}
