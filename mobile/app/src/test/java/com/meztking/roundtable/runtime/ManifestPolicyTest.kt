// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/test/java/com/labteto/dshmobile/runtime/ManifestPolicyTest.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ManifestPolicyTest {
    private val sha = "a".repeat(64)
    private fun json(channel: String = "test", compression: String = "xz", file: String = "base-x86_64.tar.xz", product: String = "roundtable") = """
        {"schemaVersion": 1, "product": "$product", "channel": "$channel", "releaseId": "runtime-2026.11.26-1", "sequence": 5,
         "minAppVersion": "0.7.0",
         "signing": {"algorithm": "Ed25519", "keyId": "abcd1234abcd1234"},
         "assetBaseUrl": "https://github.com/MEZTKING/agent-harness/releases/download/runtime-2026.11.26-1/",
         "roundtable": {"version": "0.8.0"},
         "archs": {
           "aarch64": {"layers": [
             {"file": "base-aarch64.tar.xz", "size": 100, "sha256": "$sha", "name": "base", "id": "b1", "compression": "xz", "unpackedSize": 300, "entries": 10},
             {"file": "rt-aarch64.tar.xz", "size": 50, "sha256": "$sha", "name": "roundtable", "id": "r1", "compression": "xz", "unpackedSize": 90, "entries": 4}]},
           "x86_64": {"layers": [
             {"file": "$file", "size": 100, "sha256": "$sha", "name": "base", "id": "b1", "compression": "$compression", "unpackedSize": 300, "entries": 10},
             {"file": "rt-x86_64.tar.xz", "size": 50, "sha256": "$sha", "name": "roundtable", "id": "r1", "compression": "xz", "unpackedSize": 90, "entries": 4}]}
         }}
    """.trimIndent()

    private val test = RuntimeManifest.parse(json().toByteArray())
    private val official = RuntimeManifest.parse(json(channel = "stable").toByteArray())
    private val signer = "abcd1234abcd1234"

    private fun decide(m: RuntimeManifest, allowTest: Boolean, app: String = "0.7.3", abis: List<String> = listOf("arm64-v8a"), installed: InstalledRecord? = null, key: String = signer) =
        ManifestPolicy.decide(m, app, abis, installed, allowTest, key)

    private fun installed(sequence: Long = 5, base: String = "b1", rt: String = "r1") = InstalledRecord(
        releaseId = "old", sequence = sequence, abi = "arm64-v8a", channel = "test", version = "0.7.0",
        base = LayerRecord(base, "base-$base", sha), roundtable = LayerRecord(rt, "roundtable-$rt", sha),
        entrypoint = RuntimeManifest.DEFAULT_ENTRYPOINT, fakeProc = emptyList(), resolvConf = "/etc/resolv.conf",
    )

    @Test
    fun `a test download is accepted by test builds only`() {
        assertTrue(decide(test, allowTest = true) is ManifestPolicy.Decision.Install)
        assertEquals(ManifestPolicy.Decision.Refused(RuntimeFailure.WrongChannel("test")), decide(test, allowTest = false))
        // The official download is fine for both.
        assertTrue(decide(official, allowTest = false) is ManifestPolicy.Decision.Install)
        assertTrue(decide(official, allowTest = true) is ManifestPolicy.Decision.Install)
    }

    @Test
    fun `the manifest must name the key that signed it`() {
        val d = decide(test, allowTest = true, key = "ffffffffffffffff")
        assertTrue((d as ManifestPolicy.Decision.Refused).failure is RuntimeFailure.BadManifest)
    }

    @Test
    fun `a fresh install takes both layers, found under the Linux arch name`() {
        val d = decide(test, allowTest = true) as ManifestPolicy.Decision.Install
        assertEquals("arm64-v8a", d.abi)
        assertEquals(listOf("base", "roundtable"), d.layers.map { it.name })
        assertEquals(150L, d.downloadBytes)
    }

    @Test
    fun `an older app, an older release and a 32-bit phone are refused`() {
        assertEquals(ManifestPolicy.Decision.Refused(RuntimeFailure.AppTooOld("0.7.0")), decide(test, true, app = "0.6.9"))
        assertEquals(ManifestPolicy.Decision.Refused(RuntimeFailure.OlderRelease(9, 5)), decide(test, true, installed = installed(sequence = 9)))
        assertTrue((decide(test, true, abis = listOf("armeabi-v7a")) as ManifestPolicy.Decision.Refused).failure is RuntimeFailure.NoBuildForDevice)
    }

    @Test
    fun `only changed layers are fetched`() {
        assertTrue(decide(test, true, installed = installed()) is ManifestPolicy.Decision.UpToDate)
        val d = decide(test, true, installed = installed(rt = "r0")) as ManifestPolicy.Decision.Install
        assertEquals(listOf("roundtable"), d.layers.map { it.name })
    }

    @Test
    fun `only 64-bit phones on Android 8 or later are offered This phone`() {
        assertTrue(ManifestPolicy.supported(26, listOf("arm64-v8a")))
        assertTrue(ManifestPolicy.supported(36, listOf("arm64-v8a"))) // Android 16, the owner's phone
        assertTrue(ManifestPolicy.supported(30, listOf("x86_64")))
        assertFalse(ManifestPolicy.supported(25, listOf("arm64-v8a")))
        assertFalse(ManifestPolicy.supported(33, emptyList())) // a 32-bit-only phone has no 64-bit ABIs
        assertFalse(ManifestPolicy.supported(33, listOf("mips64")))
    }

    @Test
    fun `bad shapes are refused`() {
        expectBad(json(compression = "zstd"), "compression")
        expectBad(json(file = "../evil.tar.xz"), "asset name")
        expectBad(json(product = "dsh"), "product")
        expectBad(json(channel = "nightly"), "channel")
        expectBad(json().replace("https://github.com", "http://github.com"), "https")
        expectBad(json().replace("\"name\": \"roundtable\", \"id\": \"r1\"", "\"name\": \"harness\", \"id\": \"r1\""), "layers")
        expectBad(json().replace("\"roundtable\": {\"version\": \"0.8.0\"},", "\"runtime\": {\"entrypoint\": \"/opt/x; rm -rf /\"},"), "entrypoint")
    }

    @Test
    fun `unknown fields are ignored`() {
        val extended = json().replaceFirst("{", """{"somethingNew": {"nested": [1, 2]},""")
        assertEquals(test, RuntimeManifest.parse(extended.toByteArray()))
    }

    private fun expectBad(text: String, mention: String) {
        try {
            RuntimeManifest.parse(text.toByteArray())
            fail("expected a refusal mentioning '$mention'")
        } catch (e: ManifestException) {
            assertTrue("'${e.message}' should mention '$mention'", e.message!!.contains(mention))
        }
    }
}
