package com.meztking.roundtable

import android.app.Application
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.Crash
import com.meztking.roundtable.data.HubBackend
import com.meztking.roundtable.data.PcBackend
import com.meztking.roundtable.data.Store
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.GitHubHub
import com.meztking.roundtable.net.LocalAccess
import com.meztking.roundtable.runtime.HarnessRuntimeService
import com.meztking.roundtable.runtime.RuntimeController
import com.meztking.roundtable.work.Watch

class RoundtableApp : Application() {
    val store: Store by lazy { Store(this) }

    @Volatile private var cached: Pair<String, Backend>? = null

    /** Roundtable on this phone ("This phone"): set-up, start, stop. */
    val runtime: RuntimeController by lazy { RuntimeController.create(this) { HarnessRuntimeService.ensure(this) } }

    /** The app's client for Roundtable on this phone: the runtime's port and launch token. */
    private val thisPhoneAccess = object : LocalAccess {
        override fun port(): Int = runtime.port()
        override suspend fun token(): String = runtime.token()
    }

    /** Whether the Table shows Roundtable on this phone: chosen, or the only way in that is set up. */
    fun usingThisPhone(): Boolean {
        val s = store
        return s.thisPhone && (s.mode == "phone" || (s.githubToken == null && s.link == null))
    }

    /** The way in that is set up and chosen (Hub mode wins when both are and none is chosen), or null. */
    fun backend(): Backend? {
        val s = store
        if (usingThisPhone()) {
            val key = "phone|${s.identity}"
            cached?.let { if (it.first == key) return it.second }
            return PcBackend(Api.thisPhone(thisPhoneAccess), s.identity).also { cached = key to it }
        }
        val token = s.githubToken
        val link = s.link
        val usePc = link != null && (s.mode == "pc" || token == null)
        val key = if (usePc) "pc|${link!!.token}|${link.hosts}|${s.identity}" else if (token != null) "hub|$token|${s.hubRepo}|${s.identity}" else return null
        cached?.let { if (it.first == key) return it.second }
        val b: Backend = if (usePc) PcBackend(Api(link!!), s.identity) else HubBackend(GitHubHub(token!!, s.hubRepo), s.identity)
        cached = key to b
        return b
    }

    override fun onCreate() {
        super.onCreate()
        Crash.install(this, runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: "?")
        runCatching { Watch.createChannel(this) }
        // after a crash, start nothing in the background until the owner has seen the safe-mode card
        if (Crash.last(this) == null && runCatching { store.configured }.getOrDefault(false)) runCatching { Watch.schedule(this) }
    }
}
