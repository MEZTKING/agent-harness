package com.meztking.roundtable.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The rename to Darkness Harness (1.0.0): the phone finds its update under either APK name. */
class ReleasesNamesTest {
    private fun asset(name: String, size: Long = 10) =
        GhAsset(name, "https://github.com/x/y/releases/download/$name", size)

    private fun rel(tag: String, vararg assets: GhAsset) = GhRelease(tag, body = "notes", assets = assets.toList())

    @Test fun theNamesAreTheOnesTheWorkflowUploads() {
        assertEquals("DarknessMobile-1.0.0-test.apk", apkNameFor("1.0.0"))
        assertEquals("RoundtableMobile-1.0.0-test.apk", legacyApkNameFor("1.0.0"))
        assertEquals(listOf("DarknessMobile-1.0.0-test.apk", "RoundtableMobile-1.0.0-test.apk"), apkNamesFor("1.0.0"))
    }

    @Test fun aReleaseWithOnlyTheOldNameIsFound() {
        val r = pickRelease(listOf(rel("v0.12.0", asset("RoundtableMobile-0.12.0-test.apk"))))!!
        assertEquals("0.12.0", r.version)
        assertEquals("RoundtableMobile-0.12.0-test.apk", r.apkName)
    }

    @Test fun aReleaseWithOnlyTheNewNameIsFound() {
        val r = pickRelease(listOf(rel("v1.1.0", asset("DarknessMobile-1.1.0-test.apk"))))!!
        assertEquals("DarknessMobile-1.1.0-test.apk", r.apkName)
    }

    @Test fun withBothNamesTheNewOneIsTaken() {
        val r = pickRelease(listOf(rel("v1.0.0",
            asset("DarknessHarness-Setup-1.0.0.exe"),
            asset("RoundtableMobile-1.0.0-test.apk", 7),
            asset("DarknessMobile-1.0.0-test.apk", 7),
        )))!!
        assertEquals("DarknessMobile-1.0.0-test.apk", r.apkName)
    }

    @Test fun theNewestWinsAcrossTheRename() {
        val r = pickRelease(listOf(
            rel("v0.12.0", asset("RoundtableMobile-0.12.0-test.apk")),
            rel("v1.0.0", asset("DarknessMobile-1.0.0-test.apk"), asset("RoundtableMobile-1.0.0-test.apk")),
        ))!!
        assertEquals("1.0.0", r.version)
    }

    @Test fun anApkForAnotherVersionOrAnotherAppIsNotTaken() {
        assertNull(pickRelease(listOf(rel("v1.0.0", asset("DarknessMobile-0.9.0-test.apk")))))
        assertNull(pickRelease(listOf(rel("v1.0.0", asset("SomethingElse-1.0.0-test.apk")))))
        assertNull(pickRelease(listOf(rel("v1.0.0", GhAsset("DarknessMobile-1.0.0-test.apk", "http://example.com/a.apk")))))
    }

    @Test fun versionsOfDownloadedFiles() {
        assertEquals("1.0.0", versionOfApk("DarknessMobile-1.0.0-test.apk"))
        assertEquals("0.12.0", versionOfApk("RoundtableMobile-0.12.0-test.apk"))
        assertNull(versionOfApk("notes.txt"))
        assertNull(versionOfApk("DarknessMobile--test.apk"))
    }

    @Test fun theIdsMachinesReadStayPut() {
        assertEquals("MEZTKING/agent-harness", UPDATE_REPO)
        // the package's name is the applicationId's root: the phone keeps its pairing and keys over the rename
        val gradle = listOf(File("build.gradle.kts"), File("app/build.gradle.kts")).first { it.isFile && it.readText().contains("applicationId") }
        val text = gradle.readText()
        assertTrue("applicationId changed in ${gradle.path}", text.contains("applicationId = \"com.meztking.roundtable\""))
        assertTrue("namespace changed in ${gradle.path}", text.contains("namespace = \"com.meztking.roundtable\""))
    }
}
