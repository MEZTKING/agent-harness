package com.meztking.roundtable.work

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
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.net.ApiJson
import java.util.concurrent.TimeUnit

/** Every 15 minutes: anything new that needs the owner becomes one notification each (at most a few, then a summary). */
class Watch(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as RoundtableApp
        val backend = app.backend() ?: return Result.success()
        val hall = runCatching { backend.hall() }.getOrElse { return Result.retry() }
        runCatching { app.store.cachedHall = ApiJson.encodeToString(HallState.serializer(), hall) }
        announce(applicationContext, hall.needs)
        return Result.success()
    }

    companion object {
        const val CHANNEL = "needs_you"
        private const val NAME = "roundtable-watch"
        const val EXTRA_PROJECT = "project"

        fun createChannel(ctx: Context) {
            if (Build.VERSION.SDK_INT >= 26) {
                val ch = NotificationChannel(CHANNEL, "Needs you", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Letters for you and high-priority to-dos from your projects"
                }
                ctx.getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
            }
        }

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<Watch>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun cancel(ctx: Context) = WorkManager.getInstance(ctx).cancelUniqueWork(NAME)

        /** Posts what hasn't been announced yet and remembers it (Store.notified). */
        fun announce(ctx: Context, needs: List<NeedView>) {
            val store = (ctx.applicationContext as RoundtableApp).store
            val seen = store.notified
            val fresh = needs.filter { it.key !in seen }
            if (fresh.isEmpty()) return
            store.notified = seen + fresh.map { it.key }
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) return
            val nm = NotificationManagerCompat.from(ctx)
            val shown = if (fresh.size > 4) fresh.take(3) else fresh
            try {
                for (n in shown) {
                    nm.notify(n.key.hashCode(), NotificationCompat.Builder(ctx, CHANNEL)
                        .setSmallIcon(R.drawable.ic_stat_seal)
                        .setContentTitle(n.title.take(80))
                        .setContentText(if (n.kind == "message") "${n.project}: ${n.text}" else n.text)
                        .setStyle(NotificationCompat.BigTextStyle().bigText(if (n.kind == "message") n.message?.body?.take(600) ?: n.text else n.text))
                        .setContentIntent(open(ctx, n.project, n.key.hashCode()))
                        .setAutoCancel(true)
                        .setGroup("needs")
                        .build())
                }
                if (fresh.size > shown.size) {
                    nm.notify(1, NotificationCompat.Builder(ctx, CHANNEL)
                        .setSmallIcon(R.drawable.ic_stat_seal)
                        .setContentTitle("${fresh.size} new things need you")
                        .setContentText(fresh.drop(shown.size).joinToString(" · ") { it.title }.take(200))
                        .setContentIntent(open(ctx, null, 1))
                        .setAutoCancel(true)
                        .setGroup("needs")
                        .build())
                }
            } catch (_: SecurityException) {
                // notifications were switched off between the check and here
            }
        }

        private fun open(ctx: Context, project: String?, code: Int): PendingIntent {
            val i = Intent(ctx, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                if (project != null) putExtra(EXTRA_PROJECT, project)
            }
            return PendingIntent.getActivity(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
    }
}
