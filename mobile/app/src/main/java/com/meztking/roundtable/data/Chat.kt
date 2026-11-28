package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName

/*
 * The chat that replaced Letters (1.5.0): the same shapes as the PC's chatstore.py and ui/chatsapi.py, frozen in
 * Step 0. The history lives in the hub, one file per device and day:
 *
 *     chats/<chat>/<day>.<seat>.jsonl     one JSON line per message, written only by the device <seat>
 *     chats/<chat>/files/<sha>.<ext>      an attached picture (at most 1600 px, 1.5 MB) or small file
 *     chats/<chat>/claims/<turn>.json     {"seat", "at"}: who is answering a waiting message
 *
 * <chat> is "hall" or the project's key in the hub; <day> is the UTC day (YYYY-MM-DD). A reader merges every
 * device's day files by (at, seat, id). Only lines this device wrote are trusted: a card is honoured only in an
 * answer to an owner's line typed here.
 */

/** One attached file: `name` shown, kept as `files/<sha>.<ext>`; `on` the seat that holds one too big for the hub. */
@Serializable
data class ChatFile(val name: String = "", val sha: String = "", val ext: String = "", val size: Long = 0,
                    val kind: String = "file", val on: String? = null)

/** A card's button. `id` is one of [ChatLayout.BUTTONS]. */
@Serializable
data class CardButton(val id: String = "", val words: String = "", val primary: Boolean = false)

/**
 * What the chat offers to do: built by the app from the parsed command, never from the model's words. `command`
 * is the checked `/` command a tap runs; `confirm` the "Are you sure?" sentence; `state` one of
 * [ChatLayout.CARD_STATES]; `queuedFor` the machine it waits for.
 */
@Serializable
data class ChatCard(
    val id: String = "",
    val title: String = "",
    val line: String = "",
    @SerialName("price_usd") val priceUsd: Double? = null,
    @SerialName("cap_usd") val capUsd: Double? = null,
    val confirm: String? = null,
    val command: String = "",
    val buttons: List<CardButton> = emptyList(),
    val state: String = "open",
    @SerialName("queued_for") val queuedFor: String? = null,
    val more: String? = null,
)

/** One message. `who`: owner, chat, project, agent or app; `state` (an owner's line): waiting or answered. */
@Serializable
data class ChatLine(
    val id: String = "",
    val at: String = "",
    val who: String = "app",
    val seat: String = "",
    val device: String? = null,
    val text: String = "",
    val thinking: String? = null,
    val files: List<ChatFile> = emptyList(),
    val card: ChatCard? = null,
    @SerialName("cost_usd") val costUsd: Double? = null,
    val model: String? = null,
    val answers: String? = null,
    val state: String? = null,
    val from: String? = null,
    val to: String? = null,
)

/** One row of the list of chats (GET /api/chats). */
@Serializable
data class ChatSummary(val id: String = "", val name: String = "", val last: String = "", val unread: Int = 0,
                       val waiting: Int = 0)

@Serializable
data class ChatList(val chats: List<ChatSummary> = emptyList())

/** Whether anything can answer now; `why` is one of [ChatLayout.CANNOT] when not. */
@Serializable
data class CanAnswer(val answer: Boolean = false, val why: String = "")

/** GET /api/chats/read: the lines since `at`, the answer being written, and whether anything can answer. */
@Serializable
data class ChatRead(val lines: List<ChatLine> = emptyList(), val at: String = "", val answering: StreamRead? = null,
                    val can: CanAnswer = CanAnswer())

/** POST /api/chats/say: the owner's line as kept, and the turn (the id the answer will have). */
@Serializable
data class SayResult(val line: ChatLine = ChatLine(), val turn: String = "")

/** POST /api/chats/tap: the card's line as it now stands. */
@Serializable
data class TapResult(val line: ChatLine = ChatLine())

object ChatLayout {
    const val HALL = "hall"
    const val ROOT = "chats"
    const val PICTURE_PX = 1600
    const val FILE_MAX_BYTES = 1_500_000L
    const val MODEL = "deepseek-v4-flash" // the phone's own answers: fixed in code, never from settings
    const val REPLY_TOKENS = 700
    const val HISTORY = 12
    val NEVER = listOf("v4-pro")
    val WHO = listOf("owner", "chat", "project", "agent", "app")
    val CARD_STATES = listOf("open", "queued", "running", "done", "cancelled")
    val BUTTONS = listOf("do", "not_now", "cancel", "here", "setup_phone", "add_key", "change_key", "top_up", "raise_today")
    val CANNOT = listOf("no_machine", "key_refused", "no_credit", "offline", "allowance", "off", "pc_stopped")
    private val CHAT = Regex("^[a-z0-9][a-z0-9-]{0,79}$")

    fun isChat(chat: String): Boolean = CHAT.matches(chat)
    fun never(model: String): Boolean = NEVER.any { model.lowercase().contains(it) }

    fun dayPath(chat: String, day: String, seat: String): String = "$ROOT/${need(chat)}/$day.${safe(seat)}.jsonl"
    fun filePath(chat: String, sha: String, ext: String): String = "$ROOT/${need(chat)}/files/${safe(sha)}.${safe(ext)}"
    fun claimPath(chat: String, turn: String): String = "$ROOT/${need(chat)}/claims/${safe(turn)}.json"

    /** How a reader merges the day files. */
    val order: Comparator<ChatLine> = compareBy<ChatLine>({ it.at }, { it.seat }, { it.id })

    fun parseLine(json: String): ChatLine = ApiJson.decodeFromString(ChatLine.serializer(), json)
    fun lineJson(line: ChatLine): String = ApiJson.encodeToString(ChatLine.serializer(), line)

    private fun need(chat: String): String = chat.also { require(isChat(it)) { "not a chat: $it" } }
    private fun safe(s: String): String = s.replace(Regex("[^A-Za-z0-9_.-]+"), "-").trim('.', '-').ifEmpty { "x" }
}
