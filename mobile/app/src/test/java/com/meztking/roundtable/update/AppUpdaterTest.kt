package com.meztking.roundtable.update

import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class AppUpdaterTest {
    private val server = MockWebServer()
    private val ctx get() = ApplicationProvider.getApplicationContext<android.content.Context>()
    private var clock = 1_000_000_000L

    @Before fun start() {
        server.start()
        ctx.getSharedPreferences("roundtable.update", 0).edit().clear().commit()
    }

    @After fun stop() = server.shutdown()

    private fun updater() = AppUpdater(ctx, server.url("/releases").toString(), OkHttpClient(), now = { clock }, allowedHosts = { true })

    private val bytes = ByteArray(300_000) { (it % 251).toByte() }
    private val hash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun releasesJson(digest: String = hash): String {
        val apkUrl = server.url("/apk").toString().replace("http://", "https://")
        return """[
      {"tag_name":"runtime-2026.11.26-1","prerelease":true,"assets":[{"name":"RoundtableMobile-99.0.0-test.apk","browser_download_url":"${server.url("/bad")}","size":1}]},
      {"tag_name":"v99.0.0","body":"Line one\nLine two","assets":[{"name":"RoundtableMobile-99.0.0-test.apk",
        "browser_download_url":"$apkUrl","size":${bytes.size},"digest":"sha256:$digest"}]}
    ]"""
    }

    @Test fun findsTheUpdateAndRemembersIt() = runBlocking {
        server.enqueue(MockResponse().setBody(releasesJson()))
        val u = updater()
        val found = u.check(quiet = false)!!
        assertEquals("99.0.0", found.version)
        assertEquals("99.0.0", u.state.value.available?.version)
        assertTrue(u.state.value.showBanner)
        u.dismissBanner()
        assertTrue(!u.state.value.showBanner)
        // a new updater (the app opened again) remembers what was found, without asking GitHub
        val again = updater()
        assertEquals("99.0.0", again.state.value.available?.version)
        assertEquals(clock, again.state.value.checkedAt)
        assertTrue(!again.state.value.showBanner)
        assertTrue(u.shouldNotify("99.0.0")); u.markNotified("99.0.0"); assertTrue(!u.shouldNotify("99.0.0"))
        assertEquals(1, server.requestCount)
    }

    @Test fun aCheckThatFailsSaysWhatToDo() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403))
        val u = updater()
        try { u.check(quiet = false); fail() } catch (e: UpdateProblem) { assertTrue(e.message!!.contains("busy")) }
        assertTrue(u.state.value.error!!.contains("Try again"))
        server.enqueue(MockResponse().setResponseCode(500))
        assertNull(u.check(quiet = true)) // quiet: no error shown
    }

    @Test fun downloadsResumesAndChecksTheDigest() = runBlocking {
        val u = updater()
        val rel = AppRelease("99.0.0", apkName = apkNameFor("99.0.0"), apkUrl = server.url("/apk").toString(), size = bytes.size.toLong(), sha256 = hash)
        // the first answer is cut short; the next asks for the rest (Range) and carries on from there
        val ranges = mutableListOf<String?>()
        server.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
            override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest): MockResponse {
                val range = request.getHeader("Range")
                ranges += range
                if (ranges.size == 1) return MockResponse().setBody(Buffer().write(bytes))
                    .setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY)
                val from = range!!.removePrefix("bytes=").removeSuffix("-").toInt()
                return MockResponse().setResponseCode(206).setHeader("Content-Range", "bytes $from-${bytes.size - 1}/${bytes.size}")
                    .setBody(Buffer().write(bytes, from, bytes.size - from))
            }
        }
        val file = u.fetch(rel)
        assertNull(verifyDownload(file, rel))
        assertEquals(hash, sha256Of(file))
        assertEquals(null, ranges[0])
        assertTrue(ranges[1]!!.startsWith("bytes=") && ranges[1] != "bytes=0-")
        // a damaged file is caught before it reaches Android
        file.writeBytes(bytes.copyOf().also { it[5] = 9 })
        assertTrue(verifyDownload(file, rel)!!.contains("doesn't match"))
    }

    @Test fun refusesHostsThatAreNotGitHub() {
        assertTrue(AppUpdater.isGitHubHost("api.github.com"))
        assertTrue(AppUpdater.isGitHubHost("release-assets.githubusercontent.com"))
        assertTrue(!AppUpdater.isGitHubHost("github.com.example.org"))
        assertTrue(!AppUpdater.isGitHubHost("example.com"))
    }
}
