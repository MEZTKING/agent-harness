// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/test/java/com/labteto/dshmobile/runtime/ProotCommandTest.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class ProotCommandTest {
    private val layout = RuntimeLayout(File("/data/user/0/app/no_backup/runtime"), File("/data/user/0/app/cache/runtime"))
    private val record = InstalledRecord(
        releaseId = "r", sequence = 1, abi = "x86_64", channel = "test", version = "0.8.0",
        base = LayerRecord("b1", "base-b1", "0".repeat(64)),
        roundtable = LayerRecord("rt-0.8.0", "roundtable-rt-0.8.0", "0".repeat(64)),
        entrypoint = "/opt/roundtable/venv/bin/roundtable",
        fakeProc = listOf(RuntimeManifest.FakeProc("/opt/rt-runtime/proc/stat", "/proc/stat")),
        resolvConf = "/etc/resolv.conf",
    )
    private val token = LaunchToken.next()
    private val command = ProotCommand.build(
        ProotCommand.Inputs(File("/data/app/x/lib/x86_64"), layout, record, 8765, token, inherited = setOf("ANDROID_DATA", "PATH", "LD_PRELOAD")),
    )
    private val argv = command.argv.map { it.replace('\\', '/') }

    private fun bindsTo(guest: String): String? {
        val i = argv.indices.firstOrNull { argv[it] == "-b" && it + 1 < argv.size && argv[it + 1].endsWith(":$guest") }
        return i?.let { argv[it + 1].substringBeforeLast(":$guest") }
    }

    @Test
    fun `the launch token is never on the command line, only in the environment`() {
        assertFalse(argv.any { token in it })
        assertFalse(argv.any { "ROUNDTABLE_LAUNCH_TOKEN" in it })
        assertEquals(token, command.environment["ROUNDTABLE_LAUNCH_TOKEN"])
        assertFalse(command.toString().contains(token))
        assertTrue(command.toString().contains("ROUNDTABLE_LAUNCH_TOKEN"))
    }

    @Test
    fun `it runs roundtable phone serve as agreed with the other side`() {
        assertEquals(
            listOf("/opt/roundtable/venv/bin/roundtable", "phone", "serve", "--local", "--port", "8765", "--home", "/root/.roundtable"),
            argv.takeLast(8),
        )
        assertEquals("/root/.roundtable", command.environment["ROUNDTABLE_HOME"])
        assertEquals("/workspaces", command.environment["ROUNDTABLE_WORKSPACES"])
    }

    @Test
    fun `the wrapper prints proot's pid and then becomes proot, with DSH's flags`() {
        assertEquals(listOf("/system/bin/sh", "-c", "echo \$\$; exec \"\$@\"", "sh", "/data/app/x/lib/x86_64/libproot.so"), argv.take(5))
        assertEquals(listOf("--kill-on-exit", "--link2symlink", "-0", "-r", "/data/user/0/app/no_backup/runtime/base-b1"), argv.drop(5).take(5))
        for (bind in listOf("/dev", "/proc", "/sys", "/proc/self/fd:/dev/fd")) assertTrue("missing -b $bind", argv.windowed(2).any { it == listOf("-b", bind) })
    }

    @Test
    fun `home, projects, the roundtable layer and the generated files are bound in`() {
        assertEquals("/data/user/0/app/no_backup/runtime/home", bindsTo("/root"))
        assertEquals("/data/user/0/app/no_backup/runtime/workspaces", bindsTo("/workspaces"))
        assertEquals("/data/user/0/app/no_backup/runtime/roundtable-rt-0.8.0/opt/roundtable", bindsTo("/opt/roundtable"))
        assertEquals("/data/user/0/app/no_backup/runtime/run/resolv.conf", bindsTo("/etc/resolv.conf"))
        assertEquals("/data/user/0/app/no_backup/runtime/run/proc-stat", bindsTo("/proc/stat"))
    }

    @Test
    fun `Android's own environment is cleared and the guest gets a clean one`() {
        assertTrue("ANDROID_DATA" in command.removeFromEnvironment)
        assertTrue("LD_PRELOAD" in command.removeFromEnvironment)
        assertTrue("PROOT_NO_SECCOMP" in command.removeFromEnvironment)
        // A name the guest gets is set, not removed.
        assertFalse("PATH" in command.removeFromEnvironment)
        assertTrue(command.environment["PATH"]!!.startsWith("/opt/roundtable/venv/bin:"))
        assertEquals("/data/app/x/lib/x86_64/libproot-loader.so", command.environment["PROOT_LOADER"]?.replace('\\', '/'))
    }

    @Test
    fun `each start gets a new token of 32 random bytes in base64url`() {
        val a = LaunchToken.next()
        assertNotEquals(a, LaunchToken.next())
        assertEquals(43, a.length)
        assertTrue(a.all { it.isLetterOrDigit() || it == '-' || it == '_' })
    }

    @Test
    fun `a free port is picked, the default when it is free`() {
        val p = FreePort.pick()
        assertTrue(p in 1..65535)
        java.net.ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1")).use { held ->
            assertNotEquals(held.localPort, FreePort.pick(held.localPort))
        }
    }

    @Test
    fun `resolv conf lists IPv4 first, at most three, with a fallback`() {
        assertEquals(
            "# Written by Roundtable Mobile at start from the device's DNS servers.\nnameserver 10.0.2.3\nnameserver 192.168.1.1\nnameserver fd00::1\n",
            ProotCommand.resolvConf(listOf("fd00::1", "10.0.2.3", "fe80::1%wlan0", "192.168.1.1", "10.0.2.3")),
        )
        assertTrue(ProotCommand.resolvConf(emptyList()).contains("nameserver 8.8.8.8\nnameserver 1.1.1.1\n"))
    }

    @Test
    fun `proc stat gets one cpu line per CPU in the shipped format`() {
        val lines = ProotCommand.procStat(RuntimeFixture.SHIPPED_STAT, 3).lines()
        assertEquals("cpu  1500 0 750 24000 36 0 18 0 0 0", lines[0])
        assertEquals("cpu2 500 0 250 8000 12 0 6 0 0 0", lines[3])
        assertEquals(1, ProotCommand.procStat(null, 1).lines().count { it.startsWith("cpu0 ") })
    }
}
