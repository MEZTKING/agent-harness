// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/test/java/com/labteto/dshmobile/runtime/ManifestVerifierTest.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.math.BigInteger
import java.util.Base64

class ManifestVerifierTest {
    private val message = """{"schemaVersion":1,"releaseId":"test"}""".toByteArray()

    @Test
    fun `a signature from the JDK's Ed25519 verifies and names its key`() {
        val key = TestSigningKey()
        val verifier = ManifestVerifier(listOf(key.rawPublicKey))
        assertTrue(verifier.verify(message, key.signatureFile(message)))
        assertEquals(ManifestVerifier.keyId(key.rawPublicKey), verifier.signer(message, key.signatureFile(message)))
    }

    @Test
    fun `with two trusted keys, either verifies and the right one is named`() {
        val test = TestSigningKey()
        val release = TestSigningKey()
        val verifier = ManifestVerifier(listOf(test.rawPublicKey, release.rawPublicKey))
        assertEquals(ManifestVerifier.keyId(release.rawPublicKey), verifier.signer(message, release.signatureFile(message)))
        assertEquals(ManifestVerifier.keyId(test.rawPublicKey), verifier.signer(message, test.signatureFile(message)))
    }

    @Test
    fun `whitespace around the base64 signature is ignored`() {
        val key = TestSigningKey()
        val sig = "\r\n  " + Base64.getEncoder().encodeToString(key.sign(message)) + " \n\n"
        assertTrue(ManifestVerifier(listOf(key.rawPublicKey)).verify(message, sig.toByteArray()))
    }

    @Test
    fun `one changed byte in the manifest fails`() {
        val key = TestSigningKey()
        val sig = key.signatureFile(message)
        val tampered = message.copyOf().also { it[5] = (it[5] + 1).toByte() }
        assertFalse(ManifestVerifier(listOf(key.rawPublicKey)).verify(tampered, sig))
        assertFalse(ManifestVerifier(listOf(key.rawPublicKey)).verify(message + '\n'.code.toByte(), sig))
    }

    @Test
    fun `a signature by another key fails`() {
        val signer = TestSigningKey()
        assertFalse(ManifestVerifier(listOf(TestSigningKey().rawPublicKey)).verify(message, signer.signatureFile(message)))
    }

    @Test
    fun `the placeholder key (no key file at build time) verifies nothing`() {
        val key = TestSigningKey()
        val none = ManifestVerifier(ManifestVerifier.decodeKeys("", "  "))
        assertTrue(none.keyIds.isEmpty())
        assertFalse(none.verify(message, key.signatureFile(message)))
        assertTrue(ManifestVerifier(listOf(ByteArray(32))).keyIds.isEmpty())
        assertEquals(1, ManifestVerifier.decodeKeys(Base64.getEncoder().encodeToString(key.rawPublicKey), "").size)
    }

    @Test
    fun `signatures that are not 64 bytes of base64 fail without throwing`() {
        val key = TestSigningKey()
        val verifier = ManifestVerifier(listOf(key.rawPublicKey))
        assertFalse(verifier.verify(message, ByteArray(0)))
        assertFalse(verifier.verify(message, "not base64 !!".toByteArray()))
        assertFalse(verifier.verify(message, Base64.getEncoder().encode(key.sign(message).copyOf(63))))
        assertFalse(verifier.verify(message, Base64.getEncoder().encode(ByteArray(64))))
    }

    @Test
    fun `a non-canonical S (S plus the group order) is refused`() {
        val key = TestSigningKey()
        val sig = key.sign(message)
        val l = BigInteger.ONE.shiftLeft(252).add(BigInteger("27742317777372353535851937790883648493"))
        val s = BigInteger(1, sig.copyOfRange(32, 64).reversedArray())
        val little = s.add(l).toByteArray().reversedArray().copyOf(32)
        val malleated = sig.copyOfRange(0, 32) + little
        assertFalse(ManifestVerifier.isCanonicalScalar(malleated))
        assertFalse(ManifestVerifier(listOf(key.rawPublicKey)).verify(message, Base64.getEncoder().encode(malleated)))
    }
}
