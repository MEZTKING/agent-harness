package com.meztking.roundtable.ui

import com.meztking.roundtable.Brand

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.data.ConnHealth
import com.meztking.roundtable.data.ProjectSettings
import com.meztking.roundtable.data.ProjectSettingsView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.SharedSettings
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.data.Sync
import com.meztking.roundtable.net.HubLink
import com.meztking.roundtable.runtime.RuntimeInstaller
import com.meztking.roundtable.runtime.RuntimeState
import com.meztking.roundtable.work.Watch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Instant

/** One connection on Your computers: its state in words, and whether it is set up. */
data class ConnectionRow(val source: Source, val set: Boolean, val line: String, val ok: Boolean?, val detail: String = "")

/** What the rows are made from (all plain values, so the wording is tested without a phone). */
data class ConnInputs(
    val phoneSet: Boolean = false,
    val phoneState: String? = null,
    val phoneRunning: Boolean = false,
    val phoneHub: HubLink? = null,
    val pcSet: Boolean = false,
    val pcName: String = "",
    val pc: ConnHealth = ConnHealth(),
    val pcHost: String? = null,
    val pcBeat: String = "",
    val hubSet: Boolean = false,
    val hubRepo: String = "",
    val hub: ConnHealth = ConnHealth(),
)

fun connectionRows(i: ConnInputs, now: Instant = Instant.now()): List<ConnectionRow> = listOf(
    if (!i.phoneSet) ConnectionRow(Source.PHONE, false, "This phone – not set up", null, "${Brand.NAME} can build on the phone itself, even with no PC.")
    else ConnectionRow(Source.PHONE, true, Sync.connectionLine(Source.PHONE, i.phoneRunning, "", phoneState = i.phoneState, now = now), i.phoneRunning,
        when {
            i.phoneHub == null -> ""
            i.phoneHub.joined -> "Syncs with your hub, so your PC sees what it does."
            !i.phoneHub.error.isNullOrBlank() -> "Couldn't join the hub: ${i.phoneHub.error}"
            else -> "Works on its own: it doesn't sync with your PC yet."
        }),
    if (!i.pcSet) ConnectionRow(Source.PC, false, "Your PC – not paired", null, "Pair once with the QR code ${Brand.NAME} shows on your PC.")
    else {
        val last = Sync.newest(i.pc.lastOk, i.pcBeat)
        ConnectionRow(Source.PC, true, Sync.connectionLine(Source.PC, i.pc.ok, last, i.pcHost, now = now), i.pc.ok,
            listOf(i.pcName, if (i.pc.ok == false) i.pc.error.orEmpty() else "").filter { it.isNotBlank() }.joinToString(" · "))
    },
    if (!i.hubSet) ConnectionRow(Source.HUB, false, "Hub – not set up", null, "The hub on GitHub works even when your PC is off.")
    else ConnectionRow(Source.HUB, true, Sync.connectionLine(Source.HUB, i.hub.ok, i.hub.lastOk, now = now), i.hub.ok,
        listOf(i.hubRepo, if (i.hub.ok == false) i.hub.error.orEmpty() else "").filter { it.isNotBlank() }.joinToString(" · ")),
)

fun phoneWords(state: RuntimeState): String = when (state) {
    is RuntimeState.Running -> "running"
    is RuntimeState.Starting -> "starting"
    is RuntimeState.Stopped -> "stopped"
    is RuntimeState.Failed -> "stopped with a problem"
    RuntimeState.NotInstalled -> "not set up"
    else -> "busy"
}

/** Settings, Your computers. */
class ConnectionsViewModel(app: Application) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    private val _rows = MutableStateFlow(emptyList<ConnectionRow>())
    val rows: StateFlow<List<ConnectionRow>> = _rows.asStateFlow()
    private val _busy = MutableStateFlow<String?>(null)
    val busy: StateFlow<String?> = _busy.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()
    private var phoneHub: HubLink? = null

    val hubSet: Boolean get() = rt.store.githubToken != null
    val phoneJoined: Boolean get() = phoneHub?.joined == true

    fun noticeShown() { _notice.value = null }

    private fun inputs(): ConnInputs {
        val s = rt.store
        val b = rt.backend()
        val state = rt.runtime.state.value
        return ConnInputs(
            phoneSet = s.thisPhone, phoneState = phoneWords(state), phoneRunning = state is RuntimeState.Running, phoneHub = phoneHub,
            pcSet = s.link != null, pcName = s.link?.name.orEmpty(), pc = b?.health(Source.PC) ?: ConnHealth(lastOk = s.lastOk(Source.PC)),
            pcHost = (b?.parts?.get(Source.PC) as? com.meztking.roundtable.data.PcBackend)?.api?.activeHost, pcBeat = b?.beat(Source.PC)?.last_seen.orEmpty(),
            hubSet = s.githubToken != null, hubRepo = s.hubRepo, hub = b?.health(Source.HUB) ?: ConnHealth(lastOk = s.lastOk(Source.HUB)),
        )
    }

    fun show() { _rows.value = connectionRows(inputs()) }

    /** Ask every connection again, then show how each stands. */
    fun refresh() {
        show()
        viewModelScope.launch {
            _busy.value = "refresh"
            runCatching { rt.backend()?.hall() }
            if (rt.store.thisPhone && rt.runtime.state.value is RuntimeState.Running) phoneHub = runCatching { rt.thisPhoneApi().hub() }.getOrNull()
            _busy.value = null
            show()
        }
    }

    /** This phone: join the hub the app already uses (its GitHub link and token), so it syncs with the PC. */
    fun joinHub() {
        val token = rt.store.githubToken ?: return say("Add the hub first (below), then join.")
        viewModelScope.launch {
            _busy.value = "join"
            try {
                if (rt.runtime.state.value !is RuntimeState.Running) rt.runtime.startIfNeeded()
                phoneHub = rt.thisPhoneApi().joinHub("https://github.com/${rt.store.hubRepo}.git", token)
                say(if (phoneHub?.joined == true) "This phone has joined your hub. Your PC sees its projects at its next sync." else "Sent, but the phone hasn't joined yet: ${phoneHub?.error ?: "try again"}")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                say(friendly(e))
            } finally {
                _busy.value = null
                show()
            }
        }
    }

    /** The paired PC didn't answer: look for it on this Wi-Fi (it may have a new address). Only an answer with the
     *  certificate this phone pinned is used, and only for its address (net/Discovery.kt). Beta. */
    fun findPc(onMoved: () -> Unit) {
        val link = rt.store.link ?: return say("Pair with your PC first.")
        viewModelScope.launch {
            _busy.value = "find"
            try {
                val moved = com.meztking.roundtable.net.Discovery.relocate(rt, link)
                if (moved == null) say("Your PC didn't answer on this Wi-Fi. Is it on, with phone access on, and on the same Wi-Fi?")
                else {
                    rt.store.link = moved
                    say("Found your PC at ${moved.hosts.first()}.")
                    onMoved()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                say(friendly(e))
            } finally {
                _busy.value = null
                refresh()
            }
        }
    }

    fun unpair() { rt.store.link = null; forgot() }
    fun removeHub() { rt.store.githubToken = null; forgot() }

    private fun forgot() {
        rt.store.mode = ""
        rt.store.cachedHall = ""
        if (!rt.store.configured) Watch.cancel(rt)
        show()
    }

    private fun say(t: String) { _notice.value = t }
    fun notify(t: String) = say(t)
}

/** Settings, Shared settings: the limits, autopilot, the default set of models and who does which job, for every machine. */
class SharedSettingsViewModel(app: Application) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    private val _settings = MutableStateFlow(Load<SharedSettings>())
    val settings: StateFlow<Load<SharedSettings>> = _settings.asStateFlow()
    private val _from = MutableStateFlow("")
    /** Where they were read, in words. */
    val from: StateFlow<String> = _from.asStateFlow()
    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()

    fun noticeShown() { _notice.value = null }

    fun load() {
        val b = rt.backend() ?: return
        viewModelScope.launch {
            _settings.update { it.copy(loading = true, error = null) }
            try {
                if (b.connected.isEmpty()) runCatching { b.hall() }
                val (src, s) = b.shared()
                _from.value = when (src) { Source.HUB -> "Read from the hub"; else -> "Read from ${src.words}" }
                _settings.value = Load(s)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _settings.update { it.copy(loading = false, error = friendly(e)) }
            }
        }
    }

    fun save(after: SharedSettings) {
        val b = rt.backend() ?: return
        val before = _settings.value.data ?: return
        val changes = SharedSettings.changes(before, after)
        if (changes.isEmpty()) { _notice.value = "Nothing changed"; return }
        viewModelScope.launch {
            _saving.value = true
            try {
                _notice.value = b.saveShared(changes)
                _settings.value = Load(after)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            } finally {
                _saving.value = false
            }
        }
    }
}

/** A project's own Settings (GET/POST /api/project/settings on the machine that builds it). */
class ProjectSettingsViewModel(app: Application, saved: SavedStateHandle) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    val id: String = saved.get<String>("id").orEmpty()
    private val _view = MutableStateFlow(Load<ProjectSettingsView>())
    val view: StateFlow<Load<ProjectSettingsView>> = _view.asStateFlow()
    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()
    private var seat: SeatView = SeatView(id)

    fun noticeShown() { _notice.value = null }

    fun start(s: SeatView?) {
        if (s != null) seat = s
        if (_view.value.data == null && !_view.value.loading) load()
    }

    fun load() {
        val b = rt.backend() ?: return
        viewModelScope.launch {
            _view.update { it.copy(loading = true, error = null) }
            try {
                _view.value = Load(b.projectSettings(seat))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _view.update { it.copy(loading = false, error = friendly(e)) }
            }
        }
    }

    fun save(drafts: Map<String, String>) {
        val b = rt.backend() ?: return
        val v = _view.value.data ?: return
        val changes = ProjectSettings.changes(v, drafts).getOrElse { _notice.value = it.message; return }
        if (changes.isEmpty()) { _notice.value = "Nothing changed"; return }
        viewModelScope.launch {
            _saving.value = true
            try {
                _view.value = Load(b.saveProjectSettings(seat, changes))
                _notice.value = "Saved. The next task uses it."
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _notice.value = friendly(e)
            } finally {
                _saving.value = false
            }
        }
    }
}

/** Harness on this phone: is there a newer Roundtable for the phone? */
sealed interface RuntimeCheck {
    data object Checking : RuntimeCheck
    data class UpToDate(val version: String) : RuntimeCheck
    data class Newer(val version: String, val bytes: Long) : RuntimeCheck
    data class Problem(val text: String) : RuntimeCheck
}

fun runtimeCheckOf(r: RuntimeInstaller.CheckResult, installed: String): RuntimeCheck = when (r) {
    is RuntimeInstaller.CheckResult.UpToDate -> RuntimeCheck.UpToDate(installed.ifBlank { r.manifest.roundtable?.version ?: r.manifest.harness.version })
    is RuntimeInstaller.CheckResult.Available -> RuntimeCheck.Newer(r.manifest.roundtable?.version?.ifBlank { null } ?: r.manifest.harness.version, r.downloadBytes)
    is RuntimeInstaller.CheckResult.Refused -> RuntimeCheck.Problem(r.failure.plain())
}
