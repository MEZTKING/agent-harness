// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/test/java/com/labteto/dshmobile/runtime/RuntimeInstallerTest.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class RuntimeInstallerTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var fx: RuntimeFixture

    @Before fun setUp() { fx = RuntimeFixture(tmp) }
    @After fun tearDown() = fx.close()

    private fun install(installer: RuntimeInstaller = fx.installer()): InstalledRecord = runBlocking {
        val result = installer.check() as RuntimeInstaller.CheckResult.Available
        installer.apply(result.manifest, result.decision, onEvent = {})
    }

    @Test
    fun `a fresh install unpacks both layers and commits them`() {
        val base = fx.baseLayer()
        val rt = fx.roundtableLayer("0.8.0")
        fx.publish(base, rt, sequence = 1)
        val record = install()
        assertEquals("x86_64", record.abi)
        assertEquals("0.8.0", record.version)
        assertTrue(record.isTest)
        assertEquals(record, InstalledStore(fx.layout).read())
        val rootfs = File(fx.layout.root, record.base.dir)
        assertTrue(File(rootfs, "usr/bin/bash").isFile)
        // Mount points for the binds exist in the base.
        assertTrue(File(rootfs, "opt/roundtable").isDirectory)
        assertTrue(File(rootfs, "workspaces").isDirectory)
        assertTrue(File(fx.layout.root, record.roundtable.dir + "/opt/roundtable/venv/bin/roundtable").isFile)
        // Downloads are cleared after the commit.
        assertTrue(fx.layout.downloads.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun `the same release again is up to date and fetches nothing`() {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1)
        install()
        val again = runBlocking { fx.installer().check() }
        assertTrue(again is RuntimeInstaller.CheckResult.UpToDate)
    }

    @Test
    fun `a new roundtable layer alone is the only download`() {
        val base = fx.baseLayer()
        fx.publish(base, fx.roundtableLayer("0.8.0"), sequence = 1)
        val first = install()
        val next = fx.roundtableLayer("0.8.1")
        fx.publish(base, next, sequence = 2)
        val result = runBlocking { fx.installer().check() } as RuntimeInstaller.CheckResult.Available
        assertEquals(listOf(LAYER_ROUNDTABLE), result.decision.layers.map { it.name })
        val second = runBlocking { fx.installer().apply(result.manifest, result.decision, onEvent = {}) }
        assertEquals(first.base, second.base)
        assertEquals("0.8.1", second.version)
        // The old roundtable layer is kept while the new one is on trial, and goes once it has started.
        assertTrue(second.onTrial)
        assertTrue(File(fx.layout.root, first.roundtable.dir).isDirectory)
        fx.installer().commitTrial()
        assertFalse(File(fx.layout.root, first.roundtable.dir).exists())
        assertFalse(InstalledStore(fx.layout).read()!!.onTrial)
    }

    @Test
    fun `an update that fails twice goes back to the previous release and is not offered again by itself`() {
        val base = fx.baseLayer()
        fx.publish(base, fx.roundtableLayer("0.8.0"), sequence = 1)
        val first = install()
        assertFalse(first.onTrial)
        fx.publish(base, fx.roundtableLayer("0.8.1"), sequence = 2)
        val bad = install()
        assertEquals("0.8.1", bad.version)
        val installer = fx.installer()
        assertEquals(1, installer.trialFailed())
        assertEquals(2, installer.trialFailed())
        val back = installer.rollbackTrial()!!
        assertEquals("0.8.0", back.version)
        assertEquals(first.roundtable, back.roundtable)
        assertFalse(back.onTrial)
        assertTrue(File(fx.layout.root, first.roundtable.dir).isDirectory)
        assertFalse(File(fx.layout.root, bad.roundtable.dir).exists())
        assertTrue(back.isHeldBack(bad.releaseId, 2))
        // The same bad release is held back, not offered; the owner's "Try the new one again" gets it.
        val again = runBlocking { fx.installer().check() }
        assertTrue("got $again", again is RuntimeInstaller.CheckResult.HeldBack)
        assertEquals("0.8.1", (again as RuntimeInstaller.CheckResult.HeldBack).version)
        val retry = runBlocking { fx.installer().check(retryHeldBack = true) }
        assertTrue(retry is RuntimeInstaller.CheckResult.Available)
        val retried = runBlocking { fx.installer().apply((retry as RuntimeInstaller.CheckResult.Available).manifest, retry.decision, onEvent = {}) }
        assertTrue(retried.onTrial)
        assertTrue(retried.heldBack.isEmpty())
        // A newer release still comes by itself.
        fx.installer().rollbackTrial()
        fx.publish(base, fx.roundtableLayer("0.8.2"), sequence = 3)
        assertTrue(runBlocking { fx.installer().check() } is RuntimeInstaller.CheckResult.Available)
    }

    @Test
    fun `a manifest signed by an unknown key is refused before it is read`() {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1, signer = TestSigningKey())
        assertEquals(RuntimeInstaller.CheckResult.Refused(RuntimeFailure.BadSignature), runBlocking { fx.installer().check() })
    }

    @Test
    fun `the official app refuses a test download, a test app takes it`() {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1, channel = "test")
        assertEquals(
            RuntimeInstaller.CheckResult.Refused(RuntimeFailure.WrongChannel("test")),
            runBlocking { fx.installer(allowTest = false).check() },
        )
        assertTrue(runBlocking { fx.installer(allowTest = true).check() } is RuntimeInstaller.CheckResult.Available)
    }

    @Test
    fun `a damaged layer is deleted and nothing is installed`() {
        val base = fx.baseLayer()
        fx.publish(base, fx.roundtableLayer("0.8.0"), sequence = 1, servedBase = base.bytes.copyOf().also { it[600] = 9 })
        try {
            install()
            fail("expected a checksum failure")
        } catch (e: DownloadException) {
            assertTrue(e.failure is RuntimeFailure.ChecksumMismatch)
        }
        assertEquals(null, InstalledStore(fx.layout).read())
    }

    @Test
    fun `not enough space is said before anything is fetched`() {
        val base = fx.baseLayer()
        fx.publish(base, fx.roundtableLayer("0.8.0"), sequence = 1)
        fx.freeBytes = 1024
        try { install(); fail("expected NoSpace") } catch (e: InstallException) { assertTrue(e.failure is RuntimeFailure.NoSpace) }
        assertTrue(fx.assetRequests(base).isEmpty())
    }

    @Test
    fun `remove keeps projects and home, delete everything does not`() {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1)
        val record = install()
        File(fx.layout.workspaces, "my-game").mkdirs()
        File(fx.layout.home, ".roundtable").mkdirs()
        fx.installer().uninstall(keepUserData = true)
        assertEquals(null, InstalledStore(fx.layout).read())
        assertFalse(File(fx.layout.root, record.base.dir).exists())
        assertTrue(File(fx.layout.workspaces, "my-game").isDirectory)
        assertTrue(File(fx.layout.home, ".roundtable").isDirectory)
        fx.installer().uninstall(keepUserData = false)
        assertFalse(fx.layout.workspaces.exists())
        assertFalse(fx.layout.home.exists())
    }

    @Test
    fun `the arch may be named the Linux way`() {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1, archKey = "x86_64")
        val m = RuntimeManifest.parse(fx.release.files.getValue("rel/manifest.json"))
        assertTrue(m.arch("x86_64") != null)
        val arm = fx.manifestJson(fx.baseLayer(), fx.roundtableLayer("0.8.0"), 1, "test", "k", "0.7.0", archKey = "aarch64")
        assertTrue(RuntimeManifest.parse(arm.toByteArray()).arch("arm64-v8a") != null)
    }
}
