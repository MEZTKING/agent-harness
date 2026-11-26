package com.meztking.roundtable.update

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.meztking.roundtable.MainActivity
import com.meztking.roundtable.R
import java.util.concurrent.TimeUnit

/** Once a day: is a newer Roundtable Mobile out? One notification per new version. */
class UpdateWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val updater = AppUpdater.get(applicationContext)
        if (!updater.enabled) return Result.success()
        val found = runCatching { updater.check(quiet = true) }.getOrNull() ?: return Result.success()
        if (updater.shouldNotify(found.version)) {
            updater.markNotified(found.version)
            notify(applicationContext, found)
        }
        return Result.success()
    }

    companion object {
        const val CHANNEL = "updates"
        private const val NAME = "roundtable-update-check"

        /** Called when the app starts: the channel, and the daily check if it's on (else none). */
        fun setUp(ctx: Context) {
            if (Build.VERSION.SDK_INT >= 26) {
                val ch = NotificationChannel(CHANNEL, "Updates", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "When a new Roundtable Mobile is out"
                }
                ctx.getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
            }
            if (AppUpdater.get(ctx).enabled) schedule(ctx) else cancel(ctx)
        }

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<UpdateWorker>(1, TimeUnit.DAYS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun cancel(ctx: Context) { WorkManager.getInstance(ctx).cancelUniqueWork(NAME) }

        fun notify(ctx: Context, r: AppRelease) {
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) return
            val open = PendingIntent.getActivity(ctx, 7301,
                Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val notes = notesPreview(r.notes)
            try {
                NotificationManagerCompat.from(ctx).notify(7301, NotificationCompat.Builder(ctx, CHANNEL)
                    .setSmallIcon(R.drawable.ic_stat_seal)
                    .setContentTitle("Roundtable Mobile ${r.version} is out")
                    .setContentText(notes.ifBlank { "Tap to update it from the Table." })
                    .setStyle(NotificationCompat.BigTextStyle().bigText((if (notes.isBlank()) "" else "$notes\n") + "Tap, then Update on the Table."))
                    .setContentIntent(open)
                    .setAutoCancel(true)
                    .build())
            } catch (_: SecurityException) {
                // notifications were switched off between the check and here
            }
        }
    }
}
