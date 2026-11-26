package com.meztking.roundtable.net

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import java.io.IOException
import java.net.Proxy
import java.util.concurrent.TimeUnit

/**
 * "This phone": Roundtable running inside this app, at http://127.0.0.1:<port>. No pinned TLS and no pairing:
 * the server only listens on the phone's own loopback, and every request carries the launch token the app
 * made at start ([com.meztking.roundtable.runtime.RuntimeController.token]).
 */
interface LocalAccess {
    fun port(): Int
    /** The launch token; waits for a start in progress, throws when Roundtable isn't running. */
    suspend fun token(): String
}

/** Refuses any request that isn't plain HTTP to the phone's own loopback, so the token can't go anywhere else. */
object LoopbackOnly : Interceptor {
    val HOSTS = setOf("127.0.0.1", "localhost", "::1", "[::1]")

    fun allowed(scheme: String, host: String): Boolean = scheme == "http" && host in HOSTS

    override fun intercept(chain: Interceptor.Chain): Response {
        val url = chain.request().url
        if (!allowed(url.scheme, url.host)) throw IOException("refused: This phone talks to 127.0.0.1 only, not ${url.host}")
        return chain.proceed(chain.request())
    }
}

/** The client for "This phone": loopback only, no proxy, no redirects. */
fun localClient(readTimeoutS: Long = 40): OkHttpClient = OkHttpClient.Builder()
    .addInterceptor(LoopbackOnly)
    .proxy(Proxy.NO_PROXY)
    .followRedirects(false)
    .followSslRedirects(false)
    .connectTimeout(3, TimeUnit.SECONDS)
    .readTimeout(readTimeoutS, TimeUnit.SECONDS)
    .build()
