// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/ManifestVerifier.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import net.i2p.crypto.eddsa.EdDSAEngine
import net.i2p.crypto.eddsa.EdDSAPublicKey
import net.i2p.crypto.eddsa.spec.EdDSANamedCurveTable
import net.i2p.crypto.eddsa.spec.EdDSAPublicKeySpec
import java.math.BigInteger
import java.security.MessageDigest
import java.util.Base64

/**
 * Checks a release manifest's Ed25519 signature against the keys compiled into the app.
 *
 * `java.security.Signature("Ed25519")` exists only from API 33 and the app supports 26, so the check runs on
 * EdDSA-Java (`net.i2p.crypto:eddsa`). That library accepts a signature whose scalar `S` is not reduced
 * (CVE-2020-36843); the check below refuses those itself, so a signature is valid here exactly when RFC 8032
 * says it is. This runs on the raw bytes of `manifest.json`, before any of it is parsed.
 *
 * [trusted] are raw 32-byte public keys: test builds trust the test key and the release key, the official
 * app only the release key ([fromBuild]). A key that is not 32 bytes (the placeholder when no key file was
 * there at build time) is dropped, so it verifies nothing.
 */
class ManifestVerifier(trusted: List<ByteArray>) {
    private val keys: List<ByteArray> = trusted.filter { it.size == 32 && it.any { b -> b != 0.toByte() } }

    /** Short ids of the trusted keys (first 16 hex digits of SHA-256), as `signing.keyId` states them. */
    val keyIds: Set<String> get() = keys.map { keyId(it) }.toSet()

    /** The id of the key that signed [manifest], or null when none of [keys] did. */
    fun signer(manifest: ByteArray, signatureFile: ByteArray): String? {
        val signature = decodeSignature(signatureFile) ?: return null
        if (!isCanonicalScalar(signature)) return null
        return keys.firstOrNull { verifyWith(it, manifest, signature) }?.let { keyId(it) }
    }

    fun verify(manifest: ByteArray, signatureFile: ByteArray): Boolean = signer(manifest, signatureFile) != null

    private fun verifyWith(publicKey: ByteArray, manifest: ByteArray, signature: ByteArray): Boolean = try {
        val spec = EdDSANamedCurveTable.getByName(EdDSANamedCurveTable.ED_25519)
        val key = EdDSAPublicKey(EdDSAPublicKeySpec(publicKey, spec))
        val engine = EdDSAEngine(MessageDigest.getInstance(spec.hashAlgorithm))
        engine.initVerify(key)
        engine.verifyOneShot(manifest, signature)
    } catch (e: Exception) {
        // A malformed point or a library complaint is a failed check, never a crash.
        false
    }

    companion object {
        /** The group order of Ed25519, `2^252 + 27742317777372353535851937790883648493`. */
        private val L = BigInteger.ONE.shiftLeft(252).add(BigInteger("27742317777372353535851937790883648493"))

        /** Keys given as base64 text; blank or unreadable ones (the placeholder) are left out. */
        fun decodeKeys(vararg base64: String): List<ByteArray> = base64.filter { it.isNotBlank() }.mapNotNull {
            runCatching { Base64.getDecoder().decode(it.trim()) }.getOrNull()
        }

        fun keyId(publicKey: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(publicKey).joinToString("") { "%02x".format(it) }.take(16)

        internal fun decodeSignature(file: ByteArray): ByteArray? {
            val text = file.decodeToString().filterNot { it.isWhitespace() }
            val bytes = try {
                Base64.getDecoder().decode(text)
            } catch (e: IllegalArgumentException) {
                return null
            }
            return bytes.takeIf { it.size == 64 }
        }

        /** RFC 8032 5.1.7: the second half of the signature, little-endian, must be below L. */
        internal fun isCanonicalScalar(signature: ByteArray): Boolean {
            val s = BigInteger(1, signature.copyOfRange(32, 64).reversedArray())
            return s < L
        }
    }
}
