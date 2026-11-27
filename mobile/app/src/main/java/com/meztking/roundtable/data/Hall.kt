package com.meztking.roundtable.data

import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.GitHubHub
import com.meztking.roundtable.net.HubSnapshot
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.net.Seat
import com.meztking.roundtable.net.Task
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.serialization.Serializable
import java.time.Duration
import java.time.Instant

enum class Mode { HUB, PC }

/** One seat at the table, the same shape in both modes. */
@Serializable
data class SeatView(
    val id: String,
    /** running | waiting | idle | done */
    val status: String = "idle",
    val statusText: String = "",
    val description: String = "",
    val repo: String = "",
    val lastActivity: String = "",
    val leftOff: String = "",
    val nextSteps: List<String> = emptyList(),
    val openTodos: Int = 0,
    val high: Int = 0,
    val unread: Int = 0,
    val progress: Progress? = null,
    val hasPlan: Boolean = false,
    /** PC mode: the harness run's folder, for its task tree and actions. */
    val path: String? = null,
    /** Autopilot answers this project's questions while the owner is away. */
    val autopilot: Boolean = false,
    /** Which connection this seat was read through: "phone", "pc" or "hub" (Source.key). */
    val source: String = "",
    /** The machine that has the project: "phone", "pc", or "" when it is elsewhere or unknown. */
    val holder: String = "",
    /** Where it lives, in words: "on your PC", "on this phone", "in the cloud". */
    val lives: String = "",
    /** The machine building it just now (from the hub's claims): its hub seat and name. */
    val machine: String = "",
    val machineName: String = "",
    /** "Building T3 of 7 on your PC", while it builds. */
    val building: String = "",
    /** The plan's name in the hub and the hub project commands go to (the PC's seats). */
    val hubName: String = "",
    val hubAgent: String = "",
    /** The other connections that also see it. */
    val seenIn: List<String> = emptyList(),
) {
    val initials: String get() = initialsOf(id)
    val badge: Int get() = unread + high
}

/** One thing that waits for the owner. [key] identifies it for "notify once". */
@Serializable
data class NeedView(
    val key: String,
    /** todo | message | run */
    val kind: String,
    val project: String,
    val title: String,
    val text: String = "",
    val actions: List<String> = emptyList(),
    val id: String? = null,
    val task: String? = null,
    val path: String? = null,
    val message: Message? = null,
    val at: String = "",
    /** A question to answer by tapping (asks.py), and how many wait on this project in all. */
    val ask: Ask? = null,
    val asks: Int = 0,
    /** Which connection it came through (Source.key); answers go back the same way. */
    val source: String = "",
)

@Serializable
data class HallState(
    val seats: List<SeatView> = emptyList(), val needs: List<NeedView> = emptyList(), val fetchedAt: String = "",
    /** Autopilot's switch and what it did lately; null when the PC or the hub doesn't say. */
    val autopilot: AutopilotState? = null,
)

/** What the Plan tab shows: the hub's plan page, or (PC mode) the run's task tree. */
/** A saved document in the hub (notes/<name>), shown by its first heading. */
@Serializable
data class Note(val name: String = "", val title: String = "", val at: String = "") {
    companion object {
        private val heading = Regex("^#{1,6}\\s+(.*\\S)")
        private val safeName = Regex("^[A-Za-z0-9][\\w .-]{0,80}\\.md$")

        fun safe(name: String) = safeName.matches(name)

        /** The first heading, else the file's name in words ("kite-links.md" -> "Kite links"). */
        fun title(md: String, name: String): String = md.lineSequence().firstNotNullOfOrNull { heading.find(it.trim())?.groupValues?.get(1) }
            ?: name.removeSuffix(".md").replace('-', ' ').replace('_', ' ').replaceFirstChar { it.uppercase() }
    }
}

data class PlanView(val doc: PlanDoc? = null, val tasks: List<Task> = emptyList(), val runStatus: String = "", val canApprove: Boolean = false,
                    /** The plan in the owner's words (title, where it stands); null for a plan published before them. */
                    val words: PlanWords? = null,
                    /** What kind of thing it is (kinds): the plan's first card; null for none or in Hub mode. */
                    val kind: PlanKind? = null)

/** The two ways in (the hub on GitHub, or the paired PC) behind one face. */
interface Backend {
    val mode: Mode
    val identity: String
    suspend fun hall(): HallState
    suspend fun projects(): List<String>
    suspend fun status(project: String): StatusDoc
    suspend fun plan(seat: SeatView): PlanView
    suspend fun inbox(project: String): List<Message>
    suspend fun letters(): List<Message>
    suspend fun send(to: String, subject: String, body: String)
    suspend fun reply(original: Message, body: String)
    /** Marks the owner's own messages read (agents' inboxes are theirs to read). */
    suspend fun markRead(messages: List<Message>)
    /** A one-tap answer on a Needs-you card. Returns a short line to show. */
    suspend fun act(need: NeedView, action: String): String
    /** The questions waiting on a project, as cards to tap. */
    suspend fun asks(seat: SeatView): List<Ask>
    /** Answer a card. Returns a short line to show. */
    suspend fun answer(ask: Ask, reply: AskReply): String
    /** Hub only: a command through the hub (see GitHubHub.command). */
    suspend fun command(project: String, action: String, fields: Map<String, Any?> = emptyMap()): String
    /** Autopilot's switch and its log (null when it can't be read). */
    suspend fun autopilot(): AutopilotState?
    /** Turn autopilot on (until, spend limit in dollars) or off. Returns a short line to show. */
    suspend fun setAutopilot(on: Boolean, until: String = "", cap: Double? = null): String
    /** The newest pictures of the project's app and its latest task's steps (the Live tab). */
    suspend fun live(seat: SeatView): LiveView

    // -- keeping several machines in step (each has a default, so a backend says only what it can) ------------

    /** This connection's own seat in the hub (its machine id), once known. */
    val seatId: String? get() = null
    /** The machines in the hub and who is building what. */
    suspend fun syncInfo(): SyncInfo = SyncInfo()
    /** The project's live session, as fresh as this connection has it; null when it has none. */
    suspend fun session(seat: SeatView): SessionLog.Result? = null
    /** The settings every machine shares; null when this connection can't read them. */
    suspend fun sharedSettings(): SharedSettings? = null

    /** The owner's saved documents in the hub (the notes folder), by their first heading; nothing more until one is opened. */
    suspend fun notes(): List<Note> = emptyList()

    /** One saved document as markdown; null when it isn't there. */
    suspend fun note(name: String): String? = null
    /** Change shared settings ([changes] in the file's own shape). [to]: the machine a hub command goes to. */
    suspend fun saveShared(changes: kotlinx.serialization.json.JsonObject, to: String? = null): String =
        throw IllegalStateException("Shared settings can't be changed this way. Connect your PC or the hub first.")
    /** One project's own settings (the machine that has it). */
    suspend fun projectSettings(seat: SeatView): ProjectSettingsView =
        throw IllegalStateException("This project's settings live on the computer that builds it. Connect that computer first.")
    suspend fun saveProjectSettings(seat: SeatView, changes: kotlinx.serialization.json.JsonObject): ProjectSettingsView =
        throw IllegalStateException("This project's settings live on the computer that builds it. Connect that computer first.")
}

class HubBackend(private val hub: GitHubHub, override val identity: String) : Backend {
    override val mode = Mode.HUB
    @Volatile private var last: HubSnapshot? = null

    private suspend fun snap(fresh: Boolean = false): HubSnapshot = (if (fresh) null else last) ?: hub.snapshot().also { last = it }

    override suspend fun projects() = snap().projects.map { it.id }

    override suspend fun hall(): HallState {
        val s = snap(fresh = true)
        val seats = s.projects.map { p ->
            val doc = StatusDoc.parse(s.status[p.id].orEmpty())
            val todos = doc.todos
            val high = todos.count { it.high }
            val unread = s.unread(p.id).size
            SeatView(
                id = p.id,
                status = if (high > 0 || (p.id == identity && unread > 0)) "waiting" else "idle",
                statusText = when {
                    doc.isEmpty -> "no status page yet"
                    high > 0 -> "$high high-priority to-do" + if (high > 1) "s" else ""
                    doc.updated.isNotEmpty() -> "idle · ${ago(doc.updated)}"
                    else -> "idle"
                },
                description = p.description.ifBlank { doc.description },
                repo = p.repo,
                lastActivity = doc.updated.ifBlank { doc.leftOffAt },
                leftOff = Markdown.plain(doc.leftOff),
                nextSteps = doc.nextSteps.map { Markdown.plain(it) },
                openTodos = todos.size, high = high, unread = unread,
                hasPlan = p.id in s.plans,
            )
        }
        val needs = mutableListOf<NeedView>()
        val mine = s.unread(identity).take(40)
        var receipts = 0
        if (mine.isNotEmpty()) {
            val letters = hub.messages(identity, mine, s.readIds[identity].orEmpty())
            // Roundtable's receipts for the owner's own commands don't need them: read at once, shown only in Letters
            val (done, real) = letters.partition { Letters.isReceipt(it) }
            if (done.isNotEmpty()) runCatching { hub.markRead(identity, done.map { it.id }) }.onSuccess { receipts = done.size }
            real.forEach { m -> needs += letterNeed(m) }
        }
        for (seat in seats) {
            val doc = StatusDoc.parse(s.status[seat.id].orEmpty())
            doc.todos.filter { it.high }.forEach { t ->
                needs += NeedView("todo:${seat.id}:${t.id ?: t.text.hashCode()}", "todo", seat.id, "To do: ${Markdown.plain(t.text)}",
                    "${seat.id} · high priority · from the journal", listOf("open"), id = t.id, at = doc.updated)
            }
        }
        needs.addAll(0, askNeeds(seats.filter { it.hasPlan }))
        lastSeats = seats
        val pilot = autopilot()
        val marked = seats.map {
            it.copy(autopilot = pilot?.on == true && it.hasPlan && it.id !in pilot.never,
                unread = if (it.id == identity) (it.unread - receipts).coerceAtLeast(0) else it.unread)
        }
        return HallState(sortSeats(marked), needs, Instant.now().toString(), pilot)
    }

    /** Every card waiting on the projects with a plan, one Needs-you item each (cards built from a plan only while it waits). */
    private suspend fun askNeeds(planned: List<SeatView>): List<NeedView> = coroutineScope {
        planned.map { seat -> async { seat.id to runCatching { cards(seat.id, forNeeds = true) }.getOrDefault(emptyList()) } }.awaitAll()
            .flatMap { (project, asks) -> asks.map { askNeed(project, listOf(it), 1) } }
    }

    private suspend fun cards(project: String, forNeeds: Boolean): List<Ask> {
        val file = hub.asks(project)
        if (file != null) return Asks.parse(file).map { it.copy(project = project) }
        val doc = PlanDoc.parse(hub.plan(project) ?: return emptyList())
        if (forNeeds && !doc.waitingForOwner) return emptyList()  // an agreed plan's leftovers are on its Plan tab, not Needs you
        return Asks.fromPlan(doc, project)
    }

    override suspend fun asks(seat: SeatView): List<Ask> = cards(seat.id, forNeeds = false)

    override suspend fun answer(ask: Ask, reply: AskReply): String {
        if (ask.local) {  // built from the plan: the plan's own commands
            val cmds = Asks.planCommands(ask, reply)
            if (cmds.isEmpty()) throw IllegalStateException("Pick an answer, or type one.")
            cmds.forEach { (action, fields) -> hub.command(identity, ask.project, action, fields) }
            return "Sent. It waits until you press Update plan."
        }
        hub.command(identity, ask.project, "answer", Asks.commandFields(ask, reply))
        return "Sent. Roundtable will reply in Letters."
    }

    override suspend fun status(project: String) = StatusDoc.parse(hub.status(project))

    override suspend fun plan(seat: SeatView): PlanView = coroutineScope {
        val words = async { runCatching { PlanWords.parse(hub.asks(seat.id)) }.getOrNull() }
        val md = hub.plan(seat.id) ?: return@coroutineScope PlanView()
        val doc = PlanDoc.parse(md)
        PlanView(doc = doc, canApprove = doc.waitingForOwner, words = words.await())
    }

    override suspend fun inbox(project: String) = hub.inbox(project)

    override suspend fun letters(): List<Message> = coroutineScope {
        val s = snap(fresh = true)
        s.projects.map { p ->
            async { hub.messages(p.id, s.inboxIds[p.id].orEmpty().take(25), s.readIds[p.id].orEmpty()) }
        }.awaitAll().flatten().sortedByDescending { it.created_at.ifBlank { it.id } }
    }

    override suspend fun send(to: String, subject: String, body: String) { hub.send(identity, to, subject, body) }

    override suspend fun reply(original: Message, body: String) {
        // answer the sender; if the owner wrote the original, the reply goes on to its recipient
        val to = if (original.sender == identity) original.recipient else original.sender
        hub.send(identity, to, "", body, inReplyTo = original)
    }

    override suspend fun markRead(messages: List<Message>) {
        val mine = messages.filter { it.recipient == identity && !it.read }.map { it.id }
        if (mine.isNotEmpty()) hub.markRead(identity, mine)
    }

    override suspend fun act(need: NeedView, action: String): String = when (action) {
        "read" -> { need.message?.let { markRead(listOf(it)) }; "Marked as read" }
        // the PC that runs the project ticks it off in its journal and replies in Letters (remote.py todo_done)
        "done" -> { hub.command(identity, need.project, "todo_done", mapOf("id" to (need.id ?: error("no id")))); "Sent: it's ticked off when your PC next syncs" }
        else -> ""
    }

    override suspend fun command(project: String, action: String, fields: Map<String, Any?>): String {
        hub.command(identity, project, action, fields)
        return "Sent. Roundtable will reply in Letters."
    }

    @Volatile private var lastSeats: List<SeatView> = emptyList()

    override suspend fun autopilot(): AutopilotState? = runCatching { Autopilot.parse(hub.autopilot()) }.getOrNull()

    override suspend fun live(seat: SeatView): LiveView = coroutineScope {
        val session = async { Live.parseSession(hub.session(seat.id)) }
        val shots = Live.parseShots(hub.shots(seat.id))
        val images = shots?.pictures.orEmpty().map { (kind, name) -> async { hub.shot(seat.id, name)?.let { kind to it } } }
        LiveView(shots, images.awaitAll().filterNotNull().toMap(), session.await())
    }

    override suspend fun syncInfo(): SyncInfo = coroutineScope {
        val machines = async { runCatching { hub.jsonFiles("machines") }.getOrDefault(emptyMap()) }
        val claims = runCatching { hub.jsonFiles("claims") }.getOrDefault(emptyMap())
        SyncInfo(
            machines.await().mapNotNull { (f, t) -> Sync.parseFile(t)?.let { Sync.machine(it, f) } },
            claims.mapNotNull { (f, t) -> Sync.parseFile(t)?.let { Sync.claim(it, f) } },
        )
    }

    /** sessions/<key>/<newest run>.jsonl, else the older one-task summary (plans/shots/<project>/session.json). */
    override suspend fun session(seat: SeatView): SessionLog.Result? {
        for (key in listOf(seat.hubName, seat.id).filter { it.isNotBlank() }.distinct()) {
            val run = runCatching { hub.sessionRuns(key) }.getOrDefault(emptyList()).firstOrNull() ?: continue
            SessionLog.parse(hub.sessionLog(key, run).orEmpty(), seat.id)?.let { return it }
        }
        return Live.parseSession(hub.session(seat.id))?.let { SessionLog.Result(it) }
    }

    override suspend fun sharedSettings(): SharedSettings? = SharedSettings.parseYaml(hub.sharedSettings())

    override suspend fun notes(): List<Note> = hub.notes().map { (name, text) -> Note(name, Note.title(text, name)) }.sortedBy { it.title.lowercase() }

    override suspend fun note(name: String): String? = if (Note.safe(name)) hub.note(name) else null

    override suspend fun saveShared(changes: kotlinx.serialization.json.JsonObject, to: String?): String {
        val target = to?.ifBlank { null } ?: throw IllegalStateException("No computer has joined the hub yet, so there's nowhere to send this. Open Roundtable Hold on your PC first.")
        hub.command(identity, target, "shared_settings", mapOf("changes" to changes))
        return "Sent: every computer takes it at its next sync."
    }

    override suspend fun setAutopilot(on: Boolean, until: String, cap: Double?): String {
        val to = Autopilot.commandTarget(autopilot(), lastSeats)
            ?: throw IllegalStateException("No project of Roundtable's is in the hub yet, so there's nowhere to send this. Start one on your PC first.")
        hub.command(identity, to, "autopilot", Autopilot.commandFields(on, until, cap))
        return "Sent. Your PC turns autopilot ${if (on) "on" else "off"} within a minute or so."
    }
}

/** A machine that runs Roundtable: the paired PC, or Roundtable on this phone ([here] says which). */
class PcBackend(val api: Api, override val identity: String, val here: Source = Source.PC) : Backend {
    override val mode = Mode.PC

    override suspend fun notes(): List<Note> = api.notes()

    override suspend fun note(name: String): String? = if (Note.safe(name)) api.note(name) else null
    @Volatile private var seats: List<Seat> = emptyList()
    @Volatile private var agent: String? = null
    override val seatId: String? get() = agent

    override suspend fun syncInfo(): SyncInfo = Sync.parseMachines(api.machines())

    override suspend fun session(seat: SeatView): SessionLog.Result? {
        val path = seat.path
        if (path != null && seat.holder == here.key) {
            SessionLog.parseAny(api.session(path), seat.id)?.let { return it }
        }
        return SessionLog.parseAny(api.hubSession(seat.hubName.ifBlank { seat.id }), seat.id)
    }

    override suspend fun sharedSettings(): SharedSettings? {
        val choices = runCatching { SharedSettings.roleChoices(api.roles()) }.getOrDefault(emptyMap())
        val text = try {
            api.sharedSettings()
        } catch (e: com.meztking.roundtable.net.ApiException) {
            if (e.status != 404) throw e
            null
        }
        val o = text?.let { runCatching { com.meztking.roundtable.net.ApiJson.parseToJsonElement(it) as kotlinx.serialization.json.JsonObject }.getOrNull() }
        if (o != null) return SharedSettings.from((o["settings"] as? kotlinx.serialization.json.JsonObject) ?: o, choices)
        // an older Roundtable Hold: show its own roles and limits (read only until it is updated)
        val roles = runCatching { com.meztking.roundtable.net.ApiJson.parseToJsonElement(api.roles()) as kotlinx.serialization.json.JsonObject }.getOrNull() ?: return null
        val wrapped = kotlinx.serialization.json.JsonObject(mapOf(
            "limits" to (roles["limits"] ?: kotlinx.serialization.json.JsonObject(emptyMap())),
            "roles" to kotlinx.serialization.json.JsonObject(choices.mapValues { (_, m) -> kotlinx.serialization.json.JsonArray(m.map { kotlinx.serialization.json.JsonPrimitive(it) }) }),
        ))
        return SharedSettings.from(wrapped, choices)
    }

    override suspend fun saveShared(changes: kotlinx.serialization.json.JsonObject, to: String?): String {
        try {
            api.saveSharedSettings(changes)
        } catch (e: com.meztking.roundtable.net.ApiException) {
            if (e.status == 404) throw IllegalStateException("${here.title} needs a newer Roundtable to change shared settings. Update it, then try again.")
            throw e
        }
        return "Saved on ${here.words}. Every computer takes it at its next sync."
    }

    override suspend fun projectSettings(seat: SeatView): ProjectSettingsView {
        val path = seat.path ?: return super.projectSettings(seat)
        return ProjectSettings.parse(api.projectSettings(path))
    }

    override suspend fun saveProjectSettings(seat: SeatView, changes: kotlinx.serialization.json.JsonObject): ProjectSettingsView {
        val path = seat.path ?: return super.saveProjectSettings(seat, changes)
        return ProjectSettings.parse(api.saveProjectSettings(path, changes))
    }

    override suspend fun projects(): List<String> {
        if (seats.isEmpty()) hall()
        return seats.filter { it.kind != "run" }.map { it.id }
    }

    override suspend fun hall(): HallState {
        val r = api.roundtable()
        seats = r.seats
        agent = r.agent ?: agent
        val views = r.seats.map { s ->
            SeatView(
                id = s.id, status = s.status,
                statusText = when {
                    s.detail.isNotBlank() -> "${s.status} · ${s.detail}"
                    s.last_activity.isNotBlank() -> "${s.status} · ${ago(s.last_activity)}"
                    else -> s.status
                },
                description = s.description.ifBlank { s.goal }, repo = s.repo, lastActivity = s.last_activity,
                leftOff = s.brief?.last_session?.text.orEmpty(), nextSteps = s.brief?.last_session?.next.orEmpty(),
                openTodos = s.open_todos, high = s.high, unread = s.unread, progress = s.progress, path = s.path,
                hasPlan = s.path != null, autopilot = s.autopilot,
                holder = if (s.where == "here" || (s.where.isBlank() && s.path != null)) here.key else "",
                hubName = s.hub_name, hubAgent = s.hub_agent, machine = s.machine, machineName = s.machine_name,
            )
        }
        val needs = r.needs_you.map { n ->
            val title = when (n.kind) {
                "run" -> when {
                    "approve" in n.actions -> "Plan waits for your seal"
                    "retry" in n.actions -> "A task failed"
                    "budget" in n.actions -> "Budget reached"
                    else -> "${n.project} waits"
                }
                "todo" -> "To do: ${n.text}"
                "messages" -> "Letters for you"
                else -> n.text
            }
            if (n.ask != null) askNeed(n.project, listOf(n.ask.copy(path = n.ask.path ?: n.path)), n.asks)
            else NeedView("pc:${n.kind}:${n.project}:${n.id ?: n.task ?: n.text}", if (n.kind == "messages") "message" else n.kind,
                n.project, title, if (n.kind == "todo") "${n.project} · high priority · from the journal" else n.text,
                n.actions, id = n.id, task = n.task, path = n.path, at = n.at)
        }
        return HallState(views, needs, Instant.now().toString(), autopilot() ?: r.autopilot)
    }

    override suspend fun status(project: String): StatusDoc {
        val seat = seats.firstOrNull { it.id == project } ?: run { hall(); seats.firstOrNull { it.id == project } }
        val b = seat?.brief ?: return StatusDoc(title = project, description = seat?.description.orEmpty())
        val md = buildString {
            appendLine("# ${b.agent}"); appendLine()
            if (b.description.isNotBlank()) { appendLine(b.description); appendLine() }
            if (b.last_activity.isNotBlank()) { appendLine("_Updated ${b.last_activity}_"); appendLine() }
            b.last_session?.let { s ->
                appendLine("## Where we left off"); appendLine()
                appendLine("**${s.created_at}**: ${s.text}"); appendLine()
                s.next.forEach { appendLine("- [ ] $it") }; appendLine()
            }
            appendLine("## To do"); appendLine()
            if (b.open_todos.isEmpty()) appendLine("_Nothing open._")
            b.open_todos.forEach { appendLine("- [ ] ${if (it.priority == "high") "**(high)** " else ""}${it.text} `${it.id}`") }
            appendLine()
            if (b.open_plans.isNotEmpty()) { appendLine("## Future plans"); appendLine(); b.open_plans.forEach { appendLine("- ${it.text} `${it.id}`") }; appendLine() }
            if (b.recent_decisions.isNotEmpty()) { appendLine("## Decisions"); appendLine(); b.recent_decisions.forEach { appendLine("- ${it.created_at.take(10)}: ${it.text}") }; appendLine() }
            if (b.recent_done.isNotEmpty()) { appendLine("## Done (latest first)"); appendLine(); b.recent_done.forEach { appendLine("- ${it.created_at.take(10)}: ${it.text}") } }
        }
        return StatusDoc.parse(md)
    }

    override suspend fun plan(seat: SeatView): PlanView {
        val path = seat.path ?: return PlanView()
        val p = api.project(path)
        val words = runCatching { api.planWords(path) }.getOrNull()
        val kind = runCatching { api.planKind(path) }.getOrNull()
        return PlanView(tasks = p.tasks, runStatus = p.meta.status, canApprove = p.meta.status == "awaiting_approval", words = words,
            kind = kind)
    }

    override suspend fun inbox(project: String) = api.inbox(project, all = true)

    override suspend fun asks(seat: SeatView): List<Ask> = seat.path?.let { api.asks(it) }.orEmpty()

    override suspend fun answer(ask: Ask, reply: AskReply): String = api.answer(ask, reply)

    override suspend fun letters(): List<Message> = coroutineScope {
        projects().map { p -> async { runCatching { api.inbox(p, all = true) }.getOrDefault(emptyList()) } }
            .awaitAll().flatten().sortedByDescending { it.created_at.ifBlank { it.id } }
    }

    override suspend fun send(to: String, subject: String, body: String) = api.send(identity, to, subject, body)

    override suspend fun reply(original: Message, body: String) {
        if (original.recipient == identity) api.reply(identity, original.id, body)
        else {
            val to = if (original.sender == identity) original.recipient else original.sender
            val subj = if (original.subject.lowercase().startsWith("re:")) original.subject else "Re: ${original.subject}"
            api.send(identity, to, subj, body)
        }
    }

    override suspend fun markRead(messages: List<Message>) {
        val mine = messages.filter { it.recipient == identity && !it.read }.map { it.id }
        if (mine.isNotEmpty()) api.markRead(identity, mine)
    }

    override suspend fun act(need: NeedView, action: String): String {
        when (action) {
            "approve" -> api.projectAction(need.path ?: error("no run"), "approve").also { return "Approved: the run starts" }
            "retry", "skip" -> api.projectAction(need.path ?: error("no run"), action, task = need.task)
                .also { return if (action == "retry") "Trying it again" else "Skipped" }
            "budget" -> api.projectAction(need.path ?: error("no run"), "raise_budget").also { return "Budget raised: the run goes on" }
            "resume" -> api.projectAction(need.path ?: error("no run"), "run").also { return "Resumed" }
            "done" -> api.closeTodo(need.project, need.id ?: error("no id")).also { return "Marked done" }
            "read" -> api.markRead(identity, api.inbox(identity).filter { !it.read }.map { it.id }).also { return "Marked as read" }
        }
        return ""
    }

    override suspend fun autopilot(): AutopilotState? = runCatching { api.autopilot() }.getOrNull()

    override suspend fun live(seat: SeatView): LiveView = coroutineScope {
        val path = seat.path ?: return@coroutineScope LiveView()
        val session = async { Live.parseSession(api.session(path)) }
        val (shots, images) = Live.parsePc(api.live(path))
        LiveView(shots, images, session.await())
    }

    override suspend fun setAutopilot(on: Boolean, until: String, cap: Double?): String {
        val st = api.setAutopilot(on, until, cap)
        return if (st.on) "Autopilot is on, ${st.label}" else "Autopilot is off"
    }

    override suspend fun command(project: String, action: String, fields: Map<String, Any?>): String {
        val seat = seats.firstOrNull { it.id == project }
        val path = seat?.path
        if (action == "approve" && path != null) {
            api.projectAction(path, "approve")
            return "Approved: the run starts"
        }
        // anything else goes into the hub, passed on by this machine (POST /api/hub/command)
        val machine = fields["machine"]?.toString().orEmpty()
        val folder = fields["project_folder"]?.toString() ?: project
        val agentTo = seat?.hub_agent?.ifBlank { null } ?: fields["hub_agent"]?.toString() ?: project
        return api.hubCommand(agentTo, folder, action, fields - setOf("machine", "project_folder", "hub_agent"), machine)
    }
}

/** A letter that needs the owner, in plain words: what it is, and its first lines. */
fun letterNeed(m: Message): NeedView {
    val p = Letters.plain(m)
    val text = if (p.reply || p.command) p.text else Markdown.plain(m.body).lines().map { it.trim() }.filter { it.isNotEmpty() }.take(3).joinToString("\n")
    val title = if (p.reply || p.command) p.title else "${m.sender}: ${m.subject.ifBlank { "(no subject)" }}"
    return NeedView("msg:${m.id}", "message", m.sender, title, text, listOf("read", "reply"), id = m.id, message = m, at = m.created_at)
}

/** A Needs-you item that is a card to tap: the project's first question, and how many wait. */
fun askNeed(project: String, asks: List<Ask>, total: Int = asks.size): NeedView {
    val a = asks.first()
    return NeedView("ask:$project:${a.id}:${a.stamp}", "ask", project, a.question, a.detail, path = a.path, ask = a,
        asks = maxOf(total, asks.size))
}

/** Running first, then waiting, idle, done; most recently active first within each group. */
fun sortSeats(seats: List<SeatView>): List<SeatView> {
    val order = mapOf("running" to 0, "waiting" to 1, "idle" to 2, "done" to 3)
    return seats.sortedWith(compareBy<SeatView> { order[it.status] ?: 9 }.thenByDescending { it.lastActivity })
}

fun initialsOf(id: String): String {
    val parts = id.split('-', '_', ' ', '.').filter { it.isNotEmpty() }
    return when {
        parts.size >= 2 -> "${parts[0][0].uppercaseChar()}${parts[1][0].lowercaseChar()}"
        id.length >= 2 -> "${id[0].uppercaseChar()}${id[1].lowercaseChar()}"
        else -> id.uppercase()
    }
}

fun parseInstant(iso: String): Instant? {
    if (iso.isBlank()) return null
    return runCatching { Instant.parse(iso) }.getOrNull()
        ?: runCatching { Instant.parse(iso + if (iso.length == 16) ":00Z" else "Z") }.getOrNull()
        ?: runCatching { java.time.OffsetDateTime.parse(iso).toInstant() }.getOrNull()
        ?: runCatching { java.time.LocalDateTime.parse(iso).toInstant(java.time.ZoneOffset.UTC) }.getOrNull()
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
fun ago(iso: String, now: Instant = Instant.now()): String {
    val t = parseInstant(iso) ?: return iso.take(10)
    val s = Duration.between(t, now).seconds.coerceAtLeast(0)
    return when {
        s < 60 -> "just now"
        s < 3600 -> "${s / 60} min ago"
        s < 86400 -> "${s / 3600} h ago"
        s < 86400 * 2 -> "yesterday"
        else -> "${s / 86400} days ago"
    }
}
