package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable

/** One line of what autopilot did (Roundtable Hold's autopilot log), newest first. */
@Serializable
data class AutopilotEntry(
    val at: String = "",
    /** on | off | chose | left */
    val kind: String = "",
    val project: String? = null,
    val path: String? = null,
    val text: String = "",
)

/**
 * Autopilot: while the owner is away, Roundtable answers what waits with the recommended answers.
 * The same shape as the PC's /api/autopilot and the hub's plans/autopilot.json.
 */
@Serializable
data class AutopilotState(
    val on: Boolean = false,
    val until: String? = null,
    val until_label: String = "",
    val spend_cap_usd: Double = 2.0,
    val spent_usd: Double = 0.0,
    /** "until 8am · $0.40 of $2.00", or "Off". */
    val label: String = "Off",
    val never: List<String> = emptyList(),
    val stopped: String = "",
    /** Hub mode: the hub project whose inbox the PC reads for commands. */
    val inbox: String? = null,
    val log: List<AutopilotEntry> = emptyList(),
)

object Autopilot {
    /** When to stop, as the owner picks it: value sent, label shown, what it means. */
    val UNTIL = listOf(
        Triple("", "Off when I'm back", "It stays on until you turn it off."),
        Triple("1h", "1 hour", "It turns itself off in an hour."),
        Triple("tonight", "Tonight", "It turns itself off at 8am tomorrow."),
    )

    fun parse(json: String?): AutopilotState? =
        if (json.isNullOrBlank()) null else runCatching { ApiJson.decodeFromString(AutopilotState.serializer(), json) }.getOrNull()

    /** The fields of the hub command `roundtable: {"action": "autopilot", ...}`. */
    fun commandFields(on: Boolean, until: String = "", cap: Double? = null): Map<String, Any?> =
        if (!on) mapOf("state" to "off")
        else buildMap { put("state", "on"); put("until", until); if (cap != null) put("cap", cap) }

    /** Which hub project to send the command to: the one the PC reads, else any project with a plan. */
    fun commandTarget(state: AutopilotState?, seats: List<SeatView>): String? =
        state?.inbox?.takeIf { it.isNotBlank() } ?: seats.firstOrNull { it.hasPlan }?.id
}
