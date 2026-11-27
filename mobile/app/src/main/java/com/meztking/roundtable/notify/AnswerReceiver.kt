package com.meztking.roundtable.notify

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.net.ApiJson

/** The answer a button on a notification gives: exactly what tapping that option on the card in the app gives. */
object NotifyAnswer {
    fun reply(ask: Ask, option: String): AskReply {
        require(Classifier.buttons(ask).any { it.id == option }) { "That answer can't be given from a notification. Open the app to answer." }
        return AskReply(listOf(option))
    }

    /** Sends it the same way the app answers cards (to the machine that has the project, or through the hub). */
    suspend fun send(backend: Backend, ask: Ask, option: String): String = backend.answer(ask, reply(ask, option))
}

/** A tap on Approve plan, Allow, or one of two choices: says "Sending…" at once, then the work sends it. */
class AnswerReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val data = workDataOf(
            K_KEY to intent.getStringExtra(K_KEY), K_KIND to intent.getStringExtra(K_KIND),
            K_PROJECT to intent.getStringExtra(K_PROJECT), K_TITLE to intent.getStringExtra(K_TITLE),
            K_ASK to intent.getStringExtra(K_ASK), K_OPTION to intent.getStringExtra(K_OPTION),
            K_LABEL to intent.getStringExtra(K_LABEL),
        )
        val key = data.getString(K_KEY) ?: return
        Notifier.replaceWith(ctx, key, data.getString(K_KIND).orEmpty(), data.getString(K_PROJECT).orEmpty(),
            data.getString(K_TITLE).orEmpty(), "Sending “${data.getString(K_LABEL).orEmpty()}”…")
        WorkManager.getInstance(ctx).enqueue(OneTimeWorkRequestBuilder<AnswerWork>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(data).build())
    }

    companion object {
        const val K_KEY = "key"; const val K_KIND = "kind"; const val K_PROJECT = "project"; const val K_TITLE = "title"
        const val K_ASK = "ask"; const val K_OPTION = "option"; const val K_LABEL = "label"

        fun intent(ctx: Context, n: News, ask: Ask, btn: NewsButton, code: Int): PendingIntent {
            val i = Intent(ctx, AnswerReceiver::class.java).apply {
                putExtra(K_KEY, n.key); putExtra(K_KIND, n.kind); putExtra(K_PROJECT, n.project); putExtra(K_TITLE, n.title)
                putExtra(K_ASK, Notifier.askJson(ask)); putExtra(K_OPTION, btn.id); putExtra(K_LABEL, btn.label)
            }
            return PendingIntent.getBroadcast(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
    }
}

/** Sends one answer from a notification, then puts what happened on the notification. Never tried twice by itself. */
class AnswerWork(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val d: Data = inputData
        val key = d.getString(AnswerReceiver.K_KEY) ?: return Result.success()
        val kind = d.getString(AnswerReceiver.K_KIND).orEmpty()
        val project = d.getString(AnswerReceiver.K_PROJECT).orEmpty()
        val title = d.getString(AnswerReceiver.K_TITLE).orEmpty()
        val line = try {
            val ask = ApiJson.decodeFromString(Ask.serializer(), d.getString(AnswerReceiver.K_ASK) ?: error("no card"))
            val backend = (applicationContext as RoundtableApp).backend()
                ?: throw IllegalStateException("Nothing is connected. Open the app, then Settings.")
            runCatching { backend.hall() }  // which machine has the project now, so the answer goes the right way
            NotifyAnswer.send(backend, ask, d.getString(AnswerReceiver.K_OPTION).orEmpty()).ifBlank { "Sent." }
        } catch (e: Exception) {
            "Couldn't send it: ${e.message ?: "try again in the app"}. Tap to open the project and answer there."
        }
        Notifier.replaceWith(applicationContext, key, kind, project, title, line)
        return Result.success()
    }
}
