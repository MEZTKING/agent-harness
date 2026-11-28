package com.meztking.roundtable.data

import com.meztking.roundtable.net.Message
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap

/** What the app remembers between starts: when each connection last answered. */
interface SeenStore {
    fun lastOk(src: Source): String
    fun setLastOk(src: Source, iso: String)
}

/** One connection's state: did its last call work, when it last worked, and what went wrong. */
data class ConnHealth(val ok: Boolean? = null, val lastOk: String = "", val error: String? = null)

/**
 * Every connection at once (This phone, your PC, the hub) behind the one [Backend] face the screens use.
 *
 * The Table merges seats and Needs you from all of them, one per project ([Sync.mergeSeats]); reading a project
 * asks the connections that see it, most direct first; a command goes to the machine that has the project, or
 * through the hub to it ([Sync.route]).
 */
class MultiBackend(
    val parts: Map<Source, Backend>,
    override val identity: String,
    private val seen: SeenStore? = null,
    private val now: () -> Instant = Instant::now,
) : Backend {
    override val mode: Mode get() = if (parts.keys.any { it != Source.HUB }) Mode.PC else Mode.HUB

    private val health = ConcurrentHashMap<Source, ConnHealth>().apply {
        parts.keys.forEach { put(it, ConnHealth(lastOk = seen?.lastOk(it).orEmpty())) }
    }
    @Volatile var seats: List<SeatView> = emptyList()
        private set
    @Volatile var info: SyncInfo = SyncInfo()
        private set
    private val letterOrigin = ConcurrentHashMap<String, Source>()

    fun health(src: Source): ConnHealth = health[src] ?: ConnHealth()
    val configured: Set<Source> get() = parts.keys
    val connected: Set<Source> get() = parts.keys.filter { health[it]?.ok == true }.toSet()

    /** The hub seats of this phone's Roundtable and the PC, as they said last. */
    val selves: Selves get() = Selves(parts[Source.PHONE]?.seatId, parts[Source.PC]?.seatId)

    /** The PC's own heartbeat in the hub, when the hub has one (for "last seen"). */
    fun beat(src: Source): MachineBeat? {
        val id = parts[src]?.seatId ?: return null
        return info.machines.firstOrNull { it.seat == id }
    }

    /** Seat this ConnHealth from a call's outcome. */
    private fun mark(src: Source, error: Throwable?) {
        val was = health[src] ?: ConnHealth()
        health[src] = if (error == null) {
            val t = now().toString()
            seen?.setLastOk(src, t)
            ConnHealth(true, t, null)
        } else was.copy(ok = false, error = error.message)
    }

    private suspend fun <T> tracked(src: Source, block: suspend () -> T): Result<T> = try {
        Result.success(block()).also { mark(src, null) }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        mark(src, e)
        Result.failure(e)
    }

    /**
     * Who answers the chat of [seat] (null: Hall). Frozen in Step 0; chat-phone fills it in: the PC or This phone
     * over /api/chats/…, falling to the phone itself after 5 seconds without an answer; in Hub mode the phone's
     * own brain with a DeepSeek key, else the waiting one.
     */
    fun chatBrain(seat: SeatView?): ChatBrain = ChatBrains.choose(parts, seat, seen as? Store)

    fun modeFor(seat: SeatView?): Mode = if (Source.of(seat?.source) == Source.HUB) Mode.HUB else if (seat == null) mode else Mode.PC

    /** Every seat seen since the app started, by id and hub name: a machine that goes off is still known. */
    private val known = ConcurrentHashMap<String, SeatView>()

    private fun seat(project: String): SeatView? =
        seats.firstOrNull { it.id == project || it.hubName == project }?.takeIf { it.holder.isNotBlank() || known[project] == null }
            ?: known[project] ?: seats.firstOrNull { it.id == project || it.hubName == project }

    /** The connections that see [seat], most direct first (every connection when the seat is unknown). */
    private fun order(seat: SeatView?): List<Pair<Source, Backend>> {
        val keys = if (seat == null) Source.entries else (listOfNotNull(Source.of(seat.source)) + seat.seenIn.mapNotNull { Source.of(it) })
        return keys.distinct().mapNotNull { k -> parts[k]?.let { k to it } }.ifEmpty { Source.entries.mapNotNull { k -> parts[k]?.let { k to it } } }
    }

    /** The first answer that has something in it; the last answer, or the first error, when none does. */
    private suspend fun <T> firstUseful(seat: SeatView?, empty: (T) -> Boolean, block: suspend (Backend) -> T): T {
        var last: T? = null
        var error: Exception? = null
        for ((_, b) in order(seat)) {
            try {
                val v = block(b)
                if (!empty(v)) return v
                last = v
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (error == null) error = e
            }
        }
        @Suppress("UNCHECKED_CAST")
        return last ?: throw (error ?: IllegalStateException("Nothing is connected. Open Settings, Your computers."))
    }

    override suspend fun hall(): HallState = coroutineScope {
        val calls = parts.map { (src, b) -> async { src to tracked(src) { b.hall() } } }
        val infoCall = async { gatherInfo() }
        val results = calls.awaitAll().sortedBy { it.first.ordinal }
        val ok = results.mapNotNull { (src, r) -> r.getOrNull()?.let { src to it } }
        if (ok.isEmpty()) throw results.firstNotNullOf { it.second.exceptionOrNull() }
        info = infoCall.await()
        val claims = Sync.claimsByProject(info.claims, now())
        val merged = Sync.mergeSeats(ok.map { (s, h) -> s to h.seats }, claims, selves)
        val needs = Sync.mergeNeeds(ok.map { (s, h) -> s to h.needs }, merged)
        seats = merged
        merged.forEach { st -> known[st.id] = st; if (st.hubName.isNotBlank()) known[st.hubName] = st }
        val pilot = ok.firstNotNullOfOrNull { (s, h) -> h.autopilot?.takeIf { s != Source.PHONE } } ?: ok.firstNotNullOfOrNull { it.second.autopilot }
        HallState(sortSeats(merged), needs, now().toString(), pilot)
    }

    /** Machines and claims: from a machine that answers (one call), else the hub's files. */
    private suspend fun gatherInfo(): SyncInfo {
        for (src in listOf(Source.PC, Source.PHONE, Source.HUB)) {
            val b = parts[src] ?: continue
            val got = runCatching { b.syncInfo() }.getOrNull() ?: continue
            if (got.machines.isNotEmpty() || got.claims.isNotEmpty()) return got
        }
        return SyncInfo()
    }

    override suspend fun projects(): List<String> {
        if (seats.isEmpty()) hall()
        return seats.map { it.id }
    }

    override suspend fun status(project: String): StatusDoc = firstUseful(seat(project), { it.isEmpty }) { it.status(project) }

    override suspend fun plan(seat: SeatView): PlanView =
        firstUseful(seat, { it.doc == null && it.tasks.isEmpty() }) { it.plan(seat.copy(path = if (it is PcBackend && Source.of(seat.holder) != it.here) null else seat.path)) }

    override suspend fun inbox(project: String): List<Message> = firstUseful(seat(project), { it.isEmpty() }) { it.inbox(project) }

    override suspend fun letters(): List<Message> = coroutineScope {
        val all = parts.map { (src, b) -> async { src to runCatching { b.letters() }.getOrDefault(emptyList()) } }.awaitAll()
            .sortedBy { it.first.ordinal }
        val byId = LinkedHashMap<String, Message>()
        for ((src, list) in all) for (m in list) if (byId.putIfAbsent(m.id, m) == null) letterOrigin[m.id] = src
        byId.values.sortedByDescending { it.created_at.ifBlank { it.id } }
    }

    /** Letters are written where every machine reads them: the PC (it writes to the hub), the hub, then this phone. */
    private fun writer(): Backend {
        val live = connected
        val src = listOf(Source.PC, Source.HUB, Source.PHONE).firstOrNull { it in parts && (it in live || it == Source.HUB) }
            ?: parts.keys.minByOrNull { it.ordinal } ?: throw IllegalStateException("Nothing is connected. Open Settings, Your computers.")
        return parts.getValue(src)
    }

    override suspend fun send(to: String, subject: String, body: String) = writer().send(to, subject, body)

    override suspend fun reply(original: Message, body: String) =
        (letterOrigin[original.id]?.let { parts[it] } ?: writer()).reply(original, body)

    override suspend fun markRead(messages: List<Message>) {
        messages.groupBy { letterOrigin[it.id]?.let { s -> parts[s] } ?: writer() }.forEach { (b, ms) -> b.markRead(ms) }
    }

    /** The hub command for a run's button, for when the machine that has it is off. */
    private fun hubAction(action: String, need: NeedView): Pair<String, Map<String, Any?>>? = when (action) {
        "approve" -> "approve" to emptyMap()
        "retry", "skip" -> action to mapOf("task" to need.task)
        "resume" -> "run" to emptyMap()
        "done" -> "todo_done" to mapOf("id" to need.id)
        else -> null
    }

    override suspend fun act(need: NeedView, action: String): String {
        val src = Source.of(need.source) ?: parts.keys.minBy { it.ordinal }
        val b = parts[src] ?: throw IllegalStateException("That came from a connection that's gone. Pull down to refresh.")
        if (src == Source.HUB || src in connected || action == "read") return b.act(need, action)
        // the machine that has it doesn't answer: through the hub, addressed to it
        val hub = parts[Source.HUB] ?: return b.act(need, action)
        val (cmd, fields) = hubAction(action, need) ?: throw IllegalStateException("${src.title} is off. Try again when it's on.")
        val s = seat(need.project)
        val route = Route(Source.HUB, false, holder = src, machine = s?.machine?.ifBlank { null } ?: parts[src]?.seatId.orEmpty())
        hub.command(s?.hubAgent?.ifBlank { null } ?: need.project, cmd, fields + addressed(s, need.project, route))
        return Sync.sentLine(route, selves)
    }

    private fun addressed(s: SeatView?, project: String, r: Route): Map<String, Any?> = buildMap {
        if (r.machine.isNotBlank()) put("machine", r.machine)
        if (s != null && s.hubAgent.isNotBlank() && s.hubAgent != project) put("project_folder", project)
    }

    override suspend fun asks(seat: SeatView): List<Ask> =
        firstUseful(seat, { it.isEmpty() }) { it.asks(seat.copy(path = if (it is PcBackend && Source.of(seat.holder) != it.here) null else seat.path)) }

    override suspend fun answer(ask: Ask, reply: AskReply): String {
        val s = seat(ask.project)
        val r = Sync.route(s, connected, configured, selves) ?: throw IllegalStateException("Nothing is connected. Open Settings, Your computers.")
        val b = parts.getValue(r.via)
        if (r.direct || r.via == Source.HUB) {
            val said = b.answer(if (r.direct) ask else ask.copy(project = s?.hubName?.ifBlank { null } ?: ask.project), reply)
            return if (r.direct || r.holder == null) said else Sync.sentLine(r, selves)
        }
        return b.answer(ask, reply)
    }

    /** A plan command: straight to the machine for Approve, otherwise into the hub addressed to that machine. */
    override suspend fun command(project: String, action: String, fields: Map<String, Any?>): String {
        val s = seat(project)
        val r = Sync.route(s, connected, configured, selves) ?: throw IllegalStateException("Nothing is connected. Open Settings, Your computers.")
        if (r.direct && action == "approve" && s?.path != null) return parts.getValue(r.via).command(project, action, fields)
        val extra = addressed(s, project, r)
        val hub = parts[Source.HUB]
        if (hub != null) {
            hub.command(s?.hubAgent?.ifBlank { null } ?: s?.hubName?.ifBlank { null } ?: project, action, fields + extra)
            return if (r.direct && r.holder != null) "Sent: ${r.holder.words} does it within a minute or so." else Sync.sentLine(r.copy(direct = false), selves)
        }
        return parts.getValue(r.via).command(project, action, fields + extra)
    }

    override suspend fun autopilot(): AutopilotState? {
        for (src in listOf(Source.PC, Source.HUB, Source.PHONE)) parts[src]?.let { b -> runCatching { b.autopilot() }.getOrNull()?.let { return it } }
        return null
    }

    override suspend fun setAutopilot(on: Boolean, until: String, cap: Double?): String {
        val src = listOf(Source.PC, Source.HUB, Source.PHONE).firstOrNull { it in parts && (it in connected || it == Source.HUB) }
            ?: parts.keys.first()
        return parts.getValue(src).setAutopilot(on, until, cap)
    }

    /** The pictures from the connection that has them, and the session from the freshest source. */
    override suspend fun live(seat: SeatView): LiveView = coroutineScope {
        val pics = async {
            runCatching { firstUseful(seat, { it.shots == null && it.images.isEmpty() }) { it.live(seat) } }.getOrDefault(LiveView())
        }
        val sess = freshestSession(seat)
        val p = pics.await()
        LiveView(p.shots, p.images, sess?.second?.summary ?: p.session, from = sess?.first?.let(::fromWords).orEmpty(),
            running = sess?.second?.running == true, progress = sess?.second?.let { SessionLog.progressLine(it) }.orEmpty())
    }

    private fun fromWords(src: Source): String = when (src) {
        Source.PHONE -> "From this phone"
        Source.PC -> "From your PC"
        Source.HUB -> "Through the hub"
    }

    /** The holder first (most direct), then any machine that reads the hub, then the hub's own files. */
    suspend fun freshestSession(seat: SeatView): Pair<Source, SessionLog.Result>? {
        val keys = (listOfNotNull(Source.of(seat.holder)) + listOf(Source.PHONE, Source.PC).filter { it in connected } + Source.HUB).distinct()
        for (k in keys) {
            val b = parts[k] ?: continue
            val r = runCatching { b.session(seat) }.getOrNull() ?: continue
            if (r.summary.task != null) return k to r
        }
        return null
    }

    // -- settings -------------------------------------------------------------------------------------------------

    /** Shared settings, and where they were read. */
    suspend fun shared(): Pair<Source, SharedSettings> {
        var error: Exception? = null
        for (src in listOf(Source.PC, Source.PHONE, Source.HUB)) {
            val b = parts[src] ?: continue
            try {
                b.sharedSettings()?.let { return src to it }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (error == null) error = e
            }
        }
        throw error ?: IllegalStateException("No shared settings yet. They appear once your PC has joined the hub.")
    }

    override suspend fun sharedSettings(): SharedSettings? = runCatching { shared().second }.getOrNull()

    /** The hub's documents: straight from the hub when it's set up, else through a machine that reads it. */
    override suspend fun notes(): List<Note> {
        var error: Exception? = null
        for (src in listOf(Source.HUB, Source.PC, Source.PHONE)) {
            val b = parts[src] ?: continue
            try { b.notes().takeIf { it.isNotEmpty() }?.let { return it } } catch (e: CancellationException) { throw e } catch (e: Exception) { if (error == null) error = e }
        }
        error?.let { throw it }
        return emptyList()
    }

    override suspend fun note(name: String): String? {
        for (src in listOf(Source.HUB, Source.PC, Source.PHONE)) {
            val b = parts[src] ?: continue
            runCatching { b.note(name) }.getOrNull()?.let { return it }
        }
        return null
    }

    /** Straight to a machine that answers; otherwise as a hub command to the machine seen most recently. */
    override suspend fun saveShared(changes: JsonObject, to: String?): String {
        for (src in listOf(Source.PC, Source.PHONE)) {
            if (src in connected) return parts.getValue(src).saveShared(changes)
        }
        val hub = parts[Source.HUB] ?: throw IllegalStateException("Your PC is off and there's no hub to send this through. Try again when it's on.")
        val target = to ?: info.machines.maxByOrNull { parseInstant(it.last_seen) ?: Instant.EPOCH }?.seat ?: selves.pc ?: selves.phone
        return hub.saveShared(changes, target)
    }

    private fun holderBackend(seat: SeatView): Backend {
        val src = Source.of(seat.holder) ?: throw IllegalStateException(
            "This project is built ${seat.lives.ifBlank { "elsewhere" }}. Its own settings can be changed from the computer that builds it.")
        return parts[src] ?: throw IllegalStateException("${src.title} isn't connected. Open Settings, Your computers.")
    }

    override suspend fun projectSettings(seat: SeatView): ProjectSettingsView = holderBackend(seat).projectSettings(seat)
    override suspend fun saveProjectSettings(seat: SeatView, changes: JsonObject): ProjectSettingsView = holderBackend(seat).saveProjectSettings(seat, changes)
}
