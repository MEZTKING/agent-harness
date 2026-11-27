package com.meztking.roundtable.ui

import android.app.Application
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.meztking.roundtable.RoundtableApp
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.LocalAccess
import com.meztking.roundtable.runtime.AndroidRuntimeSystem
import com.meztking.roundtable.runtime.RuntimeInstaller
import com.meztking.roundtable.runtime.RuntimeState
import com.meztking.roundtable.work.Watch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The "This phone" set-up page and the Harness on this phone page. */
class RuntimeViewModel(app: Application) : AndroidViewModel(app) {
    private val rt get() = getApplication<RoundtableApp>()
    private val runtime get() = rt.runtime
    val state: StateFlow<RuntimeState> get() = runtime.state

    data class Ui(
        /** Bytes the download still needs (null until checked). */
        val downloadBytes: Long? = null,
        /** The download is a test one (signed with the public test key). */
        val test: Boolean = false,
        /** On mobile data: waiting for the owner's yes before downloading. */
        val askMobileData: Boolean = false,
        val waitingForWifi: Boolean = false,
        val savingKey: Boolean = false,
        val keyError: String? = null,
        val done: Boolean = false,
        val storage: Long? = null,
        val projects: Long? = null,
        val log: String? = null,
    )

    private val _ui = MutableStateFlow(Ui(test = runtime.installed?.isTest == true))
    val ui: StateFlow<Ui> = _ui.asStateFlow()

    val supported: Boolean get() = AndroidRuntimeSystem(rt).supported
    val commandChoice: String get() = rt.store.commandChoice

    /** "run" or "ask"; Roundtable takes it at its next start (ROUNDTABLE_ASK_FIRST), so a running one restarts. */
    fun chooseCommands(choice: String) {
        val was = rt.store.commandChoice
        rt.store.commandChoice = choice
        if (was.isNotBlank() && was != choice && runtime.state.value is RuntimeState.Running) runtime.restart()
    }

    /** "The new version didn't start, so the one before it is back." (DS-08), or null. */
    val updateNotice: StateFlow<com.meztking.roundtable.runtime.UpdateNotice?> get() = runtime.notice

    /** Try the release that went back once more, by the owner's choice. */
    fun tryNewAgain() {
        _check.value = null
        runtime.retryHeldBack()
    }

    /** Projects on this phone (DS-55): clone, import, share, through This phone's own API. */
    val phoneProjects: com.meztking.roundtable.data.PhoneProjects
        get() = com.meztking.roundtable.data.PhoneProjects { m, p, b -> localApi().feature(m, p, b) }

    fun projectNames(): List<String> = runtime.projectNames()

    private fun localApi() = Api.thisPhone(object : LocalAccess {
        override fun port() = runtime.port()
        override suspend fun token() = runtime.token()
    })

    private val _check = MutableStateFlow<RuntimeCheck?>(null)
    /** The answer to Check for a newer Roundtable. */
    val check: StateFlow<RuntimeCheck?> = _check.asStateFlow()

    fun checkForNewer() {
        _check.value = RuntimeCheck.Checking
        viewModelScope.launch {
            _check.value = try {
                runtimeCheckOf(runtime.check(), runtime.installed?.version.orEmpty())
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                RuntimeCheck.Problem(friendly(e))
            }
        }
    }

    /** Download the newer one; Roundtable stops for the swap and starts again by itself. */
    fun updateRuntime() {
        _check.value = null
        runtime.install()
    }

    /** Set up: check the download, ask before using mobile data, then download, unpack and start. */
    fun setUp(mobileDataOk: Boolean = false) {
        _ui.update { it.copy(askMobileData = false, waitingForWifi = false) }
        if (runtime.installed != null) { runtime.startIfNeeded(); return }
        viewModelScope.launch {
            val result = runtime.check()
            if (result is RuntimeInstaller.CheckResult.Available) {
                _ui.update { it.copy(downloadBytes = runtime.remainingBytes() ?: result.downloadBytes, test = result.manifest.isTest) }
                if (!mobileDataOk && metered()) { _ui.update { it.copy(askMobileData = true) }; return@launch }
            }
            if (result !is RuntimeInstaller.CheckResult.Refused) runtime.install()
        }
    }

    fun waitForWifi() = _ui.update { it.copy(askMobileData = false, waitingForWifi = true) }
    fun cancel() = runtime.cancel()
    fun start() { runtime.start() }
    fun stop() = runtime.stop()
    fun restart() = runtime.restart()

    fun remove(keepProjects: Boolean) {
        runtime.remove(keepProjects)
        rt.store.thisPhone = false
        if (rt.store.mode == "phone") rt.store.mode = ""
        rt.store.cachedHall = ""
        if (!rt.store.configured) Watch.cancel(rt)
        refreshStorage()
    }

    /** Add a key: straight to Roundtable on this phone (it keeps it; the app doesn't). */
    fun saveKey(key: String) {
        val k = key.trim()
        if (k.length < 10) { _ui.update { it.copy(keyError = "Paste the whole DeepSeek key (it starts with sk-).") }; return }
        _ui.update { it.copy(savingKey = true, keyError = null) }
        viewModelScope.launch {
            try {
                Api.thisPhone(object : LocalAccess {
                    override fun port() = runtime.port()
                    override suspend fun token() = runtime.token()
                }).saveKey("deepseek", k)
                useThisPhone()
                _ui.update { it.copy(savingKey = false, done = true) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(savingKey = false, keyError = friendly(e)) }
            }
        }
    }

    /** Skip the key for now (one can be added later); the Table opens on This phone. */
    fun skipKey() {
        useThisPhone()
        _ui.update { it.copy(done = true) }
    }

    private fun useThisPhone() {
        rt.store.thisPhone = true
        rt.store.mode = "phone"
        rt.store.cachedHall = ""
        if (rt.store.commandChoice.isBlank()) rt.store.commandChoice = "run"
    }

    fun refreshStorage() {
        viewModelScope.launch { _ui.update { it.copy(storage = runtime.storageUsed(), projects = runtime.projectsSize()) } }
    }

    fun showLog(show: Boolean) = _ui.update { it.copy(log = if (show) runtime.logTail().ifBlank { "Nothing logged yet." } else null) }

    fun doneShown() = _ui.update { it.copy(done = false) }

    private fun metered(): Boolean = runCatching { rt.getSystemService(ConnectivityManager::class.java)?.isActiveNetworkMetered == true }.getOrDefault(false)
}
