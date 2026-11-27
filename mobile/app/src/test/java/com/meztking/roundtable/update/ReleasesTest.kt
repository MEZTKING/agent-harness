package com.meztking.roundtable.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class ReleasesTest {
    private fun apk(v: String, digest: String? = null, size: Long = 10) =
        GhAsset(apkNameFor(v), "https://github.com/x/y/releases/download/v$v/${apkNameFor(v)}", size, digest)

    private fun rel(tag: String, vararg assets: GhAsset, draft: Boolean = false, pre: Boolean = false) =
        GhRelease(tag, body = "notes for $tag", draft = draft, prerelease = pre, assets = assets.toList())

    @Test fun versionsCompareNumberByNumber() {
        assertTrue(isNewerVersion("0.7.4", "0.7.3"))
        assertTrue(isNewerVersion("0.7.10", "0.7.9"))
        assertTrue(isNewerVersion("v1.0", "0.9.9"))
        assertTrue(isNewerVersion("0.8", "0.7.12"))
        assertFalse(isNewerVersion("0.7.3", "0.7.3"))
        assertFalse(isNewerVersion("0.7.3", "0.7.3.0"))
        assertFalse(isNewerVersion("0.7.2", "0.7.10"))
        assertFalse(isNewerVersion("0.7.3-rc1", "0.7.3"))
        assertFalse(isNewerVersion("rubbish", "0.7.3"))
    }

    @Test fun picksTheNewestPublishedPhoneBuild() {
        val r = pickRelease(listOf(
            rel("runtime-2026.11.26-1", apk("2026.11.26"), pre = true),
            rel("v0.8.0", apk("0.8.0"), draft = true),
            rel("v0.7.5", apk("0.7.5"), pre = true),
            rel("v0.7.4", GhAsset("RoundtableHold-Setup-0.7.4.exe", "https://github.com/a.exe")), // no phone APK
            rel("v0.7.10", apk("0.7.10", "sha256:" + "AB".repeat(32), 1234)),
            rel("v0.7.9", apk("0.7.9")),
            rel("nightly", apk("9.9.9")),
        ))!!
        assertEquals("0.7.10", r.version)
        assertEquals("DarknessMobile-0.7.10-test.apk", r.apkName)
        assertEquals("ab".repeat(32), r.sha256)
        assertEquals(1234L, r.size)
        assertEquals("notes for v0.7.10", r.notes)
    }

    @Test fun nothingToPick() {
        assertNull(pickRelease(emptyList()))
        assertNull(pickRelease(listOf(rel("runtime-1", apk("1"), pre = true), rel("v0.9.0", apk("0.9.0"), draft = true))))
        // the APK must be the one for that version, and over https
        assertNull(pickRelease(listOf(rel("v0.9.0", apk("0.8.0")))))
        assertNull(pickRelease(listOf(rel("v0.9.0", GhAsset(apkNameFor("0.9.0"), "http://example.com/a.apk")))))
    }

    @Test fun digests() {
        assertEquals("0f".repeat(32), sha256FromDigest("sha256:" + "0F".repeat(32)))
        assertNull(sha256FromDigest(null))
        assertNull(sha256FromDigest("md5:abc"))
        assertNull(sha256FromDigest("sha256:short"))
    }

    @Test fun theDownloadIsChecked() {
        val f = Files.createTempFile("rt", ".apk").toFile()
        f.writeText("hello")
        val hash = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" // sha256("hello")
        val good = AppRelease("1.0", apkName = "a", apkUrl = "https://x", size = 5, sha256 = hash)
        assertNull(verifyDownload(f, good))
        assertNull(verifyDownload(f, good.copy(sha256 = null, size = -1))) // no digest from GitHub: the size is enough
        assertTrue(verifyDownload(f, good.copy(size = 6))!!.contains("wrong size"))
        assertTrue(verifyDownload(f, good.copy(sha256 = "0".repeat(64)))!!.contains("doesn't match"))
        assertTrue(verifyDownload(File(f.parent, "missing.apk"), good)!!.contains("missing"))
        f.delete()
    }

    @Test fun checksAtMostEveryFourHours() {
        val h = 60L * 60 * 1000
        val last = 100 * h
        assertTrue(checkDue(last, 0))                    // never checked
        assertFalse(checkDue(last + 1, last))
        assertFalse(checkDue(last + 4 * h - 1, last))
        assertTrue(checkDue(last + 4 * h, last))
        assertTrue(checkDue(last - h, last))             // the clock went back: check
    }

    @Test fun notesForTheCard() {
        assertEquals("What's new · Faster table · A **bold** fix".replace("**", ""),
            notesPreview("## What's new\n\n- Faster table\n* A **bold** fix\n- Not shown"))
        assertEquals("", notesPreview(""))
        assertTrue(notesPreview("x".repeat(500)).endsWith("…"))
    }
}
