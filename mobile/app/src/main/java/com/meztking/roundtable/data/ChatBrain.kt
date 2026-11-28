package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flowOf

/** What arrives while the chat answers: the owner's line as kept, words and thinking as written, then the answer. */
sealed interface Piece {
    data class Sent(val line: ChatLine, val turn: String) : Piece
    data class Words(val text: String) : Piece
    data class Thinking(val text: String) : Piece
    /** The answer's line (the model's, or the app's own when nothing can answer: `who` "app"). */
    data class Answer(val line: ChatLine) : Piece
}

/**
 * Who answers the chat on this phone (frozen in Step 0; chat-phone fills them in): `ApiBrain` (PC and This
 * phone, over /api/chats/…), `PhoneBrain` (Hub mode with a DeepSeek key: the phone itself) and `WaitingBrain`
 * (Hub mode without one: the message waits for a machine). [MultiBackend.chatBrain] chooses.
 */
interface ChatBrain {
    /** `draftKey`: the composer draft whose files go with the message. */
    suspend fun say(chat: String, text: String, draftKey: String? = null): Flow<Piece>
    /** A tap on one of a card's buttons; only this runs anything that spends or can't be undone. */
    suspend fun tap(chat: String, card: String, button: String = "do", confirmed: Boolean = false): ChatLine
    suspend fun read(chat: String, since: String = ""): ChatRead
    suspend fun chats(): List<ChatSummary> = emptyList()
    suspend fun stop(chat: String, turn: String) {}
}

/** The stub until chat-phone's brains are in: it answers in the app's own words, and sends nothing. */
object NoChatBrain : ChatBrain {
    private fun line(text: String) = ChatLine(who = "app", text = text)

    override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> =
        flowOf(Piece.Answer(line("The chat isn't ready on this phone yet.")))

    override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean): ChatLine =
        line("The chat isn't ready on this phone yet.")

    override suspend fun read(chat: String, since: String): ChatRead = ChatRead(at = since, can = CanAnswer(false, "off"))
}

/**
 * The app's own words when nothing can answer, the same on every device (chat.py CANNOT and BUTTON_WORDS): a line
 * with `who: app` and, where something can be done, a card with those buttons.
 */
object ChatWords {
    val CANNOT: Map<String, Pair<String, List<String>>> = mapOf(
        "no_machine" to ("Nothing can answer right now: your PC last listened {ago}. Add a DeepSeek key to get answers " +
            "here at once (about a tenth of a cent a message), or I'll answer when your PC is next on." to listOf("add_key")),
        "key_refused" to ("DeepSeek refused the key. Your message is kept." to listOf("change_key")),
        "no_credit" to ("The DeepSeek account is empty. Your message is kept." to listOf("top_up")),
        "offline" to ("No internet. Your message is kept and sent when you're back." to emptyList()),
        "allowance" to ("Today's chat allowance ({limit}) is used." to listOf("raise_today")),
        "off" to ("The chat is switched off in Settings." to emptyList()),
        "pc_stopped" to ("Your PC stopped answering; I'm answering from this phone." to emptyList()),
    )

    val BUTTON_WORDS = mapOf(
        "do" to "Do it", "not_now" to "Not now", "cancel" to "Cancel", "here" to "Run it on This phone instead",
        "setup_phone" to "Set up This phone first", "add_key" to "Add a DeepSeek key", "change_key" to "Change the key",
        "top_up" to "Top up", "raise_today" to "Raise it for today",
    )

    /** What the owner reads for one of a card's buttons. */
    fun button(id: String, primary: Boolean = false, words: String? = null): CardButton =
        CardButton(id, words ?: Words.t(BUTTON_WORDS[id] ?: id), primary)

    /** The app's own line for [why] (one of [ChatLayout.CANNOT]); [vals] fill {ago}, {limit}. */
    fun cannot(why: String, vararg vals: Pair<String, String>, answers: String? = null, seat: String = ""): ChatLine {
        val (english, buttons) = CANNOT[why] ?: CANNOT.getValue("offline")
        val words = Words.t(english, *vals)
        val card = if (buttons.isEmpty()) null else ChatCard(id = "app-$why", line = words, state = "open",
            buttons = buttons.mapIndexed { i, b -> button(b, primary = i == 0) })
        return ChatLine(id = "app-$why-" + System.nanoTime().toString(36), at = java.time.Instant.now().toString(), who = "app",
            seat = seat, text = words, card = card, answers = answers)
    }

    /** A plain line from the app (no card). */
    fun note(text: String, answers: String? = null, seat: String = ""): ChatLine =
        ChatLine(id = "app-" + System.nanoTime().toString(36), at = java.time.Instant.now().toString(), who = "app", seat = seat,
            text = text, answers = answers)
}

/** One call of the PC's (or This phone's) API: method, path, body; returns the answer's text. */
fun interface ChatCalls {
    suspend fun call(method: String, path: String, body: String?): String
}

/**
 * PC mode and This phone: the chat over the machine's own /api/chats/… routes (ui/chatsapi.py). The answer is read
 * once a second from `answering`, as the desktop does; [upload] sends a draft's files to the machine first and gives
 * the machine's own draft key.
 */
class ApiBrain(
    private val calls: ChatCalls,
    private val upload: (suspend (String) -> String?)? = null,
    private val pollMs: Long = 1000,
    private val waitMs: Long = 180_000,
) : ChatBrain {
    private fun q(s: String) = java.net.URLEncoder.encode(s, "UTF-8")

    override suspend fun chats(): List<ChatSummary> =
        ApiJson.decodeFromString(ChatList.serializer(), calls.call("GET", "/api/chats", null)).chats

    override suspend fun read(chat: String, since: String): ChatRead =
        ApiJson.decodeFromString(ChatRead.serializer(), calls.call("GET", "/api/chats/read?chat=${q(chat)}&since=${q(since)}", null))

    override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> {
        val key = if (draftKey != null && upload != null) upload.invoke(draftKey) else null
        val body = kotlinx.serialization.json.buildJsonObject {
            put("chat", kotlinx.serialization.json.JsonPrimitive(chat)); put("text", kotlinx.serialization.json.JsonPrimitive(text))
            if (key != null) put("key", kotlinx.serialization.json.JsonPrimitive(key))
        }.toString()
        val sent = ApiJson.decodeFromString(SayResult.serializer(), calls.call("POST", "/api/chats/say", body))
        return kotlinx.coroutines.flow.flow {
            emit(Piece.Sent(sent.line, sent.turn))
            var words = ""
            var thinking = ""
            var quiet = 0
            val start = System.currentTimeMillis()
            while (System.currentTimeMillis() - start < waitMs) {
                kotlinx.coroutines.delay(pollMs)
                val r = read(chat, sent.line.at)
                val a = r.answering
                if (a != null) {
                    if (a.thinking.length > thinking.length && a.thinking.startsWith(thinking)) { emit(Piece.Thinking(a.thinking.drop(thinking.length))); thinking = a.thinking }
                    if (a.text.length > words.length && a.text.startsWith(words)) { emit(Piece.Words(a.text.drop(words.length))); words = a.text }
                }
                val answer = r.lines.firstOrNull { it.answers == sent.line.id && it.who != "owner" }
                if (answer != null) { emit(Piece.Answer(answer)); return@flow }
                if (a == null && !r.can.answer && r.can.why.isNotBlank() && ++quiet >= 3) {
                    emit(Piece.Answer(ChatWords.cannot(r.can.why, "ago" to Words.t("a while ago"), "limit" to "$1.00", answers = sent.line.id)))
                    return@flow
                }
            }
            emit(Piece.Answer(ChatWords.cannot("pc_stopped", answers = sent.line.id)))
        }
    }

    override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean): ChatLine {
        val body = kotlinx.serialization.json.buildJsonObject {
            put("chat", kotlinx.serialization.json.JsonPrimitive(chat)); put("card", kotlinx.serialization.json.JsonPrimitive(card))
            put("button", kotlinx.serialization.json.JsonPrimitive(button)); put("confirmed", kotlinx.serialization.json.JsonPrimitive(confirmed))
        }.toString()
        return ApiJson.decodeFromString(TapResult.serializer(), calls.call("POST", "/api/chats/tap", body)).line
    }

    override suspend fun stop(chat: String, turn: String) {
        calls.call("POST", "/api/chats/stop", """{"chat": ${kotlinx.serialization.json.JsonPrimitive(chat)}, "turn": ${kotlinx.serialization.json.JsonPrimitive(turn)}}""")
    }
}

/**
 * The PC first, the phone itself when the PC doesn't answer within [timeoutMs] (or stops mid-answer): the chat then
 * says so ("Your PC stopped answering; I'm answering from this phone.") and carries on through [fallback].
 */
class FallbackBrain(
    private val primary: ChatBrain,
    private val fallback: ChatBrain?,
    private val timeoutMs: Long = 5000,
) : ChatBrain {
    /** True once the PC failed to answer; reads and taps then go to the phone until a read works again. */
    @Volatile var fellBack: Boolean = false
        private set

    private fun down(answers: String? = null): ChatLine = if (fallback != null) ChatWords.cannot("pc_stopped", answers = answers)
        else ChatWords.note(Words.t("Your PC isn't answering, so your message wasn't sent. Try again when it's on."), answers)

    override suspend fun say(chat: String, text: String, draftKey: String?): Flow<Piece> {
        val first = try {
            kotlinx.coroutines.withTimeoutOrNull(timeoutMs) { primary.say(chat, text, draftKey) }
        } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { null }
        if (first == null) {
            fellBack = fallback != null
            val rest = fallback?.say(chat, text, draftKey)
            return kotlinx.coroutines.flow.flow { emit(Piece.Answer(down())); if (rest != null) emitAll(rest) }
        }
        fellBack = false
        return kotlinx.coroutines.flow.flow {
            var sent = false
            var answered = false
            try {
                first.collect { p -> if (p is Piece.Sent) sent = true; if (p is Piece.Answer) answered = true; emit(p) }
            } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) {
                if (answered) return@flow
                fellBack = fallback != null
                emit(Piece.Answer(down()))
                if (fallback != null) emitAll(fallback.say(chat, text, draftKey).let { f ->
                    // the PC already kept the owner's line: don't show it twice
                    if (sent) kotlinx.coroutines.flow.flow { f.collect { if (it !is Piece.Sent) emit(it) } } else f
                })
            }
        }
    }

    override suspend fun read(chat: String, since: String): ChatRead {
        val r = try {
            kotlinx.coroutines.withTimeoutOrNull(timeoutMs) { primary.read(chat, since) }
        } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { null }
        if (r != null) { fellBack = false; return r }
        return fallback?.read(chat, since) ?: throw IllegalStateException(Words.t("Your PC isn't answering. Try again when it's on."))
    }

    override suspend fun tap(chat: String, card: String, button: String, confirmed: Boolean): ChatLine =
        if (fellBack && fallback != null) fallback.tap(chat, card, button, confirmed)
        else try { primary.tap(chat, card, button, confirmed) } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) {
            fallback?.tap(chat, card, button, confirmed) ?: throw e
        }

    override suspend fun chats(): List<ChatSummary> = try {
        kotlinx.coroutines.withTimeoutOrNull(timeoutMs) { primary.chats() } ?: fallback?.chats().orEmpty()
    } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { fallback?.chats().orEmpty() }

    override suspend fun stop(chat: String, turn: String) {
        runCatching { primary.stop(chat, turn) }; runCatching { fallback?.stop(chat, turn) }
    }
}
