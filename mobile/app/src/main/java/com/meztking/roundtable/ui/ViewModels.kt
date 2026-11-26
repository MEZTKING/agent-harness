package com.meztking.roundtable.ui

import android.app.Application
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskReply
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.HallState
import com.meztking.roundtable.data.NeedView
import com.meztking.roundtable.data.PlanView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.ApiJson
import com.meztking.roundtable.net.GitHubHub
import com.meztking.roundtable.net.Message
import com.meztking.roundtable.net.PairingOffer
import com.meztking.roundtable.work.Watch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Called once a send finishes: true when it went, false when it failed (the reason is shown as a notice). */
typealias Done = (Boolean) -> Unit

/** Something loaded from the network: what we have, whether a load is running, and what went wrong. */
data class Load<T>(val data: T? = null, val loading: Boolean = false, val error: String? = null)

fun friendly(e: Throwable): String = when (e) {
    is java.net.UnknownHostException -> "No connection. Is the phone online?"
    is java.net.SocketTimeoutException -> "It took too long to answer. Try again."
    is kotlinx.serialization.SerializationException -> "Got an answer the app doesn't understand. Is everything up to date?"
    else -> e.message?.replaceFirstChar { it.uppercase() } ?: "Something went wrong. Try again."
}

private suspend fun <T> MutableStateFlow<Load<T>>.fetch(block: suspend () -> T) {
    update { it.copy(loading = true, error = null) }
    try {
        val v = block()
        value = Load(v)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {  // errors too (out of memory, a missing method): show them, don't close the app
        update { it.copy(loading = false, error = if (e is Exception) friendly(e) else "Something went wrong loading this (${e::class.simpleName}). Try again, or send the details from Settings.") }
    }
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    val backend: Backend? get() = rt.backend()

    /** What the app saved when it last crashed; while set, nothing loads by itself (safe mode). */
    private val _crash = MutableStateFlow(com.meztking.roundtable.data.Crash.last(app))
    val crash: StateFlow<String?> = _crash.asStateFlow()
    private val _hall = MutableStateFlow(Load(if (_crash.value != null) null else cachedHall()))
    val hall: StateFlow<Load<HallState>> = _hall.asStateFlow()
    private val _letters = MutableStateFlow(Load<List<Message>>())
    val letters: StateFlow<Load<List<Message>>> = _letters.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    /** A short line to show in a snackbar (sent, done, or what went wrong). */
    val notice: StateFlow<String?> = _notice.asStateFlow()
    private val _busy = MutableStateFlow<Set<String>>(emptySet())
    val busy: StateFlow<Set<String>> = _busy.asStateFlow()

    private fun cachedHall(): HallState? = runCatching {
        val s = rt.store.cachedHall
        if (s.isBlank()) null else ApiJson.decodeFromString(HallState.serializer(), s)
    }.getOrNull()

    /** Leave safe mode: forget the crash and load as usual. */
    fun crashSeen() {
        com.meztking.roundtable.data.Crash.clear(rt)
        _crash.value = null
        refresh()
    }

    /** Send the crash details to the owner's own inbox on the hub (the PC sees them; so does Roundtable). */
    fun sendCrash() {
        val b = backend ?: return say("Connect to your hub first, then send it.")
        val text = _crash.value ?: return
        viewModelScope.launch {
            try {
                b.send("harness", "Roundtable Mobile crashed", text)
                say("Sent to your hub. Thank you!")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                say("Couldn't send it: ${e.message ?: e::class.simpleName}")
            }
        }
    }

    fun noticeShown() { _notice.value = null }
    fun say(text: String) { _notice.value = text }

    fun refresh() {
        val b = backend ?: return
        viewModelScope.launch {
            _hall.fetch { b.hall() }
            _hall.value.data?.let { h ->
                runCatching { rt.store.cachedHall = ApiJson.encodeToString(HallState.serializer(), h) }
                // what the owner has just seen on screen needn't be announced again
                rt.store.notified = rt.store.notified + h.needs.map { it.key }
            }
        }
    }

    fun loadLetters() {
        val b = backend ?: return
        viewModelScope.launch { _letters.fetch { b.letters() } }
    }

    fun act(need: NeedView, action: String) {
        val b = backend ?: return
        viewModelScope.launch {
            _busy.update { it + need.key }
            try {
                val said = b.act(need, action)
                if (said.isNotBlank()) _notice.value = said
                _hall.value.data?.let { h -> _hall.value = _hall.value.copy(data = h.copy(needs = h.needs.filter { it.key != need.key })) }
                refresh()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            } finally {
                _busy.update { it - need.key }
            }
        }
    }

    /** A card tapped on Needs you: the answer goes the way this phone is connected (hub command or the PC). */
    fun answer(need: NeedView, reply: AskReply) {
        val b = backend ?: return
        val ask = need.ask ?: return
        viewModelScope.launch {
            _busy.update { it + need.key }
            try {
                _notice.value = b.answer(ask.copy(project = need.project, path = ask.path ?: need.path), reply)
                _hall.value.data?.let { h -> _hall.value = _hall.value.copy(data = h.copy(needs = h.needs.filter { it.key != need.key })) }
                refresh()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            } finally {
                _busy.update { it - need.key }
            }
        }
    }

    /** Autopilot on (until, spend limit) or off, from the Table's switch. */
    fun autopilot(on: Boolean, until: String, cap: Double?) {
        val b = backend ?: return
        viewModelScope.launch {
            try {
                _notice.value = b.setAutopilot(on, until, cap)
                refresh()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            }
        }
    }

    fun send(to: String, subject: String, body: String, onDone: Done) {
        val b = backend ?: return
        viewModelScope.launch {
            try {
                b.send(to, subject, body)
                _notice.value = "Sent to $to"
                onDone(true)
                loadLetters()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
                onDone(false)
            }
        }
    }

    fun reply(original: Message, body: String, onDone: Done) {
        val b = backend ?: return
        viewModelScope.launch {
            try {
                b.reply(original, body)
                runCatching { b.markRead(listOf(original)) }
                _notice.value = "Reply sent"
                onDone(true)
                loadLetters()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
                onDone(false)
            }
        }
    }

    /** Opening one of the owner's own letters marks it read (quietly; it is only a convenience). */
    fun opened(m: Message) {
        val b = backend ?: return
        if (m.read || m.recipient != b.identity) return
        viewModelScope.launch {
            runCatching { b.markRead(listOf(m)) }.onSuccess {
                _letters.update { l -> l.copy(data = l.data?.map { if (it.id == m.id) it.copy(read = true) else it }) }
            }
        }
    }

    fun projectIds(): List<String> = _hall.value.data?.seats?.map { it.id }.orEmpty()

    /** Settings changed (way in, token, identity): start again. */
    fun reset() {
        _hall.value = Load()
        _letters.value = Load()
        rt.store.cachedHall = ""
        refresh()
    }
}

class ProjectViewModel(app: Application, saved: SavedStateHandle) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    val id: String = saved.get<String>("id").orEmpty()

    private val _seat = MutableStateFlow<SeatView?>(null)
    val seat: StateFlow<SeatView?> = _seat.asStateFlow()
    private val _status = MutableStateFlow(Load<StatusDoc>())
    val status: StateFlow<Load<StatusDoc>> = _status.asStateFlow()
    private val _plan = MutableStateFlow(Load<PlanView>())
    val plan: StateFlow<Load<PlanView>> = _plan.asStateFlow()
    private val _inbox = MutableStateFlow(Load<List<Message>>())
    val inbox: StateFlow<Load<List<Message>>> = _inbox.asStateFlow()
    private val _sent = MutableStateFlow<Map<String, String>>(emptyMap())
    /** Plan controls that were answered: control key -> what to show instead. */
    val sent: StateFlow<Map<String, String>> = _sent.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()
    private val _asks = MutableStateFlow(Load<List<Ask>>())
    /** The questions waiting on this project, as cards to tap. */
    val asks: StateFlow<Load<List<Ask>>> = _asks.asStateFlow()

    fun noticeShown() { _notice.value = null }

    fun start(seat: SeatView?) {
        if (seat != null) _seat.value = seat
        if (_status.value.data == null && !_status.value.loading) refresh()
    }

    fun refresh() {
        val b = rt.backend() ?: return
        viewModelScope.launch { _status.fetch { b.status(id) } }
        viewModelScope.launch { _inbox.fetch { b.inbox(id) } }
        loadPlan()
    }

    fun loadPlan() {
        val b = rt.backend() ?: return
        viewModelScope.launch { _plan.fetch { b.plan(_seat.value ?: SeatView(id)) } }
        viewModelScope.launch { _asks.fetch { b.asks(_seat.value ?: SeatView(id)) } }
    }

    /** A card answered on the plan tab; it shows Roundtable's reply in place of its buttons. */
    fun answer(ask: Ask, reply: AskReply) {
        val b = rt.backend() ?: return
        val key = "ask:${ask.id}"
        _sent.update { it + (key to "Sending…") }
        viewModelScope.launch {
            try {
                val said = b.answer(ask.copy(project = ask.project.ifBlank { id }, path = ask.path ?: _seat.value?.path), reply)
                _sent.update { it + (key to said) }
                _notice.value = said
                if (b.mode == com.meztking.roundtable.data.Mode.PC) loadPlan()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _sent.update { it - key }
                _notice.value = friendly(e)
            }
        }
    }

    /** A plan command (Hub mode: through the hub). [key] marks which control was used. */
    fun command(key: String, action: String, fields: Map<String, Any?> = emptyMap()) {
        val b = rt.backend() ?: return
        _sent.update { it + (key to "Sending…") }
        viewModelScope.launch {
            try {
                val said = b.command(id, action, fields)
                _sent.update { it + (key to said) }
                _notice.value = said
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _sent.update { it - key }
                _notice.value = friendly(e)
            }
        }
    }

    fun act(action: String) {
        val b = rt.backend() ?: return
        val seat = _seat.value ?: return
        viewModelScope.launch {
            try {
                _notice.value = b.act(NeedView("p", "run", id, "", actions = listOf(action), path = seat.path), action)
                loadPlan()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            }
        }
    }

    fun reply(original: Message, body: String, onDone: Done) {
        val b = rt.backend() ?: return
        viewModelScope.launch {
            try {
                b.reply(original, body)
                _notice.value = "Reply sent"
                onDone(true)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
                onDone(false)
            }
        }
    }

    fun send(subject: String, body: String, onDone: Done) {
        val b = rt.backend() ?: return
        viewModelScope.launch {
            try {
                b.send(id, subject, body)
                _notice.value = "Sent to $id"
                onDone(true)
                _inbox.fetch { b.inbox(id) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
                onDone(false)
            }
        }
    }

    fun opened(m: Message) {
        val b = rt.backend() ?: return
        if (m.read || m.recipient != b.identity) return
        viewModelScope.launch { runCatching { b.markRead(listOf(m)) } }
    }
}

class SetupViewModel(app: Application) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    data class State(val busy: Boolean = false, val error: String? = null, val done: Boolean = false, val found: List<String> = emptyList())

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun clearError() = _state.update { it.copy(error = null) }

    fun checkHub(repo: String, token: String) {
        val r = repo.trim().removePrefix("https://github.com/").removeSuffix("/").removeSuffix(".git")
        if (!Regex("^[\\w.-]+/[\\w.-]+$").matches(r)) { _state.value = State(error = "Write the repository as owner/name, for example MEZTKING/agent-hub-data."); return }
        if (token.isBlank()) { _state.value = State(error = "Paste the GitHub token first."); return }
        _state.value = State(busy = true)
        viewModelScope.launch {
            try {
                val projects = GitHubHub(token.trim(), r).projects()
                rt.store.hubRepo = r
                rt.store.githubToken = token.trim()
                rt.store.mode = "hub"
                rt.store.cachedHall = ""
                Watch.schedule(rt)
                _state.value = State(done = true, found = projects)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = State(error = friendly(e))
            }
        }
    }

    fun pair(offer: PairingOffer, code: String) {
        val c = code.trim().uppercase().ifBlank { offer.code }
        if (c.length < 6) { _state.value = State(error = "Type the 8-letter code shown on your PC."); return }
        _state.value = State(busy = true)
        viewModelScope.launch {
            try {
                val link = Api.pair(offer, "${Build.MANUFACTURER} ${Build.MODEL}".trim(), c)
                rt.store.link = link
                rt.store.mode = "pc"
                rt.store.cachedHall = ""
                Watch.schedule(rt)
                _state.value = State(done = true)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = State(error = friendly(e))
            }
        }
    }

    fun reset() { _state.value = State() }
}
