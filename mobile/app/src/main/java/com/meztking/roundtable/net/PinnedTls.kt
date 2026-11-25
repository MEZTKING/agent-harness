package com.meztking.roundtable.net

import okhttp3.OkHttpClient
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * The PC makes its own certificate, so there is no certificate authority to ask. Instead the
 * phone trusts exactly one certificate: the one whose SHA-256 fingerprint came in the pairing
 * QR code. Anything else (someone in the middle on the Wi-Fi) is refused.
 */
class PinnedTrustManager(private val fingerprint: String) : X509TrustManager {
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
        throw CertificateException("not used")

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("no certificate")
        if (sha256(leaf.encoded) != fingerprint.lowercase()) {
            throw CertificateException("this isn't your PC (its certificate doesn't match the one you paired with)")
        }
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    companion object {
        fun sha256(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}

fun pinnedClient(fingerprint: String, readTimeoutS: Long = 40): OkHttpClient {
    val tm = PinnedTrustManager(fingerprint)
    val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
    return OkHttpClient.Builder()
        .sslSocketFactory(ctx.socketFactory, tm)
        .hostnameVerifier { _, _ -> true } // identity is the pinned certificate, not a name
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(readTimeoutS, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
}
