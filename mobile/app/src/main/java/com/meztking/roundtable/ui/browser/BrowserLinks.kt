package com.meztking.roundtable.ui.browser

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.UriHandler
import com.meztking.roundtable.data.browser.isLocalWebAddress

/**
 * Taps on links (DS-81): a local address the agent printed (`localhost:5173`, an address on the Wi-Fi) opens in the
 * Browser tab ([openTab]); anything else goes to the phone's own browser as before.
 */
class TabUriHandler(private val system: UriHandler, private val openTab: (String) -> Unit) : UriHandler {
    override fun openUri(uri: String) = if (isLocalWebAddress(uri)) openTab(uri) else system.openUri(uri)
}

/** Wraps [content] so its links follow [TabUriHandler]. MainActivity provides it around its screens. */
@Composable
fun ProvideBrowserTab(openTab: (String) -> Unit, content: @Composable () -> Unit) {
    val system = LocalUriHandler.current
    CompositionLocalProvider(LocalUriHandler provides TabUriHandler(system, openTab)) { content() }
}
