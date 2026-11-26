// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/RuntimeManifest.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * `manifest.json` of a Roundtable runtime release (a GitHub release of agent-harness whose tag starts
 * `runtime-`), schema version 1.
 *
 * DSH Mobile's format, adapted: `product` is "roundtable", `channel` says whether it is a test download
 * (signed with the public test key) or the official one, the two layers are `base` (Debian with Python, git
 * and Node) and `roundtable` (Roundtable in `/opt/roundtable/venv`), and layers are `.tar.xz`. Unknown fields
 * are ignored. Only fields the app acts on are modelled.
 *
 * Never build one of these from bytes whose signature has not been checked: [ManifestVerifier] comes first,
 * then [RuntimeManifest.parse].
 */
@Serializable
data class RuntimeManifest(
    val schemaVersion: Int,
    val product: String = PRODUCT,
    /** "stable" (the official one) or "test". A test download is refused by the official app ([ManifestPolicy]). */
    val channel: String = CHANNEL_STABLE,
    val releaseId: String,
    val sequence: Long,
    val createdAt: String = "",
    val minAppVersion: String = "0.0.0",
    val signing: Signing,
    val assetBaseUrl: String,
    /** Roundtable's version in the download (DSH's field name, kept by the runtime build). */
    val harness: Component = Component(),
    val roundtable: Component? = null,
    val runtime: Runtime = Runtime(),
    /** Keyed by Android ABI (`arm64-v8a`, `x86_64`) or by the Linux name (`aarch64`, `x86_64`). */
    val archs: Map<String, Arch>,
) {
    @Serializable
    data class Signing(val algorithm: String, val keyId: String, val signatureFile: String = "manifest.json.sig")

    @Serializable
    data class Component(val version: String = "")

    /**
     * How to start Roundtable: [entrypoint] + [args] (`{port}` filled in), with [env], and the launch token
     * in the variable [launchTokenEnv] (never in [args]). Ready when a line starts with [readinessPrefix] and
     * then `GET` [healthPath] (no token) answers.
     */
    @Serializable
    data class Runtime(
        val entrypoint: String = DEFAULT_ENTRYPOINT,
        val args: List<String> = DEFAULT_ARGS,
        val env: Map<String, String> = DEFAULT_ENV,
        val launchTokenEnv: String = "ROUNDTABLE_LAUNCH_TOKEN",
        val readinessPrefix: String = DEFAULT_READINESS,
        val healthPath: String = "/api/health",
        val fakeProc: List<FakeProc> = emptyList(),
        val resolvConf: String = "/etc/resolv.conf",
    )

    @Serializable
    data class FakeProc(val source: String, val target: String)

    @Serializable
    data class Arch(
        val debianArch: String = "",
        val layers: List<Layer>,
    )

    @Serializable
    data class Layer(
        val file: String,
        val size: Long,
        val sha256: String,
        val name: String,
        val id: String,
        val compression: String,
        val unpackedSize: Long = 0,
        val entries: Int = 0,
    )

    /** The layers for an Android [abi], whichever name the manifest uses for it. */
    fun arch(abi: String): Arch? = archs[abi] ?: ABI_ALIASES[abi]?.let { archs[it] }

    fun layer(abi: String, name: String): Layer? = arch(abi)?.layers?.firstOrNull { it.name == name }

    val isTest: Boolean get() = channel == CHANNEL_TEST

    /** Roundtable's version, whichever field carries it. */
    val version: String get() = roundtable?.version?.ifBlank { null } ?: harness.version

    companion object {
        const val SCHEMA_VERSION = 1
        const val PRODUCT = "roundtable"
        const val CHANNEL_TEST = "test"
        const val CHANNEL_STABLE = "stable"
        /** Accepted as the official channel too. */
        const val CHANNEL_RELEASE = "release"
        const val DEFAULT_ENTRYPOINT = "/opt/roundtable/venv/bin/roundtable"
        const val DEFAULT_READINESS = "Roundtable is ready on"
        val DEFAULT_ARGS = listOf("phone", "serve", "--local", "--port", "{port}", "--home", "/root/.roundtable")
        val DEFAULT_ENV = mapOf("ROUNDTABLE_HOME" to "/root/.roundtable", "ROUNDTABLE_WORKSPACES" to "/workspaces")

        /** Android ABI -> the Linux architecture name the runtime build uses. */
        val ABI_ALIASES = mapOf("arm64-v8a" to "aarch64", "x86_64" to "x86_64")

        private val json = Json {
            ignoreUnknownKeys = true
            isLenient = false
        }

        /** Parse verified manifest bytes. Throws [ManifestException] on anything malformed. */
        fun parse(bytes: ByteArray): RuntimeManifest {
            val manifest = try {
                json.decodeFromString(serializer(), bytes.decodeToString(throwOnInvalidSequence = true))
            } catch (e: Exception) {
                throw ManifestException("not a runtime manifest: ${e.message?.take(200)}")
            }
            manifest.validate()
            return manifest
        }
    }

    /**
     * Shape checks that do not depend on the device or on what is installed. Asset names become URLs and
     * file names here, so they are held to plain names.
     */
    private fun validate() {
        if (schemaVersion > SCHEMA_VERSION) throw ManifestException("schema $schemaVersion is newer than $SCHEMA_VERSION")
        if (schemaVersion < 1) throw ManifestException("schema $schemaVersion")
        if (product != PRODUCT) throw ManifestException("product $product")
        if (channel != CHANNEL_TEST && channel != CHANNEL_STABLE && channel != CHANNEL_RELEASE) throw ManifestException("channel $channel")
        if (signing.algorithm != "Ed25519") throw ManifestException("signing algorithm ${signing.algorithm}")
        if (!assetBaseUrl.startsWith("https://") || !assetBaseUrl.endsWith("/")) {
            throw ManifestException("assetBaseUrl must be https and end with /")
        }
        if (!isGuestPath(runtime.entrypoint)) throw ManifestException("entrypoint ${runtime.entrypoint}")
        if (!isGuestPath(runtime.resolvConf)) throw ManifestException("resolvConf ${runtime.resolvConf}")
        // These become argv words and environment entries of the guest: plain values only.
        if (runtime.args.size > 32 || runtime.args.any { it.length > 200 || it.any { c -> c.code < 32 } }) throw ManifestException("args")
        if ("{port}" !in runtime.args) throw ManifestException("args have no {port}")
        if (!GUEST_ENV_NAME.matches(runtime.launchTokenEnv)) throw ManifestException("launchTokenEnv ${runtime.launchTokenEnv}")
        for ((name, value) in runtime.env) {
            if (!GUEST_ENV_NAME.matches(name) || value.length > 400 || value.any { it.code < 32 }) throw ManifestException("env $name")
        }
        if (runtime.readinessPrefix.isBlank()) throw ManifestException("readinessPrefix is empty")
        if (!runtime.healthPath.startsWith("/") || runtime.healthPath.any { it.isWhitespace() }) throw ManifestException("healthPath ${runtime.healthPath}")
        for (proc in runtime.fakeProc) {
            if (!isGuestPath(proc.source) || !isGuestPath(proc.target) || !proc.target.startsWith("/proc/")) {
                throw ManifestException("fakeProc ${proc.source} -> ${proc.target}")
            }
        }
        for ((abi, arch) in archs) {
            for (layer in arch.layers) {
                checkAsset(abi, layer.file, layer.size, layer.sha256)
                if (layer.compression != "xz") throw ManifestException("$abi ${layer.name}: compression ${layer.compression}")
                if (layer.id.isBlank()) throw ManifestException("$abi ${layer.name}: empty id")
                if (layer.unpackedSize < 0 || layer.entries < 0) throw ManifestException("$abi ${layer.name}: negative sizes")
            }
            val names = arch.layers.map { it.name }
            if (names != listOf(LAYER_BASE, LAYER_ROUNDTABLE)) throw ManifestException("$abi layers $names")
        }
    }

    private fun checkAsset(abi: String, file: String, size: Long, sha256: String) {
        if (!isPlainFileName(file)) throw ManifestException("$abi: asset name '$file'")
        if (size <= 0) throw ManifestException("$abi: $file has size $size")
        if (!SHA256_HEX.matches(sha256)) throw ManifestException("$abi: $file has a malformed sha256")
    }
}

const val LAYER_BASE = "base"
const val LAYER_ROUNDTABLE = "roundtable"

private val SHA256_HEX = Regex("[0-9a-f]{64}")
private val GUEST_ENV_NAME = Regex("[A-Z_][A-Z0-9_]{0,63}")

internal fun isPlainFileName(name: String): Boolean =
    name.isNotEmpty() && name.length <= 200 && name != "." && name != ".." &&
        name.all { it.isLetterOrDigit() || it == '.' || it == '-' || it == '_' } && name.none { it.code > 127 }

private fun isGuestPath(path: String): Boolean =
    path.startsWith("/") && path.split('/').none { it == ".." } && '\u0000' !in path &&
        path.none { it.isWhitespace() || it == '\'' || it == '"' || it == '$' || it == '`' || it == ';' || it == '&' || it == '|' }

class ManifestException(message: String) : Exception(message)
