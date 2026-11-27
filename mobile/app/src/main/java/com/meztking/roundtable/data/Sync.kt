package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import java.time.Duration
import java.time.Instant

/**
 * The three ways the phone sees Roundtable, most direct first: Roundtable on this phone, the paired PC, and the
 * hub on GitHub. When the same project is seen through more than one, the most direct one wins.
 */
enum class Source(val key: String, val lives: String, val words: String, val title: String) {
    PHONE("phone", "on this phone", "this phone", "This phone"),
    PC("pc", "on your PC", "your PC", "Your PC"),
    HUB("hub", "in the cloud", "the hub", "Hub");

    companion object {
        fun of(key: String?): Source? = entries.firstOrNull { it.key == key }
    }
}

/** A machine's heartbeat in the hub (machines/<seat>.json). */
@Serializable
data class MachineBeat(
    val seat: String = "",
    val name: String = "",
    val last_seen: String = "",
    val version: String = "",
    val listening: Boolean = false,
)

/** Which machine builds a project just now (claims/<project-key>.json): one at a time. */
@Serializable
data class Claim(
    val project: String = "",
    val machine: String = "",
    val machine_name: String = "",
    val since: String = "",
    val heartbeat: String = "",
)

/** The hub seats that are this phone's own Roundtable and the paired PC (so a claim can say "your PC"). */
data class Selves(val phone: String? = null, val pc: String? = null)

/** Where a command for a project goes: straight to the machine that has it, or through the hub to it. */
data class Route(val via: Source, val direct: Boolean, val holder: Source? = null, val machine: String = "", val machineName: String = "")

/** The machines and claims, wherever they were read. */
data class SyncInfo(val machines: List<MachineBeat> = emptyList(), val claims: List<Claim> = emptyList())

object Sync {
    /** A claim older than this is forgotten (its machine stopped without letting go). */
    val CLAIM_FRESH: Duration = Duration.ofMinutes(15)

    /** "your PC", "this phone", or the machine's own name. */
    fun machineWords(machine: String, name: String, selves: Selves): String = when {
        machine.isNotBlank() && machine == selves.phone -> Source.PHONE.words
        machine.isNotBlank() && machine == selves.pc -> Source.PC.words
        name.isNotBlank() -> name
        else -> machine.ifBlank { "another computer" }
    }

    fun holderOf(machine: String, selves: Selves): Source? = when {
        machine.isBlank() -> null
        machine == selves.phone -> Source.PHONE
        machine == selves.pc -> Source.PC
        else -> null
    }

    fun fresh(c: Claim, now: Instant = Instant.now()): Boolean {
        val t = parseInstant(c.heartbeat.ifBlank { c.since }) ?: return false
        return Duration.between(t, now) <= CLAIM_FRESH
    }

    /** Claims by project key, fresh ones only. */
    fun claimsByProject(claims: List<Claim>, now: Instant = Instant.now()): Map<String, Claim> =
        claims.filter { it.project.isNotBlank() && fresh(it, now) }.associateBy { it.project }

    private fun aliases(s: SeatView): Set<String> = setOf(s.id, s.hubName).filter { it.isNotBlank() }.toSet()

    /**
     * One seat per project from every source. Two seats are the same project when their id or hub name match; the
     * seat from the most direct source (this phone, then the PC, then the hub) is kept, filled in from the others.
     * Each seat then says where it lives and which machine is building it.
     */
    fun mergeSeats(
        parts: List<Pair<Source, List<SeatView>>>, claims: Map<String, Claim> = emptyMap(), selves: Selves = Selves(),
    ): List<SeatView> {
        val groups = mutableListOf<MutableList<SeatView>>()
        for ((src, seats) in parts.sortedBy { it.first.ordinal }) {
            for (s in seats) {
                val tagged = s.copy(source = src.key)
                val names = aliases(tagged)
                val g = groups.firstOrNull { grp -> grp.any { aliases(it).any { a -> a in names } } }
                if (g == null) groups += mutableListOf(tagged) else g += tagged
            }
        }
        return groups.map { g -> finish(combine(g), claims, selves) }
    }

    private fun combine(g: List<SeatView>): SeatView {
        val p = g.first()
        val rest = g.drop(1)
        if (rest.isEmpty()) return p
        return p.copy(
            description = p.description.ifBlank { rest.firstOrNull { it.description.isNotBlank() }?.description.orEmpty() },
            repo = p.repo.ifBlank { rest.firstOrNull { it.repo.isNotBlank() }?.repo.orEmpty() },
            leftOff = p.leftOff.ifBlank { rest.firstOrNull { it.leftOff.isNotBlank() }?.leftOff.orEmpty() },
            nextSteps = p.nextSteps.ifEmpty { rest.firstOrNull { it.nextSteps.isNotEmpty() }?.nextSteps.orEmpty() },
            lastActivity = (g.map { it.lastActivity }).maxOrNull().orEmpty(),
            openTodos = g.maxOf { it.openTodos }, high = g.maxOf { it.high }, unread = g.maxOf { it.unread },
            progress = p.progress ?: rest.firstNotNullOfOrNull { it.progress },
            hasPlan = g.any { it.hasPlan },
            path = p.path ?: rest.firstNotNullOfOrNull { it.path },
            autopilot = g.any { it.autopilot },
            holder = p.holder.ifBlank { rest.firstOrNull { it.holder.isNotBlank() }?.holder.orEmpty() },
            hubName = p.hubName.ifBlank { rest.firstOrNull { it.hubName.isNotBlank() }?.hubName.orEmpty() },
            hubAgent = p.hubAgent.ifBlank { rest.firstOrNull { it.hubAgent.isNotBlank() }?.hubAgent.orEmpty() },
            status = if (g.any { it.status == "running" }) "running" else p.status,
            seenIn = g.map { it.source }.distinct().drop(1),
        )
    }

    private fun finish(s: SeatView, claims: Map<String, Claim>, selves: Selves): SeatView {
        val claim = claims[s.id] ?: claims[s.hubName]
        val holder = Source.of(s.holder) ?: claim?.let { holderOf(it.machine, selves) }
        val lives = when {
            holder != null -> holder.lives
            claim != null -> "on " + machineWords(claim.machine, claim.machine_name, selves)
            Source.of(s.source) == Source.HUB -> Source.HUB.lives
            else -> ""
        }
        val who = claim?.let { machineWords(it.machine, it.machine_name, selves) } ?: holder?.words
        val building = if (s.status == "running") buildingLine(s.progress, who) else ""
        return s.copy(
            holder = holder?.key.orEmpty(), lives = lives,
            machine = claim?.machine.orEmpty(), machineName = claim?.machine_name.orEmpty(),
            building = building, statusText = building.ifBlank { s.statusText },
        )
    }

    /** "Building T3 of 7 on your PC". [who] is "your PC", "this phone" or a machine's name. */
    fun buildingLine(progress: com.meztking.roundtable.net.Progress?, who: String?): String {
        val step = progress?.takeIf { it.total > 0 && it.done < it.total }?.let { " T${it.done + 1} of ${it.total}" }.orEmpty()
        return "Building$step" + (who?.let { " on $it" } ?: "")
    }

    /** What makes two Needs-you items the same thing, whichever source saw it. */
    fun needIdentity(n: NeedView, canonical: (String) -> String = { it }): String {
        val p = canonical(n.project)
        return when {
            n.ask != null -> "ask:$p:${n.ask.id}"
            n.message != null -> "msg:${n.message.id}"
            n.kind == "message" -> "msg:${n.id ?: n.key}"
            n.kind == "todo" -> "todo:$p:${n.id ?: n.title}"
            n.kind == "run" -> "run:$p:${n.actions.sorted().joinToString(",")}"
            else -> n.key
        }
    }

    /** Needs you from every source, each thing once (the most direct source's copy), tagged with its source. */
    fun mergeNeeds(parts: List<Pair<Source, List<NeedView>>>, seats: List<SeatView> = emptyList()): List<NeedView> {
        val canon = buildMap { seats.forEach { s -> put(s.id, s.id); if (s.hubName.isNotBlank()) put(s.hubName, s.id) } }
        val seen = HashSet<String>()
        val out = mutableListOf<NeedView>()
        for ((src, needs) in parts.sortedBy { it.first.ordinal }) {
            for (n in needs) {
                if (seen.add(needIdentity(n) { canon[it] ?: it })) out += n.copy(source = src.key)
            }
        }
        return out
    }

    /**
     * Where a command for [seat] goes. Straight to the machine that holds the project when it answers now;
     * otherwise through the hub, addressed to that machine; with no hub set up, through a machine that answers
     * (it passes the command on through the hub). Null: nowhere to send it.
     */
    fun route(seat: SeatView?, connected: Set<Source>, configured: Set<Source> = connected, selves: Selves = Selves()): Route? {
        val holder = Source.of(seat?.holder) ?: Source.of(seat?.source)?.takeIf { it != Source.HUB }
        val machine = seat?.machine?.ifBlank { null } ?: when (holder) {
            Source.PHONE -> selves.phone.orEmpty()
            Source.PC -> selves.pc.orEmpty()
            else -> ""
        }
        if (holder != null && holder in connected) return Route(holder, direct = true, holder = holder, machine = machine)
        if (Source.HUB in configured) return Route(Source.HUB, direct = false, holder = holder, machine = machine, machineName = seat?.machineName.orEmpty())
        val relay = listOf(Source.PC, Source.PHONE).firstOrNull { it in connected } ?: return null
        return Route(relay, direct = false, holder = holder, machine = machine, machineName = seat?.machineName.orEmpty())
    }

    /** What to say once a command went the indirect way. */
    fun sentLine(r: Route, selves: Selves = Selves()): String = when {
        r.direct -> "Done"
        r.holder == Source.PC -> "Sent: your PC picks it up when it's on."
        r.holder == Source.PHONE -> "Sent: this phone picks it up when the harness runs on it."
        r.machine.isNotBlank() -> "Sent: ${machineWords(r.machine, r.machineName, selves)} picks it up when it's on."
        else -> "Sent. The harness will reply in Letters."
    }

    // -- reading the machines and claims ------------------------------------------------------------------------

    /**
     * GET /api/machines, or the hub's files. Takes a list of machines, or {machines: [...], claims: [...]}; a machine
     * may be keyed `seat` or `id`, its name `name` or `machine_name`. Anything it can't read is skipped.
     */
    fun parseMachines(json: String?): SyncInfo {
        val root = json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.parseToJsonElement(it) }.getOrNull() } ?: return SyncInfo()
        val machines = (if (root is JsonArray) root else (root as? JsonObject)?.get("machines") as? JsonArray)
            ?.mapNotNull { (it as? JsonObject)?.let(::machine) }.orEmpty()
        val claims = ((root as? JsonObject)?.get("claims") as? JsonArray)?.mapNotNull { (it as? JsonObject)?.let { o -> claim(o, "") } }.orEmpty()
        return SyncInfo(machines, claims)
    }

    fun machine(o: JsonObject, file: String = ""): MachineBeat? {
        val seat = str(o, "seat") ?: str(o, "id") ?: str(o, "machine") ?: file.removeSuffix(".json").ifBlank { null } ?: return null
        return MachineBeat(seat, str(o, "name") ?: str(o, "machine_name") ?: "", str(o, "last_seen") ?: str(o, "at") ?: "",
            str(o, "version") ?: "", (o["listening"] as? JsonPrimitive)?.booleanOrNull ?: false)
    }

    /** One claims/<project-key>.json; [file] gives the project when the file doesn't. */
    fun claim(o: JsonObject, file: String): Claim? {
        val project = str(o, "project") ?: file.removeSuffix(".json").ifBlank { null } ?: return null
        val machine = str(o, "machine") ?: return null
        return Claim(project, machine, str(o, "machine_name") ?: "", str(o, "since") ?: "", str(o, "heartbeat") ?: "")
    }

    private fun str(o: JsonObject, k: String): String? = (o[k] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }

    fun parseFile(text: String?): JsonObject? =
        text?.let { runCatching { ApiJson.parseToJsonElement(it) as? JsonObject }.getOrNull() }

    // -- each connection's state in words ------------------------------------------------------------------------

    /** How a PC address is reached: on the home network, or through Tailscale. */
    fun network(host: String?): String {
        val h = host.orEmpty()
        if (h.endsWith(".ts.net")) return "through Tailscale"
        val p = h.split('.').mapNotNull { it.toIntOrNull() }
        if (p.size == 4) {
            if (p[0] == 100 && p[1] in 64..127) return "through Tailscale"
            if (p[0] == 10 || (p[0] == 192 && p[1] == 168) || (p[0] == 172 && p[1] in 16..31)) return "on Wi-Fi"
        }
        return if (h.isBlank()) "" else "at $h"
    }

    /** "Your PC – connected on Wi-Fi", "Your PC – off, last seen 2 h ago", "Hub – synced 1 min ago". */
    fun connectionLine(src: Source, ok: Boolean?, lastOk: String, host: String? = null, phoneState: String? = null, now: Instant = Instant.now()): String {
        val head = src.title
        return when (src) {
            Source.PHONE -> "$head – ${phoneState ?: if (ok == true) "running" else "not running"}"
            Source.PC -> when {
                ok == true -> "$head – connected" + network(host).let { if (it.isBlank()) "" else " $it" }
                lastOk.isNotBlank() -> "$head – off, last seen ${ago(lastOk, now)}"
                ok == false -> "$head – off"
                else -> "$head – not checked yet"
            }
            Source.HUB -> when {
                ok == true -> "$head – synced ${ago(lastOk.ifBlank { now.toString() }, now)}"
                ok == false && lastOk.isNotBlank() -> "$head – can't reach it, last synced ${ago(lastOk, now)}"
                ok == false -> "$head – can't reach it"
                else -> "$head – not synced yet"
            }
        }
    }

    /** The newest of two times, as ISO text ("" when neither). */
    fun newest(a: String, b: String): String {
        val ta = parseInstant(a)
        val tb = parseInstant(b)
        return when {
            ta == null -> if (tb == null) "" else b
            tb == null -> a
            tb.isAfter(ta) -> b
            else -> a
        }
    }

    @Suppress("unused")
    private fun JsonElement.text(): String? = (this as? JsonPrimitive)?.contentOrNull
}
