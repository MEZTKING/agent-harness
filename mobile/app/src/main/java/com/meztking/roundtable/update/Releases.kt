package com.meztking.roundtable.update

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.io.File
import java.security.MessageDigest

/** Where the phone's updates come from: the desktop app's own releases. Never change it (tests/test_passage.py). */
const val UPDATE_REPO = "MEZTKING/agent-harness"
const val RELEASES_URL = "https://api.github.com/repos/$UPDATE_REPO/releases?per_page=30"
const val RELEASES_PAGE = "https://github.com/$UPDATE_REPO/releases"

/** Check when the app opens at most this often. */
const val CHECK_EVERY_MS = 4L * 60 * 60 * 1000

/** The parts of a GitHub release this app reads. */
@Serializable
data class GhRelease(
    @SerialName("tag_name") val tag: String = "",
    val name: String? = null,
    val body: String? = null,
    val draft: Boolean = false,
    val prerelease: Boolean = false,
    @SerialName("html_url") val page: String = "",
    @SerialName("published_at") val published: String? = null,
    val assets: List<GhAsset> = emptyList(),
)

@Serializable
data class GhAsset(
    val name: String = "",
    @SerialName("browser_download_url") val url: String = "",
    val size: Long = -1,
    /** "sha256:<hex>" on releases made since mid-2025; null on older ones. */
    val digest: String? = null,
)

/** A phone build that can be installed: the version, its notes and the APK to fetch. */
@Serializable
data class AppRelease(
    val version: String,
    val notes: String = "",
    val page: String = RELEASES_PAGE,
    val apkName: String,
    val apkUrl: String,
    val size: Long = -1,
    /** Lower-case hex, or null when GitHub gave no digest. */
    val sha256: String? = null,
)

/** The phone's test build attached to the desktop release v<version>, under its name from 1.0.0. */
fun apkNameFor(version: String) = "$APK_PREFIX$version$APK_SUFFIX"

/** The same build under its name before 1.0.0. Every 1.x release carries both, for phones not yet updated. */
fun legacyApkNameFor(version: String) = "$LEGACY_APK_PREFIX$version$APK_SUFFIX"

/** Both names, the new one first: the one taken when a release has both. */
fun apkNamesFor(version: String) = listOf(apkNameFor(version), legacyApkNameFor(version))

const val APK_PREFIX = "DarknessMobile-"
const val LEGACY_APK_PREFIX = "RoundtableMobile-"
private const val APK_SUFFIX = "-test.apk"

/** The version in a downloaded APK's file name (either name), or null when it isn't one of ours. */
fun versionOfApk(fileName: String): String? {
    if (!fileName.endsWith(APK_SUFFIX)) return null
    val prefix = listOf(APK_PREFIX, LEGACY_APK_PREFIX).firstOrNull { fileName.startsWith(it) } ?: return null
    return fileName.removePrefix(prefix).removeSuffix(APK_SUFFIX).takeIf { it.isNotBlank() }
}

private val RELEASE_TAG = Regex("^v[0-9]+(\\.[0-9]+)*$")
private val SHA256_HEX = Regex("^[0-9a-f]{64}$")

/**
 * Is [candidate] a later version than [current]? Numbers part by part (0.7.10 is after 0.7.9); a `v`
 * in front and anything after `-` or `+` are ignored. Anything unreadable means "not newer", never a crash.
 * (Borrowed from DSH Mobile's UpdateChecker.isNewerVersion.)
 */
fun isNewerVersion(candidate: String, current: String): Boolean {
    fun parts(value: String): List<Int> = value.trim().removePrefix("v").substringBefore('-').substringBefore('+')
        .split('.').map { it.trim().toIntOrNull() ?: 0 }
    val a = parts(candidate)
    val b = parts(current)
    if (a.all { it == 0 }) return false
    for (i in 0 until maxOf(a.size, b.size)) {
        val left = a.getOrElse(i) { 0 }
        val right = b.getOrElse(i) { 0 }
        if (left != right) return left > right
    }
    return false
}

/** "sha256:ABC…" to "abc…"; null when it's missing or not a SHA-256. */
fun sha256FromDigest(digest: String?): String? {
    val d = digest?.trim() ?: return null
    if (!d.startsWith("sha256:", ignoreCase = true)) return null
    return d.substring(7).lowercase().takeIf { SHA256_HEX.matches(it) }
}

/**
 * The newest phone build among [releases]: only published `v<number>` releases (not drafts, not
 * pre-releases such as `runtime-…`), and only those that carry the phone's APK under either name
 * (DarknessMobile-… from 1.0.0, RoundtableMobile-… before). Null when there is none.
 */
fun pickRelease(releases: List<GhRelease>): AppRelease? = releases
    .filter { !it.draft && !it.prerelease && RELEASE_TAG.matches(it.tag) }
    .mapNotNull { r ->
        val version = r.tag.removePrefix("v")
        val apk = apkNamesFor(version).firstNotNullOfOrNull { want ->
            r.assets.firstOrNull { it.name == want && it.url.startsWith("https://") }
        } ?: return@mapNotNull null
        AppRelease(version, r.body.orEmpty(), r.page.ifBlank { RELEASES_PAGE }, apk.name, apk.url, apk.size, sha256FromDigest(apk.digest))
    }
    .reduceOrNull { best, r -> if (isNewerVersion(r.version, best.version)) r else best }

/** Time for another check when the app opens: never checked, 4 hours gone, or the clock went backwards. */
fun checkDue(now: Long, lastChecked: Long, every: Long = CHECK_EVERY_MS): Boolean =
    lastChecked <= 0L || now < lastChecked || now - lastChecked >= every

/** The first few lines of the release notes, without Markdown marks, for the card. */
fun notesPreview(notes: String, lines: Int = 3, maxChars: Int = 240): String {
    val plain = notes.lineSequence()
        .map { it.trim().trimStart('#', '-', '*', '>', ' ').replace("**", "").replace("`", "").trim() }
        .filter { it.isNotEmpty() }
        .take(lines)
        .joinToString(" · ")
    return if (plain.length > maxChars) plain.take(maxChars).trimEnd() + "…" else plain
}

/** Lower-case hex SHA-256 of [file]. (Borrowed from DSH Mobile's Checksums.sha256Of.) */
fun sha256Of(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

/** Why a downloaded file isn't the release's file, in words for the owner; null when it is. */
fun verifyDownload(file: File, release: AppRelease): String? {
    if (!file.isFile) return "The download is missing. Tap Download and install to try again."
    if (release.size > 0 && file.length() != release.size) {
        return "The download came out the wrong size, so it wasn't installed. Tap Download and install to fetch it again."
    }
    val want = release.sha256 ?: return null
    if (sha256Of(file) != want) {
        return "The download doesn't match the release (it may have been damaged on the way), so it wasn't installed. " +
            "Tap Download and install to fetch it again."
    }
    return null
}
