package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/**
 * The checking dial and who did each task (the PC's GET /api/tandem?path, harness/dial.py and ui/tandemapi.py):
 * the plan's level (Lean, Balanced, Maximum) with its price, and per task who built it, who checked it and whether
 * they disagreed. The PC writes the one line and the folded lines; [Tandem.line] makes the same line when an older
 * PC left it out.
 */
@Serializable
data class TandemReview(val model: String = "", val maker: String = "", val approved: Boolean = false,
                        val feedback: String = "", val breaks: String = "", val counted: Boolean = true)

@Serializable
data class TandemRival(val id: String = "", val model: String = "", val maker: String = "", val picked: Boolean = false,
                       val why: String = "")

@Serializable
data class TandemTask(
    val built_by: String = "",
    val built_by_label: String = "",
    val agent: String = "",
    val agent_name: String = "",
    val rivals: List<TandemRival> = emptyList(),
    val reviews: List<TandemReview> = emptyList(),
    val disagreed: Boolean = false,
    val same_maker: Boolean = false,
    val line: String = "",
    val fold: List<String> = emptyList(),
)

@Serializable
data class TandemAllowance(val usd: Double? = null, val spent: Double = 0.0, val used_up: Boolean = false)

@Serializable
data class TandemEstimate(val cost_usd: Double? = null, val minutes: Double? = null, val extra_usd: Double = 0.0,
                          val planning_usd: Double? = 0.0, val unpriced: Boolean = false)

@Serializable
data class TandemView(
    val level: String = "lean",
    val label: String = "",
    val words: String = "",
    val allowance: TandemAllowance = TandemAllowance(),
    val estimates: Map<String, TandemEstimate> = emptyMap(),
    val tasks: Map<String, TandemTask> = emptyMap(),
)

object Tandem {
    val LEVELS = listOf("lean", "balanced", "maximum")
    private val NAMES = mapOf("lean" to "Lean", "balanced" to "Balanced", "maximum" to "Maximum")

    /** The PC's address for a project's who-did-what (for Api.feature("GET", ...)). */
    fun url(path: String): String = "/api/tandem?path=${URLEncoder.encode(path, "UTF-8")}"

    fun parse(json: String?): TandemView? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(TandemView.serializer(), it) }.getOrNull() }

    fun levelName(level: String): String = NAMES[level] ?: "Lean"

    /** "Checking: Balanced", always labelled (the model sets have a Balanced too). */
    fun label(v: TandemView): String = v.label.ifBlank { "Checking: ${levelName(v.level)}" }

    /** "anthropic/claude-opus-5-5" -> "Claude Opus 5 5"-ish short name, only when the PC sent no label. */
    fun shortName(ref: String): String {
        val name = ref.substringAfterLast('/')
        if (name.isBlank()) return ""
        return name.split('-', '_').filter { it.isNotBlank() }.joinToString(" ") { w -> w.replaceFirstChar { it.uppercase() } }
    }

    private fun and(names: List<String>): String {
        val n = names.filter { it.isNotBlank() }.distinct()
        return when (n.size) { 0 -> ""; 1 -> n[0]; else -> n.dropLast(1).joinToString(", ") + " and " + n.last() }
    }

    /** "Built by Claude Opus · checked by GPT and Gemini · they disagreed". */
    fun line(t: TandemTask): String {
        if (t.line.isNotBlank()) return t.line
        val parts = mutableListOf("Built by " + t.built_by_label.ifBlank { shortName(t.built_by) }.ifBlank { "a model" } +
            (if (t.agent.isNotBlank()) " (${t.agent_name.ifBlank { t.agent }})" else ""))
        if (t.rivals.size > 1) parts.add("best of ${t.rivals.size}")
        val checkers = and(t.reviews.map { shortName(it.model) })
        if (checkers.isNotBlank()) parts.add("checked by $checkers")
        if (t.disagreed) parts.add("they disagreed")
        if (t.same_maker) parts.add("one checker is from the same company")
        return parts.joinToString(" · ")
    }

    /** Behind "More": each try, why a rival won, each checker's verdict and quote. */
    fun foldLines(t: TandemTask): List<String> = t.fold.ifEmpty {
        t.rivals.map { "Rival ${it.id} ${shortName(it.model)}: ${if (it.picked) "chosen" else "not chosen"}" +
            (if (it.why.isNotBlank()) ": ${it.why}" else "") } +
            t.reviews.map { r -> "${shortName(r.model)} ${if (r.approved) "approved" else "sent it back"}" +
                (if (r.breaks.isNotBlank()) " – “${r.breaks}”" else if (r.feedback.isNotBlank()) " – ${r.feedback}" else "") }
    }

    /** "about $1.20" for a level's button, or "price not known". */
    fun priceWords(e: TandemEstimate?): String =
        if (e?.cost_usd == null || e.unpriced) "price not known" else "about $" + String.format(java.util.Locale.UK, "%.2f", e.cost_usd)
}
