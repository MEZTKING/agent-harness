package com.meztking.roundtable.data.browser

import com.meztking.roundtable.ui.browser.BrowserGo
import com.meztking.roundtable.ui.browser.browserGo
import org.junit.Test

/** DS-81 on the phone: what opens, and the PC's localhost said plainly. */
class BrowserTabTest {
    private val pc = BrowserConnection.Pc("192.168.1.20", 8766)

    @Test
    fun `this phone opens its own localhost`() {
        assertEquals(BrowserGo.Load("http://localhost:5173/"), browserGo("localhost:5173", BrowserConnection.ThisPhone))
    }

    @Test
    fun `the PC's localhost is never loaded on the phone, the PC's address is offered`() {
        val g = browserGo("http://localhost:5173/app?x=1", pc)
        assertIs<BrowserGo.Stop>(g)
        assertTrue(g.words.contains("PC's own localhost"))
        assertEquals("http://192.168.1.20:5173/app?x=1", g.offer)
        // 0.0.0.0 as dev servers print it is the PC's localhost too
        assertIs<BrowserGo.Stop>(browserGo("http://0.0.0.0:3000", pc))
        // over Tailscale (100.64/10) the address is offered as well
        assertEquals("http://100.101.1.2:3000/", (browserGo("localhost:3000", BrowserConnection.Pc("100.101.1.2", 8766)) as BrowserGo.Stop).offer)
        // hub mode knows no PC address: said, nothing offered
        val hub = browserGo("localhost:3000", BrowserConnection.Hub)
        assertIs<BrowserGo.Stop>(hub)
        assertNull(hub.offer)
    }

    @Test
    fun `a page on the Wi-Fi opens, the PC's phone link does not, nor anything but web pages`() {
        assertEquals(BrowserGo.Load("http://192.168.1.20:5173/"), browserGo("192.168.1.20:5173", pc))
        assertIs<BrowserGo.Stop>(browserGo("http://192.168.1.20:8766/api/ping", pc))
        for (bad in listOf("javascript:alert(1)", "file:///sdcard/x", "intent://x#Intent;end", "content://x", "http://a@b.test/", "")) {
            assertIs<BrowserGo.Stop>(browserGo(bad, pc), bad)
        }
    }

    @Test
    fun `the pages the agent mentioned, newest first and each once`() {
        val texts = listOf("Local: http://localhost:5173/ and https://example.com", "Now on http://localhost:3000.", "again http://localhost:5173/")
        assertEquals(listOf("http://localhost:5173/", "http://localhost:3000/"), mentionedLocalAddresses(texts))
    }
}
