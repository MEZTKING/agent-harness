package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import kotlinx.coroutines.launch

/** Where the owner gets a key and tops up, opened in the app's own browser. */
const val DEEPSEEK_KEYS_PAGE = "https://platform.deepseek.com/api_keys"
const val DEEPSEEK_TOP_UP_PAGE = "https://platform.deepseek.com/top_up"

/** What Save and check found, in words. "" (the key works) → null. */
fun keyCheckWords(why: String): String? = when (why) {
    "" -> null
    "key_refused" -> Words.t("DeepSeek refused that key. Copy it again from DeepSeek's page and paste it here.")
    "no_credit" -> Words.t("The key works, but the DeepSeek account is empty. Top it up, then the chat answers here.")
    else -> Words.t("No internet just now. The key is saved; it's checked again with your next message.")
}

/**
 * The DeepSeek key form (Hub mode's own answers): one field, Save and check, where to get one. The key goes only into
 * the phone's locked store ([onSave]); the field hides it and can't be copied, and afterwards only its last four
 * characters show. "Remove key" takes it away; "Use it for This phone too" hands it to This phone's harness only on a tap.
 *
 * [check] runs DeepSeek's free balance check with a key and gives its reason ("" when it works).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatKeyCard(
    keyEnd: String?,
    onSave: (String) -> Unit,
    onRemove: () -> Unit,
    check: suspend (String) -> String,
    onOpenPage: (String) -> Unit = {},
    onToThisPhone: (suspend () -> Unit)? = null,
    onClose: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    // never rememberSaveable: the key must not go into the screen's saved state
    var typed by remember { mutableStateOf("") }
    var checking by remember { mutableStateOf(false) }
    var said by remember { mutableStateOf<String?>(null) }
    Panel(Modifier.fillMaxWidth()) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(Words.t("YOUR DEEPSEEK KEY"), style = Label, color = Hall.muted)
            Text(Words.t("With a key, this phone answers the chat itself when your PC is off: about a tenth of a cent a message, " +
                "at most \$1 a day."), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            if (keyEnd != null) Text(Words.t("Saved: the key ending {end}.", "end" to keyEnd), color = Hall.text, style = MaterialTheme.typography.bodyMedium)
            OutlinedTextField(typed, { typed = it.trim(); said = null }, Modifier.fillMaxWidth(), singleLine = true,
                label = { Text(if (keyEnd == null) Words.t("Paste your DeepSeek key") else Words.t("Paste a new key")) },
                visualTransformation = PasswordVisualTransformation(), // also stops it being copied or cut
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false))
            said?.let { Text(it, color = Hall.muted, style = MaterialTheme.typography.bodySmall) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Button({
                    val k = typed
                    scope.launch {
                        checking = true
                        val why = runCatching { check(k) }.getOrDefault("offline")
                        checking = false
                        if (why == "key_refused") { said = keyCheckWords(why); return@launch }
                        onSave(k)
                        typed = ""
                        said = keyCheckWords(why) ?: Words.t("Saved and checked: it works.")
                    }
                }, enabled = typed.length >= 8 && !checking, colors = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
                    if (checking) CircularProgressIndicator(strokeWidth = 2.dp) else Text(Words.t("Save and check"))
                }
                OutlinedButton({ onOpenPage(DEEPSEEK_KEYS_PAGE) }) { Text(Words.t("Get a key")) }
                if (keyEnd != null) OutlinedButton({ onRemove(); said = Words.t("Removed. If you lost the phone, delete the key on DeepSeek's page too.") }) {
                    Text(Words.t("Remove key"))
                }
                if (keyEnd != null && onToThisPhone != null) TextButton({ scope.launch {
                    said = runCatching { onToThisPhone(); Words.t("This phone's harness has the key too.") }
                        .getOrElse { Words.t("This phone's harness didn't take it. Start it in Settings, then try again.") }
                } }) { Text(Words.t("Use it for This phone too")) }
                TextButton(onClose) { Text(Words.t("Done")) }
            }
        }
    }
}
