package com.meztking.roundtable.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * A manifest made and signed by the runtime build's own scripts (runtime/make_manifest.py and sign_manifest.py
 * with the public test key, over two tiny made-up layers), so the app and the build can't drift apart.
 */
class RuntimeBuildFormatTest {
    private fun resource(name: String): ByteArray =
        requireNotNull(javaClass.getResourceAsStream("/runtime/$name")) { "missing fixture $name" }.use { it.readBytes() }

    private val bytes = resource("sample-test.manifest.json")
    private val sig = resource("sample-test.manifest.json.sig")
    private val testKey = ManifestVerifier.decodeKeys("tvwd6ngxHYEox9BF0fwscb+LDIfen8G2td97hTEmKnc=")

    @Test
    fun `the build's signature checks out against the test key, and names it`() {
        val verifier = ManifestVerifier(testKey)
        assertEquals("75763b846c59086a", verifier.signer(bytes, sig))
        assertFalse(verifier.verify(bytes.copyOf().also { it[40] = (it[40] + 1).toByte() }, sig))
    }

    @Test
    fun `the build's manifest parses and installs on both ABIs in a test build only`() {
        val m = RuntimeManifest.parse(bytes)
        assertTrue(m.isTest)
        assertEquals("0.7.3", m.version)
        assertEquals("Roundtable is ready on", m.runtime.readinessPrefix)
        assertEquals("ROUNDTABLE_LAUNCH_TOKEN", m.runtime.launchTokenEnv)
        for (abi in listOf("arm64-v8a", "x86_64")) {
            val d = ManifestPolicy.decide(m, m.minAppVersion, listOf(abi), null, allowTest = true, signerKeyId = "75763b846c59086a")
            assertEquals(listOf("base", "roundtable"), (d as ManifestPolicy.Decision.Install).layers.map { it.name })
        }
        assertEquals(
            ManifestPolicy.Decision.Refused(RuntimeFailure.WrongChannel("test")),
            ManifestPolicy.decide(m, m.minAppVersion, listOf("arm64-v8a"), null, allowTest = false, signerKeyId = "75763b846c59086a"),
        )
    }

    @Test
    fun `its start command is the agreed one, with the port filled in and the token only in the environment`() {
        val m = RuntimeManifest.parse(bytes)
        val layer = { n: String -> m.layer("arm64-v8a", n)!!.let { LayerRecord(it.id, "$n-dir", it.sha256) } }
        val record = InstalledRecord(
            m.releaseId, m.sequence, "arm64-v8a", m.channel, m.version, layer("base"), layer("roundtable"),
            m.runtime.entrypoint, m.runtime.fakeProc, m.runtime.resolvConf, m.runtime.args, m.runtime.env,
            m.runtime.launchTokenEnv, m.runtime.readinessPrefix, m.runtime.healthPath,
        )
        val token = LaunchToken.next()
        val c = ProotCommand.build(ProotCommand.Inputs(File("/lib"), RuntimeLayout(File("/r"), File("/c")), record, 8765, token))
        assertEquals(
            listOf("/opt/roundtable/venv/bin/roundtable", "phone", "serve", "--local", "--port", "8765", "--home", "/root/.roundtable"),
            c.argv.takeLast(8),
        )
        assertFalse(c.argv.any { token in it })
        assertEquals(token, c.environment["ROUNDTABLE_LAUNCH_TOKEN"])
        assertEquals("/workspaces", c.environment["ROUNDTABLE_WORKSPACES"])
        assertEquals("/root/.roundtable", c.environment["ROUNDTABLE_HOME"])
    }
}
