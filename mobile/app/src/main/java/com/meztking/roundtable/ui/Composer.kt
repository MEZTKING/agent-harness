package com.meztking.roundtable.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.AtWord
import com.meztking.roundtable.data.Caps
import com.meztking.roundtable.data.ComposerDraft
import com.meztking.roundtable.data.ComposerProblem
import com.meztking.roundtable.data.ComposerSender
import com.meztking.roundtable.data.ComposerText
import com.meztking.roundtable.data.Delivery
import com.meztking.roundtable.data.DraftFile
import com.meztking.roundtable.data.DraftStore
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * The message box: one box for a new idea, a note to the planner, a question and a letter. What's written is
 * kept on the phone until it's sent (closing the app keeps it). Photos and files go with it (photos made
 * smaller first), @ picks a file of the project, Speak turns speech into words with the phone's own speech
 * service (offline when the phone has the language), and for a project at work, Next task or Now.
 *
 * Data: data/ComposerData.kt. The PC side: ui/attachapi.py.
 */

/** Drafts live in the app's own files (`drafts/`). */
fun draftStore(context: Context): DraftStore = DraftStore(File(context.filesDir, "drafts"))

/** Where the box sends: Roundtable on this phone, else the paired PC; null when neither is set up (the hub alone
 * can't take pictures). */
fun composerApi(app: RoundtableApp): Api? = when {
    app.store.thisPhone -> app.thisPhoneApi()
    app.store.link != null -> Api(app.store.link!!)
    else -> null
}

fun composerSender(api: Api): ComposerSender = ComposerSender { m, p, b -> api.attach(m, p, b) }

/** What the box shows: everything the stateless [ComposerBox] draws. */
data class ComposerUi(
    val text: TextFieldValue = TextFieldValue(""),
    val files: List<DraftFile> = emptyList(),
    val delivery: Delivery = Delivery.QUEUE,
    val showDelivery: Boolean = false,
    val atFiles: List<String> = emptyList(),
    val sending: Boolean = false,
    val canSpeak: Boolean = true,
    val textless: Boolean = false,
    val saved: Boolean = false,
)

/** The box itself, drawn from [ui] (screenshots use this with made-up states). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ComposerBox(
    ui: ComposerUi,
    thumbs: Map<String, ImageBitmap> = emptyMap(),
    placeholder: String = "Write here…",
    sendLabel: String? = "Send",
    onText: (TextFieldValue) -> Unit = {},
    onPhotos: () -> Unit = {},
    onFiles: () -> Unit = {},
    onSpeak: () -> Unit = {},
    onRemove: (String) -> Unit = {},
    onDelivery: (Delivery) -> Unit = {},
    onAtPick: (String) -> Unit = {},
    onSend: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (!ui.textless) {
            OutlinedTextField(ui.text, onText, Modifier.fillMaxWidth().heightIn(min = 110.dp), placeholder = { Text(placeholder) },
                enabled = !ui.sending)
            if (ui.atFiles.isNotEmpty()) Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Hall.panel).border(1.dp, Hall.line, RoundedCornerShape(10.dp))
                    .padding(4.dp),
            ) {
                Text("FILES IN THE PROJECT", style = Label, modifier = Modifier.padding(6.dp))
                ui.atFiles.take(8).forEach { f ->
                    Text(f, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall, color = Hall.text, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.fillMaxWidth().clickable { onAtPick(f) }.padding(8.dp))
                }
            }
        }
        if (ui.files.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            ui.files.forEach { f -> FileChip(f, thumbs[f.id], onRemove = { onRemove(f.id) }) }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Tip("Add photos from your gallery. Big photos are made smaller first.") {
                OutlinedButton(onPhotos, enabled = !ui.sending) { Text("Photo") }
            }
            Tip("Add any file: a document, a list, a recording.") {
                OutlinedButton(onFiles, enabled = !ui.sending) { Text("File") }
            }
            if (!ui.textless && ui.canSpeak) Tip("Speak instead of typing. Your words appear in the box; nothing is sent until you press the button. " +
                "The phone's own speech service does it, on the phone when it has your language.") {
                OutlinedButton(onSpeak, enabled = !ui.sending) { Text("Speak") }
            }
        }
        if (ui.showDelivery) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("It arrives", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            Delivery.entries.forEach { d ->
                Tip(d.tip) { FilterChip(ui.delivery == d, { onDelivery(d) }, label = { Text(d.label) }) }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (ui.saved) "Draft kept" else "", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.weight(1f))
            if (sendLabel != null) Button(onSend, enabled = !ui.sending && (ui.textless || ui.text.text.isNotBlank()),
                colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                if (ui.sending) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text(sendLabel)
            }
        }
    }
}

@Composable
private fun FileChip(f: DraftFile, thumb: ImageBitmap?, onRemove: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(8.dp)).background(Hall.bgDeep).border(1.dp, Hall.line, RoundedCornerShape(8.dp))
            .padding(start = 6.dp).widthIn(max = 240.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (thumb != null) Image(thumb, null, Modifier.size(32.dp).clip(RoundedCornerShape(4.dp)), contentScale = ContentScale.Crop)
        else Box(Modifier.size(32.dp).clip(RoundedCornerShape(4.dp)).background(Hall.panel), contentAlignment = Alignment.Center) {
            Text(f.name.substringAfterLast('.', "").take(4).uppercase().ifEmpty { "FILE" }, style = Label)
        }
        Column(Modifier.padding(horizontal = 6.dp).weight(1f, fill = false)) {
            Text(f.name, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Hall.text, style = MaterialTheme.typography.bodySmall)
            Text(ComposerText.sizeWords(f.size), color = Hall.muted, style = MaterialTheme.typography.labelSmall)
        }
        TextButton(onRemove, Modifier.semantics { contentDescription = "Remove ${f.name}" }) { Text("✕", color = Hall.muted) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Tip(text: String, content: @Composable () -> Unit) {
    TooltipBox(TooltipDefaults.rememberPlainTooltipPositionProvider(), tooltip = { PlainTooltip { Text(text) } },
        state = rememberTooltipState()) { content() }
}

/**
 * The working box: keeps its draft under [key], adds photos and files, @ from [project] (a project's path on the PC
 * or this phone; null: no @), Speak, Next task or Now ([showDelivery]). [onSend] gets the draft and returns the
 * reply to show; the draft is emptied once it went.
 */
@OptIn(FlowPreview::class)
@Composable
fun Composer(
    key: String,
    onSend: suspend (ComposerDraft, (DraftFile) -> ByteArray) -> String,
    onSent: (String) -> Unit,
    onProblem: (String) -> Unit,
    modifier: Modifier = Modifier,
    sender: ComposerSender? = null,
    project: String? = null,
    placeholder: String = "Write here…",
    sendLabel: String = "Send",
    showDelivery: Boolean = false,
) {
    val context = LocalContext.current
    val store = remember(context) { draftStore(context) }
    val scope = rememberCoroutineScope()
    val first = remember(key) { store.load(key) }
    var ui by remember(key) {
        mutableStateOf(ComposerUi(TextFieldValue(first.text, TextRange(first.text.length)), first.files, Delivery.of(first.mode),
            showDelivery = showDelivery, saved = !first.empty))
    }
    var thumbs by remember(key) { mutableStateOf(mapOf<String, ImageBitmap>()) }
    var at by remember { mutableStateOf<AtWord?>(null) }

    LaunchedEffect(ui.files) { thumbs = withContext(Dispatchers.IO) { ui.files.filter { it.isPicture }.associate { f -> f.id to thumb(store.read(key, f)) }.filterValues { it != null }.mapValues { it.value!! } } }
    LaunchedEffect(key) {  // the draft is kept as it's typed
        snapshotFlow { ui.text.text to ui.delivery }.debounce(400).collect { (t, d) ->
            withContext(Dispatchers.IO) { store.setText(key, t, d) }
            ui = ui.copy(saved = t.isNotBlank() || ui.files.isNotEmpty())
        }
    }
    LaunchedEffect(at?.word, project) {
        val a = at
        ui = ui.copy(atFiles = if (a == null || project == null || sender == null) emptyList()
        else runCatching { sender.files(project, a.word) }.getOrDefault(emptyList()))
    }

    fun add(uris: List<Uri>) = scope.launch {
        for (u in uris) {
            try {
                val d = withContext(Dispatchers.IO) { val (name, mime, bytes) = readUri(context, u); store.addFile(key, name, mime, bytes) }
                ui = ui.copy(files = d.files, saved = true)
            } catch (e: ComposerProblem) { onProblem(e.message ?: "That file couldn't be added.") }
            catch (e: Exception) { onProblem("That file couldn't be read. Try another one.") }
        }
    }
    val photos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(10)) { add(it) }
    val files = rememberLauncherForActivityResult(ActivityResultContracts.GetMultipleContents()) { add(it) }
    val speak = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val said = r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.trim().orEmpty()
        if (said.isNotEmpty()) {
            val t = ui.text.text
            val joined = if (t.isEmpty() || t.endsWith(" ") || t.endsWith("\n")) t + said else "$t $said"
            ui = ui.copy(text = TextFieldValue(joined, TextRange(joined.length)))
        }
    }

    ComposerBox(
        ui, thumbs, placeholder, sendLabel,
        onText = { v -> ui = ui.copy(text = v); at = ComposerText.atWord(v.text, v.selection.start) },
        onPhotos = { photos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
        onFiles = { files.launch("*/*") },
        onSpeak = {
            val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-GB")
                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                .putExtra(RecognizerIntent.EXTRA_PROMPT, "Say your message")
            try { speak.launch(i) } catch (e: ActivityNotFoundException) {
                ui = ui.copy(canSpeak = false); onProblem("This phone has no speech service. Type instead, or add one from the Play Store (Speech Services by Google).")
            }
        },
        onRemove = { id -> scope.launch { val d = withContext(Dispatchers.IO) { store.remove(key, id) }; ui = ui.copy(files = d.files) } },
        onDelivery = { ui = ui.copy(delivery = it) },
        onAtPick = { path ->
            val a = at ?: return@ComposerBox
            val (t, caret) = ComposerText.pick(ui.text.text, a, ui.text.selection.start, path)
            ui = ui.copy(text = TextFieldValue(t, TextRange(caret)), atFiles = emptyList()); at = null
        },
        onSend = {
            scope.launch {
                ui = ui.copy(sending = true)
                try {
                    val d = withContext(Dispatchers.IO) { store.setText(key, ui.text.text, ui.delivery) }
                    val reply = onSend(d) { f -> store.read(key, f) }
                    withContext(Dispatchers.IO) { store.clear(key) }
                    ui = ComposerUi(showDelivery = showDelivery, delivery = ui.delivery)
                    onSent(reply)
                } catch (e: Exception) {
                    ui = ui.copy(sending = false)
                    onProblem(friendly(e))
                }
            }
        },
        modifier = modifier,
    )
}

/** A file picked on the phone: its name, type and bytes; a photo is made smaller (longest side 1568) as a JPEG. */
private fun readUri(context: Context, uri: Uri, caps: Caps = Caps()): Triple<String, String, ByteArray> {
    val cr = context.contentResolver
    var name = "file"
    cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) name = c.getString(0) ?: name }
    val mime = cr.getType(uri) ?: "application/octet-stream"
    val bytes = cr.openInputStream(uri)?.use { it.readBytes() } ?: throw ComposerProblem("That file couldn't be read. Try another one.")
    if (mime == "image/jpeg" || mime == "image/png" || mime == "image/webp" || mime == "image/heic" || mime == "image/heif") {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
        val (w, h) = o.outWidth to o.outHeight
        if (w > 0 && h > 0 && (maxOf(w, h) > caps.maxPx || bytes.size > 1_500_000 || mime.startsWith("image/hei"))) {
            val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = ComposerText.sampleSize(w, h, caps.maxPx) })
                ?: return Triple(name, mime, bytes)
            val (tw, th) = ComposerText.scaled(bmp.width, bmp.height, caps.maxPx)
            val scaled = if (tw != bmp.width) Bitmap.createScaledBitmap(bmp, tw, th, true) else bmp
            val out = ByteArrayOutputStream()
            scaled.compress(Bitmap.CompressFormat.JPEG, 85, out)
            return Triple(name.substringBeforeLast('.') + ".jpg", "image/jpeg", out.toByteArray())
        }
    }
    return Triple(name, mime, bytes)
}

private fun thumb(bytes: ByteArray): ImageBitmap? = runCatching {
    val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = ComposerText.sampleSize(o.outWidth, o.outHeight, 96) })
        ?.asImageBitmap()
}.getOrNull()

/**
 * A new project from an idea, written (or spoken) with photos and files: the planner makes a plan to check
 * before anything is built. Needs your PC or This phone (the hub alone can't take pictures).
 */
@Composable
fun NewIdeaScreen(onBack: () -> Unit, onStarted: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as RoundtableApp
    val api = remember { composerApi(app) }
    val sender = remember(api) { api?.let { composerSender(it) } }
    var notice by remember { mutableStateOf<String?>(null) }
    NewIdeaContent(
        connected = sender != null, notice = notice, onBack = onBack,
        box = {
            Composer(
                key = "new-idea",
                onSend = { d, read -> sender!!.startIdea(d, read) },
                onSent = onStarted,
                onProblem = { notice = it },
                placeholder = "What should be built? Who is it for, what must it do? Add a sketch or a photo if you like.",
                sendLabel = "Make the plan",
            )
        },
    )
}

@Composable
fun NewIdeaContent(connected: Boolean, notice: String?, onBack: () -> Unit, box: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TextButton(onBack) { Text("← Back", color = Hall.muted) }
        Text("New idea", style = MaterialTheme.typography.titleLarge, color = Hall.goldBright)
        Text("Write it, say it, add photos. The planner makes a plan for you to check; nothing is built until you approve it. " +
            "Making the plan costs a little, usually a few cents.", color = Hall.muted)
        if (connected) box()
        else Text("New ideas with photos need your PC or Roundtable on this phone. Connect one in Settings → Connections.", color = Hall.warn)
        if (notice != null) Text(notice, color = Hall.bad)
    }
}
