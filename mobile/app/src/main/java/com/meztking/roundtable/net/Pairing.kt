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
    fun parse(text: String): PairingOffer? {
        val uri = runCatching { URI(text.trim()) }.getOrNull() ?: return null
        if (uri.scheme != "roundtable" || uri.host != "pair") return null
        val q = (uri.rawQuery ?: "").split("&").filter { "=" in it }.associate {
            val (k, v) = it.split("=", limit = 2)
            k to URLDecoder.decode(v, "UTF-8")
        }
        if (q["v"] != "1") return null
        val hosts = q["h"].orEmpty().split(",").map { it.trim() }.filter { it.isNotEmpty() }
        val port = q["p"]?.toIntOrNull() ?: return null
        val code = q["c"].orEmpty()
        val fp = q["f"].orEmpty().lowercase()
        if (hosts.isEmpty() || code.length < 6 || !Regex("^[0-9a-f]{64}$").matches(fp)) return null
        return PairingOffer(q["n"].orEmpty().ifBlank { "PC" }, hosts, port, code, fp)
    }
}
