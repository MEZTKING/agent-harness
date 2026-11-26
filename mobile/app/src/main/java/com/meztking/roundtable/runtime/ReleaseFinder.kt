package com.meztking.roundtable.runtime

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

/**
 * Finds the newest runtime download: the latest GitHub release of [repo] whose tag starts `runtime-`, and
 * its `manifest.json` and `manifest.json.sig` assets. The repository is public, so no token is sent.
 * Drafts are skipped; pre-releases count (test downloads are published as pre-releases).
 */
class ReleaseFinder(
    private val client: OkHttpClient,
    private val repo: String,
    private val apiBase: String = "https://api.github.com",
) {
    suspend fun latest(): ManifestSource = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$apiBase/repos/$repo/releases?per_page=30")
            .header("Accept", "application/vnd.github+json").build()
        val text = try {
            client.newCall(request).execute().use { r ->
                if (!r.isSuccessful) throw InstallException(RuntimeFailure.Network("GitHub answered HTTP ${r.code}"))
                r.body?.string().orEmpty()
            }
        } catch (e: InstallException) {
            throw e
        } catch (e: IOException) {
            throw InstallException(RuntimeFailure.Network(e.message ?: e.javaClass.simpleName), e)
        }
        pick(text) ?: throw InstallException(RuntimeFailure.NoRelease)
    }

    companion object {
        const val TAG_PREFIX = "runtime-"
        private val json = Json { ignoreUnknownKeys = true }

        /** The first (newest) usable runtime release in a GitHub `releases` listing, or null. */
        fun pick(listing: String): ManifestSource? {
            val releases = runCatching { json.parseToJsonElement(listing) as JsonArray }.getOrNull() ?: return null
            for (item in releases) {
                val release = item as? JsonObject ?: continue
                val tag = release["tag_name"]?.jsonPrimitive?.content.orEmpty()
                if (!tag.startsWith(TAG_PREFIX)) continue
                if (release["draft"]?.jsonPrimitive?.boolean == true) continue
                val assets = (release["assets"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
                fun url(name: String) = assets.firstOrNull { it["name"]?.jsonPrimitive?.content == name }
                    ?.get("browser_download_url")?.jsonPrimitive?.content?.takeIf { it.startsWith("https://") }
                val manifest = url("manifest.json") ?: continue
                val signature = url("manifest.json.sig") ?: continue
                return ManifestSource(manifest, signature)
            }
            return null
        }
    }
}
