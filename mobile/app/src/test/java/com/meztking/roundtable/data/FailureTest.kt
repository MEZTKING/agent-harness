package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiException
import com.meztking.roundtable.runtime.RuntimeFailure
import com.meztking.roundtable.ui.friendly
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.security.cert.CertificateException
import java.security.cert.CertificateNotYetValidException

/** DS-11: every error a screen can show is a named failure, never raw text. */
class FailureTest {
    private val raw = listOf(
        "java.lang.IllegalStateException: boom", "TypeError: 'NoneType' object is not subscriptable", "HTTP 502",
        "{\"detail\": \"x\"}", "Unexpected JSON token at offset 0", "unexpected end of stream on http://10.0.0.2:8765/...",
        "Traceback (most recent call last):", "  at com.meztking.roundtable.net.Api.call(Api.kt:54)", "null",
        "KeyError: 'plan_id'", "Expected start of the object '{', but had 'EOF' instead", "failed to connect to /192.168.1.4 (port 8765)",
        "ECONNREFUSED", "Read timed out", "SSL handshake aborted: ssl=0x7b: I/O error", "no_such_route",
    )

    private val throwables: List<Throwable> = buildList {
        for (r in raw) {
            add(IOException(r)); add(RuntimeException(r)); add(IllegalStateException(r)); add(IOException("wrap", Exception(r)))
            for (status in listOf(0, 400, 401, 403, 404, 409, 422, 429, 500, 502)) add(ApiException(r, status))
        }
        add(java.net.UnknownHostException("api.github.com")); add(java.net.SocketTimeoutException("timeout"))
        add(java.net.ConnectException("Connection refused")); add(kotlinx.serialization.SerializationException("Field 'x' is required"))
        add(OutOfMemoryError("Java heap space")); add(NullPointerException()); add(Exception())
        add(IOException("x", CertificateNotYetValidException("NotBefore: Fri"))); add(javax.net.ssl.SSLHandshakeException("pin"))
    }

    @Test
    fun `no raw error text reaches a screen`() {
        val allowed = Failure.entries.map { it.sentence }.toSet()
        for (t in throwables) {
            val shown = friendly(t)
            assertTrue("$t showed: $shown", shown in allowed)
            for (r in raw) assertFalse("$t leaked $r", r.length > 4 && shown.contains(r))
        }
    }

    @Test
    fun `every exception type maps to a named failure`() {
        assertEquals(Failure.OFFLINE, Failure.of(java.net.UnknownHostException("x")))
        assertEquals(Failure.TOO_SLOW, Failure.of(java.net.SocketTimeoutException("x")))
        assertEquals(Failure.PC_APP_NOT_RUNNING, Failure.of(java.net.ConnectException("x")))
        assertEquals(Failure.NOT_UNDERSTOOD, Failure.of(kotlinx.serialization.SerializationException("x")))
        assertEquals(Failure.CLOCKS_APART, Failure.of(IOException("x", CertificateNotYetValidException("x"))))
        assertEquals(Failure.PC_IDENTITY_CHANGED, Failure.of(IOException("x", CertificateException("x"))))
        assertEquals(Failure.UNKNOWN, Failure.of(NullPointerException()))
    }

    @Test
    fun `pairing, hub and pc answers are named`() {
        // the PC's pairing answers (phone.py claim)
        assertEquals(Failure.WRONG_CODE, Failure.of(ApiException("That code isn't right: check the code on the PC and type it again.", 403)))
        assertEquals(Failure.CODE_EXPIRED, Failure.of(ApiException("The PC isn't waiting for a phone (the code lasts 5 minutes): press Pair a phone on the PC and try again.", 403)))
        assertEquals(Failure.TOO_MANY_CODES, Failure.of(ApiException("Too many wrong codes: press Pair a phone on the PC for a new one.", 403)))
        assertEquals(Failure.NOT_PAIRED, Failure.of(ApiException("This phone isn't paired with the PC (or was removed): pair it again from the PC's Settings.", 401)))
        // Api.friendly's words when no address answered
        assertEquals(Failure.PC_APP_NOT_RUNNING, Failure.of(ApiException("can't reach your PC. Is it on, with Darkness open and phone access on?", 0)))
        assertEquals(Failure.PC_IDENTITY_CHANGED, Failure.of(ApiException("this isn't your PC: its certificate doesn't match.", 0)))
        assertEquals(Failure.PC_TOO_OLD, Failure.of(ApiException("HTTP 404", 404)))
        assertEquals(Failure.PC_ONLY, Failure.of(ApiException("That can only be done on the PC itself.", 403)))
        assertEquals(Failure.PC_TROUBLE, Failure.of(ApiException("TypeError: x", 500)))
        // GitHubHub throws the list's own sentences
        assertEquals(Failure.KEY_EXPIRED, Failure.of(ApiException(Failure.KEY_EXPIRED.sentence, 401)))
        assertEquals(Failure.KEY_CANT_WRITE, Failure.of(ApiException("GitHub refused access", 403)))
        assertEquals(Failure.TOO_MANY_REQUESTS, Failure.of(ApiException("GitHub: API rate limit exceeded", 403)))
        assertEquals(Failure.REPO_MISSING, Failure.of(ApiException("GitHub: not found", 404)))
    }

    @Test
    fun `the harness's own plain sentences still get through, machine text does not`() {
        assertEquals("No plan yet: write the idea first.", friendly(ApiException("No plan yet: write the idea first.", 400)))
        assertEquals(Failure.UNKNOWN.sentence, friendly(ApiException("KeyError: 'plan_id'", 400)))
        assertEquals(Failure.UNKNOWN.sentence, friendly(ApiException("No plan yet: write the idea first.", 0)))
    }

    @Test
    fun `every failure has one sentence and one button`() {
        for (f in Failure.entries) {
            assertTrue(f.name, (f.sentence.endsWith(".") || f.sentence.endsWith("?")) && f.sentence.length < 200)
            assertTrue(f.name, f.button.isNotBlank() && f.button.length <= 20)
            assertEquals(f, Failure.ofSentence(f.sentence))
        }
    }

    @Test
    fun `the runtime's failures carry no raw detail`() {
        val detail = "java.io.IOException: EACCES (Permission denied)"
        for (f in listOf(RuntimeFailure.Storage(detail), RuntimeFailure.BadManifest(detail), RuntimeFailure.StartFailed(detail))) {
            assertFalse(f.plain().contains("EACCES"))
        }
    }
}
