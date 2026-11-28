package com.meztking.roundtable.notify

import android.content.Context
import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.ChatNotices
import com.meztking.roundtable.data.ChatSummary
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.HubChat
import com.meztking.roundtable.data.MultiBackend
import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.builtins.ListSerializer

/**
 * The chat in the background (the Watch worker, every 15 minutes): a chat where this phone's message waits for an
 * answer, or a queued card waits to be done, is read again; what changed since the last look becomes one
 * notification each ("Your message was answered: …", "Done: …"; [ChatNotices.news]). Only those chats are read, so
 * the rest stay unread where they are.
 */
object ChatWatch {
    private const val MAX_CHATS = 6
    private const val KEEP = 60
    private const val PREFS = "chat-watch"

    /** The chats worth reading now: those the machine says wait for an answer, and those that waited last time. */
    fun toRead(summaries: List<ChatSummary>, pending: Set<String>): List<String> =
        (summaries.filter { it.waiting > 0 }.map { it.id } + pending).distinct().take(MAX_CHATS)

    /** Whether [lines] still hold something this phone waits for: its own waiting line, or a queued or running card. */
    fun pending(lines: List<ChatLine>, seat: String): Boolean =
        lines.any { it.who == "owner" && it.seat == seat && it.state == "waiting" } ||
            lines.any { it.card?.state == "queued" || it.card?.state == "running" }

    /** The notifications for one chat, from the lines before and after. */
    fun news(chat: String, name: String, project: String, before: List<ChatLine>, after: List<ChatLine>, seat: String): List<News> =
        ChatNotices.news(before, after, seat).map { words ->
            News("chat:$chat:${words.hashCode()}", NewsKind.NEEDS_YOU, project, name, words, group = project.ifBlank { chat })
        }

    suspend fun look(ctx: Context, backend: MultiBackend, hall: HallState, seat: String) {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val lines = ListSerializer(ChatLine.serializer())
        val summaries = runCatching { backend.chatBrain(null).chats() }.getOrNull() ?: return
        val pending = prefs.getStringSet("pending", emptySet()).orEmpty()
        val still = mutableSetOf<String>()
        val out = mutableListOf<News>()
        for (chat in toRead(summaries, pending)) {
            val s = hall.seats.firstOrNull { HubChat.chatOf(it) == chat }
            val after = runCatching { backend.chatBrain(s).read(chat, "").lines }.getOrNull() ?: continue
            val before = prefs.getString("before.$chat", null)?.let { runCatching { ApiJson.decodeFromString(lines, it) }.getOrNull() }
            prefs.edit().putString("before.$chat", ApiJson.encodeToString(lines, after.takeLast(KEEP))).apply()
            if (pending(after, seat)) still += chat
            if (before != null) out += news(chat, summaries.firstOrNull { it.id == chat }?.name ?: chat, s?.id.orEmpty(), before, after, seat)
        }
        prefs.edit().putStringSet("pending", still).apply()
        if (out.isNotEmpty()) Notifier.announceChat(ctx, out)
    }
}
