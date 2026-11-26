package com.meztking.roundtable.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.net.Pairing
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.hallBackground
import androidx.compose.runtime.remember
import androidx.compose.material3.rememberModalBottomSheetState

const val TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"

@Composable
fun SetupScreen(onDone: () -> Unit, onBack: (() -> Unit)?, vm: SetupViewModel = viewModel()) {
    val ctx = LocalContext.current
    val store = (ctx.applicationContext as RoundtableApp).store
    val state by vm.state.collectAsState()
    var tab by rememberSaveable { mutableIntStateOf(if (store.mode == "pc") 1 else 0) }
    LaunchedEffect(state.done) { if (state.done) { vm.reset(); onDone() } }

    Column(
        Modifier.fillMaxSize().hallBackground().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (onBack != null) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
            TableMark(Modifier.size(36.dp))
            Spacer(Modifier.width(10.dp))
            Column {
                Text("ROUNDTABLE", style = MaterialTheme.typography.titleLarge.copy(letterSpacing = MaterialTheme.typography.titleLarge.fontSize * 0.14f), color = Hall.goldBright)
                Text("See your projects from anywhere", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("Two ways in. The hub on GitHub works even when your PC is off.", color = Hall.text)
        PrimaryTabRow(selectedTabIndex = tab, containerColor = Hall.panel) {
            Tab(tab == 0, { tab = 0; vm.clearError() }, text = { Text("Hub on GitHub") })
            Tab(tab == 1, { tab = 1; vm.clearError() }, text = { Text("Pair with my PC") })
        }
        if (tab == 0) HubForm(vm, state) else PairForm(vm, state)
    }
}

@Composable
private fun HubForm(vm: SetupViewModel, state: SetupViewModel.State) {
    val ctx = LocalContext.current
    val store = (ctx.applicationContext as RoundtableApp).store
    var repo by rememberSaveable { mutableStateOf(store.hubRepo) }
    var token by rememberSaveable { mutableStateOf("") }
    var show by rememberSaveable { mutableStateOf(false) }
    Panel {
        Text("HUB ON GITHUB", style = Label)
        Spacer(Modifier.height(8.dp))
        Text(
            "The app reads your hub repository straight from GitHub: your projects, their status pages, plans and letters. " +
                "It needs a GitHub token that can read and write that one repository.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(10.dp))
        Text("How to make the token", style = MaterialTheme.typography.titleSmall, color = Hall.goldBright)
        Text(
            "1. Open the GitHub page below and sign in.\n" +
                "2. Give it a name, such as \"Roundtable phone\", and an expiry date.\n" +
                "3. Repository access: choose \"Only select repositories\" and pick agent-hub-data.\n" +
                "4. Permissions: Contents: Read and write.\n" +
                "5. Press Generate token, copy it and paste it here.",
            style = MaterialTheme.typography.bodySmall, color = Hall.text,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(TOKEN_URL))) }) {
            Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Open GitHub to make a token")
        }
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            repo, { repo = it }, Modifier.fillMaxWidth(), label = { Text("Hub repository") }, singleLine = true,
            supportingText = { Text("owner/name") },
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false, keyboardType = KeyboardType.Uri),
        )
        OutlinedTextField(
            token, { token = it }, Modifier.fillMaxWidth(), label = { Text("GitHub token") }, singleLine = true,
            placeholder = { Text(if (store.githubToken != null) "Saved. Paste a new one to replace it" else "github_pat_…") },
            visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
            trailingIcon = {
                IconButton(onClick = { show = !show }) {
                    Icon(if (show) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, if (show) "Hide token" else "Show token")
                }
            },
        )
        state.error?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp)) }
        Spacer(Modifier.height(10.dp))
        Button(
            onClick = { vm.checkHub(repo, token.ifBlank { store.githubToken.orEmpty() }) },
            enabled = !state.busy, modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Hall.ink)
            else Text("Check and save")
        }
        Spacer(Modifier.height(6.dp))
        Text("The token is kept encrypted on this phone and only ever sent to GitHub.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun PairForm(vm: SetupViewModel, state: SetupViewModel.State) {
    var link by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var localError by remember { mutableStateOf<String?>(null) }
    val scan = androidx.activity.compose.rememberLauncherForActivityResult(ScanContract()) { r ->
        val text = r.contents ?: return@rememberLauncherForActivityResult
        val offer = Pairing.parse(text)
        if (offer == null) localError = "That QR code isn't a Roundtable pairing code."
        else { localError = null; link = text; vm.pair(offer, offer.code) }
    }
    Panel {
        Text("PAIR WITH MY PC", style = Label)
        Spacer(Modifier.height(8.dp))
        Text(
            "Needs Roundtable Hold 0.7 or later on your PC, with phone access on (Settings > Phone). " +
                "Press Pair a phone there, then scan the code. Away from home, your phone and PC both need Tailscale.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Text("Optional for now: the hub on GitHub works without it.", color = Hall.muted, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(10.dp))
        Button(onClick = {
            scan.launch(ScanOptions().setPrompt("Point at the code on your PC").setBeepEnabled(false)
                .setOrientationLocked(false).setDesiredBarcodeFormats(ScanOptions.QR_CODE))
        }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.QrCodeScanner, null, Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Scan the QR code")
        }
        Spacer(Modifier.height(12.dp))
        Text("Or by hand", style = MaterialTheme.typography.titleSmall, color = Hall.goldBright)
        OutlinedTextField(link, { link = it }, Modifier.fillMaxWidth(), label = { Text("Pairing link (roundtable://pair?…)") },
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, keyboardType = KeyboardType.Uri), maxLines = 3)
        OutlinedTextField(code, { code = it.uppercase().take(8) }, Modifier.fillMaxWidth(), label = { Text("8-letter code") }, singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, autoCorrectEnabled = false))
        (localError ?: state.error)?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp)) }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = {
            val offer = Pairing.parse(link)
            if (offer == null) localError = "Paste the whole pairing link from your PC (it starts with roundtable://pair)."
            else { localError = null; vm.pair(offer, code) }
        }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
            if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Pair")
        }
    }
}
