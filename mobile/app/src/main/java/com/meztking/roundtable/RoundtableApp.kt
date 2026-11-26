package com.meztking.roundtable

import android.app.Application
import com.meztking.roundtable.data.Backend
import com.meztking.roundtable.data.Crash
import com.meztking.roundtable.data.HubBackend
import com.meztking.roundtable.data.PcBackend
import com.meztking.roundtable.data.Store
import com.meztking.roundtable.net.Api
import com.meztking.roundtable.net.GitHubHub
import com.meztking.roundtable.update.UpdateWorker
import com.meztking.roundtable.work.Watch

class RoundtableApp : Application() {
    val store: Store by lazy { Store(this) }

    @Volatile private var cached: Pair<String, Backend>? = null

    /** The way in that is set up and chosen (Hub mode wins when both are and none is chosen), or null. */
    fun backend(): Backend? {
        val s = store
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
        runCatching { UpdateWorker.setUp(this) } // even after a crash: an update may be the fix
        // after a crash, start nothing in the background until the owner has seen the safe-mode card
        if (Crash.last(this) == null && runCatching { store.configured }.getOrDefault(false)) runCatching { Watch.schedule(this) }
    }
}
