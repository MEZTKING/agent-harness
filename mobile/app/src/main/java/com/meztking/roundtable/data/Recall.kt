package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder

/** One piece found by meaning in your projects, documents and the journal (GET /api/recall). */
@Serializable
data class RecallPiece(val kind: String = "", val kind_words: String = "", val title: String = "", val text: String = "",
                       val where: String = "", val private: Boolean = false)

@Serializable
data class RecallFound(val pieces: List<RecallPiece> = emptyList(), val words: String = "", val name: String = "")

@Serializable
data class RecallQuote(val text: String = "", val title: String = "", val source: String = "")

/** POST /api/recall/ask: without confirm the price ([words], [price_usd]) and nothing sent; with it the [answer]. */
@Serializable
data class RecallAnswer(val question: String = "", val answer: String = "", val quotes: List<RecallQuote> = emptyList(),
                        val pieces: List<RecallPiece> = emptyList(), val held: Int = 0, val price_usd: Double = 0.0,
                        val cost_usd: Double = 0.0, val model_label: String = "", val words: String = "")

object Recall {
    fun findUrl(words: String) = "/api/recall?q=${URLEncoder.encode(words.trim(), "UTF-8")}"
    const val ASK = "/api/recall/ask"

    fun found(json: String): RecallFound = ApiJson.decodeFromString(RecallFound.serializer(), json)
    fun answer(json: String): RecallAnswer = ApiJson.decodeFromString(RecallAnswer.serializer(), json)

    fun askBody(question: String, confirm: Boolean): String =
        buildJsonObject { put("question", question.trim()); put("confirm", confirm) }.toString()

    /** The first lines of a piece, without Markdown marks, for its row. */
    fun snippet(p: RecallPiece, max: Int = 160): String {
        val flat = Markdown.plain(p.text).lines().map { it.trim() }.filter { it.isNotBlank() && it != p.title }.joinToString(" ")
        return if (flat.length > max) flat.take(max).trimEnd() + "…" else flat
    }

    /** The price line before asking: the PC's own words, else "About $x to answer". */
    fun priceLine(a: RecallAnswer): String = a.words.ifBlank { "About ${Money.usd(a.price_usd)} to answer." }
}
