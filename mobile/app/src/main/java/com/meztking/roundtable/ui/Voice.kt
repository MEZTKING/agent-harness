package com.meztking.roundtable.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import java.util.Locale

/**
 * The phone's own voice (Android's text to speech, British English where the phone has it). Made on first use and
 * shut when the screen goes. [say] calls [then] on the main thread once it has finished speaking.
 */
class Voice(private val context: Context) {
    private var tts: TextToSpeech? = null
    private var ready = false
    private var waiting: Pair<String, (() -> Unit)?>? = null
    private val after = mutableMapOf<String, () -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    fun say(text: String, then: (() -> Unit)? = null) {
        if (text.isBlank()) { then?.invoke(); return }
        if (tts == null) TextToSpeech(context.applicationContext) { status ->
            ready = status == TextToSpeech.SUCCESS
            if (ready) {
                tts?.language = if (tts?.isLanguageAvailable(Locale.UK) ?: TextToSpeech.LANG_NOT_SUPPORTED >= 0) Locale.UK else Locale.getDefault()
                waiting?.let { (w, th) -> waiting = null; speak(w, th) }
            } else waiting?.second?.let { main.post(it) }
        }.also { made ->
            tts = made
            made.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(id: String?) {}
                override fun onDone(id: String?) { after.remove(id)?.let { main.post(it) } }
                @Deprecated("Deprecated in Java") override fun onError(id: String?) { after.remove(id)?.let { main.post(it) } }
            })
        }
        if (ready) speak(text, then) else waiting = text to then
    }

    private fun speak(text: String, then: (() -> Unit)?) {
        val id = "say-" + System.nanoTime()
        if (then != null) after[id] = then
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
    }

    fun stop() { tts?.stop() }

    fun shut() { tts?.shutdown(); tts = null; ready = false }
}

/** The phone's voice for one screen, shut when the screen goes. */
@Composable
fun rememberVoice(): Voice {
    val ctx = LocalContext.current
    val v = remember(ctx) { Voice(ctx) }
    DisposableEffect(v) { onDispose { v.shut() } }
    return v
}

/** Listening with Android's own speech recogniser: call the result to start; [onHeard] gets the words (nothing when
 * the owner said nothing), [onNone] when the phone has no speech service. */
@Composable
fun rememberListener(prompt: String, onHeard: (String) -> Unit, onNone: () -> Unit): () -> Unit {
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val said = r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.trim().orEmpty()
        if (said.isNotEmpty()) onHeard(said)
    }
    return {
        val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-GB")
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            .putExtra(RecognizerIntent.EXTRA_PROMPT, prompt)
        try { launcher.launch(i) } catch (_: ActivityNotFoundException) { onNone() }
    }
}
