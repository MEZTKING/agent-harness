// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/RuntimeLayout.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

/**
 * Where the runtime lives on disk.
 *
 * Everything persistent is under [root] (the app's `noBackupFilesDir/runtime`), so none of it is ever part
 * of a backup: the Linux files have no business in a cloud backup, and Roundtable's home holds API keys.
 * Downloads and proot's scratch space are in the cache directory.
 *
 * ```
 * runtime/
 *   installed.json          the commit record; a layer directory it does not name is garbage
 *   base-<id>/              the base layer, unpacked (the guest's /)
 *   roundtable-<id>/        the roundtable layer, unpacked (opt/roundtable)
 *   home/                   bound over the guest's /root: Roundtable's own state (/root/.roundtable)
 *   workspaces/             bound at /workspaces: the projects
 *   run/                    files written before each start (resolv.conf, proc-stat)
 *   logs/                   Roundtable's output, size-capped, token masked
 *   .staging-*              an unpack in progress; deleted on sight
 * ```
 */
class RuntimeLayout(val root: File, val cache: File) {
    val installedFile = File(root, "installed.json")
    val home = File(root, "home")
    val workspaces = File(root, "workspaces")
    val run = File(root, "run")
    val logs = File(root, "logs")
    val downloads = File(cache, "downloads")
    val prootTmp = File(cache, "proot-tmp")

    fun baseDir(id: String, sha256: String) = File(root, "base-" + safeName(id) + "-" + sha256.take(12))
    fun roundtableDir(id: String, sha256: String) = File(root, "roundtable-" + safeName(id) + "-" + sha256.take(12))
    fun staging(name: String) = File(root, STAGING_PREFIX + safeName(name))

    /** Directories under [root] that hold no user data and that [record] does not name. */
    fun orphans(record: InstalledRecord?): List<File> {
        val keep = buildSet {
            add(installedFile.name)
            add(home.name)
            add(workspaces.name)
            add(run.name)
            add(logs.name)
            if (record != null) addAll(record.layerDirs())
        }
        return root.listFiles().orEmpty().filter {
            it.name !in keep && (it.name.startsWith("base-") || it.name.startsWith("roundtable-") ||
                it.name.startsWith(STAGING_PREFIX) || it.name.startsWith("installed.json."))
        }
    }

    companion object {
        const val STAGING_PREFIX = ".staging-"

        fun safeName(id: String): String = id.map { if (it.isLetterOrDigit() || it == '.' || it == '-' || it == '_') it else '_' }.joinToString("").take(120)
    }
}

/** One unpacked layer: its manifest id and the directory it lives in (a name under the layout root). */
@Serializable
data class LayerRecord(val id: String, val dir: String, val sha256: String)

/**
 * `installed.json`: what is installed, written last and atomically. A runtime is installed exactly when this
 * file exists and parses; it is written only after every layer it names is complete and in place. The guest
 * command line comes from the manifest that was installed, so a start never needs the network.
 */
@Serializable
data class InstalledRecord(
    val releaseId: String,
    val sequence: Long,
    val abi: String,
    val channel: String,
    val version: String,
    val base: LayerRecord,
    val roundtable: LayerRecord,
    val entrypoint: String,
    val fakeProc: List<RuntimeManifest.FakeProc>,
    val resolvConf: String,
    val args: List<String> = RuntimeManifest.DEFAULT_ARGS,
    val env: Map<String, String> = RuntimeManifest.DEFAULT_ENV,
    val launchTokenEnv: String = "ROUNDTABLE_LAUNCH_TOKEN",
    val readinessPrefix: String = RuntimeManifest.DEFAULT_READINESS,
    val healthPath: String = "/api/health",
    /**
     * What was installed before this update, kept (its layer directories included) until this release has
     * started and answered once. A release that fails its start twice is swapped for it. Null: nothing on trial.
     */
    val trial: PriorInstall? = null,
    /** Starts of the release on trial that failed so far (two put the previous one back). */
    val trialFailures: Int = 0,
    /** Releases that failed their trial here: never installed again by themselves, only by "Try the new one again". */
    val heldBack: List<HeldBack> = emptyList(),
) {
    val isTest: Boolean get() = channel == RuntimeManifest.CHANNEL_TEST
    val onTrial: Boolean get() = trial != null

    /** Every layer directory this record needs on disk, the one on trial's predecessor included. */
    fun layerDirs(): Set<String> = buildSet {
        add(base.dir)
        add(roundtable.dir)
        trial?.let { add(it.base.dir); add(it.roundtable.dir) }
    }

    fun isHeldBack(releaseId: String, sequence: Long): Boolean = heldBack.any { it.releaseId == releaseId && it.sequence == sequence }

    /** This record as the state to come back to if the next one does not start. */
    fun asPrior() = PriorInstall(
        releaseId, sequence, channel, version, base, roundtable, entrypoint, fakeProc, resolvConf, args, env, launchTokenEnv, readinessPrefix, healthPath,
    )
}

/** A release that failed its trial on this phone (DS-08). */
@Serializable
data class HeldBack(val releaseId: String, val sequence: Long, val version: String)

/**
 * An installed release as [InstalledRecord] keeps it while its successor is on trial. The shape of DSH Mobile's
 * `PriorInstall` (app/src/main/java/com/labteto/dshmobile/runtime/RuntimeLayout.kt), with Roundtable's fields.
 */
@Serializable
data class PriorInstall(
    val releaseId: String,
    val sequence: Long,
    val channel: String,
    val version: String,
    val base: LayerRecord,
    val roundtable: LayerRecord,
    val entrypoint: String,
    val fakeProc: List<RuntimeManifest.FakeProc>,
    val resolvConf: String,
    val args: List<String> = RuntimeManifest.DEFAULT_ARGS,
    val env: Map<String, String> = RuntimeManifest.DEFAULT_ENV,
    val launchTokenEnv: String = "ROUNDTABLE_LAUNCH_TOKEN",
    val readinessPrefix: String = RuntimeManifest.DEFAULT_READINESS,
    val healthPath: String = "/api/health",
) {
    fun restore(abi: String, heldBack: List<HeldBack>) = InstalledRecord(
        releaseId = releaseId, sequence = sequence, abi = abi, channel = channel, version = version, base = base, roundtable = roundtable,
        entrypoint = entrypoint, fakeProc = fakeProc, resolvConf = resolvConf, args = args, env = env, launchTokenEnv = launchTokenEnv,
        readinessPrefix = readinessPrefix, healthPath = healthPath, heldBack = heldBack,
    )
}

/** Reads and atomically replaces `installed.json`. */
class InstalledStore(private val layout: RuntimeLayout) {
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }

    fun read(): InstalledRecord? {
        val file = layout.installedFile
        if (!file.isFile) return null
        return runCatching { json.decodeFromString(InstalledRecord.serializer(), file.readText()) }.getOrNull()
    }

    /** Write via a temporary file, flushed to disk, then `rename(2)`: readers see old or new, never half. */
    fun write(record: InstalledRecord) {
        layout.root.mkdirs()
        val tmp = File(layout.root, layout.installedFile.name + ".tmp")
        FileOutputStream(tmp).use { out ->
            out.write(json.encodeToString(InstalledRecord.serializer(), record).toByteArray())
            out.flush()
            out.fd.sync()
        }
        if (!tmp.renameTo(layout.installedFile)) {
            layout.installedFile.delete()
            if (!tmp.renameTo(layout.installedFile)) throw IOException("could not commit ${layout.installedFile}")
        }
    }

    fun clear() {
        layout.installedFile.delete()
    }
}
