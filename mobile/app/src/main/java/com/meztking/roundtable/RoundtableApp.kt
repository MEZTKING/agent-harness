package com.meztking.roundtable

import android.app.Application
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.Crash
import com.meztking.roundtable.data.HubBackend
import com.meztking.roundtable.data.MultiBackend
import com.meztking.roundtable.data.Source
import com.meztking.roundtable.data.PcBackend
import com.meztking.roundtable.data.Store
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.GitHubHub
import com.meztking.roundtable.net.LocalAccess
import com.meztking.roundtable.runtime.HarnessRuntimeService
import com.meztking.roundtable.runtime.RuntimeController
import com.meztking.roundtable.update.UpdateWorker
import com.meztking.roundtable.work.Watch

/**
 * "Ask me first" for commands Roundtable on this phone wants to run, handed over at start. Roundtable reads
 * ROUNDTABLE_ASK_FIRST=1 once it has the switch; until then the choice is kept and shown as coming soon.
 */
fun askFirstEnv(choice: String): Map<String, String> = if (choice == "ask") mapOf("ROUNDTABLE_ASK_FIRST" to "1") else emptyMap()

class RoundtableApp : Application() {
    val store: Store by lazy { Store(this) }

    @Volatile private var cached: Pair<String, MultiBackend>? = null

    /** Roundtable on this phone ("This phone"): set-up, start, stop. */
    val runtime: RuntimeController by lazy {
        RuntimeController.create(this, extraEnv = { askFirstEnv(store.commandChoice) }) { HarnessRuntimeService.ensure(this) }
    }

    /** The app's client for Roundtable on this phone: the runtime's port and launch token. */
    private val thisPhoneAccess = object : LocalAccess {
        override fun port(): Int = runtime.port()
        override suspend fun token(): String = runtime.token()
    }

    /** Whether Roundtable on this phone is one of the connections (it then starts with the app). */
    fun usingThisPhone(): Boolean = store.thisPhone

    /**
     * Every connection that is set up, at once: This phone, your PC and the hub ([MultiBackend]); null when none is.
     * Rebuilt only when a connection's settings change.
     */
    fun backend(): MultiBackend? {
        val s = store
        val link = s.link
        val token = s.githubToken
        val key = listOf(s.thisPhone, link?.token, link?.hosts, token, s.hubRepo, s.identity).joinToString("|")
        cached?.let { if (it.first == key) return it.second }
        val parts = buildMap<Source, Backend> {
            if (s.thisPhone) put(Source.PHONE, PcBackend(Api.thisPhone(thisPhoneAccess), s.identity, Source.PHONE))
            if (link != null) put(Source.PC, PcBackend(Api(link), s.identity, Source.PC))
            if (token != null) put(Source.HUB, HubBackend(GitHubHub(token, s.hubRepo), s.identity))
        }
        if (parts.isEmpty()) { cached = null; return null }
        return MultiBackend(parts, s.identity, s).also { cached = key to it }
    }

    /** The way to Roundtable on this phone, for its own pages (keys, the hub). */
    fun thisPhoneApi(): Api = Api.thisPhone(thisPhoneAccess)

    override fun onCreate() {
        super.onCreate()
        Crash.install(this, runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: "?")
        runCatching { Watch.createChannel(this) }
        runCatching { UpdateWorker.setUp(this) } // even after a crash: an update may be the fix
        // after a crash, start nothing in the background until the owner has seen the safe-mode card
        if (Crash.last(this) == null && runCatching { store.configured }.getOrDefault(false)) runCatching { Watch.schedule(this) }
    }
}
