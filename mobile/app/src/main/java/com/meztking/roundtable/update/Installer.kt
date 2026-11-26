package com.meztking.roundtable.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.IntentCompat
import java.io.File

/**
 * Hands a checked APK to Android's own installer through a [PackageInstaller] session: no browser, no
 * file manager, no file:// address. Android shows its usual "Do you want to update this app?" prompt.
 * (Adapted from DSH Mobile's PackageInstallerGateway and UpdateInstallReceiver.)
 */
object Installer {
    const val ACTION_STATUS = "com.meztking.roundtable.update.INSTALL_STATUS"

    /** Whether Android lets Roundtable Mobile install updates ("Install unknown apps"). */
    fun canInstall(ctx: Context): Boolean = ctx.packageManager.canRequestPackageInstalls()

    /** The system page where the owner allows installs from Roundtable Mobile. */
    fun permissionIntent(ctx: Context): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    /** Copy [apk] into a new session and commit it; the answer arrives at [InstallReceiver]. */
    fun commit(ctx: Context, apk: File): Int {
        val installer = ctx.packageManager.packageInstaller
        installer.mySessions.filter { !it.isActive }.forEach { runCatching { installer.abandonSession(it.sessionId) } }
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(ctx.packageName)
            setSize(apk.length())
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
        }
        val id = installer.createSession(params)
        try {
            installer.openSession(id).use { session ->
                session.openWrite("base.apk", 0, apk.length()).use { out ->
                    apk.inputStream().use { it.copyTo(out, 64 * 1024) }
                    session.fsync(out)
                }
                val callback = Intent(ctx, InstallReceiver::class.java).setAction(ACTION_STATUS).setPackage(ctx.packageName)
                // mutable: Android fills in the status; explicit (this app's own receiver), as Android 14 asks
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
                session.commit(PendingIntent.getBroadcast(ctx, id, callback, flags).intentSender)
            }
        } catch (e: Exception) {
            runCatching { installer.abandonSession(id) }
            throw e
        }
        return id
    }
}

/** What Android said about an install, in the owner's words; null while it waits or when it worked. */
fun installFailureText(status: Int, message: String?): String? = when (status) {
    PackageInstaller.STATUS_PENDING_USER_ACTION, PackageInstaller.STATUS_SUCCESS -> null
    PackageInstaller.STATUS_FAILURE_ABORTED ->
        if (message?.contains("INSTALL_FAILED_VERIFICATION", ignoreCase = true) == true)
            "Your phone's app checker (Play Protect) stopped the install. Tap Download and install again; if it asks, choose Install anyway."
        else "The install was cancelled. Tap Download and install when you're ready."
    PackageInstaller.STATUS_FAILURE_BLOCKED -> "Your phone wouldn't allow the install (a work profile or a security setting). Install it from the releases page instead."
    PackageInstaller.STATUS_FAILURE_CONFLICT ->
        "Android refused it: the Roundtable Mobile on this phone was signed differently. Uninstall it, then install the new one from the releases page."
    PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "This build doesn't work on this phone's version of Android."
    PackageInstaller.STATUS_FAILURE_INVALID -> "The file was damaged. Tap Download and install to fetch it again."
    PackageInstaller.STATUS_FAILURE_STORAGE -> "Not enough space to install. Free some space, then tap Download and install again."
    else -> "Android couldn't install it" + (message?.trim()?.takeIf { it.isNotEmpty() }?.let { " ($it)" } ?: "") +
        ". Tap Download and install to try again."
}

/** Where Android reports a session this app committed. Not exported: Android answers through our PendingIntent. */
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Installer.ACTION_STATUS) return
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
        val confirm = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_INTENT, Intent::class.java)
        AppUpdater.get(context).onInstallStatus(status, message, confirm)
    }
}
