// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// core/src/commonMain/kotlin/com/labteto/dshmobile/core/browser/BrowserReach.kt and MentionedAddresses.kt.
// See THIRD_PARTY_NOTICES.md. Changed: the connections are This phone, a paired PC and Hub mode; the mentioned
// addresses are read from plain texts (the phone's chat and Live), and the words are the app's.
package com.meztking.roundtable.data.browser

/** How the app reaches the harness, which decides what `localhost` in the Browser tab means (DS-81). */
sealed interface BrowserConnection {
    /** The harness runs on this phone: `localhost` is this phone, and opens. */
    data object ThisPhone : BrowserConnection

    /** A paired PC at [host] (the address the phone uses to reach it: the Wi-Fi or Tailscale). */
    data class Pc(val host: String, val port: Int) : BrowserConnection

    /** Hub mode: the phone talks to GitHub, never to the PC, so no PC address is known. */
    data object Hub : BrowserConnection
}

/** What the tab does with an address on the current connection. */
sealed interface BrowserReach {
    data object Open : BrowserReach

    /**
     * The PC's own `localhost`, which the phone can't reach: loading it here would open the phone's own
     * `localhost` instead, so the tab doesn't. [onPcAddress] is the same page at the PC's address, offered as a
     * choice (a dev server often listens on `localhost` only, so it may not answer).
     */
    data class PcLoopback(val onPcAddress: String?) : BrowserReach

    /** The PC's phone server itself (the app already is that). */
    data object PcItself : BrowserReach
}

fun browserReach(address: WebAddress, connection: BrowserConnection): BrowserReach {
    val pc = (connection as? BrowserConnection.Pc)?.let { hostAddress(it.host, it.port) }
    if (pc != null && address.host == pc.host && address.effectivePort == pc.effectivePort) return BrowserReach.PcItself
    if (address.scope != AddressScope.Loopback) return BrowserReach.Open
    return when (connection) {
        BrowserConnection.ThisPhone -> BrowserReach.Open
        BrowserConnection.Hub -> BrowserReach.PcLoopback(null)
        is BrowserConnection.Pc -> BrowserReach.PcLoopback(
            pc?.takeIf { it.scope == AddressScope.PrivateNetwork || it.scope == AddressScope.LinkLocal }?.let { onHost(address, it.host) },
        )
    }
}

/** The words the tab shows for [reach] (null: nothing to say, it opens). */
fun reachWords(reach: BrowserReach): String? = when (reach) {
    BrowserReach.Open -> null
    BrowserReach.PcItself -> "That's your PC's phone link, which this app already uses. Open the page you want instead."
    is BrowserReach.PcLoopback -> if (reach.onPcAddress != null)
        "That page is on your PC's own localhost, which the phone can't reach. Try it at your PC's address instead; it only works if the page listens on the network."
    else "That page is on your PC's own localhost, which the phone can't reach from here."
}

private fun hostAddress(host: String, port: Int): WebAddress? {
    val h = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
    return (parseBrowserAddress("http://$h:$port/") as? AddressInput.Web)?.address
}

private fun onHost(address: WebAddress, host: String): String {
    val scheme = if (address.secure) "https" else "http"
    val authority = "$scheme://${address.host}" + (address.port?.let { ":$it" } ?: "")
    val rest = address.url.removePrefix(authority)
    return "$scheme://$host" + (address.port?.let { ":$it" } ?: "") + rest
}

/** One web address found in text: [start] inclusive, [end] exclusive. */
data class WebLink(val start: Int, val end: Int, val url: String)

/** Bare `http://` and `https://` addresses in [text], as a dev server or an agent prints them. */
fun findWebLinks(text: String): List<WebLink> {
    val links = mutableListOf<WebLink>()
    var i = 0
    while (i < text.length) {
        val start = schemeAt(text, i)
        if (start < 0) { i++; continue }
        var end = start
        while (end < text.length && !text[end].isWhitespace() && text[end] !in LINK_STOPS) end++
        end = trimLinkEnd(text, start, end)
        val candidate = text.substring(start, end)
        val hostStart = candidate.indexOf("://") + 3
        if (hostStart < candidate.length && parseBrowserAddress(candidate) is AddressInput.Web) {
            links += WebLink(start, end, candidate)
            i = end
        } else {
            i = start + 1
        }
    }
    return links
}

fun findLocalWebLinks(text: String): List<WebLink> = findWebLinks(text).filter { isLocalWebAddress(it.url) }

fun isLocalWebAddress(raw: String): Boolean = (parseBrowserAddress(raw) as? AddressInput.Web)?.address?.isLocal == true

/** Local addresses in [texts] (oldest first, as a chat reads), newest first and each once: what the tab offers. */
fun mentionedLocalAddresses(texts: List<String>, limit: Int = 4, scanChars: Int = 32 * 1024): List<String> {
    val found = LinkedHashSet<String>()
    for (text in texts.asReversed()) {
        val window = if (text.length > scanChars) text.substring(text.length - scanChars) else text
        for (link in findLocalWebLinks(window).asReversed()) {
            val url = (parseBrowserAddress(link.url) as? AddressInput.Web)?.address?.url ?: continue
            found += url
            if (found.size >= limit) return found.toList()
        }
    }
    return found.toList()
}

private val LINK_STOPS = setOf('<', '>', '"', '`', '\u0000')

private fun schemeAt(text: String, i: Int): Int {
    if (i > 0 && (text[i - 1].isLetterOrDigit() || text[i - 1] == '/' || text[i - 1] == '@')) return -1
    val matches = text.regionMatches(i, "http://", 0, 7, ignoreCase = true) || text.regionMatches(i, "https://", 0, 8, ignoreCase = true)
    return if (matches) i else -1
}

private fun trimLinkEnd(text: String, start: Int, initialEnd: Int): Int {
    var end = initialEnd
    while (end > start) {
        val c = text[end - 1]
        val link = text.substring(start, end)
        val drop = when (c) {
            '.', ',', ';', ':', '!', '?', '\'', '*', '_', '~' -> true
            ')' -> link.count { it == '(' } < link.count { it == ')' }
            ']' -> link.count { it == '[' } < link.count { it == ']' }
            '}' -> link.count { it == '{' } < link.count { it == '}' }
            else -> false
        }
        if (!drop) break
        end--
    }
    return end
}
