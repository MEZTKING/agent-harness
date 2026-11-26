package com.meztking.roundtable.runtime

import java.net.InetAddress
import java.net.ServerSocket
import java.security.SecureRandom
import java.util.Base64

/** The secret Roundtable on this phone accepts (ROUNDTABLE_LAUNCH_TOKEN): 32 random bytes, base64url, new each start. */
object LaunchToken {
    private val random = SecureRandom()

    fun next(): String {
        val bytes = ByteArray(32)
        random.nextBytes(bytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }
}

/** A free port on 127.0.0.1: [preferred] when nothing holds it, otherwise one the system picks. */
object FreePort {
    const val DEFAULT = 8765

    fun pick(preferred: Int = DEFAULT): Int {
        val loopback = InetAddress.getByName("127.0.0.1")
        runCatching { ServerSocket(preferred, 1, loopback).use { return it.localPort } }
        return ServerSocket(0, 1, loopback).use { it.localPort }
    }
}
