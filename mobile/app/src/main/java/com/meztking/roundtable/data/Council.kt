package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.net.URLEncoder

/**
 * The planning council on a plan (the PC's GET /api/tandem/council?path, harness/council.py): two or three rival
 * planners each planned the idea, and the owner's own planner merged them. One line first; the points they differed
 * on, and who planned, behind a tap. Nothing for a plan made by one planner, or an older PC.
 */
@Serializable
data class CouncilPlanner(val label: String = "", val model: String = "", val maker: String = "", val tasks: Int = 0,
                          val summary: String = "", val votes: Int = 0)

@Serializable
data class CouncilSaid(val who: String = "", val says: String = "")

@Serializable
data class CouncilPoint(val topic: String = "", val options: List<CouncilSaid> = emptyList(), val chosen: String = "",
                        val why: String = "")

@Serializable
data class CouncilView(val found: Boolean = true, val words: String = "", val planners: List<CouncilPlanner> = emptyList(),
                       val disagreements: List<CouncilPoint> = emptyList(), val chair: String = "",
                       val merged: Boolean = false, val best: String = "", val stopped: String = "",
                       val cost_usd: Double? = null)

object Council {
    fun url(path: String): String = "/api/tandem/council?path=${URLEncoder.encode(path, "UTF-8")}"

    /**
     * The council from any of: the council API's answer, a plan document ({"council": …}) or GET /api/plan's answer
     * ({"doc": {"council": …}}). Null when there is none.
     */
    fun parse(json: String?): CouncilView? {
        if (json.isNullOrBlank()) return null
        val root = runCatching { ApiJson.parseToJsonElement(json).jsonObject }.getOrNull() ?: return null
        val obj: JsonObject = (root["doc"] as? JsonObject)?.get("council") as? JsonObject
            ?: root["council"] as? JsonObject
            ?: root
        val v = runCatching { ApiJson.decodeFromJsonElement(CouncilView.serializer(), obj) }.getOrNull() ?: return null
        return v.takeIf { it.found && it.planners.isNotEmpty() }
    }

    private fun number(n: Int) = when (n) { 2 -> "Two"; 3 -> "Three"; else -> "$n" }

    /** The one line, made here when the PC sends none (the same words as council.words on the PC). */
    fun line(v: CouncilView): String = v.words.ifBlank {
        val who = "${number(v.planners.size)} planners"
        val k = v.disagreements.size
        when {
            !v.merged && v.best.isNotBlank() -> "$who each made a plan; the one the others liked best (${v.best}) was used"
            !v.merged -> "$who each made a plan"
            k == 0 -> "$who agreed on the whole plan"
            else -> "$who agreed on most of it; they differed on $k thing${if (k == 1) "" else "s"}"
        }
    }

    /** A point they differed on, in lines: what each plan said, then what was chosen. */
    fun pointLines(p: CouncilPoint): List<String> = buildList {
        p.options.forEach { add("Plan ${it.who}: ${it.says}") }
        if (p.chosen.isNotBlank()) add("Chosen: ${p.chosen}" + if (p.why.isNotBlank()) " – ${p.why}" else "")
    }

    /** Behind More: who planned, the chair, and what it cost. */
    fun moreLines(v: CouncilView): List<String> = buildList {
        v.planners.forEach { p ->
            add("Plan ${p.label} · ${p.model} · ${p.tasks} task${if (p.tasks == 1) "" else "s"}" +
                if (p.votes > 0) " · liked best by ${p.votes}" else "")
        }
        if (v.chair.isNotBlank()) add("Merged by ${v.chair}, your own planner")
        if (v.stopped == "cap") add("The planners reached their spending cap, so the best plan so far was used")
        else if (v.stopped.isNotBlank()) add("Not merged: ${v.stopped}")
        v.cost_usd?.let { add("The planners cost $" + String.format(java.util.Locale.UK, "%.2f", it)) }
    }
}
