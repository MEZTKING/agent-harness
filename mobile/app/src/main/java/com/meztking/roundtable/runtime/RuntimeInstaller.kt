// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/RuntimeInstaller.kt. See THIRD_PARTY_NOTICES.md.
// Trimmed for Roundtable: no update trial, no "go back", no previous release.
package com.meztking.roundtable.runtime

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.io.InputStream

/** Free bytes on the filesystem holding a directory. */
fun interface SpaceProbe {
    fun availableBytes(dir: File): Long
}

data class DownloadProgress(val layer: String, val index: Int, val count: Int, val done: Long, val total: Long)
data class UnpackProgress(val layer: String, val index: Int, val count: Int, val entries: Int, val totalEntries: Int, val bytes: Long)

/** What the installer is doing, for progress. */
sealed interface InstallEvent {
    data object Checking : InstallEvent
    data class Downloading(val progress: DownloadProgress) : InstallEvent
    data class Verifying(val layer: String) : InstallEvent
    data class Unpacking(val progress: UnpackProgress) : InstallEvent
}

/** An install step failed in a way the state can name. */
class InstallException(val failure: RuntimeFailure, cause: Throwable? = null) : IOException(failure.toString(), cause)

/** Where a release's manifest and its signature are. */
data class ManifestSource(val manifestUrl: String, val signatureUrl: String)

/**
 * Downloads, verifies and unpacks runtime releases, and commits them with one atomic write.
 *
 * Plain Kotlin over [FsOps], [SpaceProbe] and an OkHttp client, so the whole flow runs in JVM tests against
 * a local HTTP server. [decoder] turns a downloaded layer into its tar stream (xz on the device).
 */
class RuntimeInstaller(
    private val layout: RuntimeLayout,
    private val store: InstalledStore,
    private val fs: FsOps,
    private val client: OkHttpClient,
    private val downloader: LayerDownloader,
    private val space: SpaceProbe,
    private val source: suspend () -> ManifestSource,
    private val appVersion: () -> String,
    private val deviceAbis: List<String>,
    private val verifier: ManifestVerifier,
    private val allowTest: Boolean,
    private val decoder: (InputStream) -> InputStream,
) {
    sealed interface CheckResult {
        data class Refused(val failure: RuntimeFailure) : CheckResult
        data class UpToDate(val manifest: RuntimeManifest) : CheckResult
        data class Available(val manifest: RuntimeManifest, val decision: ManifestPolicy.Decision.Install) : CheckResult {
            /** Bytes still to fetch, counting what a cut download already has. */
            val downloadBytes: Long get() = decision.downloadBytes
        }
    }

    fun installed(): InstalledRecord? = store.read()

    /** Bytes still to download for [result], less what a cut download already holds. */
    fun remainingBytes(result: CheckResult.Available): Long =
        result.decision.layers.sumOf { downloader.remainingBytes(asset(result.manifest, it)) }

    /** Fetch the latest manifest, check its signature before reading a byte of it, and decide. */
    suspend fun check(): CheckResult = withContext(Dispatchers.IO) {
        val manifestBytes: ByteArray
        val signature: ByteArray
        try {
            val where = source()
            manifestBytes = fetchSmall(where.manifestUrl)
            signature = fetchSmall(where.signatureUrl)
        } catch (e: InstallException) {
            return@withContext CheckResult.Refused(e.failure)
        }
        val signer = verifier.signer(manifestBytes, signature) ?: return@withContext CheckResult.Refused(RuntimeFailure.BadSignature)
        val manifest = try {
            RuntimeManifest.parse(manifestBytes)
        } catch (e: ManifestException) {
            return@withContext CheckResult.Refused(RuntimeFailure.BadManifest(e.message ?: "unreadable"))
        }
        when (val decision = ManifestPolicy.decide(manifest, appVersion(), deviceAbis, store.read(), allowTest, signer)) {
            is ManifestPolicy.Decision.Refused -> CheckResult.Refused(decision.failure)
            is ManifestPolicy.Decision.UpToDate -> CheckResult.UpToDate(manifest)
            is ManifestPolicy.Decision.Install -> CheckResult.Available(manifest, decision)
        }
    }

    /**
     * Download, verify and unpack [decision]'s layers, then commit them. [beforeCommit] runs after everything
     * is unpacked and before `installed.json` changes: the controller stops a running Roundtable there.
     */
    suspend fun apply(
        manifest: RuntimeManifest,
        decision: ManifestPolicy.Decision.Install,
        onEvent: (InstallEvent) -> Unit,
        beforeCommit: suspend () -> Unit = {},
    ): InstalledRecord = withContext(Dispatchers.IO) {
        layout.root.mkdirs()
        layout.downloads.mkdirs()
        val installed = store.read()?.takeIf { it.abi == decision.abi }
        val layers = decision.layers
        val assets = layers.map { asset(manifest, it) }

        // Before any byte is fetched: is there room for the download and for what it unpacks to?
        requireSpace(assets.sumOf { downloader.remainingBytes(it) } + unpackNeed(layers))

        val files = assets.mapIndexed { index, asset ->
            val layer = layers[index]
            downloader.download(
                asset,
                onBytes = { done, total -> onEvent(InstallEvent.Downloading(DownloadProgress(layer.name, index, assets.size, done, total))) },
                onVerifying = { onEvent(InstallEvent.Verifying(layer.name)) },
            ).let { layer to it }
        }

        requireSpace(unpackNeed(layers))

        val unpacked = mutableMapOf<String, LayerRecord>()
        try {
            files.forEachIndexed { index, (layer, file) -> unpacked[layer.name] = unpack(layer, file, index, files.size, onEvent) }
        } catch (e: Throwable) {
            // Nothing below is referenced by installed.json yet; take it all away again.
            unpacked.values.forEach { FsTree.delete(fs, File(layout.root, it.dir)) }
            throw e
        }

        val base = unpacked[LAYER_BASE] ?: installed?.base ?: throw InstallException(RuntimeFailure.BadManifest("no base layer to install"))
        val roundtable = unpacked[LAYER_ROUNDTABLE] ?: installed?.roundtable
            ?: throw InstallException(RuntimeFailure.BadManifest("no roundtable layer to install"))
        val record = InstalledRecord(
            releaseId = manifest.releaseId,
            sequence = manifest.sequence,
            abi = decision.abi,
            channel = manifest.channel,
            version = manifest.version,
            base = base,
            roundtable = roundtable,
            entrypoint = manifest.runtime.entrypoint,
            fakeProc = manifest.runtime.fakeProc,
            resolvConf = manifest.runtime.resolvConf,
            args = manifest.runtime.args,
            env = manifest.runtime.env,
            launchTokenEnv = manifest.runtime.launchTokenEnv,
            readinessPrefix = manifest.runtime.readinessPrefix,
            healthPath = manifest.runtime.healthPath,
        )
        beforeCommit()
        store.write(record)
        cleanOrphans()
        downloader.prune()
        record
    }

    /**
     * Remove the runtime. `installed.json` goes first, so a crash halfway leaves garbage that the next start
     * deletes, never a runtime that looks installed. [keepUserData] keeps the projects and Roundtable's home.
     */
    fun uninstall(keepUserData: Boolean) {
        store.clear()
        layout.root.listFiles().orEmpty().forEach { child ->
            val userData = child.name == layout.home.name || child.name == layout.workspaces.name
            if (!userData || !keepUserData) FsTree.delete(fs, child)
        }
        FsTree.delete(fs, layout.downloads)
        FsTree.delete(fs, layout.prootTmp)
    }

    /** Delete unpacks that were abandoned and layers no record names. */
    fun cleanOrphans() {
        layout.orphans(store.read()).forEach { runCatching { FsTree.delete(fs, it) } }
    }

    private suspend fun unpack(layer: RuntimeManifest.Layer, file: File, index: Int, count: Int, onEvent: (InstallEvent) -> Unit): LayerRecord {
        val finalDir = if (layer.name == LAYER_BASE) layout.baseDir(layer.id, layer.sha256) else layout.roundtableDir(layer.id, layer.sha256)
        val staging = layout.staging(layer.name + "-" + layer.id)
        FsTree.delete(fs, staging)
        if (!staging.mkdirs()) throw InstallException(RuntimeFailure.Storage("mkdir ${staging.name}"))
        val job = currentCoroutineContext()[Job]
        try {
            onEvent(InstallEvent.Unpacking(UnpackProgress(layer.name, index, count, 0, layer.entries, 0)))
            BufferedInputStream(decoder(BufferedInputStream(FileInputStream(file), READ_BUFFER)), READ_BUFFER).use { tar ->
                TarExtractor(fs).extract(
                    tar,
                    staging,
                    onProgress = { entries, bytes -> onEvent(InstallEvent.Unpacking(UnpackProgress(layer.name, index, count, entries, layer.entries, bytes))) },
                    checkCancelled = { if (job?.isActive == false) throw CancellationException("unpack cancelled") },
                )
            }
            if (layer.name == LAYER_BASE) prepareBase(staging) else checkRoundtable(staging)
            FsTree.delete(fs, finalDir)
            if (!staging.renameTo(finalDir)) throw InstallException(RuntimeFailure.Storage("rename ${staging.name}"))
            return LayerRecord(layer.id, finalDir.name, layer.sha256)
        } catch (e: ArchiveException) {
            throw InstallException(RuntimeFailure.BadArchive("${layer.file}: ${e.message}"), e)
        } catch (e: InstallException) {
            throw e
        } catch (e: IOException) {
            throw InstallException(storageFailure(e, unpackNeed(listOf(layer))), e)
        } finally {
            FsTree.delete(fs, staging)
        }
    }

    /** Mount points for what start binds into the base, so proot never invents glue directories. */
    private fun prepareBase(rootfs: File) {
        for (dir in listOf("opt/roundtable", "workspaces", "root", "tmp")) {
            val target = File(rootfs, dir)
            if (fs.lstat(target) == FileKind.NONE && !target.mkdirs()) throw IOException("mkdir $dir")
        }
    }

    private fun checkRoundtable(dir: File) {
        if (fs.lstat(File(dir, "opt/roundtable")) != FileKind.DIRECTORY) throw ArchiveException("roundtable layer has no opt/roundtable")
    }

    private fun requireSpace(needed: Long) {
        layout.root.mkdirs()
        val available = space.availableBytes(layout.root)
        if (available < needed) throw InstallException(RuntimeFailure.NoSpace(needed, available))
    }

    /** ENOSPC surfaces as all sorts of errors mid-unpack (even ENOENT on chmod); free space decides. */
    private fun storageFailure(e: IOException, needed: Long): RuntimeFailure {
        val available = runCatching { space.availableBytes(layout.root) }.getOrDefault(Long.MAX_VALUE)
        val message = e.message.orEmpty()
        return if (available < LOW_SPACE || "ENOSPC" in message || "No space" in message) {
            RuntimeFailure.NoSpace(needed, available)
        } else {
            RuntimeFailure.Storage(message.ifEmpty { e.javaClass.simpleName })
        }
    }

    private fun asset(manifest: RuntimeManifest, layer: RuntimeManifest.Layer) =
        LayerDownloader.Asset(manifest.assetBaseUrl + layer.file, layer.file, layer.size, layer.sha256)

    private fun fetchSmall(url: String): ByteArray {
        try {
            client.newCall(Request.Builder().url(url).build()).execute().use { response ->
                if (response.code != 200) throw InstallException(RuntimeFailure.Network("HTTP ${response.code} for ${url.substringAfterLast('/')}"))
                val body = response.body ?: throw InstallException(RuntimeFailure.Network("empty body"))
                val length = body.contentLength()
                if (length > MAX_MANIFEST) throw InstallException(RuntimeFailure.BadManifest("$length bytes"))
                val bytes = body.byteStream().use { it.readLimited(MAX_MANIFEST + 1) }
                if (bytes.size > MAX_MANIFEST) throw InstallException(RuntimeFailure.BadManifest("too large"))
                return bytes
            }
        } catch (e: InstallException) {
            throw e
        } catch (e: IOException) {
            throw InstallException(RuntimeFailure.Network(e.message ?: e.javaClass.simpleName), e)
        } catch (e: IllegalArgumentException) {
            throw InstallException(RuntimeFailure.BadManifest("not a manifest URL"), e)
        }
    }

    companion object {
        private const val MAX_MANIFEST = 1 shl 20
        private const val READ_BUFFER = 1 shl 20
        private const val HEADROOM = 128L shl 20
        private const val LOW_SPACE = 16L shl 20

        /** Disk an unpack needs: 1.3 times the unpacked bytes, plus headroom. */
        fun unpackNeed(layers: List<RuntimeManifest.Layer>): Long =
            if (layers.isEmpty()) 0 else layers.sumOf { it.unpackedSize + it.unpackedSize * 3 / 10 } + HEADROOM

        internal fun InputStream.readLimited(limit: Int): ByteArray {
            val out = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (out.size() < limit) {
                val n = read(buffer, 0, minOf(buffer.size, limit - out.size()))
                if (n < 0) break
                out.write(buffer, 0, n)
            }
            return out.toByteArray()
        }
    }
}
