package com.meztking.roundtable.runtime

import org.junit.Assert.assertEquals
import org.junit.Test

class ReleaseFinderTest {
    private fun release(tag: String, draft: Boolean = false, assets: List<String> = listOf("manifest.json", "manifest.json.sig")) = """
        {"tag_name": "$tag", "draft": $draft, "prerelease": true,
         "assets": [${assets.joinToString(",") { """{"name": "$it", "browser_download_url": "https://github.com/MEZTKING/agent-harness/releases/download/$tag/$it"}""" }}]}
    """.trimIndent()

    @Test
    fun `the newest runtime release with a signed manifest is picked`() {
        val listing = "[" + listOf(
            release("v0.7.3"), // the desktop app's own release: not a runtime
            release("runtime-2026.11.27-1", draft = true),
            release("runtime-2026.11.26-2", assets = listOf("manifest.json")), // no signature: skipped
            release("runtime-2026.11.26-1"),
            release("runtime-2026.11.20-1"),
        ).joinToString(",") + "]"
        assertEquals(
            ManifestSource(
                "https://github.com/MEZTKING/agent-harness/releases/download/runtime-2026.11.26-1/manifest.json",
                "https://github.com/MEZTKING/agent-harness/releases/download/runtime-2026.11.26-1/manifest.json.sig",
            ),
            ReleaseFinder.pick(listing),
        )
    }

    @Test
    fun `nothing usable is null`() {
        assertEquals(null, ReleaseFinder.pick("[]"))
        assertEquals(null, ReleaseFinder.pick("{\"message\": \"rate limited\"}"))
        assertEquals(null, ReleaseFinder.pick("[" + release("v0.7.3") + "]"))
    }
}
