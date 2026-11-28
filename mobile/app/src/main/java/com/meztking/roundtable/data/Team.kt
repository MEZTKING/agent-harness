package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

// Read-only views of the PC's wave 8 pages: the checks on GitHub, who last listened, what each service used, the named
// agents and the board. The owner changes these on the PC; the phone shows them, short first.

/** One check run (GET /api/ci). [detail] is never shown: it may hold the PC's raw error. */
@Serializable
data class CiRun(val name: String = "", val conclusion: String? = null, val status: String = "", val url: String = "")

@Serializable
data class CiView(val state: String = "", val words: String = "", val repo: String = "", val branch: String = "",
                  val failing: List<CiRun> = emptyList(), val runs: List<CiRun> = emptyList()) {
    /** Whether the chip is worth showing: nothing for a project not on GitHub. */
    val shown: Boolean get() = state.isNotBlank() && state != "not_github"
}

/** Which harness last listened for work (GET /api/listening). */
@Serializable
data class Listening(val machine: String = "", val at: String? = null, val minutes: Double? = null, val words: String = "") {
    /** Long quiet: the line is shown as a warning. */
    val stale: Boolean get() = minutes == null || minutes > 15
}

@Serializable
data class UsageUsed(val calls: Int = 0, val day_usd: Double = 0.0, val month_usd: Double = 0.0, val unpriced: Int = 0)

@Serializable
data class UsageService(val id: String = "", val name: String = "", val words: String = "", val reached: String = "",
                        val balance_words: String = "", val unpriced_words: String = "", val used: UsageUsed = UsageUsed())

/** What each service used against the owner's limits (GET /api/usage); the limits are set on the PC. */
@Serializable
data class UsageView(val words: String = "", val note: String = "", val services: List<UsageService> = emptyList()) {
    val monthUsd: Double get() = services.sumOf { it.used.month_usd }
    val reached: List<UsageService> get() = services.filter { it.reached.isNotBlank() }
}

/** A named agent (GET /api/agents); [face] is a picture the image model made, as a data address. */
@Serializable
data class Agent(val id: String = "", val name: String = "", val job: String = "", val job_name: String = "", val about: String = "",
                 val line: String = "", val initials: String = "", val hired: Boolean = false, val traits: List<String> = emptyList(),
                 val face: String = "")

@Serializable
data class AgentJob(val job: String = "", val name: String = "", val words: String = "", val hired: Boolean = false)

@Serializable
data class AgentsView(val agents: List<Agent> = emptyList(), val jobs: List<AgentJob> = emptyList(), val words: String = "") {
    /** The agent doing [job] now, if one is hired for it. */
    fun hiredFor(job: String): Agent? = agents.firstOrNull { it.job == job && it.hired }
}

@Serializable
data class BoardMove(val to: String = "", val label: String = "", val confirm: Boolean = false)

@Serializable
data class BoardCard(val id: String = "", val number: String = "", val title: String = "", val line: String = "", val status: String = "",
                     val column: String = "", val moves: List<BoardMove> = emptyList())

@Serializable
data class BoardColumn(val id: String = "", val title: String = "", val cards: List<BoardCard> = emptyList())

@Serializable
data class BoardState(val word: String = "", val line: String = "", val state: String = "")

/** Every task as a card in its column (GET /api/board); on the phone, read only. */
@Serializable
data class BoardView(val columns: List<BoardColumn> = emptyList(), val state: BoardState? = null, val busy: Boolean = false) {
    /** The columns that hold cards (an empty Left out column isn't shown, as on the PC). */
    val shown: List<BoardColumn> get() = columns.filter { it.cards.isNotEmpty() }

    /** "3 done · 1 building", the columns with cards, in order. */
    val summary: String get() = shown.joinToString(" · ") { "${it.cards.size} ${it.title.lowercase()}" }
}

object Team {
    fun ciUrl(path: String) = "/api/ci?path=${e(path)}"
    const val LISTENING = "/api/listening"
    const val USAGE = "/api/usage"
    const val AGENTS = "/api/agents"
    fun boardUrl(path: String) = "/api/board?path=${e(path)}"

    fun ci(json: String): CiView = ApiJson.decodeFromString(CiView.serializer(), json)
    fun listening(json: String): Listening = ApiJson.decodeFromString(Listening.serializer(), json)
    fun usage(json: String): UsageView = ApiJson.decodeFromString(UsageView.serializer(), json)
    fun agents(json: String): AgentsView = ApiJson.decodeFromString(AgentsView.serializer(), json)
    fun board(json: String): BoardView = ApiJson.decodeFromString(BoardView.serializer(), json)

    /** "$0.0013 this month across 2 services". */
    fun usageLine(v: UsageView): String {
        val n = v.services.size
        if (n == 0) return "Nothing used yet."
        return "${Money.usd(v.monthUsd)} this month across $n service${if (n == 1) "" else "s"}" +
            if (v.reached.isNotEmpty()) ". ${v.reached.size} reached a limit." else "."
    }

    /** Hiring: the PC's answer to "Give this job to…": its own sentence ("Saved Maelin.") and the agent as it is now. */
    @Serializable
    data class Hired(val reply: String = "", val agent: Agent? = null)

    fun hired(json: String): Hired = ApiJson.decodeFromString(Hired.serializer(), json)

    /** The agents who could take [job]: those not doing it now (making a new agent stays on the PC). */
    fun canTake(v: AgentsView, job: String): List<Agent> = v.agents.filter { !(it.job == job && it.hired) }

    private fun e(s: String) = URLEncoder.encode(s, "UTF-8")
}

/** Dollars in the owner's words: "$0.41", "$0.0013", "$0". */
object Money {
    fun usd(v: Double): String = when {
        v <= 0.0 -> "$0"
        v < 0.01 -> "$" + String.format(java.util.Locale.UK, "%.4f", v)
        else -> "$" + String.format(java.util.Locale.UK, "%.2f", v)
    }
}
