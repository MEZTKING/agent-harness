package com.meztking.roundtable.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.net.ApiJson
import com.meztking.roundtable.notify.Classifier
import com.meztking.roundtable.notify.Notifier
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import java.util.concurrent.TimeUnit

/**
 * Every 15 minutes: what's news since the last look (finished, needs you, failed, money, idle; notify/Classifier.kt)
 * becomes one notification each on its own channel, grouped per project, never the same twice.
 */
class Watch(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as RoundtableApp
        val backend = app.backend() ?: return Result.success()
        val hall = runCatching { backend.hall() }.getOrElse { return Result.retry() }
        runCatching { app.store.cachedHall = ApiJson.encodeToString(HallState.serializer(), hall) }
        announce(applicationContext, hall, plans(backend, hall))
        return Result.success()
    }

    /** Hub projects' state from their plans (finished or building), which the hub's seats don't carry. */
    private suspend fun plans(backend: Backend, hall: HallState): Map<String, String> = coroutineScope {
        hall.seats.filter { it.hasPlan && it.path == null && it.status != "running" && it.status != "done" }.take(MAX_PLANS)
            .map { s -> async { runCatching { backend.plan(s).doc }.getOrNull()?.let { d -> Classifier.planStatus(d.state, d.finished)?.let { s.id to it } } } }
            .awaitAll().filterNotNull().toMap()
    }

    companion object {
        /** The Needs-you channel (one of five now; see Notifier). */
        const val CHANNEL = "needs_you"
        private const val NAME = "roundtable-watch"
        private const val MAX_PLANS = 10
        const val EXTRA_PROJECT = Notifier.EXTRA_PROJECT

        fun createChannel(ctx: Context) = Notifier.createChannels(ctx)

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<Watch>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun cancel(ctx: Context) = WorkManager.getInstance(ctx).cancelUniqueWork(NAME)

        /** Classifies [hall] against the last look and posts what's new (Needs-you items already seen in the app are skipped). */
        fun announce(ctx: Context, hall: HallState, plans: Map<String, String> = emptyMap()) {
            val store = (ctx.applicationContext as RoundtableApp).store
            val seenInApp = runCatching { store.notified }.getOrDefault(emptySet())
            Notifier.announce(ctx, Classifier.snapshot(hall, plans = plans), seenInApp)
            runCatching { store.notified = seenInApp + hall.needs.map { it.key } }
        }
    }
}
