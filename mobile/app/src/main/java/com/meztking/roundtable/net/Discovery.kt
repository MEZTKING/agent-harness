package com.meztking.roundtable.net

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.net.URLEncoder
import java.security.MessageDigest

/** A PC that answered on the Wi-Fi: its name, where it is, and the certificate it says it has (not trusted by itself). */
data class FoundPc(val name: String, val host: String, val port: Int, val fingerprint: String) {
    /** A pairing offer without the code: the owner types the code shown on the PC ([Discovery.codeMatches] checks it). */
    fun toOffer(): PairingOffer = PairingOffer(name.ifBlank { "PC" }, listOf(host), port, "", fingerprint)

    /** The same offer as a pairing link, for the "Pairing link" box. */
    fun toLink(): String = "roundtable://pair?v=1&n=${enc(name)}&h=${enc(host)}&p=$port&f=$fingerprint"

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
}

/**
 * Finding the PC on the Wi-Fi (the PC's side is `roundtable/discovery.py`). The phone sends `ROUNDTABLE? v1` to the
 * Wi-Fi's broadcast address on UDP 8767; each Roundtable Hold with phone access on answers with its name, port and
 * certificate fingerprint – never the pairing code.
 *
 * Nothing in an answer is trusted on its own:
 * - for a PC already paired, only an answer with the pinned fingerprint is used, and only for its address
 *   ([relocated]); TLS pinning still decides when the phone connects;
 * - for a first pairing without the QR code, the last two letters of the PC's code come from its certificate, and
 *   [codeMatches] checks them against the fingerprint the phone is about to pin *before* the code is sent, so a
 *   stand-in on the same Wi-Fi never sees it. (Pinning makes the certificate seen equal the fingerprint checked.)
 */
object Discovery {
    const val PORT = 8767
    const val PROBE = "ROUNDTABLE? v1"
    private const val ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    private const val CODE_LENGTH = 8
    private const val CHECK_LETTERS = 2

    const val NOTHING = "Nothing answered: is the PC on, with phone access on, and on the same Wi-Fi?"
    const val NO_NETWORK = "This phone isn't on a Wi-Fi network. Turn on Wi-Fi, join the same network as your PC, and look again."
    const val CODE_MISMATCH = "That code doesn't belong to the PC that answered. Check the code on your PC and type it again. " +
        "If it's right, scan the QR code instead: something else on this Wi-Fi may be posing as your PC."

    // -- the pairing code's check (mirrors discovery.py `bound_code`) -------------------------------------------
    private fun check(fingerprint: String, head: String): String {
        val fp = fingerprint.lowercase().replace(":", "").trim()
        val d = MessageDigest.getInstance("SHA-256").digest("roundtable-pair-v1:$fp:${head.uppercase()}".toByteArray())
        return (0 until CHECK_LETTERS).map { ALPHABET[(d[it].toInt() and 0xff) % ALPHABET.length] }.joinToString("")
    }

    /** Whether a typed 8-letter code belongs to the PC with this certificate fingerprint. */
    fun codeMatches(code: String, fingerprint: String): Boolean {
        val c = code.trim().uppercase()
        if (c.length != CODE_LENGTH || c.any { it !in ALPHABET }) return false
        val want = check(fingerprint, c.dropLast(CHECK_LETTERS))
        return MessageDigest.isEqual(c.takeLast(CHECK_LETTERS).toByteArray(), want.toByteArray())
    }

    /** Throws the plain-words error before a code is sent to a PC it doesn't belong to. */
    fun requireCode(code: String, fingerprint: String) {
        if (!codeMatches(code, fingerprint)) throw ApiException(CODE_MISMATCH, 0)
    }

    // -- answers ------------------------------------------------------------------------------------------------
    /** A home or office address (or this phone): the only places an answer is taken from. */
    fun isPrivate(ip: String): Boolean {
        val p = ip.split(".").map { it.toIntOrNull() ?: return false }
        if (p.size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 10 || (p[0] == 172 && p[1] in 16..31) || (p[0] == 192 && p[1] == 168) ||
            (p[0] == 169 && p[1] == 254) || p[0] == 127
    }

    /** One answer read, or null when it isn't a proper one (never throws). */
    fun parseReply(text: String, sender: String): FoundPc? = runCatching {
        if (!isPrivate(sender)) return null
        val o = ApiJson.parseToJsonElement(text) as? JsonObject ?: return null
        if ((o["v"] as? JsonPrimitive)?.intOrNull != 1) return null
        val port = (o["port"] as? JsonPrimitive)?.intOrNull ?: return null
        val fp = (o["fp"] as? JsonPrimitive)?.takeIf { it.isString }?.content?.lowercase() ?: return null
        if (port !in 1..65535 || !Regex("^[0-9a-f]{64}$").matches(fp)) return null
        val name = (o["name"] as? JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty().take(60)
        FoundPc(name, sender, port, fp)
    }.getOrNull()

    /** The paired PC's link with the address it answered from first, or null when none of [found] is that PC. */
    fun relocated(link: PcLink, found: List<FoundPc>): PcLink? {
        val pc = found.firstOrNull { it.fingerprint.equals(link.fingerprint, ignoreCase = true) } ?: return null
        return link.copy(hosts = listOf(pc.host) + link.hosts.filter { it != pc.host }, port = pc.port)
    }

    // -- asking ------------------------------------------------------------------------------------------------
    /** Where to send the probe: every Wi-Fi's broadcast address, then the general one. */
    fun broadcastTargets(port: Int = PORT): List<InetSocketAddress> {
        val out = mutableListOf<InetAddress>()
        runCatching {
            for (nif in NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()) {
                if (!nif.isUp || nif.isLoopback) continue
                nif.interfaceAddresses.mapNotNullTo(out) { a -> a.broadcast?.takeIf { a.address is Inet4Address } }
            }
        }
        out.add(InetAddress.getByName("255.255.255.255"))
        return out.distinct().map { InetSocketAddress(it, port) }
    }

    /** Sends the probe to [targets] and collects the answers for [timeoutMs] (one per PC). */
    suspend fun probe(targets: List<InetSocketAddress>, timeoutMs: Long = 2000): List<FoundPc> = withContext(Dispatchers.IO) {
        val found = LinkedHashMap<String, FoundPc>()
        DatagramSocket().use { s ->
            s.broadcast = true
            val probe = PROBE.toByteArray()
            var sent = 0
            for (t in targets) if (runCatching { s.send(DatagramPacket(probe, probe.size, t)) }.isSuccess) sent++
            if (sent == 0) return@withContext emptyList()
            val buf = ByteArray(1024)
            val end = System.currentTimeMillis() + timeoutMs
            while (true) {
                val left = end - System.currentTimeMillis()
                if (left <= 0) break
                s.soTimeout = left.toInt().coerceAtLeast(1)
                val p = DatagramPacket(buf, buf.size)
                try { s.receive(p) } catch (_: SocketTimeoutException) { break }
                val sender = p.address?.hostAddress ?: continue
                parseReply(String(p.data, 0, p.length, Charsets.UTF_8), sender)?.let { found.putIfAbsent("${it.host}/${it.fingerprint}", it) }
            }
        }
        found.values.toList()
    }

    /** What a look on the Wi-Fi found, or the plain reason it found nothing. */
    data class Look(val found: List<FoundPc>, val problem: String? = null)

    /** Looks for Roundtable Hold on this phone's Wi-Fi, holding a multicast lock so the Wi-Fi chip passes the answers on. */
    suspend fun find(context: Context, timeoutMs: Long = 2000): Look {
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? android.net.wifi.WifiManager
        val lock = runCatching { wifi?.createMulticastLock("roundtable-find")?.apply { setReferenceCounted(false); acquire() } }.getOrNull()
        try {
            if (wifi?.isWifiEnabled == false) return Look(emptyList(), NO_NETWORK)
            val found = runCatching { probe(broadcastTargets(), timeoutMs) }.getOrElse { return Look(emptyList(), NO_NETWORK) }
            return Look(found, if (found.isEmpty()) NOTHING else null)
        } finally {
            runCatching { lock?.release() }
        }
    }

    /** The paired PC at its new address, if it answers on this Wi-Fi with the certificate this phone pinned. */
    suspend fun relocate(context: Context, link: PcLink, timeoutMs: Long = 2000): PcLink? = relocated(link, find(context, timeoutMs).found)
}
