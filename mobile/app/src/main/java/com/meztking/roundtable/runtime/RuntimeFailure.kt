package com.meztking.roundtable.runtime
import com.meztking.roundtable.Brand

/**
 * Why setting up or starting Roundtable on this phone failed, with what to tell the owner.
 * (DSH Mobile keeps its equivalent in its shared core; this is Roundtable's own, shorter list.)
 */
sealed class RuntimeFailure {
    data class Network(val detail: String) : RuntimeFailure()
    data object BadSignature : RuntimeFailure()
    data class BadManifest(val detail: String) : RuntimeFailure()
    data class ChecksumMismatch(val file: String) : RuntimeFailure()
    data class BadArchive(val detail: String) : RuntimeFailure()
    data class NoSpace(val needed: Long, val available: Long) : RuntimeFailure()
    data class Storage(val detail: String) : RuntimeFailure()
    data class AppTooOld(val needs: String) : RuntimeFailure()
    data class OlderRelease(val installed: Long, val offered: Long) : RuntimeFailure()
    data class NoBuildForDevice(val abi: String) : RuntimeFailure()
    /** A test download offered to the official app (or the other way round). */
    data class WrongChannel(val channel: String) : RuntimeFailure()
    data object NoRelease : RuntimeFailure()
    data class StartFailed(val detail: String) : RuntimeFailure()

    /** Plain words for the owner: what happened and what to do next. */
    fun plain(): String = when (this) {
        is Network -> "Couldn't download it: the connection dropped or GitHub didn't answer. Check the phone is online and press Try again; it carries on where it stopped."
        BadSignature -> "The download's signature doesn't match, so it wasn't used. Nothing was changed. Try again later, or update the app."
        is BadManifest -> "The download's description couldn't be read ($detail). Update the app, then try again."
        is ChecksumMismatch -> "A downloaded file was damaged, so it was deleted. Press Try again to fetch it afresh."
        is BadArchive -> "A downloaded file couldn't be unpacked safely, so nothing was installed. Press Try again."
        is NoSpace -> "Not enough free space: it needs about ${mb(needed)} and the phone has ${mb(available)}. Free some space, then press Try again."
        is Storage -> "Couldn't write to the phone's storage ($detail). Restart the phone, then press Try again."
        is AppTooOld -> "This download needs a newer app (version $needs or later). Update the ${Brand.NAME} app first."
        is OlderRelease -> "The download is older than the one already on the phone, so it wasn't used."
        is NoBuildForDevice -> "There's no download for this kind of phone ($abi)."
        is WrongChannel -> if (channel == "test") "This is a test download, which the official app doesn't accept. Use the test app, or wait for the official download."
            else "This download is for a different app ($channel)."
        NoRelease -> "There's no download ready yet. Try again later."
        is StartFailed -> "${Brand.NAME} didn't start ($detail). Press Restart, or open Show log for the details."
    }

    companion object {
        fun mb(bytes: Long): String = if (bytes >= 1L shl 30) "%.1f GB".format(bytes / (1024.0 * 1024 * 1024)) else "${bytes / (1024 * 1024)} MB"
    }
}
