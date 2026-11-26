package com.meztking.roundtable.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairingTest {
    private val fp = "ab".repeat(32)

    @Test fun parsesTheQrLink() {
        val o = Pairing.parse("roundtable://pair?v=1&n=My%20PC&h=192.168.1.5,100.64.0.2&p=8766&c=ABCD2345&f=$fp")!!
        assertEquals(PairingOffer("My PC", listOf("192.168.1.5", "100.64.0.2"), 8766, "ABCD2345", fp), o)
    }

    @Test fun codeMayBeTypedInstead() {
        val o = Pairing.parse("  roundtable://pair?v=1&h=10.0.0.2&p=8766&f=${fp.uppercase()}  ")!!
        assertEquals("", o.code)
        assertEquals("PC", o.pcName)
        assertEquals(fp, o.fingerprint)
    }

    @Test fun ipv6AndLowercaseCode() {
        val o = Pairing.parse("roundtable://pair?v=1&n=x&h=fe80%3A%3A1&p=9000&c=abcd2345&f=$fp")!!
        assertEquals(listOf("fe80::1"), o.hosts)
        assertEquals("ABCD2345", o.code)
    }

    @Test fun rejectsWhatIsNotAPairingLink() {
        assertNull(Pairing.parse("https://example.com"))
        assertNull(Pairing.parse("roundtable://pair?v=2&h=1.2.3.4&p=1&c=ABCDEFGH&f=$fp")) // unknown version
        assertNull(Pairing.parse("roundtable://pair?v=1&h=&p=8766&c=ABCDEFGH&f=$fp")) // no address
        assertNull(Pairing.parse("roundtable://pair?v=1&h=1.2.3.4&p=x&c=ABCDEFGH&f=$fp")) // no port
        assertNull(Pairing.parse("roundtable://pair?v=1&h=1.2.3.4&p=8766&c=ABC&f=$fp")) // code too short
        assertNull(Pairing.parse("roundtable://pair?v=1&h=1.2.3.4&p=8766&c=ABCDEFGH&f=1234")) // bad fingerprint
        assertNull(Pairing.parse("roundtable://pair?v=1&h=1.2.3.4&p=8766&c=%ZZ&f=$fp")) // bad escape: no crash
        assertNull(Pairing.parse(""))
    }
}
