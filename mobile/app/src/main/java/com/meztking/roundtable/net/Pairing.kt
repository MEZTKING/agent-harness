package com.meztking.roundtable.net

import java.net.URI
import java.net.URLDecoder

/** What the PC's pairing QR code carries: roundtable://pair?v=1&n=NAME&h=IP,IP&p=PORT&c=CODE&f=SHA256 */
data class PairingOffer(
    val pcName: String,
    val hosts: List<String>,
    val port: Int,
    val code: String,
    val fingerprint: String,
)

object Pairing {
    /** The offer in a pairing link, or null when it isn't one (never throws). */
    fun parse(text: String): PairingOffer? = runCatching { read(text) }.getOrNull()

    private fun read(text: String): PairingOffer? {
        val uri = runCatching { URI(text.trim().replace(" ", "%20")) }.getOrNull() ?: return null
        if (uri.scheme != "roundtable" || uri.host != "pair") return null
        val q = (uri.rawQuery ?: "").split("&").filter { "=" in it }.associate {
            val (k, v) = it.split("=", limit = 2)
            k to URLDecoder.decode(v, "UTF-8")
        }
        if (q["v"] != "1") return null
        val hosts = q["h"].orEmpty().split(",").map { it.trim() }.filter { it.isNotEmpty() }
        val port = q["p"]?.toIntOrNull() ?: return null
        // the code may be left out of a pasted link and typed by hand instead
        val code = q["c"].orEmpty().trim().uppercase()
        val fp = q["f"].orEmpty().lowercase().replace(":", "")
        if (hosts.isEmpty() || port !in 1..65535 || (code.isNotEmpty() && code.length < 6) || !Regex("^[0-9a-f]{64}$").matches(fp)) return null
        return PairingOffer(q["n"].orEmpty().ifBlank { "PC" }, hosts, port, code, fp)
    }
}
