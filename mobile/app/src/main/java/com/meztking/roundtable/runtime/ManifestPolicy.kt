// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/ManifestPolicy.kt. See THIRD_PARTY_NOTICES.md.
package com.meztking.roundtable.runtime

/**
 * Decides whether a verified manifest may be installed on this device, and what it would take.
 *
 * Pure: the device's ABIs, the app's version, the build's channel rule and the installed record come in
 * as values.
 */
object ManifestPolicy {

    /** The ABIs a runtime is built for, in preference order. */
    val SUPPORTED_ABIS = listOf("arm64-v8a", "x86_64")

    /** Android 8.0: the oldest version "This phone" runs on (the app's own minimum). */
    const val MIN_SDK = 26

    /** The first of the device's ABIs (most preferred first, like `Build.SUPPORTED_ABIS`) we ship. */
    fun deviceAbi(deviceAbis: List<String>): String? = deviceAbis.firstOrNull { it in SUPPORTED_ABIS }

    /** Whether to offer "This phone" at all: a 64-bit phone (arm64-v8a or x86_64) on Android 8 or later. */
    fun supported(sdkInt: Int, deviceAbis64: List<String>): Boolean = sdkInt >= MIN_SDK && deviceAbi(deviceAbis64) != null

    /** What an install or update of [manifest] means for this device. */
    sealed interface Decision {
        data class Refused(val failure: RuntimeFailure) : Decision

        /** Nothing to do: the installed layers are the manifest's. */
        data class UpToDate(val abi: String) : Decision

        /** [layers] are the ones to download and unpack, in install order. */
        data class Install(val abi: String, val layers: List<RuntimeManifest.Layer>) : Decision {
            val downloadBytes: Long get() = layers.sumOf { it.size }
        }
    }

    /**
     * [allowTest] is true only in test builds: the official app refuses `"channel": "test"`. [signerKeyId] is
     * the key that the signature actually checked out against; the manifest must name that same key.
     */
    fun decide(
        manifest: RuntimeManifest,
        appVersion: String,
        deviceAbis: List<String>,
        installed: InstalledRecord?,
        allowTest: Boolean,
        signerKeyId: String,
    ): Decision {
        if (manifest.isTest && !allowTest) return Decision.Refused(RuntimeFailure.WrongChannel(manifest.channel))
        if (manifest.signing.keyId != signerKeyId) {
            // The signature checked out against one of our keys, but the manifest names another: a release
            // tooling bug, refused rather than guessed about.
            return Decision.Refused(RuntimeFailure.BadManifest("keyId ${manifest.signing.keyId}"))
        }
        if (!AppVersion.satisfies(appVersion, manifest.minAppVersion)) {
            return Decision.Refused(RuntimeFailure.AppTooOld(manifest.minAppVersion))
        }
        if (installed != null && manifest.sequence < installed.sequence) {
            return Decision.Refused(RuntimeFailure.OlderRelease(installed.sequence, manifest.sequence))
        }
        val abi = deviceAbi(deviceAbis)
            ?: return Decision.Refused(RuntimeFailure.NoBuildForDevice(deviceAbis.firstOrNull() ?: "unknown"))
        val arch = manifest.arch(abi) ?: return Decision.Refused(RuntimeFailure.NoBuildForDevice(abi))
        if (installed != null && installed.abi != abi) return Decision.Install(abi, arch.layers)
        val needed = arch.layers.filter { layer ->
            when (layer.name) {
                LAYER_BASE -> !installed?.base.isLayer(layer)
                LAYER_ROUNDTABLE -> !installed?.roundtable.isLayer(layer)
                else -> false
            }
        }
        return if (needed.isEmpty()) Decision.UpToDate(abi) else Decision.Install(abi, needed)
    }
}

/** Whether this unpacked layer is [layer]: same id *and* same archive hash. */
fun LayerRecord?.isLayer(layer: RuntimeManifest.Layer): Boolean =
    this != null && id == layer.id && sha256 == layer.sha256
