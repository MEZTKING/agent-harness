package com.meztking.roundtable.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.meztking.roundtable.MainActivity
import com.meztking.roundtable.R
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer

/** The project on screen just now (set by [QuietWhileOpen]): its news is kept but makes no sound. */
object OnScreen {
    @Volatile var project: String? = null
}

/** The phone's own switches and memory for notifications (not secret, so plain preferences). */
class NotifyPrefs(ctx: Context) {
    private val prefs: SharedPreferences = ctx.applicationContext.getSharedPreferences("roundtable.notify", Context.MODE_PRIVATE)

    fun on(kind: String): Boolean = prefs.getBoolean("kind.$kind", true)
    fun set(kind: String, on: Boolean) = prefs.edit().putBoolean("kind.$kind", on).apply()

    /** Keys of news already given, newest last, so the same news never comes twice. */
    var seen: List<String>
        get() = runCatching { ApiJson.decodeFromString(ListSerializer(String.serializer()), prefs.getString("seen", "[]")!!) }.getOrDefault(emptyList())
        set(v) = prefs.edit().putString("seen", ApiJson.encodeToString(ListSerializer(String.serializer()), v.takeLast(KEEP))).apply()

    /** The last snapshot the classifier saw. */
    var last: Snapshot?
        get() = prefs.getString("last", null)?.let { runCatching { ApiJson.decodeFromString(Snapshot.serializer(), it) }.getOrNull() }
        set(v) = prefs.edit().apply { if (v == null) remove("last") else putString("last", ApiJson.encodeToString(Snapshot.serializer(), v)) }.apply()

    companion object { const val KEEP = 500 }
}

/**
 * Posts the news: one channel per kind (the owner can mute each in Android's settings, or here in the app's
 * Settings), grouped per project, the same key never twice, quiet while that project is on screen.
 */
object Notifier {
    const val EXTRA_PROJECT = "project"
    /** The old single channel's id, kept so the owner's choice for it stays. */
    private val CHANNELS = mapOf(
        NewsKind.NEEDS_YOU to "needs_you", NewsKind.FINISHED to "finished", NewsKind.FAILED to "failed",
        NewsKind.MONEY to "money", NewsKind.IDLE to "idle",
    )
    private const val MAX_SHOWN = 5

    fun channel(kind: String): String = CHANNELS[kind] ?: "needs_you"

    fun createChannels(ctx: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        for (kind in NewsKind.ALL) {
            val importance = if (kind == NewsKind.IDLE || kind == NewsKind.FINISHED) NotificationManager.IMPORTANCE_DEFAULT
                else NotificationManager.IMPORTANCE_HIGH
            nm.createNotificationChannel(NotificationChannel(channel(kind), NewsKind.name(kind), importance).apply {
                description = NewsKind.hint(kind)
            })
        }
    }

    /** Which of [news] to post: switched on, not given before ([seen], plus Needs-you items seen in the app). */
    fun fresh(news: List<News>, seen: Collection<String>, seenInApp: Set<String>, on: (String) -> Boolean): List<News> {
        val given = seen.toHashSet()
        return news.filter { n ->
            n.key !in given && on(n.kind) && n.key.substringAfter(':') !in seenInApp
        }.distinctBy { it.key }
    }

    /** Classify [now] against the last snapshot, post what's new and remember it. Returns what was posted. */
    fun announce(ctx: Context, now: Snapshot, seenInApp: Set<String> = emptySet()): List<News> {
        val prefs = NotifyPrefs(ctx)
        val old = prefs.last
        val news = Classifier.classify(old, now, OnScreen.project)
        prefs.last = now
        val seen = prefs.seen
        val fresh = fresh(news, seen, seenInApp, prefs::on)
        // everything classified counts as given, switched off or not: turning a kind on later doesn't replay old news
        prefs.seen = seen + news.map { it.key }.filter { it !in seen }
        val loud = fresh.filter { !it.quiet }
        if (loud.isEmpty() || !allowed(ctx)) return emptyList()
        post(ctx, loud)
        return loud
    }

    /** The chat's news (ChatWatch): posted once each on the Needs-you channel, when that kind is switched on. */
    fun announceChat(ctx: Context, news: List<News>): List<News> {
        val prefs = NotifyPrefs(ctx)
        val seen = prefs.seen
        val fresh = fresh(news, seen, emptySet(), prefs::on)
        prefs.seen = seen + news.map { it.key }.filter { it !in seen }
        if (fresh.isEmpty() || !allowed(ctx)) return emptyList()
        post(ctx, fresh)
        return fresh
    }

    private fun allowed(ctx: Context) = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun id(key: String) = key.hashCode()

    private fun post(ctx: Context, news: List<News>) {
        val nm = NotificationManagerCompat.from(ctx)
        val shown = if (news.size > MAX_SHOWN) news.take(MAX_SHOWN - 1) else news
        try {
            for (n in shown) nm.notify(id(n.key), build(ctx, n).build())
            // a summary per project with more than one, so Android folds them together
            shown.groupBy { it.group }.filter { it.value.size > 1 }.forEach { (project, items) ->
                nm.notify(id("group:$project"), NotificationCompat.Builder(ctx, channel(items.first().kind))
                    .setSmallIcon(R.drawable.ic_stat_seal)
                    .setContentTitle(items.first().name)
                    .setContentText("${items.size} new things")
                    .setStyle(NotificationCompat.InboxStyle().also { s -> items.forEach { s.addLine(it.title) } })
                    .setGroup(group(project)).setGroupSummary(true).setAutoCancel(true)
                    .setContentIntent(open(ctx, project, id("group:$project")))
                    .build())
            }
            if (news.size > shown.size) {
                val rest = news.drop(shown.size)
                nm.notify(1, NotificationCompat.Builder(ctx, channel(NewsKind.NEEDS_YOU))
                    .setSmallIcon(R.drawable.ic_stat_seal)
                    .setContentTitle("${rest.size} more things for you")
                    .setContentText(rest.joinToString(" · ") { it.title }.take(200))
                    .setContentIntent(open(ctx, null, 1))
                    .setAutoCancel(true)
                    .build())
            }
        } catch (_: SecurityException) {
            // notifications were switched off between the check and here
        }
    }

    private fun group(project: String) = "project:$project"

    fun build(ctx: Context, n: News): NotificationCompat.Builder {
        val b = NotificationCompat.Builder(ctx, channel(n.kind))
            .setSmallIcon(R.drawable.ic_stat_seal)
            .setContentTitle(n.title.take(80))
            .setContentText(n.text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(n.text.take(600)))
            .setContentIntent(open(ctx, n.project, id(n.key)))
            .setAutoCancel(true)
            .setGroup(group(n.group))
            .setCategory(if (n.kind == NewsKind.NEEDS_YOU) NotificationCompat.CATEGORY_REMINDER else NotificationCompat.CATEGORY_STATUS)
        val ask = n.ask
        if (ask != null) n.buttons.take(3).forEachIndexed { i, btn ->
            b.addAction(0, btn.label.take(24), AnswerReceiver.intent(ctx, n, ask, btn, id(n.key) * 4 + i))
        }
        return b
    }

    /** Replace a notification after a tap on one of its buttons: what happened, in a line. */
    fun replaceWith(ctx: Context, key: String, kind: String, project: String, title: String, line: String) {
        if (!allowed(ctx)) return
        try {
            NotificationManagerCompat.from(ctx).notify(id(key), NotificationCompat.Builder(ctx, channel(kind))
                .setSmallIcon(R.drawable.ic_stat_seal)
                .setContentTitle(title.take(80)).setContentText(line)
                .setContentIntent(open(ctx, project, id(key)))
                .setAutoCancel(true).setOnlyAlertOnce(true).setSilent(true)
                .setGroup(group(project))
                .build())
        } catch (_: SecurityException) {
        }
    }

    fun open(ctx: Context, project: String?, code: Int): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            if (project != null) putExtra(EXTRA_PROJECT, project)
        }
        return PendingIntent.getActivity(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    fun askJson(ask: Ask): String = ApiJson.encodeToString(Ask.serializer(), ask.copy(detail = ask.detail.take(200)))
}
