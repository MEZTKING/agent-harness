package com.meztking.roundtable.data

import kotlinx.coroutines.flow.Flow
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
