// The WebView's settings and the way it refuses other apps' links follow DSH Mobile's Browser tab
// (MIT License, Copyright (c) 2026 DSH Mobile contributors), app/src/main/java/com/labteto/dshmobile/ui/screens/main/
// browser/BrowserView.kt. See THIRD_PARTY_NOTICES.md. The screen itself is the app's own.
package com.meztking.roundtable.ui.browser

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.net.http.SslError
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.meztking.roundtable.data.browser.AddressInput
import com.meztking.roundtable.data.browser.AddressRefusal
import com.meztking.roundtable.data.browser.BrowserConnection
import com.meztking.roundtable.data.browser.BrowserReach
import com.meztking.roundtable.data.browser.browserReach
import com.meztking.roundtable.data.browser.parseBrowserAddress
import com.meztking.roundtable.data.browser.reachWords
import com.meztking.roundtable.ui.theme.hallBackground
import com.meztking.roundtable.ui.theme.Hall

/** What the address bar's value means: a page to load, or the plain words why not (and maybe a page to offer). */
sealed interface BrowserGo {
    data class Load(val url: String) : BrowserGo
    data class Stop(val words: String, val offer: String? = null) : BrowserGo
}

/** The address bar's rule, pure so it is tested: what [input] does on [connection]. */
fun browserGo(input: String, connection: BrowserConnection): BrowserGo {
    val parsed = parseBrowserAddress(input, toAscii = { runCatching { java.net.IDN.toASCII(it) }.getOrNull() })
    val address = when (parsed) {
        is AddressInput.Web -> parsed.address
        is AddressInput.Refused -> return BrowserGo.Stop(when (parsed.reason) {
            AddressRefusal.Empty -> "Type an address, for example localhost:5173."
            AddressRefusal.TooLong -> "That address is too long."
            AddressRefusal.Credentials -> "Addresses with a name or password in them aren't opened here."
            AddressRefusal.UnsupportedScheme -> "Only web pages (http and https) open here."
            AddressRefusal.Invalid -> "That isn't an address the browser can open. Check it and try again."
        })
    }
    val reach = browserReach(address, connection)
    return when (reach) {
        BrowserReach.Open -> BrowserGo.Load(address.url)
        is BrowserReach.PcLoopback -> BrowserGo.Stop(reachWords(reach)!!, reach.onPcAddress)
        BrowserReach.PcItself -> BrowserGo.Stop(reachWords(reach)!!)
    }
}

/**
 * The Browser tab (DS-81): an address bar, back, forward, reload or stop, Open in browser, Copy link and Clear site
 * data. View only: pages get no access to the app (no bridge, no files, no other apps' links), and the PC's own
 * `localhost` is never loaded as the phone's. [mentioned] are local addresses the agent printed, offered by a tap.
 */
@OptIn(ExperimentalLayoutApi::class)
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun BrowserScreen(initial: String?, connection: BrowserConnection, mentioned: List<String>, onBack: () -> Unit) {
    val ctx = LocalContext.current
    var field by rememberSaveable { mutableStateOf(initial.orEmpty()) }
    var url by rememberSaveable { mutableStateOf<String?>(null) }
    var title by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var canBack by remember { mutableStateOf(false) }
    var canForward by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    var offer by remember { mutableStateOf<String?>(null) }
    var menu by remember { mutableStateOf(false) }
    val view = remember { mutableStateOf<WebView?>(null) }

    fun go(input: String) {
        when (val g = browserGo(input, connection)) {
            is BrowserGo.Load -> { problem = null; offer = null; url = g.url; field = g.url; view.value?.loadUrl(g.url) }
            is BrowserGo.Stop -> { problem = g.words; offer = g.offer }
        }
    }

    DisposableEffect(Unit) {
        if (!initial.isNullOrBlank() && url == null) go(initial)
        onDispose { view.value?.apply { stopLoading(); destroy() }; view.value = null }
    }

    Column(Modifier.fillMaxSize().hallBackground().safeDrawingPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.Filled.Close, "Close the browser") }
            OutlinedTextField(field, { field = it }, Modifier.weight(1f), singleLine = true, placeholder = { Text("localhost:5173") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go), keyboardActions = KeyboardActions(onGo = { go(field) }))
            Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Open in browser") }, leadingIcon = { Icon(Icons.AutoMirrored.Filled.OpenInNew, null) }, enabled = url != null, onClick = {
                        menu = false
                        url?.let { runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } }
                    })
                    DropdownMenuItem({ Text("Copy link") }, leadingIcon = { Icon(Icons.Filled.ContentCopy, null) }, enabled = url != null, onClick = {
                        menu = false
                        val cm = ctx.getSystemService(android.content.ClipboardManager::class.java)
                        url?.let { cm?.setPrimaryClip(ClipData.newPlainText("Link", it)) }
                    })
                    DropdownMenuItem({ Text("Clear site data") }, onClick = {
                        menu = false
                        CookieManager.getInstance().removeAllCookies(null); WebStorage.getInstance().deleteAllData(); view.value?.clearCache(true)
                    })
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { view.value?.goBack() }, enabled = canBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back a page") }
            IconButton(onClick = { view.value?.goForward() }, enabled = canForward) { Icon(Icons.AutoMirrored.Filled.ArrowForward, "Forward a page") }
            IconButton(onClick = { if (loading) view.value?.stopLoading() else view.value?.reload() }, enabled = url != null) {
                Icon(if (loading) Icons.Filled.Close else Icons.Filled.Refresh, if (loading) "Stop" else "Reload")
            }
            Text(title, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Hall.gold)
        problem?.let { p ->
            Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text(p, color = Hall.ember, style = MaterialTheme.typography.bodyMedium)
                offer?.let { o -> TextButton(onClick = { go(o) }) { Text("Try $o") } }
            }
        }
        if (url == null && mentioned.isNotEmpty()) Column(Modifier.padding(12.dp)) {
            Text("Pages the agent mentioned:", style = MaterialTheme.typography.bodySmall, color = Hall.muted)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) { for (m in mentioned) TextButton(onClick = { go(m) }) { Text(m) } }
        }
        AndroidView(modifier = Modifier.fillMaxWidth().weight(1f), factory = { c ->
            WebView(c).apply {
                with(settings) {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    allowFileAccess = false
                    allowContentAccess = false
                    @Suppress("DEPRECATION") allowFileAccessFromFileURLs = false
                    @Suppress("DEPRECATION") allowUniversalAccessFromFileURLs = false
                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    setGeolocationEnabled(false)
                    javaScriptCanOpenWindowsAutomatically = false
                    setSupportMultipleWindows(false)
                    mediaPlaybackRequiresUserGesture = true
                    builtInZoomControls = true
                    displayZoomControls = false
                    useWideViewPort = true
                    loadWithOverviewMode = true
                    safeBrowsingEnabled = true
                }
                CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
                setDownloadListener { _, _, _, _, _ -> problem = "Downloads aren't saved from here. Use Open in browser to download it." }
                webChromeClient = object : WebChromeClient() {
                    override fun onReceivedTitle(v: WebView?, t: String?) { title = t.orEmpty() }
                }
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(v: WebView?, request: WebResourceRequest?): Boolean {
                        val u = request?.url ?: return true
                        val scheme = u.scheme?.lowercase()
                        if (scheme != "http" && scheme != "https") return true // another app's link: never followed from a page
                        if (!request.isForMainFrame) return false
                        return when (val g = browserGo(u.toString(), connection)) {
                            is BrowserGo.Load -> false
                            is BrowserGo.Stop -> { problem = g.words; offer = g.offer; true }
                        }
                    }
                    override fun onPageStarted(v: WebView?, u: String?, favicon: android.graphics.Bitmap?) {
                        loading = true; problem = null; u?.let { url = it; field = it }
                        canBack = v?.canGoBack() == true; canForward = v?.canGoForward() == true
                    }
                    override fun onPageFinished(v: WebView?, u: String?) {
                        loading = false; canBack = v?.canGoBack() == true; canForward = v?.canGoForward() == true
                    }
                    override fun onReceivedError(v: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                        if (request?.isForMainFrame != true) return
                        loading = false
                        problem = "The page didn't answer. Is it running? Check the address, then press Reload."
                    }
                    override fun onRenderProcessGone(v: WebView?, detail: android.webkit.RenderProcessGoneDetail?): Boolean {
                        // the default would close the whole app; this page's view is gone, the app stays
                        if (view.value === v) view.value = null
                        loading = false
                        problem = "The page stopped working. Close the browser and open it again."
                        return true
                    }
                    override fun onReceivedSslError(v: WebView?, handler: SslErrorHandler?, error: SslError?) {
                        handler?.cancel() // never "go on anyway"
                        loading = false
                        problem = "That page's secure connection couldn't be checked, so it wasn't opened."
                    }
                }
                view.value = this
                url?.let { loadUrl(it) }
            }
        })
    }
}
