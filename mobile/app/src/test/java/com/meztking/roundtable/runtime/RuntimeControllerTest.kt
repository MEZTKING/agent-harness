package com.meztking.roundtable.runtime

import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.LocalAccess
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
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
import java.net.InetAddress

/**
 * The whole "This phone" path on the JVM: install a made-up release, start it with a fake proot that stands
 * up a local server on the port it was given, and talk to it the way the app does.
 */
class RuntimeControllerTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var fx: RuntimeFixture
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var roundtable = MockWebServer()
    private var launched: List<String> = emptyList()
    private var launchEnv: Map<String, String> = emptyMap()

    @Before fun setUp() { fx = RuntimeFixture(tmp) }
    @After fun tearDown() { scope.cancel(); fx.close(); runCatching { roundtable.shutdown() } }

    /** A "proot" that serves Roundtable's API on the port in its argv, checking the token from its environment. */
    /** Releases whose start fails at once (a made-up bad release). */
    private var broken: Set<String> = emptySet()
    private var starts = 0

    private val launcher = ProcessLauncher { argv, environment, _, _ ->
        starts++
        if (broken.any { b -> argv.any { "roundtable-roundtable-$b-" in it } }) {
            val exit = CompletableDeferred(3)
            return@ProcessLauncher object : HarnessProcess {
                override suspend fun readLine(): String? = null
                override suspend fun awaitExit(): Int = exit.await()
                override val isAlive: Boolean get() = false
            }
        }
        launched = argv
        launchEnv = environment
        runCatching { roundtable.shutdown() }
        roundtable = MockWebServer()
        val token = environment.getValue(ProotCommand.TOKEN_ENV)
        roundtable.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.path == "/api/health" -> MockResponse().setBody("""{"ok": true}""")
                request.getHeader("Authorization") != "Bearer $token" -> MockResponse().setResponseCode(401).setBody("""{"error": "wrong token"}""")
                request.path == "/api/roundtable" -> MockResponse().setBody("""{"seats": []}""")
                else -> MockResponse().setResponseCode(404)
            }
        }
        roundtable.start(InetAddress.getByName("127.0.0.1"), argv[argv.indexOf("--port") + 1].toInt())
        val lines = Channel<String>(Channel.UNLIMITED).apply { trySend("4242"); trySend("Roundtable is ready on http://127.0.0.1:${argv[argv.indexOf("--port") + 1]}") }
        val exit = CompletableDeferred<Int>()
        object : HarnessProcess {
            override suspend fun readLine(): String? = lines.receiveCatching().getOrNull()
            override suspend fun awaitExit(): Int = exit.await()
            override val isAlive: Boolean get() = !exit.isCompleted
        }
    }

    private val noProcs = object : ProcessTable {
        override val selfPid = 1
        override fun snapshot() = emptyList<ProcInfo>()
        override fun signal(pid: Int, signal: Int) {}
        override fun isAlive(pid: Int) = false
    }

    private fun controller(): RuntimeController {
        val log = RotatingLog(File(fx.layout.logs, "roundtable.log"))
        return RuntimeController(
            fx.layout, fx.installer(), HarnessSupervisor(scope, launcher, noProcs, log), log, fx.fs,
            nativeLibraryDir = { File("/data/app/x/lib/x86_64") }, dnsServers = { listOf("10.0.2.3") }, cpuCount = { 4 },
            scope = scope, inherited = { setOf("ANDROID_ROOT") },
        )
    }

    @Test
    fun `not set up, there is no token to have`() = runBlocking {
        val c = controller()
        assertEquals(RuntimeState.NotInstalled, c.state.value)
        try { c.token(); fail("expected NotRunning") } catch (e: RuntimeController.NotRunningException) { }
    }

    @Test
    fun `set up, start, and the app's client gets in with the token while the log never holds it`() = runBlocking {
        fx.publish(fx.baseLayer(), fx.roundtableLayer("0.8.0"), sequence = 1)
        val c = controller()
        c.install()
        val running = withTimeout(30_000) { c.state.first { it is RuntimeState.Running || it is RuntimeState.Failed } }
        assertTrue("got $running", running is RuntimeState.Running)
        val token = c.token()
        assertFalse(launched.any { token in it })
        assertEquals(token, launchEnv[ProotCommand.TOKEN_ENV])
        val api = Api.thisPhone(object : LocalAccess {
            override fun port() = c.port()
            override suspend fun token() = c.token()
        })
        assertEquals(0, api.roundtable().seats.size)
        assertFalse(File(fx.layout.logs, "roundtable.log").readText().contains(token))
        assertTrue(File(fx.layout.run, "resolv.conf").readText().contains("nameserver 10.0.2.3"))
    }

    @Test
    fun `a bad update is tried twice, the previous release comes back with one line, and it is not retried by itself`() = runBlocking {
        val base = fx.baseLayer()
        fx.publish(base, fx.roundtableLayer("0.8.0"), sequence = 1)
        val c = controller()
        c.install()
        assertTrue(withTimeout(30_000) { c.state.first { it is RuntimeState.Running || it is RuntimeState.Failed } } is RuntimeState.Running)
        broken = setOf("0.8.1")
        fx.publish(base, fx.roundtableLayer("0.8.1"), sequence = 2)
        starts = 0
        c.check()
        c.install()
        val notice = withTimeout(60_000) { c.notice.first { it != null } }!!
        val after = withTimeout(30_000) { c.state.first { it is RuntimeState.Running || it is RuntimeState.Failed } }
        assertTrue("got $after", after is RuntimeState.Running)
        assertEquals("0.8.0", c.installed!!.version)
        assertEquals(3, starts) // two tries of the new one, then the old one
        assertTrue(notice.plain().contains("didn't start"))
        assertFalse(notice.plain().contains("Exception"))
        assertTrue(c.check() is RuntimeInstaller.CheckResult.HeldBack)
    }
}
