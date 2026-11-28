package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable

/** One card the PC left for the owner to answer on its own, and why (its own sentence). */
@Serializable
data class LeftCard(val id: String = "", val path: String = "", val why: String = "")

@Serializable
data class AnsweredCard(val id: String = "", val path: String = "", val reply: String = "")

/** What POST /api/board/answer-several did: which cards got their recommended answer, which were left and why. */
@Serializable
data class AnswerSeveralResult(val answered: List<AnsweredCard> = emptyList(), val left: List<LeftCard> = emptyList(), val reply: String = "")

/**
 * Answer these: with three or more cards waiting, the owner ticks several and gives each its recommended answer in one
 * go. A card that spends, deletes or can't be undone (its recommended answer has `confirm`), a command, a card with no
 * recommended answer, and a card only the PC answers are never ticked: they are shown greyed with "Answer this one by
 * itself". The PC checks all of this again (boardapi.needs_alone, phone.PHONE_NARROW); this is only what the phone shows.
 */
object AnswerThese {
    /** How many cards must wait before the bar shows. */
    const val AT_LEAST = 3
    const val URL = "/api/board/answer-several"

    /** Cards answered only on the PC itself (phone.PC_ONLY_ASKS). */
    private val PC_ONLY = listOf("shipoffer")

    /** Why [ask] must be answered on its own; "" when it can be ticked. */
    fun alone(ask: Ask): String {
        if (PC_ONLY.any { ask.id.startsWith(it) }) return "Only your PC can answer this one."
        if (ask.kind == "command") return "A command is always answered on its own."
        if (ask.local || ask.path.isNullOrBlank()) return "This one waits for Update plan, so it's answered on its own."
        val rec = ask.recommended ?: return "It has no recommended answer."
        val opt = ask.options.firstOrNull { it.id == rec } ?: return "It has no recommended answer."
        if (opt.confirm != null) return "Its recommended answer spends money or can't be undone, so it's answered on its own."
        if (ask.stamp.isBlank()) return "It was sent without the question it answers. Look at it again."
        return ""
    }

    /** Whether the bar shows for these cards. */
    fun shown(cards: List<Ask>): Boolean = cards.size >= AT_LEAST

    /** The cards that may be ticked, ticked to start with. */
    fun ticked(cards: List<Ask>): Set<String> = cards.filter { alone(it).isEmpty() }.map { it.id }.toSet()

    /** The request's items for the ticked cards: {path, id, stamp} each; a card that must be answered alone never goes. */
    fun items(cards: List<Ask>, ticked: Set<String>): List<Triple<String, String, String>> =
        cards.filter { it.id in ticked && alone(it).isEmpty() }.map { Triple(it.path.orEmpty(), it.id, it.stamp) }

    fun parse(json: String): AnswerSeveralResult = ApiJson.decodeFromString(AnswerSeveralResult.serializer(), json)

    /** What was left and why, one line each, with the card's own question: "Which look? · Its recommended answer…". */
    fun leftLines(r: AnswerSeveralResult, cards: List<Ask>): List<String> = r.left.map { l ->
        val q = cards.firstOrNull { it.id == l.id }?.question?.ifBlank { null } ?: Words.t("A question")
        "$q · ${l.why.ifBlank { Words.t("Answer it on its own.") }}"
    }

    /** The bar's line: "3 questions wait. Tick the ones to answer with the recommended answer." */
    fun barLine(cards: List<Ask>): String {
        val n = cards.size
        val can = ticked(cards).size
        return Words.t("{n} questions wait.", "n" to n) + " " +
            if (can == 0) Words.t("Each one needs answering on its own.") else Words.t("Tick the ones to answer with the recommended answer.")
    }
}
