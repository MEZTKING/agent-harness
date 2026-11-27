package com.meztking.roundtable.net

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.ui.FindPcCard
import com.meztking.roundtable.ui.FindPcContent
import com.meztking.roundtable.ui.FindPcState
import com.meztking.roundtable.ui.theme.Panel
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import kotlin.concurrent.thread

class DiscoveryTest {
    private val fp = "ab".repeat(32)
    private val other = "cd".repeat(32)
    private val link = PcLink("desk-pc", listOf("192.168.1.5", "100.64.0.2"), 8766, fp, "token")

    @Test fun `the code check is the PC's own`() {
        // made on the PC by discovery.py bound_code (the same fingerprint and first six letters)
        assertTrue(Discovery.codeMatches("ABCDEFMV", fp))
        assertTrue(Discovery.codeMatches("abcdefmv", fp.uppercase()))
        assertTrue(Discovery.codeMatches("K7M2PQ5J", "0123456789abcdef".repeat(4)))
        assertTrue(Discovery.codeMatches("ABCDEFZQ", other))
        assertTrue(Discovery.codeMatches("ABCDEFMV", fp.chunked(2).joinToString(":")))
    }

    @Test fun `a code fails for another certificate`() {
        assertFalse(Discovery.codeMatches("ABCDEFMV", other)) // a stand-in PC
        assertFalse(Discovery.codeMatches("ABCDEFZQ", fp))
        assertFalse(Discovery.codeMatches("ABCDEFMW", fp))
        for (bad in listOf("", "ABC", "ABCDEFM0", "ABCDEFMVX", "ABCDEF  ")) assertFalse(bad, Discovery.codeMatches(bad, fp))
        val e = runCatching { Discovery.requireCode("ABCDEFMV", other) }.exceptionOrNull()
        assertTrue(e is ApiException && e.message == Discovery.CODE_MISMATCH)
        Discovery.requireCode("ABCDEFMV", fp) // no error
    }

    @Test fun `answers are read carefully`() {
        val good = """{"v":1,"name":"desk-pc","port":8766,"fp":"${fp.uppercase()}"}"""
        assertEquals(FoundPc("desk-pc", "192.168.1.30", 8766, fp), Discovery.parseReply(good, "192.168.1.30"))
        assertNull(Discovery.parseReply(good, "8.8.8.8")) // not from a home network
        assertNull(Discovery.parseReply(good, "100.64.0.2")) // Tailscale isn't a Wi-Fi neighbour
        for (bad in listOf("", "nonsense", "[]", """{"v":2,"port":8766,"fp":"$fp"}""", """{"v":1,"port":0,"fp":"$fp"}""",
                """{"v":1,"port":8766,"fp":"1234"}""", """{"v":1,"port":"x","fp":"$fp"}""", """{"v":1,"port":8766,"fp":5}""")) {
            assertNull(bad, Discovery.parseReply(bad, "192.168.1.30"))
        }
        for (ip in listOf("10.0.0.1", "172.16.4.4", "172.31.0.1", "192.168.0.9", "169.254.1.1", "127.0.0.1")) assertTrue(ip, Discovery.isPrivate(ip))
        for (ip in listOf("172.32.0.1", "1.1.1.1", "fe80::1", "192.168.1", "300.1.1.1", "")) assertFalse(ip, Discovery.isPrivate(ip))
    }

    @Test fun `a wrong fingerprint is never taken for the paired PC`() {
        val stranger = FoundPc("desk-pc", "192.168.1.66", 8766, other) // same name, another certificate
        assertNull(Discovery.relocated(link, listOf(stranger)))
        assertNull(Discovery.relocated(link, emptyList()))
        val moved = Discovery.relocated(link, listOf(stranger, FoundPc("desk-pc", "192.168.1.77", 8770, fp.uppercase())))!!
        assertEquals(listOf("192.168.1.77", "192.168.1.5", "100.64.0.2"), moved.hosts)
        assertEquals(8770, moved.port)
        assertEquals(fp, moved.fingerprint) // the pin never changes
        assertEquals("token", moved.token)
        val same = Discovery.relocated(link, listOf(FoundPc("desk-pc", "192.168.1.5", 8766, fp)))!!
        assertEquals(link.hosts, same.hosts)
    }

    @Test fun `a found PC becomes an offer without the code`() {
        val f = FoundPc("Desk PC", "192.168.1.30", 8766, fp)
        assertEquals(PairingOffer("Desk PC", listOf("192.168.1.30"), 8766, "", fp), f.toOffer())
        assertEquals(f.toOffer(), Pairing.parse(f.toLink()))
        assertEquals("PC", FoundPc("", "10.0.0.2", 8766, fp).toOffer().pcName)
    }

    @Test fun `the probe finds a PC that answers, and only proper answers`() = runBlocking {
        DatagramSocket(0, InetAddress.getByName("127.0.0.1")).use { pc ->
            pc.soTimeout = 3000
            val t = thread {
                val buf = ByteArray(64)
                val p = DatagramPacket(buf, buf.size)
                pc.receive(p)
                if (String(p.data, 0, p.length) != Discovery.PROBE) return@thread
                for (answer in listOf("junk", """{"v":1,"name":"desk-pc","port":8766,"fp":"$fp"}""", """{"v":1,"name":"desk-pc","port":8766,"fp":"$fp"}""")) {
                    val b = answer.toByteArray()
                    pc.send(DatagramPacket(b, b.size, p.socketAddress))
                }
            }
            val found = Discovery.probe(listOf(InetSocketAddress("127.0.0.1", pc.localPort)), 800)
            t.join()
            assertEquals(listOf(FoundPc("desk-pc", "127.0.0.1", 8766, fp)), found) // one per PC
        }
    }

    @Test fun `nothing answering gives an empty list quickly`() = runBlocking {
        DatagramSocket(0, InetAddress.getByName("127.0.0.1")).use { quiet ->
            val start = System.currentTimeMillis()
            assertTrue(Discovery.probe(listOf(InetSocketAddress("127.0.0.1", quiet.localPort)), 300).isEmpty())
            assertTrue(System.currentTimeMillis() - start < 2000)
        }
    }

    @Test fun `the broadcast address is always among the targets`() {
        assertTrue(Discovery.broadcastTargets().any { it.address.hostAddress == "255.255.255.255" && it.port == Discovery.PORT })
    }
}

/** The "Look for my PC" card: its states as pictures, and a tap that hands the PC on (made-up names). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class FindPcCardTest {
    @get:Rule val compose = createComposeRule()
    private val fp = "ab".repeat(32)

    @Test fun `states as pictures`() {
        val dir = System.getProperty("screenshots.dir") ?: "build/screenshots"
        captureRoboImage("$dir/find-pc.png") {
            RoundtableTheme {
                Box(Modifier.fillMaxSize().hallBackground()) {
                    Column(Modifier.padding(16.dp)) {
                        Panel { FindPcContent(FindPcState(), onLook = {}, onPick = {}) }
                        Panel(Modifier.padding(top = 12.dp)) {
                            FindPcContent(FindPcState(found = listOf(FoundPc("Desk PC", "192.168.1.30", 8766, fp),
                                FoundPc("Studio laptop", "192.168.1.41", 8766, "cd".repeat(32))), looked = true), onLook = {}, onPick = {})
                        }
                        Panel(Modifier.padding(top = 12.dp)) { FindPcContent(FindPcState(problem = Discovery.NOTHING, looked = true), onLook = {}, onPick = {}) }
                    }
                }
            }
        }
    }

    @Test fun `looking and picking`() {
        var picked: FoundPc? = null
        val pc = FoundPc("Desk PC", "192.168.1.30", 8766, fp)
        compose.setContent { RoundtableTheme { FindPcCard(onFound = { picked = it }, look = { Discovery.Look(listOf(pc)) }) } }
        compose.onNodeWithText("Look for my PC").performClick()
        compose.waitUntil(3000) { runCatching { compose.onNodeWithText("Desk PC").assertExists() }.isSuccess }
        compose.onNodeWithText("Desk PC").performClick()
        assertEquals(pc, picked)
    }

    @Test fun `nothing found says what to check`() {
        compose.setContent { RoundtableTheme { FindPcCard(onFound = {}, look = { Discovery.Look(emptyList(), Discovery.NOTHING) }) } }
        compose.onNodeWithText("Look for my PC").performClick()
        compose.waitUntil(3000) { runCatching { compose.onNodeWithText(Discovery.NOTHING).assertExists() }.isSuccess }
        compose.onNodeWithText("Look again").assertExists()
    }
}
