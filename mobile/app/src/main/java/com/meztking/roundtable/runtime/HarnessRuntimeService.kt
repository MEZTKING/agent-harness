// Adapted from DSH Mobile (MIT License, Copyright (c) 2026 DSH Mobile contributors),
// app/src/main/java/com/labteto/dshmobile/runtime/HarnessRuntimeService.kt. See THIRD_PARTY_NOTICES.md.
// Trimmed for Roundtable: no Hilt, no update coordinator, one plain notification.
package com.meztking.roundtable.runtime

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.meztking.roundtable.MainActivity
import com.meztking.roundtable.R
import com.meztking.roundtable.RoundtableApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import com.meztking.roundtable.Brand

/**
 * Keeps the app's process alive while Roundtable on this phone sets up or runs, and shows it.
 *
 * Type `specialUse`: Roundtable is a local server the owner started and expects to keep running for hours
 * (`dataSync` is capped at 6 hours a day on Android 15). The process itself is owned by [RuntimeController];
 * this service only pins the process with an ongoing notification (with Stop) and holds a wake lock while it
 * runs. It stops itself when nothing is setting up or running.
 */
class HarnessRuntimeService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var following = false
    private var stopJob: Job? = null
    private val controller get() = (application as RoundtableApp).runtime

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!enterForeground()) return START_NOT_STICKY
        if (intent?.action == ACTION_STOP) controller.stop()
        follow()
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        releaseWakeLock()
        scope.cancel()
        super.onDestroy()
    }

    private fun enterForeground(): Boolean {
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        return try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, build(controller.state.value), type)
            true
        } catch (e: IllegalStateException) {
            // Android 12+ refuses it from the background; Roundtable keeps running without the service's protection.
            stopSelf()
            false
        }
    }

    private fun follow() {
        if (following) return
        following = true
        scope.launch {
            controller.state.map { notice(it) to it }.distinctUntilChanged { a, b -> a.first == b.first }.conflate().collect { (_, state) ->
                if (state.needsService) {
                    stopJob?.cancel()
                    if (state is RuntimeState.Running) acquireWakeLock() else releaseWakeLock()
                    if (NotificationManagerCompat.from(this@HarnessRuntimeService).areNotificationsEnabled()) {
                        runCatching { NotificationManagerCompat.from(this@HarnessRuntimeService).notify(NOTIFICATION_ID, build(state)) }
                    }
                } else {
                    releaseWakeLock()
                    if (stopJob?.isActive != true) stopJob = scope.launch {
                        delay(STOP_GRACE_MS)
                        if (!controller.state.value.needsService) {
                            ServiceCompat.stopForeground(this@HarnessRuntimeService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                            stopSelf()
                        }
                    }
                }
                delay(NOTIFY_INTERVAL_MS)
            }
        }
    }

    private fun build(state: RuntimeState): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, HarnessRuntimeService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val b = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_seal)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentTitle(notice(state))
        when (state) {
            is RuntimeState.Downloading -> b.setProgress(100, percent(state.done, state.total), false)
            is RuntimeState.Unpacking -> b.setProgress(100, percent(state.entries.toLong(), state.totalEntries.toLong()), state.totalEntries == 0)
            is RuntimeState.Running -> b.setContentText("Your projects can build while the phone is locked.").addAction(0, "Stop", stop)
            is RuntimeState.Starting -> b.setProgress(0, 0, true).addAction(0, "Stop", stop)
            else -> b.setProgress(0, 0, true)
        }
        return b.build()
    }

    @Suppress("WakelockTimeout")
    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val power = getSystemService(PowerManager::class.java) ?: return
        // No timeout on purpose: held exactly while Roundtable runs, released when it stops.
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "roundtable:this-phone").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    companion object {
        const val ACTION_STOP = "com.meztking.roundtable.runtime.STOP"
        const val CHANNEL = "this_phone"
        private const val NOTIFICATION_ID = 21
        private const val NOTIFY_INTERVAL_MS = 1_000L
        private const val STOP_GRACE_MS = 4_000L

        fun notice(state: RuntimeState): String = when (state) {
            is RuntimeState.Downloading -> "Setting up ${Brand.NAME}: downloading ${percent(state.done, state.total)}%"
            RuntimeState.Verifying -> "Setting up ${Brand.NAME}: checking the download"
            is RuntimeState.Unpacking -> "Setting up ${Brand.NAME}: unpacking"
            is RuntimeState.Starting -> "Starting ${Brand.NAME} on this phone"
            is RuntimeState.Running -> "${Brand.NAME} is running on this phone"
            RuntimeState.Stopping -> "Stopping ${Brand.NAME}"
            else -> "${Brand.NAME} on this phone"
        }

        private fun percent(done: Long, total: Long): Int = if (total <= 0) 0 else ((done * 100) / total).toInt().coerceIn(0, 100)

        fun createChannel(ctx: Context) {
            if (Build.VERSION.SDK_INT >= 26) {
                val ch = NotificationChannel(CHANNEL, "${Brand.NAME} on this phone", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Shows while ${Brand.NAME} sets up or runs on this phone"
                }
                ctx.getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
            }
        }

        /** Ask for the service; quietly does nothing when Android refuses it (the app is in the background). */
        fun ensure(ctx: Context) {
            runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, HarnessRuntimeService::class.java)) }
        }
    }
}
